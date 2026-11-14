"""Explicit opt-in macOS smoke: temporary roots and uniquely namespaced OS agents only."""
import os
from pathlib import Path
import platform
import shutil
import subprocess
import tempfile
import unittest

from runner.maintenance import Maintenance
from runner.schedule import Scheduler
from runner.schedule_doctor import ScheduleDoctor
from runner.store import Store, default_job


@unittest.skipUnless(platform.system() == "Darwin" and os.environ.get("SCRIPT_MANAGER_TEST_LAUNCHD") == "1",
                     "Explicit opt-in required for real temporary launchd registrations")
class NativeMaintenanceTests(unittest.TestCase):
    def test_reset_reuse_uninstall_and_reinstalled_orphan_cleanup(self):
        cache = Path(__file__).resolve().parents[1] / ".cache"
        cache.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="maintenance-native-", dir=cache) as folder:
            base = Path(folder)
            first, second = Store(base / "first"), Store(base / "second")
            schedulers = [Scheduler(first), Scheduler(second)]
            labels = []
            def register(store, scheduler):
                item = store.create(default_job("maintenance-test"))
                scheduler.save(item["id"], "daily", {"id": "daily", "name": "temporary test", "type": "calendar",
                    "enabled": True, "times": ["23:59"], "weekdays": [7]}, item["etag"], True)
                label = scheduler.label(item["id"], "daily")
                if label not in labels:
                    labels.append(label)
                return label
            try:
                one = register(first, schedulers[0])
                two = register(second, schedulers[1])
                doctor = ScheduleDoctor(first)
                by_id = {r["id"]: r for r in doctor.scan()["schedules"]}
                self.assertEqual(by_id[one]["status"], "healthy", by_id[one])
                self.assertEqual(by_id[two]["status"], "healthy", by_id[two])
                manager = Maintenance(first)
                plan = manager.preview()
                self.assertFalse(plan["blockers"], plan["blockers"])
                result = manager.execute("reset", plan["plan_hash"])
                self.assertTrue(result["success"], result)
                self.assertTrue(schedulers[1].observed("maintenance-test", "daily")["loaded"])
                self.assertFalse(schedulers[0].observed("maintenance-test", "daily")["loaded"])
                register(first, schedulers[0])
                plan = manager.preview("uninstall")
                self.assertTrue(manager.execute("uninstall", plan["plan_hash"])["success"])
                self.assertTrue(first.root.exists())
                # Simulate the unsafe user action only on this disposable root.
                shutil.rmtree(second.root)
                fresh = Store(base / "reinstall")
                fresh_doctor = ScheduleDoctor(fresh)
                orphan = next(r for r in fresh_doctor.scan()["schedules"] if r["id"] == two)
                self.assertEqual(orphan["status"], "orphan", orphan)
                self.assertTrue(fresh_doctor.remove(two, orphan["fingerprint"])["verified"])
                self.assertFalse(any(r["id"] in labels for r in fresh_doctor.scan()["schedules"]))
            finally:
                # These labels are exclusively this test's random namespaces.
                for label in labels:
                    subprocess.run(["launchctl", "bootout", "gui/" + str(os.getuid()) + "/" + label], capture_output=True)
                    (Path.home() / "Library/LaunchAgents" / (label + ".plist")).unlink(missing_ok=True)
                for label in labels:
                    result = subprocess.run(["launchctl", "print", "gui/" + str(os.getuid()) + "/" + label], capture_output=True)
                    self.assertEqual(result.returncode, 113, "Temporary native reservation survived cleanup")
