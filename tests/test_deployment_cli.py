import contextlib
import io
import json
import tempfile
import unittest
from unittest.mock import patch

from deployments.client import Deployment
from deployments.packages import Packages
from runner.__main__ import main
from runner.store import Store, default_job, dump_yaml


class DeploymentCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(self.temp.name)
        self.store.create(default_job("sample"))
        self.targets = self.store.root / "deployments/targets.yaml"
        self.targets.parent.mkdir(exist_ok=True)
        self.targets.write_text(dump_yaml({"version": 1, "targets": {
            "test": {"ssh_host": "never-contacted", "root": "/srv/script-manager-test"}}}))
        self.packages = Packages(self.store)
        self.package_id = self.packages.create("sample")["id"]
        # Every CLI invocation uses the real Deployment service, with SSH replaced.
        ssh_patch = patch.object(Deployment, "_ssh", autospec=True, return_value={"ok": True})
        self.ssh = ssh_patch.start()
        self.addCleanup(ssh_patch.stop)

    def cli(self, *args):
        output, errors = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            code = main(["--root", self.temp.name, *args])
        return code, json.loads(output.getvalue() or errors.getvalue())

    def plan(self, package_id=None):
        code, plan = self.cli("deploy-plan", "sample", "test", "--package-id",
                              package_id or self.package_id)
        self.assertEqual(code, 0, plan)
        return plan

    def assert_rejected(self, *args):
        code, result = self.cli(*args)
        self.assertEqual(code, 1, result)
        self.assertTrue(result["error"])
        self.ssh.assert_not_called()
        self.assertEqual(Deployment(self.store).history("sample"), [])

    def test_help_and_required_options_parse_before_store_initialization(self):
        cases = [(["deploy-plan", "--help"], 0, "--package-id"),
                 (["deploy", "--help"], 0, "--plan-hash"),
                 (["deploy-plan", "sample", "test"], 2, "--package-id"),
                 (["deploy", "sample", "test", "--plan-hash", "a" * 64], 2, "--package-id"),
                 (["deploy", "sample", "test", "--package-id", self.package_id], 2, "--plan-hash"),
                 (["deploy-plan", "sample", "test", "--package-id"], 2, "expected one argument")]
        for args, expected_code, message in cases:
            with self.subTest(args=args), patch("runner.__main__.Store") as store:
                output, errors = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
                    with self.assertRaises(SystemExit) as caught:
                        main(args)
                self.assertEqual(caught.exception.code, expected_code)
                self.assertIn(message, output.getvalue() + errors.getvalue())
                if "--help" in args and args[0] == "deploy":
                    self.assertIn("--package-id", output.getvalue())
                store.assert_not_called()
        self.ssh.assert_not_called()

    def test_cli_forwards_package_and_confirmed_hash_to_existing_service(self):
        with patch.object(Deployment, "plan", autospec=True, return_value={}) as plan:
            self.assertEqual(self.cli("deploy-plan", "sample", "test", "--package-id", self.package_id)[0], 0)
            self.assertEqual(plan.call_args.args[1:], ("sample", "test", self.package_id))
        confirmed = "a" * 64
        with patch.object(Deployment, "deploy", autospec=True, return_value={}) as deploy:
            self.assertEqual(self.cli("deploy", "sample", "test", "--package-id", self.package_id,
                                      "--plan-hash", confirmed)[0], 0)
            self.assertEqual(deploy.call_args.args[1:], ("sample", "test", self.package_id, confirmed))
        self.ssh.assert_not_called()

    def test_offline_plan_and_deploy_use_fixed_package_after_live_job_edit(self):
        plan = self.plan()
        self.assertEqual(plan["package_id"], self.package_id)
        self.assertEqual(plan["package_hash"], self.packages.get(self.package_id, "sample")["content_hash"])
        self.ssh.assert_not_called()
        # Live Job edits must not invalidate or replace an immutable Package.
        (self.store.job_dir("sample") / "main.py").write_text("print('changed after planning')\n")
        self.assertEqual(self.plan()["plan_hash"], plan["plan_hash"])
        code, receipt = self.cli("deploy", "sample", "test", "--package-id", self.package_id,
                                 "--plan-hash", plan["plan_hash"])
        self.assertEqual(code, 0, receipt)
        self.assertEqual(receipt["status"], "verified")
        self.assertEqual(receipt["package_id"], self.package_id)
        self.ssh.assert_called_once()
        _, target, payload = self.ssh.call_args.args
        self.assertEqual(target["id"], "test")
        self.assertEqual(payload["action"], "deploy")
        self.assertEqual(payload["info"]["package_id"], self.package_id)
        self.assertEqual(payload["info"]["plan_hash"], plan["plan_hash"])
        self.assertEqual(receipt["snapshot"]["files"], plan["files"])

    def test_empty_malformed_and_unknown_package_ids_rejected_before_ssh(self):
        for package_id in ("", "../escape", "INVALID", "p-" + "0" * 32):
            for action in ("deploy-plan", "deploy"):
                with self.subTest(package_id=package_id, action=action):
                    args = [action, "sample", "test", "--package-id", package_id]
                    if action == "deploy":
                        args += ["--plan-hash", "a" * 64]
                    self.assert_rejected(*args)

    def test_package_from_another_job_rejected_before_ssh(self):
        self.store.create(default_job("other"))
        other = self.packages.create("other")["id"]
        self.assert_rejected("deploy-plan", "sample", "test", "--package-id", other)
        self.assert_rejected("deploy", "sample", "test", "--package-id", other, "--plan-hash", "a" * 64)

    def test_empty_malformed_and_incorrect_hashes_rejected_before_ssh(self):
        plan = self.plan()
        wrong_hash = ("0" if plan["plan_hash"][0] != "0" else "1") + plan["plan_hash"][1:]
        for plan_hash in ("", "not-a-hash", wrong_hash):
            with self.subTest(plan_hash=plan_hash):
                self.assert_rejected("deploy", "sample", "test", "--package-id", self.package_id,
                                     "--plan-hash", plan_hash)

    def test_hash_for_different_package_rejected_before_ssh(self):
        plan = self.plan()
        second = self.packages.create("sample")["id"]
        self.assertNotEqual(second, self.package_id)
        self.assert_rejected("deploy", "sample", "test", "--package-id", second,
                             "--plan-hash", plan["plan_hash"])

    def test_target_change_after_planning_rejected_before_ssh(self):
        plan = self.plan()
        self.targets.write_text(self.targets.read_text().replace("never-contacted", "changed-target"))
        self.assertNotEqual(self.plan()["plan_hash"], plan["plan_hash"])
        self.assert_rejected("deploy", "sample", "test", "--package-id", self.package_id,
                             "--plan-hash", plan["plan_hash"])

    def test_package_corruption_after_planning_rejected_before_ssh(self):
        plan = self.plan()
        archive = self.packages.root / self.package_id / "package.zip"
        archive.chmod(0o600)
        archive.write_bytes(b"corrupt fixture archive")
        self.assert_rejected("deploy-plan", "sample", "test", "--package-id", self.package_id)
        self.assert_rejected("deploy", "sample", "test", "--package-id", self.package_id,
                             "--plan-hash", plan["plan_hash"])

    def test_missing_package_zip_after_planning_rejected_before_ssh(self):
        plan = self.plan()
        (self.packages.root / self.package_id / "package.zip").unlink()
        self.assert_rejected("deploy-plan", "sample", "test", "--package-id", self.package_id)
        self.assert_rejected("deploy", "sample", "test", "--package-id", self.package_id,
                             "--plan-hash", plan["plan_hash"])
