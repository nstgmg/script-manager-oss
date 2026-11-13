import copy
import json
from pathlib import Path
import plistlib
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from runner.common import ManagerError, digest, write_json
from runner.execution import Execution
from runner.schedule import Scheduler
from runner.store import Store, default_job, dump_yaml, schedules, validate
from tests.test_schedule import LaunchctlFake
from tests import test_deployments as deployment_tests


def calendar(sid="morning", enabled=True):
    return {"id": sid, "name": "평일 오전", "enabled": enabled, "type": "calendar",
            "times": ["08:00"], "weekdays": [1, 2, 3, 4, 5]}


def interval(sid="check", enabled=True):
    return {"id": sid, "name": "주기 확인", "enabled": enabled, "type": "interval", "interval_seconds": 1800}


class MultiScheduleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(self.temp.name)
        config = default_job("sample")
        config["command"] = [sys.executable, "main.py"]
        self.store.create(config)
        self.store.create(default_job("other"))
        self.fake = LaunchctlFake()
        self.scheduler = Scheduler(self.store, Path(self.temp.name) / "agents", self.fake)
        patcher = patch("runner.schedule.platform.system", return_value="Darwin")
        patcher.start()
        self.addCleanup(patcher.stop)

    def save(self, entry, create=False, job="sample"):
        return self.scheduler.save(job, entry["id"], entry, self.store.get(job)["etag"], create)

    def test_mixed_schedules_independent_edit_pause_resume_delete_and_other_job(self):
        self.save(calendar(), True)
        self.save(interval(), True)
        self.save(calendar("evening"), True, "other")
        first = self.scheduler.state("sample", "morning")
        other = self.scheduler.state("other", "evening")
        path = Path(self.scheduler.plan("sample", schedule_id="morning")["path"])
        first_plist = path.read_bytes()
        for enabled in (False, True):
            result = self.save({**interval(), "enabled": enabled, "interval_seconds": 15})
            self.assertEqual(result["state"]["loaded"], enabled)
            self.assertEqual(self.scheduler.state("sample", "morning"), first)
            self.assertEqual(path.read_bytes(), first_plist)
            self.assertTrue(self.scheduler.observed("sample", "morning")["desired_matches"])
        self.scheduler.save("sample", "check", None, self.store.get("sample")["etag"])
        self.assertFalse(self.scheduler.observed("sample", "check")["loaded"])
        self.assertEqual(len(schedules(self.store.get("sample")["config"])), 1)
        self.assertEqual(self.scheduler.state("other", "evening"), other)
        self.assertEqual(len(self.fake.services), 2)
        self.assertEqual(plistlib.loads(first_plist)["StartCalendarInterval"][0]["Hour"], 8)

    def test_failed_create_edit_delete_restore_exact_yaml_and_all_os_states(self):
        self.save(calendar(), True)
        current = self.store.get("sample")
        previous = self.scheduler.state("sample", "morning")
        self.fake.fail_next_bootstrap = True
        with self.assertRaisesRegex(ManagerError, "복구 완료"):
            self.save({**calendar(), "times": ["09:00"]})
        self.assertEqual(self.store.get("sample")["yaml"], current["yaml"])
        self.assertEqual(self.scheduler.state("sample", "morning"), previous)
        self.fake.fail_next_bootstrap = True
        with self.assertRaises(ManagerError):
            self.save(interval(), True)
        self.assertEqual(self.store.get("sample")["etag"], current["etag"])
        self.assertTrue(self.scheduler.observed("sample", "morning")["loaded"])
        original_command = self.scheduler.command
        def fail_bootout(args, **kwargs):
            if args[:2] == ["launchctl", "bootout"]:
                raise OSError("injected bootout failure")
            return original_command(args, **kwargs)
        self.scheduler.command = fail_bootout
        with self.assertRaises(ManagerError):
            self.scheduler.save("sample", "morning", None, current["etag"])
        self.assertEqual(self.store.get("sample")["yaml"], current["yaml"])

    def test_legacy_migration_transfers_registration_without_duplicates_and_keeps_source(self):
        item = self.store.get("sample")
        config = item["config"]
        config.pop("schedules")
        config["schedule"] = {"enabled": True, "mode": "interval", "interval": {"value": 2, "unit": "hours"}}
        item = self.store.update("sample", "# keep me\n" + dump_yaml(config), item["etag"])
        source = (self.store.job_dir("sample") / "main.py").read_bytes()
        self.scheduler.apply("sample", item["etag"])
        old_label = self.scheduler.label("sample")
        self.assertIn(old_label, self.fake.services)
        self.assertEqual(self.scheduler.rows("sample")[0]["schedule"]["interval_seconds"], 7200)
        self.assertEqual(self.store.get("sample")["etag"], item["etag"])  # reads never migrate
        self.fake.fail_next_bootstrap = True
        with self.assertRaises(ManagerError):
            self.save(calendar(), True)
        self.assertIn(old_label, self.fake.services)
        self.assertEqual(self.store.get("sample")["yaml"], item["yaml"])
        migrated = self.save(calendar(), True)
        self.assertTrue(migrated["migrated"])
        self.assertNotIn(old_label, self.fake.services)
        self.assertEqual(len(self.fake.services), 2)
        self.assertNotIn("schedule", migrated["job"]["config"])
        self.assertEqual(migrated["job"]["config"]["schedules"][0]["interval_seconds"], 7200)
        self.assertIn("# keep me", migrated["job"]["yaml"])
        self.assertEqual((self.store.runtime / "trash" / ("sample-" + item["etag"] + ".yaml")).read_text(), item["yaml"])
        self.assertEqual((self.store.job_dir("sample") / "main.py").read_bytes(), source)
        # Both newer calls and stale old launchd invocations share the Job run guard.
        with self.assertRaises(ManagerError):
            Execution(self.store).start("sample", "schedule", "old-generation")

    def test_disabled_legacy_migration_and_external_ownership_conflict(self):
        item = self.store.get("sample")
        config = item["config"]
        config.pop("schedules")
        config["schedule"] = {"enabled": False, "times": ["23:59"], "weekdays": [7]}
        item = self.store.update("sample", dump_yaml(config), item["etag"])
        legacy_path = self.scheduler.agents / (self.scheduler.label("sample") + ".plist")
        legacy_path.parent.mkdir()
        legacy_path.write_text("external")
        with self.assertRaises(ManagerError):
            self.save(interval(), True)
        self.assertEqual(self.store.get("sample")["yaml"], item["yaml"])
        self.assertEqual(legacy_path.read_text(), "external")
        legacy_path.unlink()
        self.save(interval(), True)
        legacy = schedules(self.store.get("sample")["config"])[0]
        self.assertFalse(legacy["enabled"])
        self.assertEqual(legacy["times"], ["23:59"])
        self.assertEqual(legacy["weekdays"], [7])

    def test_etag_conflict_and_orphan_detection_cleanup(self):
        before = self.store.get("sample")
        self.save(calendar(), True)
        with self.assertRaises(ManagerError) as cm:
            self.scheduler.save("sample", "check", interval(), before["etag"], True)
        self.assertEqual(cm.exception.status, 409)
        item = self.store.get("sample")
        config = item["config"]
        config["schedules"] = []
        self.store.update("sample", dump_yaml(config), item["etag"])
        row = self.scheduler.rows("sample")[0]
        self.assertTrue(row["orphan"])
        self.assertFalse(row["state"]["desired_matches"])
        generation = self.scheduler.state("sample", "morning")["generation"]
        with self.assertRaises(ManagerError):
            Execution(self.store).start("sample", "schedule", generation, "morning")
        self.scheduler.save("sample", "morning", None, self.store.get("sample")["etag"])
        self.assertEqual(self.scheduler.rows("sample"), [])

    def test_all_schedules_share_execution_lock_and_sibling_edits_do_not_stale_generation(self):
        self.save(calendar(), True)
        generation = self.scheduler.state("sample", "morning")["generation"]
        self.save(interval(), True)
        with self.store.job_lock("sample", "run", False):
            with self.assertRaises(ManagerError):
                self.save({**interval(), "enabled": False})
            with self.assertRaises(ManagerError):
                Execution(self.store).start("sample", "schedule", generation, "morning")
        run = Execution(self.store).start("sample", "schedule", generation, "morning")
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            result = Execution(self.store).get("sample", run["id"])
            if result["state"] not in ("queued", "running"):
                break
            time.sleep(.05)
        self.assertEqual(result["state"], "succeeded")
        self.assertEqual(result["schedule_id"], "morning")

    def test_external_yaml_during_failure_is_preserved_and_drift_is_visible(self):
        self.save(calendar(), True)
        original = self.scheduler.command
        once = [True]
        def external_edit(args, **kwargs):
            if args[:2] == ["launchctl", "bootstrap"] and once[0]:
                once[0] = False
                path = self.store.job_dir("sample") / "job.yaml"
                path.write_text(path.read_text() + "\n# concurrent Codex change\n")
                self.fake.fail_next_bootstrap = True
            return original(args, **kwargs)
        self.scheduler.command = external_edit
        with self.assertRaisesRegex(ManagerError, "외부 YAML 변경을 보존"):
            self.save({**calendar(), "times": ["09:00"]})
        self.assertIn("# concurrent Codex change", self.store.get("sample")["yaml"])
        self.assertTrue(self.scheduler.observed("sample", "morning")["loaded"])
        self.assertFalse(self.scheduler.observed("sample", "morning")["desired_matches"])

    def test_unsafe_migration_checks_ownership_before_writing_yaml(self):
        path = self.scheduler.agents / (self.scheduler.label("sample") + ".plist")
        path.parent.mkdir()
        path.write_text("unmanaged file")
        with patch.object(self.store, "_update_locked", wraps=self.store._update_locked) as update:
            with self.assertRaises(ManagerError):
                self.save(calendar(), True)
            update.assert_not_called()

    def test_os_disabled_override_is_observed_and_restored_on_failure(self):
        self.save(calendar(), True)
        label = self.scheduler.label("sample", "morning")
        self.fake.disabled_services.add(label)
        state = self.scheduler.observed("sample", "morning")
        self.assertTrue(state["os_disabled"])
        self.assertFalse(state["desired_matches"])
        self.fake.fail_next_bootstrap = True
        with self.assertRaises(ManagerError):
            self.save({**calendar(), "times": ["09:00"]})
        self.assertIn(label, self.fake.disabled_services)
        self.assertTrue(self.scheduler.observed("sample", "morning")["os_disabled"])

    def test_compatibility_apply_and_remove_never_create_duplicate_job_label(self):
        item = self.store.get("sample")
        config = item["config"]
        config.pop("schedules")
        config["schedule"] = {"enabled": True, "times": ["23:59"]}
        legacy = self.store.update("sample", dump_yaml(config), item["etag"])
        self.scheduler.apply("sample", legacy["etag"])
        self.scheduler.apply("sample", legacy["etag"], "legacy")
        migrated = self.store.get("sample")
        self.assertNotIn("schedule", migrated["config"])
        self.assertEqual(self.fake.services, {self.scheduler.label("sample", "legacy")})
        self.scheduler.apply("sample", migrated["etag"])
        self.assertEqual(len(self.fake.services), 1)
        reverted = self.store.update("sample", legacy["yaml"], migrated["etag"])
        with self.assertRaises(ManagerError):
            self.scheduler.apply("sample", reverted["etag"])
        self.assertEqual(len(self.fake.services), 1)
        migrated = self.store.update("sample", migrated["yaml"], reverted["etag"])
        self.scheduler.remove("sample")
        self.assertEqual(self.fake.services, set())

    def test_loaded_orphan_without_receipt_or_file_is_visible_and_preserved(self):
        label = self.scheduler.label("sample", "ghost")
        self.fake.services.add(label)
        rows = self.scheduler.rows("sample")
        self.assertEqual(rows[0]["schedule"]["id"], "ghost")
        self.assertTrue(rows[0]["orphan"])
        self.assertTrue(self.scheduler.has_registration("sample"))
        before = self.store.get("sample")
        with self.assertRaisesRegex(ManagerError, "소유권"):
            self.scheduler.save("sample", "ghost", None, before["etag"])
        self.assertEqual(self.store.get("sample")["etag"], before["etag"])
        self.assertIn(label, self.fake.services)

    def test_schedule_save_size_limit_is_checked_before_atomic_write(self):
        item = self.store.get("sample")
        config = item["config"]
        config["description"] = "a" * 130800
        item = self.store.update("sample", dump_yaml(config), item["etag"])
        entry = {**calendar(), "name": "긴이름" * 60}
        with self.assertRaisesRegex(ManagerError, "128 KiB"):
            self.save(entry, True)
        self.assertEqual(self.store.get("sample")["etag"], item["etag"])
        self.assertEqual(self.fake.services, set())

    def test_schema_rejects_duplicate_ids_mixed_fields_and_accepts_seconds(self):
        config = default_job("sample")
        config["schedules"] = [calendar(), interval()]
        validate(config)
        for bad in ([calendar(), calendar()], [{**interval(), "times": []}],
                    [{**calendar(), "interval_seconds": 60}], [{**interval(), "interval_seconds": True}],
                    [{**calendar(), "name": ""}], [{**calendar(), "type": "other"}]):
            with self.subTest(bad=bad), self.assertRaises(ManagerError):
                validate({**config, "schedules": bad})
        validate({**config, "schedules": [{**interval(), "interval_seconds": 1}]})


