"""Exercise the actual Apple catalog compiler used by all packaging paths."""
import json
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts/release'))
import app_icons


@unittest.skipUnless(sys.platform == 'darwin', 'Requires Apple asset tools')
class AppIconPackagingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.app = Path(cls.temporary.name) / 'Probe.app'
        (cls.app / 'Contents').mkdir(parents=True)
        cls.info = cls.app / 'Contents/Info.plist'
        cls.info.write_bytes(plistlib.dumps(dict(
            CFBundleIdentifier='ly.bleep.iconprobe', CFBundleVersion='23',
            LSMinimumSystemVersion='15.0')))
        app_icons.build(cls.app)
        cls.metadata = cls.info.read_bytes()

    def test_primary_icon_and_theme_survive_the_same_compilation(self):
        info = plistlib.loads(self.metadata)
        self.assertEqual(info['CFBundleIconName'], 'AppIcon')
        self.assertEqual(info['NSAccentColorName'], 'AccentColor')
        self.assertEqual(info['CFBundleVersion'], '23')
        entries = json.loads(subprocess.check_output([
            'xcrun', 'assetutil', '--info',
            str(self.app / 'Contents/Resources/Assets.car')], text=True))
        self.assertTrue({'AppIcon', 'AccentColor', 'HeaderLogo'}.issubset(
            {item.get('Name') for item in entries}))
        self.assertEqual(app_icons.audit(self.app)['store_icon'], '1024x1024')

    def test_missing_primary_icon_metadata_is_rejected(self):
        info = plistlib.loads(self.metadata)
        del info['CFBundleIconName']
        self.info.write_bytes(plistlib.dumps(info))
        try:
            with self.assertRaisesRegex(ValueError, 'primary AppIcon'):
                app_icons.audit(self.app)
        finally:
            self.info.write_bytes(self.metadata)

    def test_theme_only_catalog_cannot_silently_replace_the_icon(self):
        resources = self.app / 'Contents/Resources'
        original = (resources / 'Assets.car').read_bytes()
        with tempfile.TemporaryDirectory() as folder:
            # Reproduce the old packaging layout with a valid standalone ICNS.
            subprocess.run(['xcrun', 'actool',
                str(app_icons.ROOT / 'macOS/Resources/Theme.xcassets'),
                '--compile', folder, '--platform', 'macosx',
                '--minimum-deployment-target', '15.0'], check=True,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            shutil.copyfile(Path(folder) / 'Assets.car', resources / 'Assets.car')
        try:
            with self.assertRaisesRegex(ValueError, '1024x1024 AppIcon'):
                app_icons.audit(self.app)
        finally:
            (resources / 'Assets.car').write_bytes(original)


if __name__ == '__main__':
    unittest.main()
