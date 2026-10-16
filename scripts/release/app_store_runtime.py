"""Prepare Python dependencies for the Mac App Store without private Apple APIs."""
import argparse
import hashlib
import json
import mmap
from pathlib import Path
import shutil
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[2]
WHEEL = 'scipy-1.17.1-cp311-cp311-macosx_12_0_arm64.whl'
SHA256 = 'e18f12c6b0bc5a592ed23d3f7b891f68fd7f8241d69b7883769eb5d5dfb52696'
URL = 'https://files.pythonhosted.org/packages/f7/58/bccc2861b305abdd1b8663d6130c0b3d7cc22e8d86663edbc8401bfd40d4/' + WHEEL
CACHE = ROOT/'.cache/app-store-runtime/wheels'
SOURCE_ARCHIVE = 'gcc-12.1-darwin-r0.tar.gz'
SOURCE_SHA256 = '75cd91f0291ea1863119ce6fdeaa6478a267c941f59128cb22635351f5d2c3f8'
SOURCE_URL = 'https://codeload.github.com/iains/gcc-12-branch/tar.gz/912ae4b9e6c9572ff9ef1c5be6693ff336324361'
SOURCE_NOTICE = '''SciPy's bundled compiler runtime sources

The official SciPy 1.17.1 macOS 12 arm64 wheel links OpenBLAS, libgfortran,
libgcc and libquadmath dynamically. Its complete copyright/license notices
are in scipy-1.17.1.dist-info/LICENSE.txt in BOTH Python runtimes. OpenBLAS is
BSD-licensed; GCC runtime libraries use GPL with the GCC Runtime Library
Exception; libquadmath is LGPL-2.1-or-later.

The upstream wheel build selects Francois-Xavier Coudert's ARM GCC 12.1
Monterey toolchain, built from Iain Sandoe's GCC Darwin branch. The unmodified
GCC 12.1 Darwin r0 source archive is included here, containing libquadmath,
the compiler runtimes and their build machinery. See the pinned archive URL
and checksum in ../app-store-runtime.json. Upstream build provenance:
https://github.com/scipy/scipy/blob/v1.17.1/tools/wheels/cibw_before_build_macos.sh
https://github.com/fxcoudert/gfortran-for-macOS/releases/tag/12.1-monterey
https://github.com/fxcoudert/gfortran-for-macOS/blob/c1ab08eea60c5701f42e9d218fc7b26ef0cb2ac2/build_package.md

To rebuild: extract the archive, install Xcode command-line tools plus GMP,
MPFR, MPC and ISL, and use a separate build directory. Follow the upstream
toolchain build notes above with these GCC 12.1 sources, aarch64-apple-darwin
as the build target, and --enable-languages=c,c++,fortran --disable-multilib
--with-sysroot=$(xcrun --show-sdk-path). Run make and install into a staging
directory using DESTDIR. No GCC source patches are applied by bleeply.

To use a modified LGPL library, replace libquadmath.0.dylib under
Contents/Resources/Runtime/Python*/lib/python3.11/site-packages/scipy/.dylibs
in BOTH runtimes of a local app copy with an ABI-compatible arm64 build.
Preserve @loader_path dependency paths (inspect with otool -L and adjust with
install_name_tool). Re-sign changed Mach-O files and the app copy using your
own signing identity. You may modify these LGPL components and reverse
engineer their integration to debug those modifications; no permission from
bleeply's developer is required. Do not modify the installed signed release.
'''
MACHO_MAGIC = {b'\xcf\xfa\xed\xfe', b'\xce\xfa\xed\xfe', b'\xfe\xed\xfa\xcf',
               b'\xfe\xed\xfa\xce', b'\xca\xfe\xba\xbe', b'\xbe\xba\xfe\xca',
               b'\xca\xfe\xba\xbf', b'\xbf\xba\xfe\xca'}
REJECTED_APIS = (b'_NSWindowDidOrderOnScreenNotification', b'_dcabs1_', b'_lsame_', b'_xerbla_array__')
SYMBOL_CHARS = b'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_'
TK_PATTERNS = ('lib/libtcl*', 'lib/libtk*', 'lib/tcl*', 'lib/tk*', 'lib/itcl*', 'lib/thread*',
               'lib/python3.11/tkinter', 'lib/python3.11/lib-dynload/_tkinter*')


def verify_wheel(path):
    if hashlib.sha256(path.read_bytes()).hexdigest() != SHA256:
        raise ValueError(f'Wrong SciPy wheel checksum: {path}')


def verify_source(path):
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != SOURCE_SHA256:
        raise ValueError(f'Missing or mismatched compiler runtime source: {path}')


def fetch():
    """Download explicitly; candidate preparation itself works offline."""
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE/WHEEL
    if not path.exists():
        data = urllib.request.urlopen(URL, timeout=60).read()
        if hashlib.sha256(data).hexdigest() != SHA256:
            raise ValueError('Downloaded SciPy wheel checksum mismatch')
        path.write_bytes(data)
    verify_wheel(path)
    source = CACHE.parent/'sources'/SOURCE_ARCHIVE
    if not source.exists():
        data = urllib.request.urlopen(SOURCE_URL, timeout=120).read()
        if hashlib.sha256(data).hexdigest() != SOURCE_SHA256:
            raise ValueError('Downloaded compiler runtime source checksum mismatch')
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(data)
    verify_source(source)
    print(path)


