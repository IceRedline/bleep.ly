import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('pyav_distribution', Path(__file__).resolve().parents[1]/'scripts/release/pyav_distribution.py')
pyav = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pyav)


class PyAVDistributionTests(unittest.TestCase):
    def fixture(self, root):
        for runtime in ['Python', 'PythonGPU']:
            libs = root/'Contents/Resources/Runtime'/runtime/'lib/python3.11/site-packages/av/.dylibs'
            libs.mkdir(parents=True)
            for name in ['avcodec', 'avdevice', 'avfilter', 'avformat', 'avutil', 'swresample', 'swscale']:
                (libs/f'lib{name}.1.2.3.dylib').write_bytes(b'--disable-gpl --disable-nonfree --disable-version3')
        return libs

    def test_both_runtimes_are_audited_and_upstream_wheel_cannot_slip_back(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(pyav, 'SOURCE_HASHES', {}):
            root = Path(temporary)
            libs = self.fixture(root)
            pyav.audit(root)
            codec = libs/'libavcodec.1.2.3.dylib'
            original = codec.read_bytes()
            for configuration in [b'--enable-libx264', b'--enable-libx265', b'--enable-gpl', b'--enable-nonfree', b'--enable-version3']:
                codec.write_bytes(original + b' ' + configuration)
                with self.subTest(configuration=configuration), self.assertRaisesRegex(ValueError, 'Incompatible'):
                    pyav.audit(root)
            codec.write_bytes(b'unknown upstream wheel')
            with self.assertRaisesRegex(ValueError, 'Unverified'):
                pyav.audit(root)
            codec.write_bytes(original)
            (libs/'libx264.165.dylib').touch()
            with self.assertRaisesRegex(ValueError, 'GPL codec'):
                pyav.audit(root)

    def test_missing_libraries_or_corresponding_sources_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            libs = self.fixture(root)
            with self.assertRaises(FileNotFoundError):
                pyav.audit(root)
            sources = root/'Contents/Resources/ThirdParty/Sources'
            sources.mkdir(parents=True)
            (sources/'ffmpeg-8.1.2.tar.xz').write_bytes(b'not the matching source')
            with self.assertRaisesRegex(ValueError, 'corresponding source'):
                pyav.audit(root)
            (libs/'libavcodec.1.2.3.dylib').unlink()
            with self.assertRaisesRegex(ValueError, 'seven'):
                pyav.audit(root)


if __name__ == '__main__':
    unittest.main()