class MultiDeploymentTests(unittest.TestCase):
    setUp = deployment_tests.DeploymentTests.setUp
    controller = deployment_tests.DeploymentTests.controller
    transport = deployment_tests.DeploymentTests.transport
    do_deploy = deployment_tests.DeploymentTests.do_deploy
    def test_rollback_can_recover_from_corrupted_current_release(self):
        first = self.do_deploy()
        (self.store.job_dir("sample") / "main.py").write_text("print('second')")
        second = self.do_deploy()
        (self.controller().release_path(second["release"]) / "source/main.py").write_text("corrupted")
        self.deploy.rollback("sample", "test", first["release"])
        self.assertEqual(self.controller().verify()["release"], first["release"])

    def test_multiple_timers_migrate_retire_and_roll_back_both_schemas(self):
        first = self.do_deploy()
        item = self.store.get("sample")
        config = item["config"]
        config.pop("schedule")
        config["schedules"] = [calendar(), interval(), calendar("disabled", False)]
        self.store.update("sample", dump_yaml(config), item["etag"])
        second = self.do_deploy()
        controller = self.controller()
        manifest = controller.verify_release(second["release"])
        units = manifest["units"]
        self.assertEqual(len([n for n in units if n.endswith(".timer")]), 3)
        self.assertFalse((controller.units / (controller.label + ".timer")).exists())
        timer_text = (controller.units / (controller.label + "-schedule-check.timer")).read_text()
        self.assertIn("OnActiveSec=1800s", timer_text)
        self.assertIn("OnUnitActiveSec=1800s", timer_text)
        self.assertEqual(len(controller.verify()["timers"]), 3)
        self.deploy.rollback("sample", "test", first["release"])
        self.assertFalse((controller.units / (controller.label + "-schedule-check.timer")).exists())
        self.assertEqual(len(controller.verify()["timers"]), 1)
        self.deploy.rollback("sample", "test", second["release"])
        self.assertEqual(len(controller.verify()["timers"]), 3)
        # Failure after stopping the old set restores every timer, including paused ones.
        item = self.store.get("sample")
        config["schedules"] = [interval("new")]
        self.store.update("sample", dump_yaml(config), item["etag"])
        self.fake.fail_enable = True
        with self.assertRaises(RuntimeError):
            self.do_deploy()
        self.assertEqual(controller.verify()["release"], second["release"])
        self.assertEqual(len(self.fake.enabled_units), 2)
