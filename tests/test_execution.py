import hashlib
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from runner.common import ManagerError
from runner.execution import Execution, LOG_LIMIT, environment, snapshot
from runner.store import Store, default_job, dump_yaml


class ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(self.temp.name)
        self.store.create(default_job("sample"))
        self.execution = Execution(self.store)
        self.active = []
        self.addCleanup(self.stop_active)

    def stop_active(self):
        for run in self.active:
            try:
                self.execution.cancel("sample", run)
                self.wait(run)
            except ManagerError:
                pass

    def configure(self, script, **extra):
        job = self.store.get("sample")
        config = job["config"]
        config["command"] = [sys.executable, "main.py"]
        config.update(extra)
        self.store.update("sample", dump_yaml(config), job["etag"])
        (self.store.job_dir("sample") / "main.py").write_text(script)

    def start(self):
        run = self.execution.start("sample")
        self.active.append(run["id"])
        return run["id"]

    def wait(self, run):
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            result = self.execution.get("sample", run)
            if result["state"] not in ("queued", "running"):
                return result
            time.sleep(0.05)
        self.fail("Runner did not finish")

    def test_success_failure_and_source_snapshot(self):
        self.configure('import time\nprint("snapshot output", flush=True)\ntime.sleep(.2)\n')
        run = self.start()
        (self.store.job_dir("sample") / "main.py").write_text('raise RuntimeError("new source")')
        self.assertEqual(self.wait(run)["state"], "succeeded")
        self.assertIn("snapshot output", self.execution.logs("sample", run)["text"])
        self.assertEqual(self.wait(self.start())["state"], "failed")

    def test_overlap_delete_blocked_and_cancelled(self):
        self.configure("import time\ntime.sleep(30)")
        run = self.start()
        with self.assertRaises(ManagerError):
            self.execution.start("sample")
        with self.assertRaises(ManagerError):
            self.store.delete("sample", self.store.get("sample")["etag"])
        self.execution.cancel("sample", run)
        self.assertEqual(self.wait(run)["state"], "cancelled")

    def test_timeout_and_bounded_logs(self):
        self.configure("import time\nprint('hello', flush=True)\ntime.sleep(30)", timeout_seconds=1)
        self.assertEqual(self.wait(self.start())["state"], "timed_out")
        self.configure("import sys\nsys.stdout.write('x' * (6 * 1024 * 1024))")
        run = self.start()
        result = self.wait(run)
        self.assertEqual(result["state"], "succeeded")
        self.assertTrue(result["logs_truncated"])
        self.assertEqual((self.execution.run_dir("sample", run) / "stdout.log").stat().st_size, LOG_LIMIT)

    def test_missing_executable_and_secrets_not_in_snapshot(self):
        secret = self.store.job_dir("sample") / ".env"
        secret.write_text("SAMPLE_SECRET=not-for-snapshot\n")
        secret.chmod(0o600)
        self.configure("import os\nassert os.environ['SAMPLE_SECRET'] == 'not-for-snapshot'\n", env_file=".env")
        run = self.start()
        self.assertEqual(self.wait(run)["state"], "succeeded")
        self.assertFalse((self.execution.run_dir("sample", run) / "source/.env").exists())
        self.assertNotIn("not-for-snapshot", (self.execution.run_dir("sample", run) / "run.json").read_text())
        job = self.store.get("sample")
        config = job["config"]
        config["command"] = ["/definitely/missing/executable"]
        self.store.update("sample", dump_yaml(config), job["etag"])
        self.assertEqual(self.wait(self.start())["state"], "failed")

    def test_shell_metacharacters_are_arguments(self):
        job = self.store.get("sample")
        config = job["config"]
        config["command"] = [sys.executable, "-c", "import sys; print(sys.argv[1])", "$(touch escaped)"]
        self.store.update("sample", dump_yaml(config), job["etag"])
        run = self.start()
        self.assertEqual(self.wait(run)["state"], "succeeded")
        self.assertIn("$(touch escaped)", self.execution.logs("sample", run)["text"])
        self.assertFalse((self.store.job_dir("sample") / "escaped").exists())

    def test_external_config_edit_between_read_and_snapshot_is_rejected(self):
        def changed(folder, dest, env_file):
            path = folder / "job.yaml"
            path.write_text(path.read_text() + "\n# external update\n")
            return snapshot(folder, dest, env_file)
        with patch("runner.execution.snapshot", side_effect=changed):
            with self.assertRaises(ManagerError) as cm:
                self.execution.start("sample")
        self.assertEqual(cm.exception.status, 409)
        self.assertEqual(self.execution.list("sample"), [])

    def root_credentials(self, names=None, text="NEEDED_SECRET=private-value\nOTHER_SECRET=unrelated-value\n"):
        item = self.store.get("sample")
        self.store.update_fields("sample", {"required_env": names if names is not None else ["NEEDED_SECRET"]},
                                 item["etag"])
        path = self.store.root / ".env"
        path.write_text(text)
        path.chmod(0o600)
        return path

    def test_root_env_allowlist_in_detached_worker_and_no_persisted_values(self):
        self.root_credentials()
        (self.store.job_dir("sample") / ".env").write_text("NEEDED_SECRET=wrong-job-file\n")
        expected = hashlib.sha256(b"private-value").hexdigest()
        self.configure("import os, hashlib\n"
                       "assert hashlib.sha256(os.environ['NEEDED_SECRET'].encode()).hexdigest() == " + repr(expected) + "\n"
                       "assert 'OTHER_SECRET' not in os.environ\n"
                       "assert 'SHELL_SECRET' not in os.environ\n"
                       "assert os.environ['SCRIPT_MANAGER_OUTPUT_DIR']\n")
        with patch.dict(os.environ, {"SHELL_SECRET": "shell-value", "NEEDED_SECRET": "wrong-shell-value"}):
            run = self.start()
        record = self.wait(run)
        self.assertEqual(record["state"], "succeeded")
        folder = self.execution.run_dir("sample", run)
        self.assertNotIn(".env", record["manifest"])
        self.assertIn("job.yaml", record["manifest"])
        self.assertEqual(record["config"]["required_env"], ["NEEDED_SECRET"])
        for path in folder.rglob("*"):
            if path.is_file():
                for secret in (b"private-value", b"unrelated-value", b"shell-value"):
                    self.assertNotIn(secret, path.read_bytes(), str(path))

    def test_missing_or_blank_root_keys_block_before_execution_without_fallback(self):
        path = self.root_credentials(text="NEEDED_SECRET=\nOTHER_SECRET=unrelated-value\n")
        (self.store.job_dir("sample") / ".env").write_text("NEEDED_SECRET=local-value\n")
        for exists in (True, False):
            if not exists:
                path.unlink()
            with patch.dict(os.environ, {"NEEDED_SECRET": "shell-value"}):
                with self.assertRaisesRegex(ManagerError, "NEEDED_SECRET") as raised:
                    self.execution.start("sample")
            self.assertNotIn("unrelated-value", str(raised.exception))
            self.assertEqual(self.execution.list("sample"), [])

    def test_root_env_validation_and_safe_error_messages(self):
        path = self.root_credentials()
        self.root_credentials(text="secret-value-without-assignment\n")
        with self.assertRaises(ManagerError) as raised:
            environment(self.store.get("sample")["config"], self.store.job_dir("sample"), self.store.root)
        self.assertNotIn("secret-value", str(raised.exception))
        self.root_credentials()
        path.chmod(0o644)
        if os.name != "nt":
            with self.assertRaisesRegex(ManagerError, "600"):
                environment(self.store.get("sample")["config"], self.store.job_dir("sample"), self.store.root)

    def test_captured_job_config_controls_allowlist_even_after_yaml_changes(self):
        self.root_credentials()
        item = self.store.get("sample")
        self.store.update_fields("sample", {"required_env": ["OTHER_SECRET"]}, item["etag"])
        env = environment(item["config"], self.store.job_dir("sample"), self.store.root)
        self.assertEqual(env["NEEDED_SECRET"], "private-value")
        self.assertNotIn("OTHER_SECRET", env)

    def test_undeclared_jobs_do_not_receive_root_secrets(self):
        path = self.store.root / ".env"
        path.write_text("ROOT_SECRET=do-not-pass\n")
        path.chmod(0o600)
        self.assertNotIn("ROOT_SECRET", environment({}, self.store.job_dir("sample"), self.store.root))

    def test_root_env_symlink_and_mixed_legacy_env_file_are_rejected(self):
        path = self.root_credentials()
        with self.assertRaisesRegex(ManagerError, "함께"):
            environment({"required_env": ["NEEDED_SECRET"], "env_file": ".env"},
                        self.store.job_dir("sample"), self.store.root)
        if os.name != "nt":
            path.unlink()
            other = self.store.root / "secret-other"
            other.write_text("NEEDED_SECRET=not-to-read\n")
            path.symlink_to(other)
            with self.assertRaisesRegex(ManagerError, "심볼릭"):
                environment(self.store.get("sample")["config"], self.store.job_dir("sample"), self.store.root)