def remove_tk(runtime):
    """The UI is SwiftUI; neither engine needs Python's optional Tk GUI stack."""
    removed = []
    for pattern in TK_PATTERNS:
        for path in sorted(runtime.glob(pattern)):
            removed.append(str(path.relative_to(runtime)))
            if path.is_symlink() or path.is_file():
                path.unlink()
            else:
                shutil.rmtree(path)
    return removed


def install(app, cache=CACHE):
    wheel = cache/WHEEL
    if not wheel.is_file():
        raise ValueError('Run python3 scripts/release/app_store_runtime.py fetch first')
    verify_wheel(wheel)
    source = cache.parent/'sources'/SOURCE_ARCHIVE
    verify_source(source)
    removed = {}
    with zipfile.ZipFile(wheel) as archive:
        for name in archive.namelist():
            path = Path(name)
            if path.is_absolute() or '..' in path.parts or path.parts[0] not in {'scipy', 'scipy-1.17.1.dist-info'}:
                raise ValueError(f'Unexpected SciPy wheel member: {name}')
        # Validate both destinations before replacing either distribution.
        runtimes = [app/'Contents/Resources/Runtime'/name for name in ('Python', 'PythonGPU')]
        for runtime in runtimes:
            if not (runtime/'lib/python3.11/site-packages').is_dir():
                raise ValueError(f'Missing runtime: {runtime}')
        for runtime in runtimes:
            site = runtime/'lib/python3.11/site-packages'
            for pattern in ('scipy', 'scipy-*.dist-info', 'scipy.libs'):
                for old in site.glob(pattern):
                    shutil.rmtree(old)
            # Preserve the wheel's SciPy, OpenBLAS and compiler runtime licenses.
            archive.extractall(site)
            removed[runtime.name] = remove_tk(runtime)
    metadata = dict(scipy='1.17.1', blas='OpenBLAS', wheel=WHEEL, wheel_sha256=SHA256,
                    compiler_runtime_source=dict(archive=SOURCE_ARCHIVE, sha256=SOURCE_SHA256, url=SOURCE_URL),
                    wheel_url=URL, removed_optional_tk=removed)
    third_party = app/'Contents/Resources/ThirdParty'
    third_party.mkdir(parents=True, exist_ok=True)
    sources = third_party/'Sources'
    sources.mkdir(exist_ok=True)
    shutil.copy2(source, sources/SOURCE_ARCHIVE)
    (sources/'SCIPY-RUNTIME-SOURCES.txt').write_text(SOURCE_NOTICE)
    (third_party/'app-store-runtime.json').write_text(json.dumps(metadata, indent=2)+'\n')
    audit(app)
    audit_distribution(app)
    return metadata


def audit_distribution(app):
    third_party = app/'Contents/Resources/ThirdParty'
    verify_source(third_party/'Sources'/SOURCE_ARCHIVE)
    if not (third_party/'Sources/SCIPY-RUNTIME-SOURCES.txt').is_file():
        raise ValueError('Missing compiler runtime rebuild instructions')
    for name in ('Python', 'PythonGPU'):
        license = app/'Contents/Resources/Runtime'/name/'lib/python3.11/site-packages/scipy-1.17.1.dist-info/LICENSE.txt'
        if not license.is_file() or not all(text in license.read_text() for text in ('OpenBLAS', 'libquadmath', 'GCC RUNTIME LIBRARY EXCEPTION')):
            raise ValueError(f'Missing SciPy dependency license notices: {name}')


def audit(app):
    """Scan all Mach-O payloads, including strings used for dynamic API lookup.

    This is a regression check for the review findings, not a complete catalog
    of Apple's private APIs. Never strip or rename imports to evade this check.
    """
    findings = []
    count = 0
    for path in app.rglob('*'):
        if not path.is_file() or path.is_symlink():
            continue
        with path.open('rb') as stream:
            if stream.read(4) not in MACHO_MAGIC:
                continue
            count += 1
            with mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as data:
                symbols = set()
                for symbol in REJECTED_APIS:
                    start = data.find(symbol)
                    while start >= 0:
                        end = start + len(symbol)
                        # Match whole names, not SciPy's prefixed implementations.
                        if (start == 0 or data[start-1] not in SYMBOL_CHARS) and (end == len(data) or data[end] not in SYMBOL_CHARS):
                            symbols.add(symbol.decode())
                            break
                        start = data.find(symbol, end)
                if symbols:
                    findings.append(f'{path.relative_to(app)}: {", ".join(sorted(symbols))}')
                if data.find(b'/libtcl') >= 0 or data.find(b'/libtk') >= 0:
                    findings.append(f'{path.relative_to(app)}: remaining Tcl/Tk native dependency')
    if findings:
        raise ValueError('App Store runtime audit failed:\n' + '\n'.join(findings))
    if not count:
        raise ValueError('App Store runtime audit found no Mach-O binaries')
    return dict(native_files=count, rejected_api_references=0)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['fetch', 'audit'])
    parser.add_argument('app', type=Path, nargs='?')
    args = parser.parse_args()
    if args.operation == 'fetch':
        fetch()
    elif args.app:
        print(json.dumps(audit(args.app), indent=2))
    else:
        parser.error('audit requires an app path')
