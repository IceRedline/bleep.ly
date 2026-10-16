import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('app_store_runtime',
    Path(__file__).resolve().parents[1]/'scripts/release/app_store_runtime.py')
runtime = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runtime)


class AppStoreRuntimeTests(unittest.TestCase):
    def test_rejected_symbols_are_detected_in_nested_native_payloads(self):
        for symbol in runtime.REJECTED_APIS:
            with self.subTest(symbol=symbol), tempfile.TemporaryDirectory() as folder:
                app = Path(folder)
                binary = app/'Contents/Runtime/nested/library.so'
                binary.parent.mkdir(parents=True)
                binary.write_bytes(b'\xcf\xfa\xed\xfe\0' + symbol + b'\0')
                with self.assertRaisesRegex(ValueError, symbol.decode()):
                    runtime.audit(app)

    def test_openblas_implementation_symbols_and_documentation_are_not_apple_imports(self):
        with tempfile.TemporaryDirectory() as folder:
            app = Path(folder)
            (app/'library.so').write_bytes(b'\xcf\xfa\xed\xfe\0_scipy_dcabs1_\0_scipy_lsame_\0_scipy_xerbla_array_\0')
            (app/'review-notes.txt').write_bytes(b'\0'.join(runtime.REJECTED_APIS))
            self.assertEqual(runtime.audit(app), {'native_files': 1, 'rejected_api_references': 0})

    def test_tk_removal_cannot_leave_a_native_tk_consumer(self):
        with tempfile.TemporaryDirectory() as folder:
            app = Path(folder)
            (app/'consumer.so').write_bytes(b'\xcf\xfa\xed\xfe\0@loader_path/../libtcl9.0.dylib\0')
            with self.assertRaisesRegex(ValueError, 'Tcl/Tk native dependency'):
                runtime.audit(app)

    def test_remove_optional_gui_stack_preserves_engine_and_unrelated_libraries(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            remove = ['lib/libtcl9tk9.0.dylib', 'lib/libtcl9.0.dylib', 'lib/tk9.0/tk.tcl',
                      'lib/tcl9.0/init.tcl', 'lib/itcl4.3.5/libtcl9itcl.dylib',
                      'lib/thread3.0.4/libtcl9thread.dylib', 'lib/python3.11/tkinter/__init__.py',
                      'lib/python3.11/lib-dynload/_tkinter.cpython-311-darwin.so']
            keep = ['lib/libpython3.11.dylib', 'lib/python3.11/site-packages/torch/__init__.py',
                    'lib/python3.11/lib-dynload/_ssl.cpython-311-darwin.so']
            for name in remove + keep:
                path = root/name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('original')
            runtime.remove_tk(root)
            self.assertTrue(all(not (root/name).exists() for name in remove))
            self.assertTrue(all((root/name).read_text() == 'original' for name in keep))
            self.assertEqual(runtime.remove_tk(root), [])

    def test_wrong_wheel_is_rejected_before_mutating_candidate(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root/runtime.WHEEL).write_bytes(b'untrusted download')
            with patch.object(runtime, 'remove_tk') as remove:
                with self.assertRaisesRegex(ValueError, 'checksum'):
                    runtime.install(root/'App.app', cache=root)
                remove.assert_not_called()
            self.assertFalse((root/'App.app').exists())

    def test_empty_payload_cannot_pass(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError, 'no Mach-O'):
                runtime.audit(Path(folder))


if __name__ == '__main__':
    unittest.main()
