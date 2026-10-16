"""Compile the primary macOS icon and theme together, including Store metadata."""
import argparse
import json
from pathlib import Path
import plistlib
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]


def build(app, project=ROOT):
    app = Path(app)
    resources = app / 'Contents/Resources'
    info_path = app / 'Contents/Info.plist'
    info = plistlib.loads(info_path.read_bytes())
    resources.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='bleep-assets-') as temporary:
        work = Path(temporary)
        catalog = work / 'Assets.xcassets'
        shutil.copytree(project / 'macOS/Resources/Theme.xcassets', catalog)
        icons = catalog / 'AppIcon.appiconset'
        icons.mkdir()
        images = []
        for size in (16, 32, 128, 256, 512):
            for scale in (1, 2):
                name = 'icon_{}x{}@{}x.png'.format(size, size, scale)
                pixels = str(size * scale)
                subprocess.run(['sips', '-s', 'format', 'png', '-z', pixels, pixels,
                                str(project / 'icon.PNG'), '--out', str(icons / name)],
                               check=True, stdout=subprocess.DEVNULL)
                images.append(dict(idiom='mac', size='{}x{}'.format(size, size),
                                   scale='{}x'.format(scale), filename=name))
        (icons / 'Contents.json').write_text(json.dumps(
            dict(images=images, info=dict(author='xcode', version=1)), indent=2) + '\n')
        partial = work / 'asset-info.plist'
        subprocess.run(['xcrun', 'actool', str(catalog), '--compile', str(resources),
                        '--platform', 'macosx', '--minimum-deployment-target',
                        info['LSMinimumSystemVersion'], '--accent-color', 'AccentColor',
                        '--app-icon', 'AppIcon', '--output-partial-info-plist', str(partial)], check=True)
        # actool supplies both the legacy file and the asset-catalog icon name.
        # Keep its metadata, rather than guessing keys independently of its output.
        info.update(plistlib.loads(partial.read_bytes()))
        info_path.write_bytes(plistlib.dumps(info))
    return audit(app)


def audit(app):
    app = Path(app)
    info = plistlib.loads((app / 'Contents/Info.plist').read_bytes())
    if info.get('CFBundleIconName') != 'AppIcon':
        raise ValueError('Missing primary AppIcon asset metadata; compile icon and theme together')
    icon_file = info.get('CFBundleIconFile', '')
    if icon_file not in ('AppIcon', 'AppIcon.icns'):
        raise ValueError('Primary icon must use the compiled AppIcon.icns fallback')
    resources = app / 'Contents/Resources'
    if not (resources / 'AppIcon.icns').is_file():
        raise ValueError('Missing compiled AppIcon.icns fallback')
    entries = json.loads(subprocess.check_output(
        ['xcrun', 'assetutil', '--info', str(resources / 'Assets.car')], text=True))
    icons = [item for item in entries if item.get('Name') == 'AppIcon']
    if not any(item.get('PixelWidth') == 1024 and item.get('PixelHeight') == 1024 for item in icons):
        raise ValueError('Missing 1024x1024 AppIcon rendition in Assets.car')
    return dict(primary_icon=info['CFBundleIconName'], icon_renditions=len(icons), store_icon='1024x1024')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['build', 'audit'])
    parser.add_argument('app', type=Path)
    args = parser.parse_args()
    print(json.dumps(build(args.app) if args.operation == 'build' else audit(args.app)))
