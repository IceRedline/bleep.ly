#!/usr/bin/env python3
"""Assemble a relocatable app from the checked, pinned local Python environments."""
import argparse
import concurrent.futures
import json
import os
from pathlib import Path
import plistlib
import shutil
import stat
import subprocess
import sys
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[2]
MAGIC = {b'\xcf\xfa\xed\xfe', b'\xce\xfa\xed\xfe', b'\xfe\xed\xfa\xcf', b'\xca\xfe\xba\xbe', b'\xbe\xba\xfe\xca'}
SUPPORTED_MACOS = (15, 0)
sys.path.insert(0, str(Path(__file__).resolve().parent))
import pyav_distribution
import app_store_runtime
import app_icons


def macho_files(folder):
    for path in folder.rglob('*'):
        if path.is_file() and not path.is_symlink():
            with path.open('rb') as stream:
                if stream.read(4) in MAGIC:
                    yield path


def normalize_permissions(app):
    """Normalize distributable payloads before signing, without following symlinks."""
    for path in [app, *app.rglob('*')]:
        mode = path.lstat().st_mode
        if stat.S_ISLNK(mode):
            continue
        if not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
            raise RuntimeError(f'Unsupported payload file: {path}')
        path.chmod(0o755 if stat.S_ISDIR(mode) or mode & 0o111 else 0o644)


def audit_mode(name, mode):
    if stat.S_ISLNK(mode):
        return
    required = 0o555 if stat.S_ISDIR(mode) or mode & 0o111 else 0o444
    if mode & required != required:
        raise RuntimeError(f'Payload inaccessible to non-root users: {name} ({mode:o})')


def audit_permissions(app):
    for path in [app, *app.rglob('*')]:
        audit_mode(path, path.lstat().st_mode)


def audit_bom(listing):
    entries = 0
    for line in listing.splitlines():
        name, mode = line.rsplit('\t', 1)
        # productbuild uses a zero-mode synthetic root for /Applications.
        # It is not an installed app payload entry.
        if name == '.' and int(mode, 8) == 0:
            continue
        audit_mode(name, int(mode, 8))
        entries += 1
    if not entries:
        raise RuntimeError('Empty installer bill of materials')
    return entries


def audit_package_permissions(pkg):
    # Extract only BOM metadata, not gigabytes of compressed runtime payloads.
    with tempfile.TemporaryDirectory(prefix='bleep-pkg-audit-') as folder:
        members = subprocess.check_output(['xar', '-tf', str(pkg)], text=True).splitlines()
        boms = [m for m in members if m.endswith('/Bom') or m == 'Bom']
        if not boms or any(Path(m).is_absolute() or '..' in Path(m).parts for m in boms):
            raise RuntimeError('Missing or unsafe installer bill of materials')
        subprocess.run(['xar', '-xf', str(pkg.resolve()), '-C', folder, *boms], check=True)
        entries = sum(audit_bom(subprocess.check_output(
            ['lsbom', '-p', 'fm', str(Path(folder)/bom)], text=True)) for bom in boms)
    print(f'Installer permissions verified: {entries} BOM entries', flush=True)


