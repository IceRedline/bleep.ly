import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


spec = importlib.util.spec_from_file_location(
    'release_bundle', Path(__file__).resolve().parents[1] / 'scripts/release/bundle-macos.py')
bundle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bundle)


class ReleaseCompatibilityTests(unittest.TestCase):
    def test_runtime_cli_audit_does_not_require_app_metadata(self):
        with patch.object(sys, 'argv', ['bundle-macos.py', '--audit-only', '/tmp/site-packages']), \
             patch.object(bundle, 'audit', return_value=([], '15.0')) as native, \
             patch.object(bundle.app_icons, 'audit') as icon:
            bundle.main()
            native.assert_called_once_with(Path('/tmp/site-packages'))
            icon.assert_not_called()

    def test_app_cli_audit_checks_primary_icon(self):
        with patch.object(sys, 'argv', ['bundle-macos.py', '--audit-only', '/tmp/bleeply.app']), \
             patch.object(bundle, 'audit', return_value=([], '15.0')), \
             patch.object(bundle.app_icons, 'audit') as icon:
            bundle.main()
            icon.assert_called_once_with(Path('/tmp/bleeply.app'))

    def audit_fixture(self, build, dependency='/usr/lib/libSystem.B.dylib'):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            folder.chmod(0o755)
            library = folder / 'libtest.dylib'
            library.write_bytes(b'\xcf\xfa\xed\xfe')

            def output(args, **kwargs):
                if args[:2] == ['otool', '-D']:
                    return f'{library}:\n@rpath/libtest.dylib\n'
                if args[:2] == ['otool', '-L']:
                    return f'{library}:\n\t{dependency} (compatibility version 1.0.0)\n'
                if isinstance(build, Exception):
                    raise build
                return build

            with patch.object(bundle.subprocess, 'check_output', side_effect=output):
                return bundle.audit(folder)[1]

    def test_accepts_sequoia_library(self):
        self.assertEqual(self.audit_fixture('cmd LC_BUILD_VERSION\n minos 15.0\n'), '15.0')

    def test_rejects_tahoe_library_instead_of_raising_release_minimum(self):
        with self.assertRaisesRegex(RuntimeError, 'requires macOS 26.2'):
            self.audit_fixture('cmd LC_BUILD_VERSION\n minos 26.2\n')

    def test_reads_legacy_deployment_command(self):
        self.assertEqual(self.audit_fixture('cmd LC_VERSION_MIN_MACOSX\n version 14.0\n'), '14.0')

    def test_missing_or_failed_inspection_cannot_pass(self):
        with self.assertRaisesRegex(RuntimeError, 'Missing macOS deployment target'):
            self.audit_fixture('')
        with self.assertRaises(subprocess.CalledProcessError):
            self.audit_fixture(subprocess.CalledProcessError(1, 'vtool'))

    def test_rejects_dependency_on_build_machine(self):
        with self.assertRaisesRegex(RuntimeError, 'External library'):
            self.audit_fixture('cmd LC_BUILD_VERSION\n minos 15.0\n', '/opt/homebrew/lib/libtest.dylib')
