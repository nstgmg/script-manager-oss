"""Opt-in real Windows smoke test; creates only uniquely named temporary tasks."""
import os
import platform
import subprocess
import sys
import tempfile
import time
import unittest

from runner.execution import Execution
from runner.schedule import Scheduler
from runner.schedule_doctor import ScheduleDoctor
from runner.store import Store, default_job


@unittest.skipUnless(platform.system() == "Windows" and os.environ.get("SCRIPT_MANAGER_TEST_WINDOWS") == "1",
                     "Set SCRIPT_MANAGER_TEST_WINDOWS=1 on Windows for native Task Scheduler verification")
class NativeWindowsTests(unittest.TestCase):
    def test_register_run_update_and_remove_independent_tasks(self):
        with tempfile.TemporaryDirectory() as root:
            store = Store(root)
            config = default_job("sample")
            config["command"] = [sys.executable, "main.py"]
            store.create(config)
            (store.job_dir("sample") / "main.py").write_text("print('native Windows run', flush=True)\n")
            scheduler = Scheduler(store)
            names = [scheduler.task_name("sample", sid) for sid in ("one", "two")]
            try:
                for sid, seconds in (("one", 60), ("two", 120)):
                    entry = {"id": sid, "name": sid, "enabled": True, "type": "interval",
                             "interval_seconds": seconds}
                    scheduler.save("sample", sid, entry, store.get("sample")["etag"], create=True)
                self.assertTrue(all(scheduler.observed("sample", sid)["loaded"] for sid in ("one", "two")))
                diagnosis = ScheduleDoctor(store, scheduler).scan()
                self.assertFalse(diagnosis["errors"], diagnosis)
                for name in names:
                    row = next(row for row in diagnosis["schedules"] if row["id"] == name)
                    self.assertEqual(row["status"], "healthy", row)
                subprocess.run(["schtasks", "/Run", "/TN", names[0]], check=True, capture_output=True)
                execution = Execution(store)
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    runs = execution.list("sample")
                    if runs and runs[0]["state"] == "succeeded":
                        break
                    time.sleep(0.2)
                else:
                    self.fail("Task Scheduler did not complete a Job run")
                self.assertIn("native Windows run", execution.logs("sample", runs[0]["id"])["text"])
                scheduler.save("sample", "one", None, store.get("sample")["etag"])
                self.assertFalse(scheduler.observed("sample", "one")["loaded"])
                self.assertTrue(scheduler.observed("sample", "two")["loaded"])
            finally:
                for name in names:
                    subprocess.run(["schtasks", "/Delete", "/TN", name, "/F"], capture_output=True)
