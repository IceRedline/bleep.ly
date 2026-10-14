#!/usr/bin/env python3
"""Draw a Retina installer background and write Finder's drag-to-Applications layout."""
import argparse
import math
from pathlib import Path
import plistlib
import subprocess
import sys
from PIL import Image, ImageDraw, ImageFont
import dmgbuild

ROOT = Path(__file__).resolve().parents[2]
parser = argparse.ArgumentParser()
parser.add_argument('--version', default='0.1.6')
parser.add_argument('--background-only', action='store_true')
args = parser.parse_args()
folder = ROOT/'build/release'
folder.mkdir(parents=True, exist_ok=True)
scale = 2
# Finder can restore its path/status bars despite the per-window preferences.
# Reserve vertical space for that chrome as well as the installation captions.
window_size = (720, 560)
image = Image.new('RGB', tuple(value * scale for value in window_size))
pixels = image.load()
for y in range(image.height):
    for x in range(image.width):
        glow = math.exp(-(((x-1100)/850)**2 + ((y-80)/650)**2))
        pixels[x,y] = (int(244+7*glow), int(245+7*glow), int(241-17*glow))
draw = ImageDraw.Draw(image)
font_path = Path('/System/Library/Fonts/Supplemental')
def text(x, y, value, size, color, bold=False, anchor='la'):
    font = ImageFont.truetype(str(font_path/('Arial Bold.ttf' if bold else 'Arial.ttf')), size*scale)
    draw.text((x*scale, y*scale), value, font=font, fill=color, anchor=anchor)
text(48, 38, 'bleep.ly', 34, '#20241b', bold=True)
text(672, 51, f'v{args.version}', 12, '#747a6c', anchor='ra')
text(48, 91, 'Keep the story. Bleep the rest.', 17, '#606756')
# Finder places the real, draggable icons over these quiet rounded wells.
for x in [202, 518]:
    draw.rounded_rectangle(((x-88)*2, 157*2, (x+88)*2, 335*2), radius=28*2,
                           fill='#ffffff', outline='#e3e6dc', width=2)
draw.rounded_rectangle((320*2, 215*2, 400*2, 257*2), radius=21*2, fill='#e2f36d')
draw.line([(340*2,236*2),(380*2,236*2)], fill='#374323', width=3*2)
draw.line([(371*2,228*2),(380*2,236*2),(371*2,244*2)], fill='#374323', width=3*2, joint='curve')
text(360, 375, 'Drag bleep.ly into Applications', 20, '#252c1e', bold=True, anchor='ma')
text(360, 412, 'Local processing. Your recordings stay on your Mac.', 13, '#717868', anchor='ma')
background = folder/'dmg-background.tiff'
image.save(background, dpi=(144,144), compression='tiff_lzw')
image.resize(window_size, Image.Resampling.LANCZOS).save(folder/'dmg-background.png')
if args.background_only:
    raise SystemExit()
app = folder/'bleep.ly.app'
info = plistlib.loads((app/'Contents/Info.plist').read_bytes())
assert info['CFBundleShortVersionString'] == args.version
out = ROOT/'dist'
out.mkdir(exist_ok=True)
if (out/f'bleep.ly-{args.version}-arm64.dmg').exists():
    parser.error('DMG already exists; preserve the previous signed image before rebuilding')
dmgbuild.build_dmg(str(out/f'bleep.ly-{args.version}-arm64.dmg'), f'bleep.ly {args.version}', settings={
    # Tens of thousands of runtime files need more HFS+ metadata space than
    # dmgbuild's default estimate (which can silently truncate a ditto copy).
    'format': 'UDZO', 'filesystem': 'HFS+', 'size': '4g',
    'files': [str(app)], 'symlinks': {'Applications': '/Applications'},
    'background': str(background), 'badge_icon': str(app/'Contents/Resources/AppIcon.icns'),
    'window_rect': ((180,180),window_size), 'default_view': 'icon-view',
    'icon_locations': {'bleep.ly.app': (202,236), 'Applications': (518,236)},
    'icon_size': 96, 'text_size': 13,
    'show_toolbar': False, 'show_status_bar': False, 'show_sidebar': False,
    'show_pathbar': False, 'show_tab_view': False,
})
subprocess.run([sys.executable, str(Path(__file__).with_name('verify-dmg.py')),
                str(out/f'bleep.ly-{args.version}-arm64.dmg'), str(app)], check=True)
