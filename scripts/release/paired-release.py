#!/usr/bin/env python3
"""Create and verify a Developer ID release paired with an App Store candidate."""
import argparse
import concurrent.futures
import hashlib
import json
from pathlib import Path
import plistlib
import shutil
import subprocess
import tempfile

import app_store_runtime


def info(app):
    return plistlib.loads((app/'Contents/Info.plist').read_bytes())


def validate_pair_metadata(store, direct):
    if store.get('CFBundleIdentifier') != 'ly.bleep.desktop' or not store.get('BleepAppSandbox'):
        raise ValueError('Source must be a sandboxed bleeply Store candidate')
    if direct.get('BleepAppSandbox') or 'BleepProjectRoot' in direct:
        raise ValueError('Direct release must not enable App Sandbox or reference a checkout')
    expected = dict(store)
    expected.pop('BleepAppSandbox')
    if expected != direct:
        raise ValueError('Paired app metadata differs beyond the sandbox flag (including version/build)')


def prepare(store, output):
    source_info = info(store)
    direct_info = dict(source_info)
    direct_info.pop('BleepAppSandbox', None)
    validate_pair_metadata(source_info, direct_info)
    if output.exists():
        raise ValueError('Output exists; preserve the previous release first')
    subprocess.run(['codesign', '--verify', '--deep', '--strict', str(store)], check=True)
    app_store_runtime.audit(store)
    app_store_runtime.audit_distribution(store)
    output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(['cp', '-cR', str(store), str(output)], check=True)
    (output/'Contents/embedded.provisionprofile').unlink(missing_ok=True)
    (output/'Contents/Info.plist').write_bytes(plistlib.dumps(direct_info))
    origin = json.loads((store/'Contents/Resources/Engine/runtime.json').read_text())
    record = dict(store_app=str(store), app_source_commit=origin['source_commit'],
                  packaging_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
                  version=direct_info['CFBundleShortVersionString'], build=direct_info['CFBundleVersion'])
    (output.parent/'paired-preparation.json').write_text(json.dumps(record, indent=2)+'\n')
    print('Prepared matching payload; Developer ID signing is required:', output)


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def unsigned_digest(path, temporary):
    """Remove only code signatures in scratch copies; never alter release apps."""
    shutil.copy2(path, temporary)
    temporary.chmod(0o600)
    subprocess.run(['codesign', '--remove-signature', str(temporary)], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    return digest(temporary)


def inventory(app):
    return {p.relative_to(app) for p in app.rglob('*')
            if (p.is_file() or p.is_symlink()) and p.relative_to(app).parts[:2] != ('Contents', '_CodeSignature')
            and p.relative_to(app) not in {Path('Contents/Info.plist'), Path('Contents/embedded.provisionprofile')}}


def verify(store, direct):
    validate_pair_metadata(info(store), info(direct))
    if (direct/'Contents/embedded.provisionprofile').exists():
        raise ValueError('Store provisioning profile leaked into direct release')
    expected, actual = inventory(store), inventory(direct)
    if expected != actual:
        raise ValueError(f'Paired file inventories differ: missing={expected-actual}, extra={actual-expected}')

    def compare(relative):
        a, b = store/relative, direct/relative
        if a.is_symlink() or b.is_symlink():
            if not (a.is_symlink() and b.is_symlink() and a.readlink() == b.readlink()):
                raise ValueError(f'Paired symlinks differ: {relative}')
            return 0
        with a.open('rb') as stream:
            native = stream.read(4) in app_store_runtime.MACHO_MAGIC
        if native:
            with tempfile.TemporaryDirectory(prefix='bleep-paired-code-') as folder:
                if unsigned_digest(a, Path(folder)/'store') != unsigned_digest(b, Path(folder)/'direct'):
                    raise ValueError(f'Paired executable code differs: {relative}')
            return 1
        if a.stat().st_size != b.stat().st_size or digest(a) != digest(b):
            raise ValueError(f'Paired resources differ: {relative}')
        return 0

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        natives = sum(pool.map(compare, sorted(expected)))
    return dict(version=info(store)['CFBundleShortVersionString'], build=info(store)['CFBundleVersion'],
                matching_files=len(expected), matching_native_files=natives,
                allowed_differences=['code signatures and entitlements', 'App Sandbox flag', 'Store provisioning profile'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['prepare', 'verify'])
    parser.add_argument('--store-app', type=Path, required=True)
    parser.add_argument('--direct-app', type=Path, required=True)
    args = parser.parse_args()
    if args.operation == 'prepare':
        prepare(args.store_app.resolve(), args.direct_app.resolve())
    else:
        print(json.dumps(verify(args.store_app.resolve(), args.direct_app.resolve()), indent=2))
