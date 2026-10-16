import importlib.util
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts/release'))
SPEC = importlib.util.spec_from_file_location('paired_release',
    Path(__file__).resolve().parents[1]/'scripts/release/paired-release.py')
paired = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(paired)


class PairedReleaseTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.store = Path(self.folder.name)/'Store.app'
        self.direct = Path(self.folder.name)/'Direct.app'
        metadata = dict(CFBundleIdentifier='ly.bleep.desktop', CFBundleShortVersionString='0.1.9',
                        CFBundleVersion='22', LSMinimumSystemVersion='15.0')
        for app in (self.store, self.direct):
            (app/'Contents/Resources').mkdir(parents=True)
            (app/'Contents/Info.plist').write_bytes(plistlib.dumps(
                {**metadata, **({'BleepAppSandbox': True} if app == self.store else {})}))
            (app/'Contents/Resources/model-config.json').write_text('same dependencies')

    def test_channel_metadata_can_differ_but_version_and_build_cannot(self):
        self.assertEqual(paired.verify(self.store, self.direct)['build'], '22')
        for key, value in [('CFBundleVersion', '23'), ('CFBundleShortVersionString', '0.1.10'),
                           ('LSMinimumSystemVersion', '26.0')]:
            with self.subTest(key=key):
                metadata = paired.info(self.direct)
                metadata[key] = value
                with self.assertRaisesRegex(ValueError, 'metadata differs'):
                    paired.validate_pair_metadata(paired.info(self.store), metadata)

    def test_dependency_changes_and_extra_files_are_rejected(self):
        resource = self.direct/'Contents/Resources/model-config.json'
        resource.write_text('different dependencies')
        with self.assertRaisesRegex(ValueError, 'resources differ'):
            paired.verify(self.store, self.direct)
        resource.write_text('same dependencies')
        (self.direct/'Contents/Resources/extra.py').write_text('extra module')
        with self.assertRaisesRegex(ValueError, 'inventories differ'):
            paired.verify(self.store, self.direct)

    def test_profile_is_allowed_only_in_store_app(self):
        (self.store/'Contents/embedded.provisionprofile').write_bytes(b'profile')
        paired.verify(self.store, self.direct)
        (self.direct/'Contents/embedded.provisionprofile').write_bytes(b'profile')
        with self.assertRaisesRegex(ValueError, 'profile leaked'):
            paired.verify(self.store, self.direct)

    @unittest.skipUnless(sys.platform == 'darwin', 'Mach-O signing tools')
    def test_different_signatures_are_allowed_but_changed_native_code_is_rejected(self):
        root = Path(self.folder.name)
        c = root/'probe.c'
        c.write_text('int main(void) { return 0; }')
        binary = root/'probe'
        subprocess.run(['cc', str(c), '-o', str(binary)], check=True)
        for app, identity in [(self.store, 'store'), (self.direct, 'direct')]:
            target = app/'Contents/probe'
            shutil.copy2(binary, target)
            subprocess.run(['codesign', '--force', '--sign', '-', '--identifier', identity, str(target)],
                           check=True, stderr=subprocess.DEVNULL)
        self.assertEqual(paired.verify(self.store, self.direct)['matching_native_files'], 1)
        c.write_text('int main(void) { return 7; }')
        subprocess.run(['cc', str(c), '-o', str(self.direct/'Contents/probe')], check=True)
        with self.assertRaisesRegex(ValueError, 'executable code differs'):
            paired.verify(self.store, self.direct)


if __name__ == '__main__':
    unittest.main()
