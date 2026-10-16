#!/usr/bin/env python3
"""Prepare a separate macOS TestFlight candidate, then sign and package it."""
import argparse
import concurrent.futures
import ctypes
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import plistlib
import shutil
import stat
import subprocess
import uuid
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import pyav_distribution
import app_store_runtime
spec = importlib.util.spec_from_file_location('bundle', Path(__file__).with_name('bundle-macos.py'))
bundle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bundle)


def command(*args):
    return subprocess.check_output(list(map(str, args)), text=True).strip()


def clear_quarantine(app):
    # Some bundled licenses are read-only. Avoid asking xattr to mutate every
    # file, including those that have no quarantine attribute in the first place.
    # Python exposes os.*xattr on Linux, but not on macOS. Use Darwin's API.
    libc = ctypes.CDLL('/usr/lib/libSystem.B.dylib', use_errno=True)
    libc.listxattr.argtypes = [ctypes.c_char_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int]
    libc.listxattr.restype = ctypes.c_ssize_t
    libc.removexattr.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int]
    libc.removexattr.restype = ctypes.c_int
    for path in [app, *app.rglob('*')]:
        encoded = os.fsencode(path)
        size = libc.listxattr(encoded, None, 0, 1)  # XATTR_NOFOLLOW
        if size < 0:
            raise OSError(ctypes.get_errno(), 'Cannot list extended attributes', str(path))
        names = ctypes.create_string_buffer(size)
        if libc.listxattr(encoded, names, size, 1) < 0:
            raise OSError(ctypes.get_errno(), 'Cannot read extended attributes', str(path))
        if b'com.apple.quarantine' not in names.raw.split(b'\0'):
            continue
        mode = stat.S_IMODE(path.lstat().st_mode)
        writable = not path.is_symlink() and not mode & stat.S_IWUSR
        try:
            if writable:
                path.chmod(mode | stat.S_IWUSR)
            if libc.removexattr(encoded, b'com.apple.quarantine', 1) != 0:
                raise OSError(ctypes.get_errno(), 'Cannot remove quarantine attribute', str(path))
        finally:
            if writable:
                path.chmod(mode)


def validate_profile(profile, bundle_id, identity):
    """Fail before modifying the app if a signing asset cannot serve TestFlight."""
    entitlements = profile.get('Entitlements', {})
    teams = profile.get('TeamIdentifier', [])
    identifier = entitlements.get('com.apple.application-identifier', '')
    if len(teams) != 1 or identifier != f'{teams[0]}.{bundle_id}':
        raise ValueError('Profile must match this explicit macOS Bundle ID and team')
    if 'OSX' not in profile.get('Platform', []):
        raise ValueError('Select a Mac App Store Connect provisioning profile')
    if profile.get('ProvisionedDevices') or profile.get('ProvisionsAllDevices'):
        raise ValueError('A device/development or Developer ID profile cannot be used for TestFlight')
    if entitlements.get('get-task-allow') or entitlements.get('com.apple.security.get-task-allow'):
        raise ValueError('A development profile cannot be used for TestFlight')
    expires = profile.get('ExpirationDate')
    if not isinstance(expires, datetime) or expires.replace(tzinfo=timezone.utc) <= datetime.now(timezone.utc):
        raise ValueError('Provisioning profile is expired or has no expiration')
    fingerprints = [hashlib.sha1(cert).hexdigest().upper() for cert in profile.get('DeveloperCertificates', [])]
    if identity.upper() not in fingerprints:
        raise ValueError('Application signing identity SHA-1 must match a certificate in the profile')
    return {
        'com.apple.application-identifier': identifier,
        'com.apple.developer.team-identifier': teams[0],
        'com.apple.security.app-sandbox': True,
        'com.apple.security.network.client': True,
        'com.apple.security.files.user-selected.read-write': True,
        'com.apple.security.files.bookmarks.app-scope': True,
    }


