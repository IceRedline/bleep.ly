from datetime import datetime, timedelta, timezone
import hashlib
import json
import importlib.util
import subprocess
from pathlib import Path
import unittest
import sys
import tempfile

SPEC = importlib.util.spec_from_file_location('testflight_packaging', Path(__file__).resolve().parents[1]/'scripts/release/testflight-macos.py')
packaging = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(packaging)


class TestFlightProfileTests(unittest.TestCase):
    def test_candidate_refreshes_engine_without_carrying_old_modules_or_caches(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            project = root/'project'
            source = project/'censor'
            (source/'__pycache__').mkdir(parents=True)
            (source/'desktop.py').write_text('current engine')
            (source/'model_downloads.py').write_text('new consent feature')
            (source/'__pycache__/desktop.pyc').write_bytes(b'cache')
            for name in ['profanity.txt', 'profanity.en.txt']:
                (project/name).write_text('current words')
            app = root/'candidate.app'
            engine = app/'Contents/Resources/Engine'
            (engine/'censor').mkdir(parents=True)
            (engine/'censor/obsolete.py').write_text('old module')
            origin = {'source_commit': 'old', 'python': '3.11.15'}
            (engine/'runtime.json').write_text(json.dumps(origin))
            self.assertEqual(packaging.refresh_engine(app, 'current', project), origin)
            self.assertEqual((engine/'censor/model_downloads.py').read_text(), 'new consent feature')
            self.assertFalse((engine/'censor/obsolete.py').exists())
            self.assertFalse((engine/'censor/__pycache__').exists())
            self.assertEqual(json.loads((engine/'runtime.json').read_text()), {**origin, 'source_commit': 'current'})

    @unittest.skipUnless(sys.platform == 'darwin', 'macOS quarantine metadata')
    def test_quarantine_cleanup_preserves_read_only_file_modes(self):
        with tempfile.TemporaryDirectory() as folder:
            app = Path(folder)
            for name, quarantined in [('LICENSE', False), ('download', True)]:
                path = app/name
                path.write_text('keep')
                if quarantined:
                    subprocess.run(['xattr', '-w', 'com.apple.quarantine', '0081;00000000;test;', str(path)], check=True)
                path.chmod(0o444)
            packaging.clear_quarantine(app)
            for path in app.iterdir():
                self.assertEqual(path.stat().st_mode & 0o777, 0o444)
                self.assertEqual(path.read_text(), 'keep')
                self.assertNotIn('com.apple.quarantine', subprocess.check_output(['xattr', str(path)], text=True))

    def setUp(self):
        certificate = b'fixture certificate bytes'
        self.identity = hashlib.sha1(certificate).hexdigest().upper()
        self.profile = {
            'TeamIdentifier': ['TEAM123456'], 'Platform': ['OSX'],
            'ExpirationDate': datetime.now(timezone.utc) + timedelta(days=30),
            'DeveloperCertificates': [certificate],
            'Entitlements': {'com.apple.application-identifier': 'TEAM123456.ly.bleep.desktop'},
        }

    def validate(self):
        return packaging.validate_profile(self.profile, 'ly.bleep.desktop', self.identity)

    def test_matching_store_profile_enables_sandbox_without_debug_access(self):
        entitlements = self.validate()
        self.assertTrue(entitlements['com.apple.security.app-sandbox'])
        self.assertEqual(entitlements['com.apple.application-identifier'], 'TEAM123456.ly.bleep.desktop')
        self.assertNotIn('com.apple.security.get-task-allow', entitlements)
        self.assertNotIn('com.apple.security.inherit', entitlements)

    def test_development_and_developer_id_profiles_are_rejected(self):
        for field, value in [('ProvisionedDevices', ['device']), ('ProvisionsAllDevices', True)]:
            with self.subTest(field=field):
                self.profile[field] = value
                with self.assertRaises(ValueError):
                    self.validate()
                del self.profile[field]

    def test_wrong_app_platform_certificate_and_expired_profiles_are_rejected(self):
        for field, value in [('Platform', ['iOS']), ('DeveloperCertificates', [b'another cert']),
                             ('ExpirationDate', datetime.now(timezone.utc)-timedelta(days=1))]:
            with self.subTest(field=field):
                original = self.profile[field]
                self.profile[field] = value
                with self.assertRaises(ValueError):
                    self.validate()
                self.profile[field] = original
        self.profile['Entitlements']['com.apple.application-identifier'] = 'TEAM123456.*'
        with self.assertRaises(ValueError):
            self.validate()

    def test_mac_store_profile_does_not_need_ios_beta_reporting_entitlement(self):
        entitlements = self.validate()
        self.assertNotIn('beta-reports-active', entitlements)


if __name__ == '__main__':
    unittest.main()
