"""Windows and Linux native interfaces simulated on the test host."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from deployments.remote_runtime import Controller
from runner.common import ManagerError, digest, write_json
from runner.installation import DESCRIPTION
from runner.maintenance import Maintenance
from runner.schedule import Scheduler
from runner.schedule_doctor import ScheduleDoctor
from runner.store import Store, default_job
from runner.windows_schedule import NS
from tests.test_windows_schedule import FakeTasks, schedule


class DoctorTasks(FakeTasks):
    def __init__(self):
        super().__init__()
        self.running = False
        self.ignore_delete = False
    def __call__(self, args, **kwargs):
        if args[0] == "powershell.exe":
            return subprocess.CompletedProcess(args, 0, "4" if self.running else "3", "")
        if self.ignore_delete and args[1] == "/Delete":
            return subprocess.CompletedProcess(args, 0, "", "")
        return super().__call__(args, **kwargs)


class WindowsDoctorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.store = Store(self.base / "one")
        self.store.create(default_job("sample"))
        patcher = patch("runner.schedule.platform.system", return_value="Windows")
        patcher.start(); self.addCleanup(patcher.stop)
        self.fake = DoctorTasks()
        self.scheduler = Scheduler(self.store, command=self.fake)
        self.scheduler.save("sample", "daily", schedule("daily"), self.store.get("sample")["etag"], True)
        self.doctor = ScheduleDoctor(self.store, self.scheduler)
        self.name = self.scheduler.task_name("sample", "daily")

    def test_reset_native_verification_and_reuse(self):
        manager = Maintenance(self.store, self.doctor)
        self.assertEqual(self.doctor.scan()["counts"]["healthy"], 1)
        plan = manager.preview()
        self.assertFalse(plan["blockers"], plan)
        self.assertTrue(manager.execute("reset", plan["plan_hash"])["success"])
        self.assertFalse(self.fake.tasks)
        self.store.create(default_job("new"))
        self.scheduler.save("new", "daily", schedule("daily"), self.store.get("new")["etag"], True)
        self.assertTrue(self.scheduler.observed("new", "daily")["loaded"])

    def test_reinstall_orphan_confirmation_and_actual_removal(self):
        shutil.rmtree(self.store.root)
        fresh = Store(self.base / "fresh")
        doctor = ScheduleDoctor(fresh, Scheduler(fresh, command=self.fake))
        row = doctor.scan()["schedules"][0]
        self.assertEqual(row["status"], "orphan")
        with self.assertRaises(ManagerError):
            doctor.remove(self.name, "wrong")
        self.assertTrue(doctor.remove(self.name, row["fingerprint"])["verified"])
        self.assertFalse(self.fake.tasks)

    def test_running_and_silent_unregister_failure_preserve_data(self):
        manager = Maintenance(self.store, self.doctor)
        for running in (True, False):
            self.fake.running = running
            self.fake.ignore_delete = not running
            plan = manager.preview()
            if running:
                self.assertTrue(plan["blockers"])
                with self.assertRaises(ManagerError):
                    manager.execute("reset", plan["plan_hash"])
            else:
                result = manager.execute("reset", plan["plan_hash"])
                self.assertFalse(result["success"])
                self.assertEqual(result["deleted"], [])
            self.assertTrue(self.store.job_dir("sample").exists())

    def test_legacy_checksums_and_unrelated_tasks_protected(self):
        tree = ET.fromstring(self.fake.tasks[self.name])
        tree.find("{" + NS + "}RegistrationInfo/{" + NS + "}Description").text = "Script Manager " + self.scheduler.state("sample", "daily")["generation"]
        self.fake.tasks[self.name] = ET.tostring(tree, encoding="unicode")
        state = self.scheduler.state("sample", "daily")
        state["task_sha256"] = digest(self.fake.tasks[self.name].encode())
        write_json(self.scheduler.state_path("sample", "daily"), state)
        self.fake.tasks["\\ordinary"] = "unrelated"
        row = self.doctor.scan()["schedules"][0]
        self.assertTrue(row["legacy"])
        self.scheduler.state_path("sample", "daily").unlink()
        self.assertEqual(self.doctor.scan()["schedules"][0]["status"], "unknown")
        with self.assertRaises(ManagerError):
            self.doctor.remove(self.name, row["fingerprint"])
        self.assertIn("\\ordinary", self.fake.tasks)

    def test_another_installation_and_extra_action_never_removed(self):
        other = Store(self.base / "two")
        other.create(default_job("other"))
        scheduler = Scheduler(other, command=self.fake)
        scheduler.save("other", "daily", schedule("daily"), other.get("other")["etag"], True)
        row = next(r for r in self.doctor.scan()["schedules"] if r["root"] == str(other.root))
        with self.assertRaises(ManagerError):
            self.doctor.remove(row["id"], row["fingerprint"])
        tree = ET.fromstring(self.fake.tasks[self.name])
        ET.SubElement(tree.find("{" + NS + "}Actions"), "{" + NS + "}ComHandler")
        self.fake.tasks[self.name] = ET.tostring(tree, encoding="unicode")
        row = next(r for r in self.doctor.scan()["schedules"] if r["id"] == self.name)
        self.assertEqual(row["status"], "unknown")


class DoctorSystemd:
    def __init__(self, units):
        self.units = units
        self.active = set()
        self.enabled = set()
        self.fail_stop = False
        self.dropin = False
        self.calls = []
    def __call__(self, args, **kwargs):
        self.calls.append(args)
        action = args[2]
        name = args[3] if len(args) > 3 else ""
        rc, out = 0, ""
        if action.startswith("list-"):
            out = "\n".join(p.name + " enabled" for p in self.units.glob("*.service")) + "\n" + "\n".join(p.name + " enabled" for p in self.units.glob("*.timer"))
        elif action == "show":
            path = self.units / name
            out = "LoadState=" + ("loaded" if path.exists() else "not-found") + "\nFragmentPath=" + (str(path) if path.exists() else "") + "\nNeedDaemonReload=no\nDropInPaths=" + ("override.conf" if self.dropin else "") + "\nActiveState=" + ("active" if name in self.active else "inactive") + "\nSubState=waiting\n"
            if path.exists():
                import shlex
                text = path.read_text()
                if name.endswith(".service") and text.startswith("# ScriptManagerMetadata "):
                    meta = json.loads(text.split("\n", 1)[0].split(" ", 2)[2])
                    out += "ExecStart={ path=" + meta["executable"] + " ; argv[]=" + " ".join(shlex.split(meta["exec_start"])) + " ; ignore_errors=no ; }\n"
                elif name.endswith(".timer"):
                    out += "Unit=" + name[:-6] + ".service\n"
        elif action == "stop":
            if self.fail_stop:
                rc = 1
            else:
                self.active.discard(name)
        elif action == "disable":
            self.enabled.discard(name)
        elif action == "is-enabled":
            rc, out = (0, "enabled") if name in self.enabled else (1, "disabled")
        return subprocess.CompletedProcess(args, rc, out, "synthetic error" if rc and action != "is-enabled" else "")


class LinuxDoctorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.remote = self.base / "remote"
        self.controller = Controller(self.remote, "sample", self.base / "home", create=True)
        self.units = self.controller.units
        self.fake = DoctorSystemd(self.units)
        config = default_job("sample")
        config["schedules"] = [schedule("daily")]
        self.unit_texts = self.controller.unit_text("r-synthetic", config)
        for name, text in self.unit_texts.items():
            if text:
                (self.units / name).write_text(text)
                if name.endswith(".timer"):
                    self.fake.active.add(name); self.fake.enabled.add(name)
        release = self.remote / "sample/releases/r-synthetic"
        (release / "manager").mkdir(parents=True)
        (release / "manager/remote_runtime.py").write_text("synthetic")
        (release / "config.json").write_text("{}")
        self.store = Store(self.base / "fresh")
        patcher = patch("runner.schedule.platform.system", return_value="Linux")
        patcher.start(); self.addCleanup(patcher.stop)
        self.doctor = ScheduleDoctor(self.store, Scheduler(self.store, command=self.fake), units=self.units)

    def test_health_then_orphan_recovery_keeps_regular_units(self):
        regular = self.units / "ordinary.timer"
        regular.write_text("ordinary")
        scan = self.doctor.scan()
        self.assertFalse(scan["errors"], scan)
        self.assertEqual(scan["counts"]["healthy"], 3, scan)
        for row in scan["schedules"]:
            with self.assertRaises(ManagerError):
                self.doctor.remove(row["id"], row["fingerprint"])
        shutil.rmtree(self.remote)
        scan = self.doctor.scan()
        self.assertEqual(scan["counts"]["orphan"], 3, scan)
        # Remove timers before the inactive companion services.
        for row in sorted(scan["schedules"], key=lambda r: not r["id"].endswith(".timer")):
            self.assertTrue(self.doctor.remove(row["id"], row["fingerprint"])["verified"])
        self.assertTrue(regular.exists())
        self.assertFalse(self.fake.active or self.fake.enabled)
        self.assertFalse(self.doctor.scan()["schedules"])

    def test_legacy_modified_dropins_and_running_services_protected(self):
        service = next(n for n in self.unit_texts if n.endswith(".service"))
        path = self.units / service
        original = path.read_text()
        path.write_text(original.split("\n", 1)[1])
        self.assertEqual(next(r for r in self.doctor.scan()["schedules"] if r["id"] == service)["status"], "unknown")
        path.write_text(original)
        self.fake.dropin = True
        self.assertTrue(all(r["status"] == "unknown" for r in self.doctor.scan()["schedules"]))
        self.fake.dropin = False
        shutil.rmtree(self.remote)
        self.fake.active.add(service)
        row = next(r for r in self.doctor.scan()["schedules"] if r["id"] == service)
        with self.assertRaises(ManagerError):
            self.doctor.remove(service, row["fingerprint"])
        self.assertTrue(path.exists() and service in self.fake.active)

    def test_timer_stop_failure_preserves_definition_and_data(self):
        shutil.rmtree(self.remote)
        row = next(r for r in self.doctor.scan()["schedules"] if r["id"].endswith(".timer"))
        self.fake.fail_stop = True
        with self.assertRaises(ManagerError):
            self.doctor.remove(row["id"], row["fingerprint"])
        self.assertTrue(Path(row["path"]).exists())

    def test_local_reset_does_not_touch_remote_deployments(self):
        plan = Maintenance(self.store, self.doctor).preview()
        self.assertFalse(plan["schedules"] or plan["blockers"])
        self.assertTrue(Maintenance(self.store, self.doctor).execute("reset", plan["plan_hash"])["success"])
        self.assertEqual(len(self.doctor.scan()["schedules"]), 3)
        self.assertTrue(self.remote.exists())
