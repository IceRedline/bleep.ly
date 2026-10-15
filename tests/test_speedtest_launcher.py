"""Exercise launcher orchestration without installing software or running ASR."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / 'Run Speed Test.command'


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.work = Path(self.temporary.name)
        self.source = self.work / 'Source with spaces'
        self.source.mkdir()
        shutil.copyfile(LAUNCHER, self.source / LAUNCHER.name)
        (self.source / 'scripts').mkdir()
        (self.source / 'scripts/speedtest.py').touch()
        (self.source / 'benchmarks/fixtures').mkdir(parents=True)
        (self.source / 'benchmarks/turbo-en.json').write_text('{}')
        (self.source / 'benchmarks/fixtures/turbo-en.flac').write_bytes(b'fixture')
        self.output = self.work / 'Reports with spaces'
        self.environment = {**os.environ, 'HOME': str(self.work / 'User Home'),
                            'TEST_SOURCE': str(self.source), 'TEST_RECORD': str(self.work / 'calls')}
        self.base = '''
source "$TEST_SOURCE/Run Speed Test.command"
uname() { if [[ "$1" == -s ]]; then echo Darwin; else echo arm64; fi; }
sw_vers() { echo 15.7; }
open() { :; }
ensure_tools() { step 'Mock setup'; }
run_logged() {
    printf '%s\n' "$*" >> "$TEST_RECORD"
    if [[ "$1" == make ]]; then return "${TEST_SETUP_EXIT:-0}"; fi
    if [[ "$1" == caffeinate ]]; then
        mkdir -p "$RAW_OUTPUT"
        printf '{"test_fixture":true}\n' > "$RAW_OUTPUT/report.json"
        printf 'Mock report\n' > "$RAW_OUTPUT/report.md"
        return "${TEST_WORKER_EXIT:-0}"
    fi
}
'''

    def run_launcher(self, extra='', options=(), env=None):
        script = self.base + '\n' + extra + '\nmain "$@"\n'
        return subprocess.run(['bash', '-c', script, 'test-launcher', '--output', str(self.output), *options],
                              env={**self.environment, **(env or {})}, stdin=subprocess.DEVNULL,
                              capture_output=True, text=True, timeout=10)

    @unittest.skipIf(os.geteuid() == 0, 'Launcher intentionally refuses root')
    def test_archive_with_spaces_runs_all_stages_and_copies_reports(self):
        result = self.run_launcher()
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertTrue(json.loads((self.output / 'report.json').read_text())['test_fixture'])
        self.assertIn('Completed successfully', (self.output / 'status.txt').read_text())
        calls = (self.work / 'calls').read_text()
        self.assertLess(calls.index('verify-audio'), calls.index('speedtest-setup'))
        self.assertLess(calls.index('speedtest-setup'), calls.index('caffeinate'))
        self.assertFalse((Path(self.environment['HOME']) / 'Library/Caches/bleeply-speedtest/running.lock').exists())

    @unittest.skipIf(os.geteuid() == 0, 'Launcher intentionally refuses root')
    def test_setup_failure_never_starts_measurement(self):
        result = self.run_launcher(env={'TEST_SETUP_EXIT': '31'})
        self.assertEqual(result.returncode, 31)
        self.assertNotIn('caffeinate', (self.work / 'calls').read_text())
        self.assertIn('Exit code: 31', (self.output / 'status.txt').read_text())
        self.assertFalse((self.output / 'report.json').exists())

    @unittest.skipIf(os.geteuid() == 0, 'Launcher intentionally refuses root')
    def test_failed_measurement_keeps_partial_report_and_nonzero_status(self):
        result = self.run_launcher(env={'TEST_WORKER_EXIT': '1'})
        self.assertEqual(result.returncode, 1)
        self.assertTrue((self.output / 'report.json').exists())
        self.assertIn('may be incomplete', (self.output / 'status.txt').read_text())
        self.assertNotIn('Completed successfully', result.stdout)

    @unittest.skipIf(os.geteuid() == 0, 'Launcher intentionally refuses root')
    def test_report_copy_failure_does_not_claim_success(self):
        result = self.run_launcher('cp() { return 1; }')
        self.assertEqual(result.returncode, 1)
        self.assertIn('saving reports', (self.output / 'status.txt').read_text())
        self.assertIn('Original reports remain in:', result.stderr)
        self.assertNotIn('Finished. Send these two files', result.stdout)

    @unittest.skipIf(os.geteuid() == 0, 'Launcher intentionally refuses root')
    def test_prepare_only_and_existing_output(self):
        result = self.run_launcher(options=['--prepare-only'])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('No benchmark was run', (self.output / 'status.txt').read_text())
        self.assertNotIn('caffeinate', (self.work / 'calls').read_text())
        before = (self.output / 'status.txt').read_bytes()
        self.assertNotEqual(self.run_launcher().returncode, 0)
        self.assertEqual(before, (self.output / 'status.txt').read_bytes())

    @unittest.skipIf(os.geteuid() == 0, 'Launcher intentionally refuses root')
    def test_concurrent_launcher_is_rejected_without_removing_its_lock(self):
        lock = Path(self.environment['HOME']) / 'Library/Caches/bleeply-speedtest/running.lock'
        lock.mkdir(parents=True)
        (lock / 'pid').write_text(str(os.getpid()))
        result = self.run_launcher()
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(lock.is_dir())
        self.assertIn('already running', result.stderr)

    def test_unsupported_hardware_fails_before_installation(self):
        result = self.run_launcher('uname() { if [[ "$1" == -s ]]; then echo Darwin; else echo x86_64; fi; }; sysctl() { echo 0; }')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Intel Macs are not supported', result.stderr)
        self.assertFalse(self.output.exists())

    def test_logged_command_failure_propagates_through_tee(self):
        result = subprocess.run(['bash', '-c', 'source "$TEST_SOURCE/Run Speed Test.command"; SETUP_LOG="$TEST_RECORD"; run_logged bash -c "exit 17"'],
                                env=self.environment, capture_output=True, text=True)
        self.assertEqual(result.returncode, 17)

    def test_missing_tools_install_only_missing_formulae(self):
        fake = self.work / 'fake brew'
        fake.write_text('''#!/bin/bash
printf '%s\n' "$*" >> "$TEST_RECORD"
case "$1" in
 list) [[ -f "$TEST_SOURCE/$3.installed" ]] ;;
 install) touch "$TEST_SOURCE/$2.installed" ;;
 --prefix) printf '/usr/local\n' ;;
esac
''')
        fake.chmod(0o755)
        script = '''
source "$TEST_SOURCE/Run Speed Test.command"
SETUP_LOG="$TEST_SOURCE/setup.log"
SUPPORT="$TEST_SOURCE"
xcode-select() {
    if [[ "$1" == --install ]]; then touch "$TEST_SOURCE/clt"; else [[ -f "$TEST_SOURCE/clt" ]]; fi
}
xcrun() { [[ -f "$TEST_SOURCE/clt" ]]; }
find_brew() { return 1; }
install_homebrew() { BREW="$TEST_BREW"; printf 'installer\n' >> "$TEST_RECORD"; }
python3.11() { :; }; ffmpeg() { :; }; ffprobe() { :; }
ensure_tools
find_brew() { printf '%s\n' "$TEST_BREW"; }
ensure_tools
'''
        result = subprocess.run(['bash', '-c', script], env={**self.environment, 'TEST_BREW': str(fake)},
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        calls = (self.work / 'calls').read_text()
        self.assertEqual(calls.count('installer'), 1)
        self.assertEqual(calls.count('install python@3.11'), 1)
        self.assertEqual(calls.count('install ffmpeg@8'), 1)


if __name__ == '__main__':
    unittest.main()
