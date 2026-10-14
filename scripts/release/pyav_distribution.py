"""Install and audit the source-built PyAV distribution in both embedded runtimes."""
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[2]
SOURCE_HASHES = {
    'ffmpeg-8.1.2.tar.xz': '464beb5e7bf0c311e68b45ae2f04e9cc2af88851abb4082231742a74d97b524c',
    'av-18.1.0.tar.gz': '47bfc286e1bc9de7ab4681fc2b575cd2460a66919d31ffe1bd5aa54fae531a28',
}
NOTICE = '''Rebuilding the bundled LGPL libraries

FFmpeg 8.1.2 and PyAV 18.1.0 sources are unmodified. Their exact source archives
are included here. build-pyav.sh builds shared FFmpeg libraries with GPL,
nonfree, version-3 components and external codec autodetection disabled, then
builds PyAV and vendors those libraries using delocate. FFmpeg-config.h and
FFmpeg-config.mak record the shared library build configuration.

The separate command-line helpers use build-ffmpeg.sh and the same FFmpeg source
archive. Python package copyright notices, including PyAV's BSD-3-Clause license,
remain in each runtime's site-packages distribution metadata.

To reproduce: check out the bleep.ly source revision in ../pyav-build.json,
create a Python 3.11 environment at .venv, install Xcode and pkg-config, then run
bash scripts/release/build-pyav.sh. Copy these source archives into
.cache/pyav-lgpl/sources first to reuse them without downloading again.

To modify FFmpeg: extract its source archive, apply your changes, and use the
configure options in build-pyav.sh to build ABI-compatible shared libraries.
Replace the corresponding libav*.dylib/libsw*.dylib files under av/.dylibs in
BOTH Runtime/Python*/lib/python3.11/site-packages directories in a local app copy.
Keep the existing library install names and relative dependency paths (otool -L
and install_name_tool can inspect/update them), or rebuild PyAV and use delocate.
Re-sign every changed Mach-O and the local app copy with your own signing identity;
macOS library validation requires matching signatures. Do not modify the installed
signed release in place. No permission from the bleep.ly developer is required
to exercise the rights granted by the included LGPL license.
'''


def install(app, artifacts=ROOT/'.cache/pyav-lgpl'):
    wheels = list((artifacts/'wheels').glob('av-18.1.0-cp311-abi3-macosx_*_arm64.whl'))
    if len(wheels) != 1:
        raise ValueError('Build exactly one LGPL PyAV wheel with scripts/release/build-pyav.sh')
    wheel = wheels[0]
    for name, digest in SOURCE_HASHES.items():
        if hashlib.sha256((artifacts/'sources'/name).read_bytes()).hexdigest() != digest:
            raise ValueError(f'Wrong corresponding source archive: {name}')
    with zipfile.ZipFile(wheel) as archive:
        for name in archive.namelist():
            path = Path(name)
            if path.is_absolute() or '..' in path.parts or path.parts[0] not in {'av', 'av-18.1.0.dist-info'}:
                raise ValueError(f'Unexpected PyAV wheel member: {name}')
        for runtime in ['Python', 'PythonGPU']:
            site = app/'Contents/Resources/Runtime'/runtime/'lib/python3.11/site-packages'
            if not site.is_dir():
                raise ValueError(f'Missing runtime: {runtime}')
            # Remove the complete old distribution, including its vendored codecs.
            for pattern in ['av', 'av-*.dist-info', 'av.libs']:
                for old in site.glob(pattern):
                    shutil.rmtree(old)
            archive.extractall(site)
    third_party = app/'Contents/Resources/ThirdParty'
    sources = third_party/'Sources'
    sources.mkdir(parents=True, exist_ok=True)
    for name in [*SOURCE_HASHES, 'FFmpeg-config.h', 'FFmpeg-config.mak', 'FFmpeg-LGPL-2.1.txt', 'build-pyav.sh', 'build-ffmpeg.sh']:
        shutil.copy2(artifacts/'sources'/name, sources/name)
    (sources/'BUILDING.txt').write_text(NOTICE)
    metadata = dict(pyav='18.1.0', ffmpeg='8.1.2', license='LGPL-2.1-or-later',
                    source_commit=subprocess.check_output(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], text=True).strip(),
                    wheel=wheel.name, wheel_sha256=hashlib.sha256(wheel.read_bytes()).hexdigest(),
                    sources=SOURCE_HASHES)
    (third_party/'pyav-build.json').write_text(json.dumps(metadata, indent=2)+'\n')
    audit(app)
    return metadata


def audit(app):
    for path in app.rglob('*'):
        if path.is_file() and re.search(r'libx26[45]', path.name, re.I):
            raise ValueError(f'Unexpected GPL codec library: {path}')
    for runtime in ['Python', 'PythonGPU']:
        site = app/'Contents/Resources/Runtime'/runtime/'lib/python3.11/site-packages'
        libraries = list((site/'av/.dylibs').glob('*.dylib'))
        if len(libraries) != 7:
            raise ValueError(f'{runtime}: expected exactly seven LGPL FFmpeg libraries')
        for library in libraries:
            if not re.fullmatch(r'lib(avcodec|avdevice|avfilter|avformat|avutil|swresample|swscale)\.\d+(?:\.\d+)*\.dylib', library.name):
                raise ValueError(f'Unexpected PyAV library: {library.name}')
            data = library.read_bytes()
            if any(flag in data for flag in [b'--enable-gpl', b'--enable-nonfree', b'--enable-version3', b'--enable-libx264', b'--enable-libx265']):
                raise ValueError(f'Incompatible FFmpeg configuration: {library}')
            if any(flag not in data for flag in [b'--disable-gpl', b'--disable-nonfree', b'--disable-version3']):
                raise ValueError(f'Unverified FFmpeg build: {library}')
    sources = app/'Contents/Resources/ThirdParty/Sources'
    for name, expected in SOURCE_HASHES.items():
        if hashlib.sha256((sources/name).read_bytes()).hexdigest() != expected:
            raise ValueError(f'Missing or mismatched corresponding source: {name}')
