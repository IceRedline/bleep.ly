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
                    wheel_url=URL, removed_optional_tk=removed)
    third_party = app/'Contents/Resources/ThirdParty'
    third_party.mkdir(parents=True, exist_ok=True)
    (third_party/'app-store-runtime.json').write_text(json.dumps(metadata, indent=2)+'\n')
    audit(app)
    return metadata


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