def refresh_engine(app, source_commit, project=ROOT):
    """Reuse pinned runtimes, but ship Python source from the same checkout as Swift."""
    engine = app/'Contents/Resources/Engine'
    runtime_origin = json.loads((engine/'runtime.json').read_text())
    shutil.rmtree(engine/'censor')
    shutil.copytree(project/'censor', engine/'censor', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    for name in ['profanity.txt', 'profanity.en.txt']:
        shutil.copy2(project/name, engine/name)
    manifest = {**runtime_origin, 'source_commit': source_commit}
    (engine/'runtime.json').write_text(json.dumps(manifest, indent=2)+'\n')
    return runtime_origin


def prepare(args):
    source = args.source_app.resolve()
    output = args.output.resolve()
    if output.exists():
        raise ValueError('Output already exists; choose a new candidate directory')
    info = plistlib.loads((source/'Contents/Info.plist').read_bytes())
    if info.get('CFBundleIdentifier') != 'ly.bleep.desktop' or info.get('BleepAppSandbox'):
        raise ValueError('Source must be the original bleeply direct-download release')
    if not args.executable.is_file():
        raise ValueError('Build the Swift app before preparing the candidate')
    if not args.build_number.isdecimal() or int(args.build_number) < int(info['CFBundleVersion']):
        raise ValueError('Build number must be an integer at least the source release build')
    # Never stamp a source revision that omits tracked implementation edits.
    subprocess.run(['git', 'diff', '--exit-code', 'HEAD', '--', 'macOS', 'censor', 'docs', 'profanity.txt', 'profanity.en.txt', 'scripts'], cwd=ROOT, check=True)
    source_commit = command('git', '-C', ROOT, 'rev-parse', 'HEAD')
    sdk_version = command('xcrun', '--sdk', 'macosx', '--show-sdk-version')
    sdk_build = command('xcrun', '--sdk', 'macosx', '--show-sdk-build-version')
    xcode = command('xcodebuild', '-version').splitlines()
    xcode_parts = xcode[0].split()[-1].split('.')
    xcode_number = xcode_parts[0] + ''.join((xcode_parts[1:] + ['0', '0'])[:2])
    output.mkdir(parents=True)
    app = output/'bleeply.app'
    subprocess.run(['cp', '-cR', str(source), str(app)], check=True)
    shutil.copy2(args.executable, app/'Contents/MacOS/Bleep')
    runtime_origin = refresh_engine(app, source_commit)
    pyav = pyav_distribution.install(app)
    store_runtime = app_store_runtime.install(app)
    documentation = app/'Contents/Resources/Documentation'
    documentation.mkdir(exist_ok=True)
    for name in ['privacy-policy.md', 'support.md', 'third-party.md']:
        shutil.copy2(ROOT/'docs'/name, documentation/name)
    info.update(CFBundleName='bleeply', CFBundleDisplayName='bleeply',
                CFBundleVersion=args.build_number, BleepBuildID=str(uuid.uuid4()), BleepAppSandbox=True,
                LSApplicationCategoryType='public.app-category.video',
                NSHumanReadableCopyright=args.copyright, CFBundleSupportedPlatforms=['MacOSX'],
                DTPlatformName='macosx', DTPlatformVersion=sdk_version, DTPlatformBuild=sdk_build,
                DTSDKName=f'macosx{sdk_version}', DTSDKBuild=sdk_build,
                DTXcode=xcode_number, DTXcodeBuild=xcode[1].split()[-1],
                DTCompiler='com.apple.compilers.llvm.clang.1_0', BuildMachineOSBuild=command('sw_vers', '-buildVersion'))
    (app/'Contents/Info.plist').write_bytes(plistlib.dumps(info))
    subprocess.run(['bash', str(ROOT/'scripts/build-theme.sh'), str(app)], check=True)
    bundle.normalize_permissions(app)
    manifest = dict(source_app=str(source), app_source_commit=source_commit, runtime_origin=runtime_origin, pyav=pyav,
                    app_store_runtime=store_runtime,
                    engine=json.loads((app/'Contents/Resources/Engine/runtime.json').read_text()),
                    build=args.build_number, version=info['CFBundleShortVersionString'],
                    executable_sha256=hashlib.sha256((app/'Contents/MacOS/Bleep').read_bytes()).hexdigest())
    (output/'preparation.json').write_text(json.dumps(manifest, indent=2)+'\n')
    print(f'Prepared unsigned candidate: {app}\nSign and validate before uploading.')


def sign(args):
    app = args.app.resolve()
    if args.pkg.exists():
        raise ValueError('Package already exists; existing artifacts are never replaced')
    info = plistlib.loads((app/'Contents/Info.plist').read_bytes())
    if not info.get('BleepAppSandbox') or not (app.parent/'preparation.json').is_file():
        raise ValueError('Only a separately prepared TestFlight candidate may be signed')
    profile_bytes = subprocess.check_output(['security', 'cms', '-D', '-i', str(args.profile)])
    entitlements = validate_profile(plistlib.loads(profile_bytes), info['CFBundleIdentifier'], args.identity)
    shutil.copy2(args.profile, app/'Contents/embedded.provisionprofile')
    clear_quarantine(app)
    bundle.normalize_permissions(app)
    bundle.app_icons.audit(app)
    pyav_distribution.audit(app)
    app_store_runtime.audit(app)
    app_store_runtime.audit_distribution(app)
    files, _ = bundle.audit(app)
    child = {'com.apple.security.app-sandbox': True, 'com.apple.security.inherit': True}
    python = {**child, 'com.apple.security.cs.allow-jit': True,
              'com.apple.security.cs.allow-unsigned-executable-memory': True}
    for name, values in [('app', entitlements), ('child', child), ('python', python)]:
        (app.parent/f'{name}.entitlements').write_bytes(plistlib.dumps(values))
    main = app/'Contents/MacOS/Bleep'

    def sign_file(path):
        options = []
        if path.name.startswith('python') and path.parent.name == 'bin':
            options = ['--entitlements', str(app.parent/'python.entitlements')]
        elif 'EXECUTE' in command('otool', '-hv', path):
            options = ['--entitlements', str(app.parent/'child.entitlements')]
        subprocess.run(['codesign', '--force', '--sign', args.identity, '--options', 'runtime', '--timestamp',
                        *options, str(path)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        for index, _ in enumerate(pool.map(sign_file, [p for p in files if p != main]), 1):
            if index % 50 == 0:
                print(f'Signed {index} nested binaries', flush=True)
    subprocess.run(['codesign', '--force', '--sign', args.identity, '--options', 'runtime', '--timestamp',
                    '--entitlements', str(app.parent/'app.entitlements'), str(app)], check=True)
    subprocess.run(['codesign', '--verify', '--deep', '--strict', '--verbose=2', str(app)], check=True)
    subprocess.run(['productbuild', '--component', str(app), '/Applications', '--sign', args.installer_identity,
                    str(args.pkg)], check=True)
    subprocess.run(['pkgutil', '--check-signature', str(args.pkg)], check=True)
    bundle.audit_package_permissions(args.pkg)
    print(f'Package ready for App Store Connect validation: {args.pkg}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='operation', required=True)
    prep = commands.add_parser('prepare', help='Clone a release without modifying its signed artifacts')
    prep.add_argument('--source-app', type=Path, default=ROOT/'build/release/bleeply.app')
    prep.add_argument('--executable', type=Path, default=ROOT/'.cache/swift-build/release/Bleep')
    prep.add_argument('--output', type=Path, required=True)
    prep.add_argument('--build-number', required=True)
    prep.add_argument('--copyright', required=True)
    prep.set_defaults(action=prepare)
    signing = commands.add_parser('sign', help='Sign a prepared candidate and create an upload package')
    signing.add_argument('--app', type=Path, required=True)
    signing.add_argument('--profile', type=Path, required=True)
    signing.add_argument('--identity', required=True, help='Application certificate SHA-1 from security find-identity')
    signing.add_argument('--installer-identity', required=True)
    signing.add_argument('--pkg', type=Path, required=True)
    signing.set_defaults(action=sign)
    args = parser.parse_args()
    try:
        args.action(args)
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        parser.exit(1, f'{error}\n')


if __name__ == '__main__':
    main()
