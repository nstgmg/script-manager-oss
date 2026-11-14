"""Isolated data and fake OS tests: no user's jobs, secrets or native reservations."""
import io
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch
from contextlib import redirect_stdout, redirect_stderr

from runner.__main__ import main
from runner.common import ManagerError, digest, read_json, write_json
from runner.execution import Execution
from runner.installation import MARKER, installation
from runner.maintenance import Maintenance
from runner.schedule import Scheduler
from runner.schedule_doctor import ScheduleDoctor
from runner.store import Store, default_job
from tests.test_schedule import LaunchctlFake


class DoctorLaunchctl(LaunchctlFake):
    def __init__(self):
        super().__init__()
        self.paths = {}
        self.fail_bootout = False
        self.ignore_bootout = False
        self.fail_list = False
        self.running = set()
        self.definitions = {}

    def __call__(self, args, **kwargs):
        if args[:2] == ["launchctl", "list"] and self.fail_list:
            return subprocess.CompletedProcess(args, 1, "", "inventory denied")
        if args[:2] == ["launchctl", "bootout"] and (self.fail_bootout or self.ignore_bootout):
            return subprocess.CompletedProcess(args, 5 if self.fail_bootout else 0, "", "bootout denied")
        result = super().__call__(args, **kwargs)
        if args[:2] == ["launchctl", "bootstrap"] and result.returncode == 0:
            path = Path(args[-1]).resolve()
            definition = plistlib.loads(path.read_bytes())
            self.paths[definition["Label"]] = path
            self.definitions[definition["Label"]] = definition
        if args[:2] == ["launchctl", "print"] and result.returncode == 0:
            label = args[-1].split("/")[-1]
            data = self.definitions[label]
            result.stdout = ("path = " + str(self.paths[label]) + "\nprogram = " + data["ProgramArguments"][0]
                + "\nworking directory = " + data["WorkingDirectory"] + "\narguments = {\n"
                + "\n".join(data["ProgramArguments"]) + "\n}\n" + ("pid = 123\n" if label in self.running else ""))
        return result


class MaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.store = Store(self.base / "one")
        self.fake = DoctorLaunchctl()
        patcher = patch("runner.schedule.platform.system", return_value="Darwin")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.scheduler = Scheduler(self.store, self.base / "agents", self.fake)
        self.doctor = ScheduleDoctor(self.store, self.scheduler)
        self.manager = Maintenance(self.store, self.doctor)
        self.create()

    def create(self, store=None, scheduler=None):
        store, scheduler = store or self.store, scheduler or self.scheduler
        job = store.create(default_job("sample"))
        scheduler.save("sample", "daily", {"id": "daily", "name": "daily", "enabled": True,
                        "type": "calendar", "times": ["23:59"], "weekdays": [7]}, job["etag"], True)

    def test_reset_all_data_then_create_run_and_schedule_again(self):
        for rel in ("workspace/file", "reports/file.html", "exports/file.zip", "runtime/job-data/sample/state/state.json",
                    "runtime/trash/old.yaml", "deployments/packages/test/meta.json", "deployments/history/test/receipt.json",
                    "deployments/targets.yaml", ".env"):
            path = self.store.root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("synthetic")
        code = self.store.root / "keep.py"
        code.write_text("print('code')")
        external = self.base / "external.html"
        external.write_text("external")
        identity = installation(self.store)
        plan = self.manager.preview()
        self.assertFalse(plan["blockers"], plan)
        result = self.manager.execute("reset", plan["plan_hash"])
        self.assertTrue(result["success"], result)
        self.assertEqual(self.store.list(), [])
        self.assertFalse(self.doctor.scan()["schedules"])
        self.assertEqual(installation(self.store), identity)
        self.assertTrue(code.exists() and external.exists())
        self.assertFalse((self.store.root / ".env").exists())
        self.create()
        self.assertEqual(self.doctor.scan()["schedules"][0]["status"], "healthy")
        execution = Execution(self.store)
        record = execution.start("sample")
        deadline = time.monotonic() + 10
        while record["state"] in ("queued", "running") and time.monotonic() < deadline:
            time.sleep(.05)
            record = execution.get("sample", record["id"])
        self.assertEqual((record["state"], record["exit_code"]), ("succeeded", 0))
        self.assertIn("completed", execution.logs("sample", record["id"])["text"])
        self.assertEqual(execution.logs("sample", record["id"], "stderr")["text"], "")

    def test_uninstall_prepares_but_keeps_program_directory(self):
        code = self.store.root / "keep.py"
        code.write_text("code")
        plan = self.manager.preview("uninstall")
        result = self.manager.execute("uninstall", plan["plan_hash"])
        self.assertTrue(result["success"], result)
        self.assertTrue(code.exists() and self.store.root.exists())
        self.assertTrue(result["next_steps"])
        self.assertFalse(self.fake.services)

    def test_orphan_after_root_deleted_can_be_removed_from_reinstall(self):
        label = self.scheduler.label("sample", "daily")
        shutil.rmtree(self.store.root)
        fresh = Store(self.base / "reinstalled")
        doctor = ScheduleDoctor(fresh, Scheduler(fresh, self.scheduler.agents, self.fake))
        row = doctor.scan()["schedules"][0]
        self.assertEqual(row["status"], "orphan")
        self.assertTrue(row["owned"])
        with self.assertRaises(ManagerError):
            doctor.remove(label, None)
        self.assertTrue(doctor.remove(label, row["fingerprint"])["verified"])
        self.assertFalse(doctor.scan()["schedules"])

    def test_other_install_and_ordinary_os_entries_are_protected(self):
        other = Store(self.base / "two")
        second = Scheduler(other, self.scheduler.agents, self.fake)
        self.create(other, second)
        regular = self.scheduler.agents / "ordinary.plist"
        regular.write_bytes(plistlib.dumps({"Label": "ordinary", "ProgramArguments": ["/usr/bin/true"]}))
        self.fake.services.add("ordinary")
        other_row = next(r for r in self.doctor.scan()["schedules"] if r["root"] == str(other.root))
        with self.assertRaises(ManagerError):
            self.doctor.remove(other_row["id"], other_row["fingerprint"])
        plan = self.manager.preview()
        self.assertEqual(len(plan["schedules"]), 1)
        self.assertTrue(self.manager.execute("reset", plan["plan_hash"])["success"])
        self.assertTrue(second.observed("sample", "daily")["loaded"])
        self.assertTrue(regular.exists() and "ordinary" in self.fake.services)

    def test_unregister_failure_or_silent_failure_keeps_all_user_data(self):
        for silent in (False, True):
            with self.subTest(silent=silent):
                self.fake.fail_bootout = not silent
                self.fake.ignore_bootout = silent
                before = (self.store.job_dir("sample") / "job.yaml").read_bytes()
                plan = self.manager.preview()
                result = self.manager.execute("reset", plan["plan_hash"])
                self.assertFalse(result["success"])
                self.assertEqual(result["phase"], "remove-schedules")
                self.assertEqual(result["deleted"], [])
                self.assertEqual((self.store.job_dir("sample") / "job.yaml").read_bytes(), before)
                self.assertTrue(self.fake.services)

    def test_unknown_modified_loaded_only_and_running_are_never_removed(self):
        label = self.scheduler.label("sample", "daily")
        path = self.scheduler.agents / (label + ".plist")
        original = path.read_bytes()
        for kind in ("modified", "missing", "running"):
            with self.subTest(kind=kind):
                path.write_bytes(original)
                self.fake.running.clear()
                if kind == "modified":
                    data = plistlib.loads(original)
                    data["ProgramArguments"] = ["/usr/bin/true"]
                    path.write_bytes(plistlib.dumps(data))
                elif kind == "missing":
                    path.unlink()
                else:
                    self.fake.running.add(label)
                row = self.doctor.scan()["schedules"][0]
                plan = self.manager.preview()
                self.assertTrue(plan["blockers"])
                with self.assertRaises(ManagerError):
                    self.manager.execute("reset", plan["plan_hash"])
                with self.assertRaises(ManagerError):
                    self.doctor.remove(label, row["fingerprint"])
                self.assertTrue(self.store.job_dir("sample").exists())
        path.write_bytes(original)

    def test_preview_confirmation_is_scoped_and_detects_changed_data(self):
        plan = self.manager.preview()
        with self.assertRaises(ManagerError):
            self.manager.execute("reset", None)
        with self.assertRaises(ManagerError):
            self.manager.execute("uninstall", plan["plan_hash"])
        (self.store.job_dir("sample") / "main.py").write_text("print('changed')")
        with self.assertRaises(ManagerError):
            self.manager.execute("reset", plan["plan_hash"])
        self.assertTrue(self.fake.services)

    def test_inventory_error_running_guard_and_symlink_preserve_data(self):
        self.fake.fail_list = True
        self.assertTrue(self.manager.preview()["blockers"])
        self.fake.fail_list = False
        with self.store.job_lock("sample", "run", False):
            self.assertTrue(self.manager.preview()["active_runs"])
        marker = self.store.root / "workspace"
        marker.symlink_to(self.base / "outside", target_is_directory=True)
        self.assertTrue(self.manager.preview()["blockers"])
        self.assertTrue(marker.is_symlink())

    def test_real_running_job_blocks_reset_without_cancelling(self):
        (self.store.job_dir("sample") / "main.py").write_text("import time; time.sleep(.6); print('finished')")
        execution = Execution(self.store)
        record = execution.start("sample")
        plan = self.manager.preview()
        self.assertTrue(plan["blockers"] and plan["active_runs"])
        with self.assertRaises(ManagerError):
            self.manager.execute("reset", plan["plan_hash"])
        deadline = time.monotonic() + 8
        while record["state"] in ("queued", "running") and time.monotonic() < deadline:
            time.sleep(.05)
            record = execution.get("sample", record["id"])
        self.assertEqual(record["state"], "succeeded")
        self.assertTrue(self.store.job_dir("sample").exists())

    def test_legacy_checksum_compatibility_and_no_checksum_no_adoption(self):
        label = self.scheduler.label("sample", "daily")
        path = self.scheduler.agents / (label + ".plist")
        data = plistlib.loads(path.read_bytes())
        data.pop(MARKER)
        path.write_bytes(plistlib.dumps(data))
        state = self.scheduler.state("sample", "daily")
        state["plist_sha256"] = digest(path.read_bytes())
        write_json(self.scheduler.state_path("sample", "daily"), state)
        self.assertTrue(self.doctor.scan()["schedules"][0]["legacy"])
        self.assertFalse(self.manager.preview()["blockers"])
        self.scheduler.state_path("sample", "daily").unlink()
        self.assertEqual(self.doctor.scan()["schedules"][0]["status"], "unknown")
        self.assertTrue(self.manager.preview()["blockers"])

    def test_no_env_content_read_and_partial_deletion_failure_is_reported(self):
        env = self.store.root / ".env"
        env.write_text("SYNTHETIC=")
        original = Path.read_text
        def guarded(path, *args, **kwargs):
            if path == env:
                raise AssertionError("must not read credentials")
            return original(path, *args, **kwargs)
        with patch.object(Path, "read_text", guarded):
            plan = self.manager.preview()
            self.assertIn(str(env), [p["path"] for p in plan["delete"]])
        with patch.object(self.manager, "_delete_tree", side_effect=PermissionError("synthetic failure")):
            result = self.manager.execute("reset", plan["plan_hash"])
        self.assertFalse(result["success"])
        self.assertEqual(result["phase"], "delete-data")
        self.assertTrue(result["remaining"])
        self.assertFalse(self.fake.services)

    def test_gate_blocks_other_store_mutations_during_maintenance(self):
        second = Store(self.store.root)
        with self.store.maintenance_lock():
            with self.assertRaises(ManagerError):
                with second.maintenance_lock(False):
                    pass

    def test_cli_preview_requires_current_confirmation_and_doctor_reads_only(self):
        def invoke(*args):
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err), patch("runner.schedule_doctor.ScheduleDoctor", return_value=self.doctor):
                code = main(["--root", str(self.store.root), *args])
            return code, json.loads(out.getvalue() or err.getvalue())
        code, result = invoke("reset")
        self.assertEqual(code, 0)
        self.assertTrue(result["delete"])
        self.assertEqual(invoke("reset", "--confirm", "wrong")[0], 1)
        code, result = invoke("schedule-doctor")
        self.assertEqual(code, 0)
        self.assertEqual(result["counts"]["healthy"], 1)
        self.assertEqual(invoke("schedule-doctor", "--remove", result["schedules"][0]["id"])[0], 1)
        self.assertEqual(len(self.fake.services), 1)

    def test_same_path_reinstall_detects_old_generation_and_old_job_only_labels(self):
        old_id = self.scheduler.label("sample", "daily")
        shutil.rmtree(self.store.root)
        fresh = Store(self.store.root)
        fresh.create(default_job("sample"))
        doctor = ScheduleDoctor(fresh, Scheduler(fresh, self.scheduler.agents, self.fake))
        row = next(r for r in doctor.scan()["schedules"] if r["id"] == old_id)
        self.assertEqual(row["status"], "orphan")
        self.assertTrue(doctor.remove(old_id, row["fingerprint"])["verified"])
        other = Store(self.base / "legacy")
        config = default_job("sample")
        config.pop("schedules")
        config["schedule"] = {"enabled":True,"times":["23:59"],"weekdays":[7]}
        job = other.create(config)
        scheduler = Scheduler(other, self.scheduler.agents, self.fake)
        scheduler.apply("sample", job["etag"])
        path = Path(scheduler.plan("sample")["path"])
        data = plistlib.loads(path.read_bytes()); data.pop(MARKER)
        path.write_bytes(plistlib.dumps(data))
        state = scheduler.state("sample"); state["plist_sha256"] = digest(path.read_bytes())
        write_json(scheduler.state_path("sample"), state)
        row = next(r for r in ScheduleDoctor(other, scheduler).scan()["schedules"] if r["id"] == scheduler.label("sample"))
        self.assertTrue(row["owned"] and row["legacy"])
        manager = Maintenance(other, ScheduleDoctor(other, scheduler))
        plan = manager.preview()
        self.assertTrue(manager.execute("reset", plan["plan_hash"])["success"])

    def test_corrupt_or_copied_install_identity_is_not_adopted(self):
        path = self.store.runtime / "installation.json"
        for value in ([], {"version":1,"installation_id":"a"*32,"root":"/other"}):
            write_json(path, value)
            with self.assertRaises(ManagerError):
                self.manager.preview()
            self.assertTrue(self.store.job_dir("sample").exists())

    def test_partial_schedule_removal_never_enters_data_deletion(self):
        self.scheduler.save("sample", "second", {"id":"second","name":"second","enabled":True,
            "type":"calendar","times":["23:59"],"weekdays":[7]}, self.store.get("sample")["etag"], True)
        original = self.doctor.remove
        def remove(label, confirmation, **kwargs):
            if label.endswith(".second"):
                raise ManagerError("injected second removal failure", 502)
            return original(label, confirmation, **kwargs)
        plan = self.manager.preview()
        with patch.object(self.doctor, "remove", side_effect=remove):
            result = self.manager.execute("reset", plan["plan_hash"])
        self.assertFalse(result["success"])
        self.assertEqual(result["phase"], "remove-schedules")
        self.assertEqual(len(result["removed_schedules"]), 1)
        self.assertEqual(result["deleted"], [])
        self.assertTrue(self.store.job_dir("sample").exists())

    def test_os_timeout_during_removal_reports_phase_and_keeps_data(self):
        plan = self.manager.preview()
        original = self.scheduler.command
        def timeout(args, **kwargs):
            if args[:2] == ["launchctl", "bootout"]:
                raise subprocess.TimeoutExpired(args, 20)
            return original(args, **kwargs)
        with patch.object(self.scheduler, "command", side_effect=timeout):
            result = self.manager.execute("reset", plan["plan_hash"])
        self.assertFalse(result["success"])
        self.assertEqual(result["phase"], "remove-schedules")
        self.assertEqual(result["deleted"], [])
        self.assertTrue(self.store.job_dir("sample").exists())
