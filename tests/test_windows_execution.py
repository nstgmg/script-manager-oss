"""Windows monitor behavior with native Job Object calls replaced on a POSIX host."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from runner.common import windows_lease_active, write_json
from runner.execution import monitor_windows


class FakeWindowsJob:
    def __init__(self, proc):
        self.proc = proc
        self.assigned = True

    def terminate(self):
        self.proc.kill()

    def close(self):
        pass


class WindowsExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        patcher = patch("runner.execution.WindowsJob", FakeWindowsJob)
        patcher.start()
        self.addCleanup(patcher.stop)
        flag = patch.object(subprocess, "CREATE_NEW_PROCESS_GROUP", 0, create=True)
        flag.start()
        self.addCleanup(flag.stop)

    def run_script(self, source, timeout=3, cancelled=lambda: False):
        return monitor_windows([sys.executable, "-c", source], self.folder, os.environ.copy(),
                               timeout, self.folder, cancelled, lambda _: None)

    def test_logs_success_and_failure(self):
        self.assertEqual(self.run_script("print('hello'); import sys; print('err', file=sys.stderr)")["state"], "succeeded")
        self.assertIn("hello", (self.folder / "stdout.log").read_text())
        self.assertIn("err", (self.folder / "stderr.log").read_text())
        self.assertEqual(self.run_script("raise RuntimeError('failed')")["state"], "failed")

    def test_timeout_and_cancel(self):
        self.assertEqual(self.run_script("import time; time.sleep(30)", timeout=0.1)["state"], "timed_out")
        self.assertEqual(self.run_script("import time; time.sleep(30)", cancelled=lambda: True)["state"], "cancelled")

    def test_run_lease_blocks_overlap_and_clears_stale_owner(self):
        path = self.folder / "sample.run.active"
        write_json(path, {"run_id": "one", "pid": 42, "created": time.time() - 60})
        with patch("runner.common.windows_pid_alive", return_value=True):
            self.assertTrue(windows_lease_active(path))
            self.assertTrue(path.exists())
        with patch("runner.common.windows_pid_alive", return_value=False):
            self.assertFalse(windows_lease_active(path))
            self.assertFalse(path.exists())
