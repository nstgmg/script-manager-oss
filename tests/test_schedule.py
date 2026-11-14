from pathlib import Path
import plistlib
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from runner.common import ManagerError
from runner.schedule import Scheduler
from runner.store import Store, default_job, dump_yaml


class LaunchctlFake:
    def __init__(self):
        self.services = set()
        self.disabled_services = set()
        self.calls = []
        self.fail_next_bootstrap = False
        self.paths = {}
        self.definitions = {}

    @property
    def loaded(self):
        return bool(self.services)

    def __call__(self, args, **kwargs):
        self.calls.append(args)
        rc, error = 0, ""
        if args[:2] == ["launchctl", "list"]:
            return subprocess.CompletedProcess(args, 0, "\n".join("-\t0\t" + label for label in self.services), "")
        if args[:2] == ["launchctl", "print-disabled"]:
            return subprocess.CompletedProcess(args, 0, "\n".join('"' + label + '" => true' for label in self.disabled_services), "")
        if args[:2] == ["launchctl", "disable"]:
            self.disabled_services.add(args[2].split("/")[-1])
        if args[:2] == ["launchctl", "enable"]:
            self.disabled_services.discard(args[2].split("/")[-1])
        if args[:2] == ["launchctl", "print"]:
            label = args[2].split("/")[-1]
            rc = 0 if label in self.services else 113
            if rc == 0 and label in self.definitions:
                data = self.definitions[label]
                return subprocess.CompletedProcess(args, 0, "path = " + str(self.paths[label])
                    + "\nprogram = " + data["ProgramArguments"][0] + "\nworking directory = " + data["WorkingDirectory"]
                    + "\narguments = {\n" + "\n".join(data["ProgramArguments"]) + "\n}\n", "")
        if args[:2] == ["launchctl", "bootout"]:
            self.services.discard(args[2].split("/")[-1])
        if args[:2] == ["launchctl", "bootstrap"]:
            if self.fail_next_bootstrap:
                self.fail_next_bootstrap = False
                rc, error = 1, "injected bootstrap failure"
            else:
                data = plistlib.loads(Path(args[-1]).read_bytes())
                self.services.add(data["Label"])
                self.paths[data["Label"]] = Path(args[-1]).resolve()
                self.definitions[data["Label"]] = data
        return subprocess.CompletedProcess(args, rc, "", error)


class ScheduleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(self.temp.name)
        config = default_job("sample")
        config.pop("schedules", None)
        config["schedule"] = {"enabled": True, "times": ["09:30"], "weekdays": [1, 7]}
        self.job = self.store.create(config)
        self.fake = LaunchctlFake()
        self.scheduler = Scheduler(self.store, Path(self.temp.name) / "agents", self.fake)
        patcher = patch("runner.schedule.platform.system", return_value="Darwin")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_calendar_mapping_and_apply_remove(self):
        plan = self.scheduler.plan("sample")
        plist = plistlib.loads(plan["plist"].encode())
        self.assertEqual(plist["StartCalendarInterval"], [
            {"Hour": 9, "Minute": 30, "Weekday": 1}, {"Hour": 9, "Minute": 30, "Weekday": 0}])
        self.scheduler.apply("sample", self.job["etag"])
        self.assertTrue(self.scheduler.observed("sample")["loaded"])
        self.scheduler.remove("sample")
        self.assertFalse(self.fake.loaded)
        self.assertFalse(Path(plan["path"]).exists())

    def test_apply_failure_restores_previous_generation(self):
        original = self.scheduler.apply("sample", self.job["etag"])
        self.fake.fail_next_bootstrap = True
        with self.assertRaises(ManagerError):
            self.scheduler.apply("sample", self.job["etag"])
        self.assertEqual(self.scheduler.state("sample"), original)
        self.assertTrue(self.fake.loaded)

    def test_switch_modes_preserves_settings_and_rolls_back_both_directions(self):
        original = self.store.get("sample")
        previous_schedule = original["config"]["schedule"]
        self.scheduler.apply("sample", original["etag"])
        original_plist = plistlib.loads(Path(self.scheduler.plan("sample")["path"]).read_bytes())
        for desired in (
            {"enabled": True, "mode": "interval", "interval": {"value": 2, "unit": "days"}},
            previous_schedule,
        ):
            before_state = self.scheduler.state("sample")
            path = Path(self.scheduler.plan("sample")["path"])
            before_plist = path.read_bytes()
            current = self.store.get("sample")
            updated = self.store.update_schedule("sample", desired, current["etag"])
            self.assertEqual(path.read_bytes(), before_plist)  # Save never applies.
            self.fake.fail_next_bootstrap = True
            with self.assertRaises(ManagerError):
                self.scheduler.apply("sample", updated["etag"])
            self.assertEqual(self.scheduler.state("sample"), before_state)
            self.assertEqual(path.read_bytes(), before_plist)
            self.assertTrue(self.fake.loaded)
            self.assertEqual(self.store.get("sample")["config"]["schedule"], desired)
            self.scheduler.apply("sample", updated["etag"])
            plist = plistlib.loads(path.read_bytes())
            if desired.get("mode") == "interval":
                self.assertEqual(plist["StartInterval"], 172800)
                self.assertNotIn("StartCalendarInterval", plist)
            else:
                self.assertNotIn("StartInterval", plist)
                self.assertEqual(plist["StartCalendarInterval"], original_plist["StartCalendarInterval"])
            state = self.scheduler.observed("sample")
            self.assertTrue(state["loaded"] and state["file_matches"])
            self.assertEqual(state["etag"], updated["etag"])
            self.assertEqual({k: v for k, v in updated["config"].items() if k != "schedule"},
                             {k: v for k, v in original["config"].items() if k != "schedule"})
        self.scheduler.remove("sample")
        self.assertFalse(path.exists())
        self.assertEqual(self.store.get("sample")["config"]["schedule"], previous_schedule)

    def test_interval_conversion_and_native_plist_validation(self):
        for unit, expected in (("minutes", 120), ("hours", 7200), ("days", 172800)):
            current = self.store.get("sample")
            self.store.update_schedule("sample", {"enabled": True, "mode": "interval",
                "interval": {"value": 2, "unit": unit}}, current["etag"])
            plan = self.scheduler.plan("sample")
            plist = plistlib.loads(plan["plist"].encode())
            self.assertEqual(plist["StartInterval"], expected)
            self.assertNotIn("StartCalendarInterval", plist)
            path = Path(self.temp.name) / "test.plist"
            path.write_text(plan["plist"])
            self.assertEqual(subprocess.run(["plutil", "-lint", str(path)], capture_output=True).returncode, 0)

    def test_conflict_running_guard_and_external_plist_edit(self):
        with self.assertRaises(ManagerError):
            self.scheduler.apply("sample", "stale")
        with self.store.job_lock("sample", "run", False):
            with self.assertRaises(ManagerError):
                self.scheduler.apply("sample", self.job["etag"])
        self.scheduler.apply("sample", self.job["etag"])
        path = Path(self.scheduler.plan("sample")["path"])
        path.write_text("external")
        with self.assertRaises(ManagerError):
            self.scheduler.remove("sample")
        self.assertEqual(path.read_text(), "external")
        self.assertFalse(any(call[:2] == ["launchctl", "kickstart"] for call in self.fake.calls))

    def test_native_plist_validation_without_registration(self):
        path = Path(self.temp.name) / "test.plist"
        path.write_text(self.scheduler.plan("sample")["plist"])
        result = subprocess.run(["plutil", "-lint", str(path)], capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_schedule_editor_preserves_other_settings_and_comments(self):
        initial = self.store.update("sample", "# original comment\n" + self.job["yaml"], self.job["etag"])
        desired = {"enabled": True, "times": ["08:15", "17:45"], "weekdays": [2, 4]}
        updated = self.store.update_schedule("sample", desired, initial["etag"])
        self.assertEqual(updated["config"]["schedule"], desired)
        before, after = dict(initial["config"]), dict(updated["config"])
        del before["schedule"], after["schedule"]
        self.assertEqual(before, after)
        self.assertIn("# original comment", updated["yaml"])
        with self.assertRaises(ManagerError) as cm:
            self.store.update_schedule("sample", {"enabled": False}, initial["etag"])
        self.assertEqual(cm.exception.status, 409)
        self.assertEqual(self.store.get("sample")["yaml"], updated["yaml"])
        with self.assertRaises(ManagerError):
            self.store.update_schedule("sample", {"enabled": True, "times": ["25:00"]}, updated["etag"])

    def test_observation_distinguishes_missing_service_from_error(self):
        self.assertFalse(self.scheduler.observed("sample")["loaded"])
        def error(args, **kwargs):
            return subprocess.CompletedProcess(args, 1, "", "permission denied")
        scheduler = Scheduler(self.store, self.scheduler.agents, error)
        state = scheduler.observed("sample")
        self.assertEqual(state["observation_error"], "permission denied")
        self.assertFalse(state["file_exists"])
