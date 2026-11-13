import base64
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from deployments.client import Deployment
from deployments.packages import Packages
from deployments.remote_runtime import Controller, load, locked, safe
from runner.common import ManagerError
from runner.store import Store, default_job, dump_yaml


class FakeSystemd:
    def __init__(self, units):
        self.units = units
        self.enabled_units = set()
        self.active_units = set()
        self.fail_enable = False
        self.calls = []

    def __call__(self, args, **kwargs):
        self.calls.append(args)
        rc, out, err = 0, "", ""
        if args[0] == "loginctl":
            out = "yes\n"
        if args[:2] == ["systemctl", "--user"]:
            action = args[2]
            if action == "is-enabled":
                rc = 0 if args[3] in self.enabled_units else 1
            elif action == "is-active":
                rc = 0 if args[3] in self.active_units else 3
            elif action == "enable":
                if self.fail_enable:
                    self.fail_enable = False
                    rc, err = 1, "injected enable failure"
                else:
                    self.enabled_units.add(args[-1])
                    if "--now" in args:
                        self.active_units.add(args[-1])
            elif action == "disable":
                self.enabled_units.discard(args[-1])
            elif action == "stop":
                self.active_units.discard(args[-1])
            elif action == "start":
                self.active_units.add(args[-1])
            elif action == "show":
                unit = self.units / args[3]
                start = next((line.split("=", 1)[1] for line in unit.read_text().splitlines()
                              if line.startswith("ExecStart=")), "")
                out = "LoadState=loaded\nNeedDaemonReload=no\nFragmentPath=" + str(unit) + "\nExecStart=" + start + "\n"
        return subprocess.CompletedProcess(args, rc, out, err)


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.store = Store(self.base / "local")
        self.remote = self.base / "remote"
        self.home = self.base / "remote-home"
        self.home.mkdir()
        self.fake = FakeSystemd(self.home / ".config/systemd/user")
        config = default_job("sample")
        config["command"] = [sys.executable, "main.py"]
        config.pop("schedules", None)
        config["schedule"] = {"enabled": True, "times": ["09:30"], "weekdays": [1, 7]}
        self.store.create(config)
        (self.store.root / "deployments").mkdir()
        (self.store.root / "deployments/targets.yaml").write_text(dump_yaml(
            {"version": 1, "targets": {"test": {"ssh_host": "never-contacted", "root": str(self.remote)}}}))
        self.calls = []
        self.deploy = Deployment(self.store, self.transport)

    def controller(self, create=False):
        return Controller(self.remote, "sample", self.home, self.fake, create)

    def transport(self, target, payload):
        self.calls.append(payload["action"])
        controller = self.controller(create=payload["action"] == "deploy")
        controller.preflight()
        if payload["action"] == "deploy":
            release = controller.stage(payload["info"], payload["files"])
            return controller.activate(release)
        if payload["action"] == "rollback":
            return controller.activate(payload["release"], recovery=True)
        return controller.verify()

    def do_deploy(self):
        package_id = Packages(self.store).create("sample")["id"]
        plan = self.deploy.plan("sample", "test", package_id)
        receipt = self.deploy.deploy("sample", "test", package_id, plan["plan_hash"])
        self.assertEqual(receipt["status"], "verified")
        return receipt

    def test_plan_is_offline_and_uses_fixed_package_after_job_edit(self):
        package_id = Packages(self.store).create("sample")["id"]
        frozen_runtime = Packages(self.store).get(package_id, "sample")["manifest"]["runtime_files"]
        _, files = self.deploy._bundle("sample", "test", package_id)
        self.assertEqual(files["manager/remote_runtime.py"]["sha256"], frozen_runtime["manager/remote_runtime.py"]["sha256"])
        with patch("deployments.client.subprocess.run", wraps=subprocess.run) as commands:
            plan = self.deploy.plan("sample", "test", package_id)
            self.assertEqual(commands.call_count, 0)
        self.assertEqual(self.calls, [])
        (self.store.job_dir("sample") / "main.py").write_text("print('changed')")
        receipt = self.deploy.deploy("sample", "test", package_id, plan["plan_hash"])
        self.assertEqual(receipt["package_id"], package_id)
        self.assertIn("sample job completed", (self.controller().release_path(receipt["release"]) / "source/main.py").read_text())

    def test_deploy_verify_version_history_and_rollback(self):
        first = self.do_deploy()
        controller = self.controller()
        (self.store.job_dir("sample") / "main.py").write_text("print('version two')")
        second = self.do_deploy()
        self.assertNotEqual(first["release"], second["release"])
        self.assertEqual(self.deploy.verify("sample", "test")["release"], second["release"])
        self.deploy.rollback("sample", "test", first["release"])
        self.assertEqual(controller.current(), first["release"])
        self.assertEqual(len(self.deploy.history("sample")), 3)

    def test_same_package_can_plan_for_multiple_targets(self):
        package_id = Packages(self.store).create("sample")["id"]
        second = self.base / "remote-second"
        (self.store.root / "deployments/targets.yaml").write_text(dump_yaml({"version": 1, "targets": {
            "test": {"ssh_host": "never-contacted", "root": str(self.remote)},
            "second": {"ssh_host": "never-contacted-2", "root": str(second)},
        }}))
        first_plan = self.deploy.plan("sample", "test", package_id)
        second_plan = self.deploy.plan("sample", "second", package_id)
        self.assertEqual(first_plan["package_id"], second_plan["package_id"])
        self.assertEqual(first_plan["package_hash"], second_plan["package_hash"])
        self.assertNotEqual(first_plan["plan_hash"], second_plan["plan_hash"])
        self.assertEqual(self.calls, [])

    def test_partial_failure_restores_previous_code_units_and_timer(self):
        first = self.do_deploy()
        (self.store.job_dir("sample") / "main.py").write_text("print('bad new release')")
        package_id = Packages(self.store).create("sample")["id"]
        plan = self.deploy.plan("sample", "test", package_id)
        self.fake.fail_enable = True
        with self.assertRaises(RuntimeError):
            self.deploy.deploy("sample", "test", package_id, plan["plan_hash"])
        verified = self.deploy.verify("sample", "test")
        self.assertEqual(verified["release"], first["release"])
        self.assertTrue(verified["timer_active"])
        self.assertEqual(self.deploy.history("sample")[0]["status"], "unconfirmed")

    def test_checksum_tampering_and_symlinks_rejected(self):
        package_id = Packages(self.store).create("sample")["id"]
        plan, files = self.deploy._bundle("sample", "test", package_id)
        relative = next(iter(files))
        files[relative]["data"] = base64.b64encode(b"tampered").decode()
        with self.assertRaises(ValueError):
            self.controller(True).stage(plan, files)
        self.assertIsNone(self.controller().current())
        (self.store.job_dir("sample") / "escape").symlink_to("/etc/passwd")
        with self.assertRaises(ManagerError):
            Packages(self.store).create("sample")

    def test_installed_file_drift_is_detected(self):
        receipt = self.do_deploy()
        controller = self.controller()
        (controller.release_path(receipt["release"]) / "source/main.py").write_text("tampered")
        with self.assertRaises(ValueError):
            self.deploy.verify("sample", "test")

    def test_disabled_schedule_and_first_deploy_failure_are_recoverable(self):
        self.fake.fail_enable = True
        package_id = Packages(self.store).create("sample")["id"]
        plan = self.deploy.plan("sample", "test", package_id)
        with self.assertRaises(RuntimeError):
            self.deploy.deploy("sample", "test", package_id, plan["plan_hash"])
        self.assertIsNone(self.controller().current())
        self.do_deploy()
        item = self.store.get("sample")
        config = item["config"]
        config["schedule"]["enabled"] = False
        self.store.update("sample", dump_yaml(config), item["etag"])
        self.do_deploy()
        verified = self.deploy.verify("sample", "test")
        self.assertFalse(verified["timer_active"])
        self.assertFalse(verified["timer_enabled"])

    def test_remote_runtime_executes_independently_without_yaml_or_dashboard(self):
        receipt = self.do_deploy()
        controller = self.controller()
        helper = controller.release_path(receipt["release"]) / "manager/remote_runtime.py"
        completed = subprocess.run([sys.executable, "-S", str(helper), "run", str(controller.job),
                                    receipt["release"]], cwd="/", capture_output=True, text=True, timeout=10)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        logdirs = list((controller.shared / "logs").iterdir())
        self.assertEqual(len(logdirs), 1)
        self.assertEqual(json.loads((logdirs[0] / "run.json").read_text())["state"], "succeeded")
        self.assertIn("sample job completed", (logdirs[0] / "stdout.log").read_text())

    def test_run_guard_and_external_unit_preservation(self):
        self.do_deploy()
        controller = self.controller()
        with locked(safe(controller.job, "run.lock")):
            with self.assertRaises(BlockingIOError):
                controller.activate(controller.current())
        service = controller.units / (controller.label + ".service")
        service.write_text("external unit")
        with self.assertRaises(ValueError):
            controller.activate(controller.current())
        self.assertEqual(service.read_text(), "external unit")

    def test_ssh_options_and_failure_not_reported_as_success(self):
        target = self.deploy.target("test")
        with patch("deployments.client.subprocess.run", return_value=subprocess.CompletedProcess([], 255, "", "offline")) as command:
            with self.assertRaises(ManagerError):
                self.deploy._ssh(target, {"action": "verify", "job_id": "sample"})
            args = command.call_args.args[0]
            self.assertEqual(args[0], "ssh")
            self.assertIn("StrictHostKeyChecking=yes", args)
            self.assertIn("BatchMode=yes", args)
            self.assertIn("--", args)
