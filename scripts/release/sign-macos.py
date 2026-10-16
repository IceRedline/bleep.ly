#!/usr/bin/env python3
"""Sign nested code from the inside out; never use --deep as a signing shortcut."""
import argparse
import concurrent.futures
import importlib.util
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('bundle', Path(__file__).with_name('bundle-macos.py'))
bundle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bundle)
parser = argparse.ArgumentParser()
parser.add_argument('--identity', required=True)
parser.add_argument('app', type=Path)
args = parser.parse_args()
bundle.normalize_permissions(args.app)
bundle.app_icons.audit(args.app)
bundle.app_store_runtime.audit(args.app)
bundle.app_store_runtime.audit_distribution(args.app)
files, minimum = bundle.audit(args.app)
files = [p for p in files if p != args.app/'Contents/MacOS/Bleep']
def sign(path):
    command = ['codesign', '--force', '--sign', args.identity, '--timestamp', '--options', 'runtime']
    if path.name.startswith('python') and path.parent.name == 'bin':
        command += ['--entitlements', str(ROOT/'scripts/release/python.entitlements')]
    result = subprocess.run([*command, str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    if result.returncode:
        raise RuntimeError(f'{path}: {result.stderr}')
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
    for index, _ in enumerate(pool.map(sign, files), 1):
        if index % 50 == 0: print(f'Signed {index}/{len(files)} native files', flush=True)
subprocess.run(['codesign', '--force', '--sign', args.identity, '--timestamp', '--options', 'runtime', str(args.app)], check=True)
subprocess.run(['codesign', '--verify', '--deep', '--strict', '--verbose=2', str(args.app)], check=True)
print(f'Signed app ({len(files)} native files, minimum macOS {minimum})')
