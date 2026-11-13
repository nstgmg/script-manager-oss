"""Opt-in test: registers a temporary GUI service, always removes it."""
import os
from pathlib import Path
import platform
import plistlib
import subprocess
import sys
import tempfile
import time
import unittest

from runner.common import ManagerError
from runner.execution import Execution
from runner.schedule import Scheduler
from runner.store import Store, default_job


@unittest.skipUnless(platform.system() == "Darwin" and os.environ.get("SCRIPT_MANAGER_TEST_LAUNCHD") == "1",
                     "Set SCRIPT_MANAGER_TEST_LAUNCHD=1 for a temporary native LaunchAgent test")
class NativeLaunchdTests(unittest.TestCase):
    def test_interval_fires_then_switches_to_calendar_and_removes(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            config = default_job("native-interval-test")
            config["command"] = [sys.executable, "main.py"]
            config.pop("schedules", None)
            config["schedule"] = {"enabled": True, "mode": "interval",
                                  "interval": {"value": 1, "unit": "minutes"}}
            job = store.create(config)
            scheduler = Scheduler(store, Path(directory) / "agents")
            service = "gui/" + str(os.getuid()) + "/" + scheduler.label(job["id"])
            path = Path(scheduler.plan(job["id"])["path"])
            try:
                scheduler.apply(job["id"], job["etag"])
                state = scheduler.observed(job["id"])
                self.assertTrue(state["loaded"] and state["file_matches"])
                self.assertEqual(plistlib.loads(path.read_bytes())["StartInterval"], 60)
                execution = Execution(store)
                deadline = time.monotonic() + 85
                completed = None
                while time.monotonic() < deadline:
                    runs = execution.list(job["id"])
                    if runs and runs[0]["state"] not in ("queued", "running"):
                        completed = runs[0]
                        break
                    time.sleep(.2)
                self.assertIsNotNone(completed, "StartInterval did not execute the Runner")
                self.assertEqual(completed["state"], "succeeded")
                calendar = {"enabled": True, "times": ["23:59"], "weekdays": [7]}
                updated = store.update_schedule(job["id"], calendar, job["etag"])
                scheduler.apply(job["id"], updated["etag"])
                self.assertNotIn("StartInterval", plistlib.loads(path.read_bytes()))
                self.assertTrue(scheduler.observed(job["id"])["loaded"])
                scheduler.remove(job["id"])
                self.assertFalse(scheduler.observed(job["id"])["loaded"])
                self.assertFalse(path.exists())
                self.assertEqual(store.get(job["id"])["config"]["schedule"], calendar)
            finally:
                subprocess.run(["launchctl", "bootout", service], capture_output=True)

    def test_register_invoke_verify_remove(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            config = default_job("native-test")
            config["command"] = [sys.executable, "main.py"]
            config.pop("schedules", None)
            config["schedule"] = {"enabled": True, "times": ["23:59"], "weekdays": [7]}
            job = store.create(config)
            scheduler = Scheduler(store, Path(directory) / "agents")
            label = scheduler.label("native-test")
            service = "gui/" + str(os.getuid()) + "/" + label
            try:
                scheduler.apply("native-test", job["etag"])
                self.assertTrue(scheduler.observed("native-test")["loaded"])
                subprocess.run(["launchctl", "kickstart", service], check=True, capture_output=True)
                execution = Execution(store)
                deadline = time.monotonic() + 20
                completed = None
                while time.monotonic() < deadline:
                    runs = execution.list("native-test")
                    if runs and runs[0]["state"] not in ("queued", "running"):
                        completed = runs[0]
                        break
                    time.sleep(0.1)
                self.assertIsNotNone(completed, "launchd did not execute the Runner")
                self.assertEqual(completed["state"], "succeeded")
                scheduler.remove("native-test")
                self.assertFalse(scheduler.observed("native-test")["loaded"])
            finally:
                subprocess.run(["launchctl", "bootout", service], capture_output=True)

    def test_multiple_native_agents_are_independent_and_share_run_guard(self):
        from runner.store import dump_yaml
        from tests.test_multi_schedule import calendar, interval
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            config = default_job("native-multi-test")
            config["command"] = [sys.executable, "main.py"]
            item = store.create(config)
            scheduler = Scheduler(store, Path(directory) / "agents")
            job = item["id"]
            services = ["gui/" + str(os.getuid()) + "/" + scheduler.label(job, sid) for sid in ("morning", "check")]
            try:
                first = scheduler.save(job, "morning", {**calendar(), "times": ["23:59"]}, item["etag"], True)
                scheduler.save(job, "check", {**interval(), "interval_seconds": 2}, first["job"]["etag"], True)
                original = scheduler.state(job, "morning")
                execution = Execution(store)
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    runs = execution.list(job)
                    if runs and runs[0]["state"] == "succeeded":
                        break
                    time.sleep(.1)
                self.assertTrue(runs and runs[0]["state"] == "succeeded", "Native interval did not fire")
                self.assertEqual(runs[0]["schedule_id"], "check")
                item = store.get(job)
                scheduler.save(job, "check", {**interval(), "interval_seconds": 3600}, item["etag"])
                self.assertEqual(scheduler.state(job, "morning"), original)
                # OS invokes both labels while a manual run holds the common Job lock.
                (store.job_dir(job) / "main.py").write_text("import time; time.sleep(3)\n")
                manual = execution.start(job)
                for service in services:
                    subprocess.run(["launchctl", "kickstart", service], check=True, capture_output=True)
                deadline = time.monotonic() + 8
                while time.monotonic() < deadline:
                    last = [store.runtime / "schedules" / (job + "." + sid + ".last.json") for sid in ("morning", "check")]
                    if all(p.exists() and "error" in p.read_text() for p in last):
                        break
                    time.sleep(.1)
                self.assertTrue(all(p.exists() and "error" in p.read_text() for p in last))
                self.assertEqual(len(execution.list(job)), 2)
                while execution.get(job, manual["id"])["state"] in ("queued", "running"):
                    time.sleep(.1)
                for enabled in (False, True):
                    item = store.get(job)
                    scheduler.save(job, "check", {**interval(), "enabled": enabled}, item["etag"])
                    self.assertEqual(scheduler.observed(job, "check")["loaded"], enabled)
                    self.assertTrue(scheduler.observed(job, "morning")["loaded"])
                scheduler.save(job, "check", None, store.get(job)["etag"])
                self.assertFalse(scheduler.observed(job, "check")["file_exists"])
                self.assertTrue(scheduler.observed(job, "morning")["loaded"])
                scheduler.save(job, "morning", None, store.get(job)["etag"])
                self.assertFalse(scheduler.has_registration(job))
            finally:
                for service in services:
                    subprocess.run(["launchctl", "bootout", service], capture_output=True)
