"""Host boundaries for synthetic OS fixtures; never changes OS permissions."""
import os
from unittest.mock import patch


def mock_launchd(test):
    """Select launchd before Scheduler construction and supply its synthetic UID.

    All launchctl/plutil calls must still go through an explicit command fake.
    This tests the adapter on any host, not native macOS registration.
    """
    for patcher in (patch("runner.schedule.platform.system", return_value="Darwin"),
                    patch("runner.schedule.os.getuid", return_value=501, create=True)):
        patcher.start()
        test.addCleanup(patcher.stop)


def symlink_or_skip(test, link, target, *, directory=False):
    """Skip only a real Windows symlink privilege denial, never a product error."""
    try:
        link.symlink_to(target, target_is_directory=directory)
    except OSError as exc:
        if os.name == "nt" and getattr(exc, "winerror", None) == 1314:
            test.skipTest("Windows symlink fixture requires privilege (WinError 1314); "
                          "real link rejection was not verified")
        raise