def audit(app):
    """Reject developer-machine dependencies and incompatible deployment targets."""
    audit_permissions(app)
    minimum = (14, 0)
    files = list(macho_files(app))
    def inspect(path):
        ids = subprocess.check_output(['otool', '-D', str(path)], text=True).splitlines()[1:]
        dependencies = subprocess.check_output(['otool', '-L', str(path)], text=True).splitlines()[1:]
        for line in dependencies:
            library = line.strip().split(' (compatibility')[0]
            if library in ids:
                continue  # A dylib's own LC_ID_DYLIB is not a dependency.
            if library.startswith('/') and not library.startswith(('/usr/lib/', '/System/Library/')):
                raise RuntimeError(f'External library in {path}: {library}')
        versions = []
        build = subprocess.check_output(['xcrun', 'vtool', '-show-build', str(path)], text=True)
        command = ''
        for line in build.splitlines():
            if line.strip().startswith('cmd '):
                command = line.split()[-1]
            if line.strip().startswith('minos ') or (command == 'LC_VERSION_MIN_MACOSX' and line.strip().startswith('version ')):
                value = line.split()[-1]
                versions.append(tuple(int(n) for n in value.split('.')[:2]))
        if not versions:
            raise RuntimeError(f'Missing macOS deployment target: {path}')
        required = max(versions)
        if required > SUPPORTED_MACOS:
            raise RuntimeError(f'{path} requires macOS {".".join(map(str, required))}; '
                               'release must support macOS 15.0')
        return required
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        minimum = max([minimum, *pool.map(inspect, files)])
    for link in app.rglob('*'):
        if link.is_symlink() and (not link.resolve().is_relative_to(app.resolve()) or not link.exists()):
            raise RuntimeError(f'External or broken symlink: {link}')
    return files, '.'.join(map(str, minimum))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--version', default='0.1.9')
    parser.add_argument('--build-number', help='Shared monotonically increasing build number for both channels')
    parser.add_argument('--python', type=Path, default=ROOT/'.cache/release-python/cpython-3.11.15-macos-aarch64-none')
    parser.add_argument('--audit-only', type=Path)
    args = parser.parse_args()
    if args.audit_only:
        # CI also audits bare site-packages directories, which have no app icon.
        if args.audit_only.suffix == '.app':
            app_icons.audit(args.audit_only)
        files, minimum = audit(args.audit_only)
        print(json.dumps(dict(native_files=len(files), minimum_macos=minimum)))
        return
    if not args.build_number or not args.build_number.isdecimal() or int(args.build_number) < 1:
        parser.error('--build-number must be a positive integer shared with the Store candidate')
    app = ROOT/'build/release/bleeply.app'
    app.parent.mkdir(parents=True, exist_ok=True)
    if app.exists():
        parser.error(f'{app} already exists; move the previous signed build aside before rebuilding')
    shutil.copytree(ROOT/'build/bleeply.app', app)
    engine = app/'Contents/Resources/Engine'
    engine.mkdir()
    shutil.copytree(ROOT/'censor', engine/'censor', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    for name in ['profanity.txt', 'profanity.en.txt']:
        shutil.copy2(ROOT/name, engine/name)
    for name, environment, lock in [('Python', '.venv', 'core'), ('PythonGPU', '.runtime/asr-env', 'gpu')]:
        source = ROOT/environment
        actual = subprocess.check_output([str(source/'bin/python'), '-m', 'pip', 'freeze'], text=True)
        expected = (ROOT/f'scripts/release/requirements-{lock}.lock').read_text()
        if sorted(actual.splitlines()) != sorted(expected.splitlines()):
            raise RuntimeError(f'{environment} does not match the release lockfile')
        target = app/'Contents/Resources/Runtime'/name
        shutil.copytree(args.python, target, symlinks=True, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        site = target/'lib/python3.11/site-packages'
        shutil.rmtree(site)
        # The experimental environment may inherit core packages through a .pth
        # file. Copy the actual selected distributions, not that machine path.
        site.mkdir()
        inventory_script = """
import importlib.metadata as md, json
names = {d.metadata['Name'] for d in md.distributions() if d.metadata['Name']}
files = []
for name in sorted(names):
    d = md.distribution(name)
    for entry in d.files or []:
        if '..' in entry.parts or '__pycache__' in entry.parts or str(entry).endswith('.pyc'):
            continue
        files.append([str(d.locate_file(entry).resolve()), str(entry)])
print(json.dumps(files))
"""
        inventory = json.loads(subprocess.check_output([str(source/'bin/python'), '-c', inventory_script], text=True))
        for original, relative in inventory:
            destination = site/relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(original, destination)
        # Entry-point scripts carry build-machine shebangs; only Python is used.
        for binary in (target/'bin').iterdir():
            if not binary.name.startswith('python'):
                binary.unlink()
        for pattern in ['**/direct_url.json', '**/*.pth']:
            for metadata in site.glob(pattern):
                if metadata.name == 'direct_url.json':
                    data = json.loads(metadata.read_text())
                    if data.get('dir_info', {}).get('editable'):
                        raise RuntimeError(f'Editable Python dependency: {metadata}')
                    if data.get('url', '').startswith('file:'):
                        # Cached wheel provenance is not a runtime dependency.
                        metadata.unlink()
                elif '/Users/' in metadata.read_text():
                    raise RuntimeError(f'Local-only Python search path: {metadata}')
    # A version-only pin selects the macOS 26.2 MLX wheel on a Tahoe build host.
    # Overlay the hash-locked macOS 15 wheels without modifying developer environments.
    with tempfile.TemporaryDirectory(prefix='bleep-release-mlx-') as temporary:
        subprocess.run([sys.executable, '-m', 'pip', 'install', '--no-deps', '--no-compile',
                        '--require-hashes', '--only-binary=:all:', '--target', temporary,
                        '-r', str(ROOT/'scripts/release/requirements-mlx-macos15.lock')], check=True)
        for name in ['Python', 'PythonGPU']:
            site = app/'Contents/Resources/Runtime'/name/'lib/python3.11/site-packages'
            for pattern in ['mlx', 'mlx-*.dist-info', 'mlx_metal-*.dist-info']:
                for old in site.glob(pattern):
                    shutil.rmtree(old)
            shutil.copytree(temporary, site, dirs_exist_ok=True)
    for name in ['ffmpeg', 'ffprobe']:
        shutil.copy2(ROOT/'.cache/release-ffmpeg/bin'/name, app/'Contents/Helpers'/name)
    licenses = app/'Contents/Resources/ThirdParty'
    licenses.mkdir()
    for name in ['COPYING.LGPLv2.1', 'LICENSE.md']:
        shutil.copy2(ROOT/'.cache/ffmpeg-8.1.2'/name, licenses/f'FFmpeg-{name}')
    shutil.copy2(args.python/'lib/python3.11/LICENSE.txt', licenses/'Python-LICENSE.txt')
    for lock in ['core', 'gpu', 'mlx-macos15']:
        shutil.copy2(ROOT/f'scripts/release/requirements-{lock}.lock', licenses)
    (licenses/'README.txt').write_text(
        'Python distribution: https://github.com/astral-sh/python-build-standalone\n'
        'Python package license files and metadata are retained in Contents/Resources/Runtime/Python*/lib/python3.11/site-packages.\n'
        'WhisperKit 1.1.0: https://github.com/argmaxinc/argmax-oss-swift (MIT).\n'
        'FFmpeg 8.1.2: https://ffmpeg.org (LGPL 2.1 or later). Unmodified source archive accompanies this release.\n'
        'Build configuration: scripts/release/build-ffmpeg.sh in the matching source release.\n'
        'FFmpeg runs as a separate executable; video is copied without re-encoding.\n')
    for package in (ROOT/'.cache/whisperkit-build/checkouts').glob('*'):
        for license_file in package.glob('LICENSE*'):
            if license_file.is_file(): shutil.copy2(license_file, licenses/f'{package.name}-{license_file.name}')
    pyav = pyav_distribution.install(app)
    shared_runtime = app_store_runtime.install(app)
    normalize_permissions(app)
    files, minimum = audit(app)
    manifest = dict(version=args.version, source_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
                    architecture='arm64', python='3.11.15', ffmpeg='8.1.2', pyav=pyav,
                    shared_runtime=shared_runtime, minimum_macos=minimum)
    (engine/'runtime.json').write_text(json.dumps(manifest, indent=2)+'\n')
    info_path = app/'Contents/Info.plist'
    info = plistlib.loads(info_path.read_bytes())
    info.pop('BleepProjectRoot', None)
    info.update(CFBundleShortVersionString=args.version, CFBundleVersion=args.build_number, LSMinimumSystemVersion=minimum,
                BleepBuildID=str(uuid.uuid4()))
    info_path.write_bytes(plistlib.dumps(info))
    subprocess.run(['bash', str(ROOT/'scripts/build-theme.sh'), str(app)], check=True)
    print(json.dumps(dict(app=str(app), native_files=len(files), **manifest), indent=2))


if __name__ == '__main__':
    main()
