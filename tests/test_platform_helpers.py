"""The fixture boundary must not hide unexpected filesystem failures."""
import unittest
from unittest.mock import Mock, patch

from tests.platform_helpers import symlink_or_skip


class SymlinkFixtureTests(unittest.TestCase):
    def test_only_windows_privilege_denial_skips(self):
        denied = OSError("synthetic privilege denial")
        denied.winerror = 1314
        link = Mock()
        link.symlink_to.side_effect = denied
        with patch("tests.platform_helpers.os.name", "nt"):
            with self.assertRaisesRegex(unittest.SkipTest, "WinError 1314"):
                symlink_or_skip(self, link, "target", directory=True)
        link.symlink_to.assert_called_once_with("target", target_is_directory=True)

    def test_other_errors_remain_errors(self):
        for host, code in (("posix", 1314), ("nt", 5), ("nt", None)):
            with self.subTest(host=host, winerror=code):
                error = OSError("synthetic filesystem failure")
                error.winerror = code
                link = Mock()
                link.symlink_to.side_effect = error
                with patch("tests.platform_helpers.os.name", host):
                    with self.assertRaises(OSError) as raised:
                        symlink_or_skip(self, link, "target")
                self.assertIs(raised.exception, error)

    def test_successful_fixture_does_not_skip(self):
        link = Mock()
        with patch("tests.platform_helpers.os.name", "nt"):
            symlink_or_skip(self, link, "target")
        link.symlink_to.assert_called_once_with("target", target_is_directory=False)
