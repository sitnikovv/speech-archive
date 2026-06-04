import unittest
from speech_archive_lib import env


class EnvTests(unittest.TestCase):
    def test_module_available_handles_missing_parent_package(self):
        self.assertFalse(env.module_available('definitely_missing_parent.child'))


if __name__ == '__main__':
    unittest.main()
