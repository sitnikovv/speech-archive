import io
import importlib.util
import sys
import unittest
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "07_name_speakers.py"


def load_script_module():
    spec = importlib.util.spec_from_file_location("name_speakers_script", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class BytesStdin:
    def __init__(self, data: bytes):
        self.buffer = io.BytesIO(data)


class FakeTtyStdin:
    def isatty(self):
        return True

    def fileno(self):
        return 123


class SpeakerInputTests(unittest.TestCase):
    def test_read_prompt_utf8_keeps_valid_utf8(self):
        module = load_script_module()
        old_stdin, old_stdout, old_stderr = sys.stdin, sys.stdout, sys.stderr
        try:
            sys.stdin = BytesStdin("Иван\n".encode("utf-8"))
            sys.stdout = io.StringIO()
            sys.stderr = io.StringIO()
            self.assertEqual(module.read_prompt_utf8("Имя: "), "Иван")
            self.assertEqual(sys.stderr.getvalue(), "")
        finally:
            sys.stdin, sys.stdout, sys.stderr = old_stdin, old_stdout, old_stderr

    def test_read_prompt_utf8_drops_malformed_bytes_with_warning(self):
        module = load_script_module()
        old_stdin, old_stdout, old_stderr = sys.stdin, sys.stdout, sys.stderr
        try:
            sys.stdin = BytesStdin(b"IV\xd0R\n")
            sys.stdout = io.StringIO()
            sys.stderr = io.StringIO()
            self.assertEqual(module.read_prompt_utf8("Имя: "), "IVR")
            self.assertIn("не-UTF-8", sys.stderr.getvalue())
            self.assertIn("4956d0520a", sys.stderr.getvalue())
        finally:
            sys.stdin, sys.stdout, sys.stderr = old_stdin, old_stdout, old_stderr
    def test_enable_utf8_erase_sets_iutf8_on_tty(self):
        module = load_script_module()
        attrs = [0, 0, 0, 0, 0, 0, []]
        with mock.patch.object(module.termios, "tcgetattr", return_value=attrs.copy()) as getattrs, \
             mock.patch.object(module.termios, "tcsetattr") as setattrs:
            self.assertTrue(module.enable_utf8_erase(FakeTtyStdin()))
        getattrs.assert_called_once_with(123)
        setattrs.assert_called_once()
        self.assertEqual(setattrs.call_args.args[0], 123)
        self.assertEqual(setattrs.call_args.args[1], module.termios.TCSANOW)
        self.assertTrue(setattrs.call_args.args[2][0] & module.termios.IUTF8)

    def test_enable_utf8_erase_skips_non_tty(self):
        module = load_script_module()
        stdin = mock.Mock()
        stdin.isatty.return_value = False
        with mock.patch.object(module.termios, "tcgetattr") as getattrs:
            self.assertFalse(module.enable_utf8_erase(stdin))
        getattrs.assert_not_called()


if __name__ == "__main__":
    unittest.main()
