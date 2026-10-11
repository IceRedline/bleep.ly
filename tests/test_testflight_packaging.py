from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
from pathlib import Path
import unittest

SPEC = importlib.util.spec_from_file_location('testflight_packaging', Path(__file__).resolve().parents[1]/'scripts/release/testflight-macos.py')
packaging = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(packaging)


class TestFlightProfileTests(unittest.TestCase):
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
