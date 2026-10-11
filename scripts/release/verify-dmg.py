#!/usr/bin/env python3
"""Verify Finder metadata and every byte copied into the read-only disk image."""
import argparse
import hashlib
from pathlib import Path
import plistlib
import subprocess
from ds_store import DSStore

parser = argparse.ArgumentParser()
parser.add_argument('dmg', type=Path)
parser.add_argument('source_app', type=Path)
args = parser.parse_args()
def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b''):
            value.update(chunk)
    return value.digest()

mounted = plistlib.loads(subprocess.check_output(['hdiutil','attach','-readonly','-nobrowse','-plist',str(args.dmg)]))
volume = Path(next(e['mount-point'] for e in mounted['system-entities'] if 'mount-point' in e))
try:
    assert (volume/'Applications').is_symlink()
    assert (volume/'Applications').readlink() == Path('/Applications')
    with DSStore.open(str(volume/'.DS_Store'), 'r') as store:
        assert tuple(store['bleep.ly.app']['Iloc'])[:2] == (202,236)
        assert tuple(store['Applications']['Iloc'])[:2] == (518,236)
        assert store['.']['icvp']['backgroundType'] == 2
        window = store['.']['bwsp']
        assert window['WindowBounds'] == '{{180, 180}, {720, 560}}', window
        for panel in ['ShowToolbar', 'ShowStatusBar', 'ShowPathbar', 'ShowSidebar', 'ShowTabView']:
            assert window[panel] is False, f'{panel} must be hidden in the installer'
    source = args.source_app.resolve()
    target = volume/source.name
    expected = {p.relative_to(source) for p in source.rglob('*') if p.is_file() or p.is_symlink()}
    actual = {p.relative_to(target) for p in target.rglob('*') if p.is_file() or p.is_symlink()}
    assert actual == expected, f'DMG contents differ: missing={expected-actual}, extra={actual-expected}'
    for relative in sorted(expected):
        a,b = source/relative,target/relative
        if a.is_symlink():
            assert b.is_symlink() and a.readlink() == b.readlink(), relative
        else:
            assert a.stat().st_size == b.stat().st_size and digest(a) == digest(b), relative
    subprocess.run(['codesign','--verify','--deep','--strict',str(target)], check=True)
    print(f'DMG verified: window bounds, hidden panels, Applications link, icon positions, background and {len(expected)} identical files', flush=True)
finally:
    subprocess.run(['hdiutil','detach',str(volume)], check=True)
