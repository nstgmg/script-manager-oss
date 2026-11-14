"""Run persistence under held/concurrent observers and injected write failures."""
import errno
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from runner.common import open_atomic_read, read_json, write_json
from runner.execution import Execution
from runner.results import Results
from runner.store import Store, default_job
from tests.execution_helpers import capture_workers


class MetadataExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(self.temp.name)
        self.execution = Execution(self.store)
        self.diagnostics = capture_workers(self, self.store.root)

    def create(self, *, command=None, parameters=None):
        config = default_job("sample")
        config["command"] = command or [sys.executable, "-c", "print('done')"]
        config["timeout_seconds"] = 1
        if parameters:
            config["parameters"] = parameters
        self.store.create(config)

    def queued(self):
        # Synchronous worker failure injection without launching a real child.
        with patch("runner.execution.subprocess.Popen") as spawn:
            spawn.return_value.pid = 12345
            return self.execution.start("sample")["id"]

    def test_initial_running_save_failure_does_not_shadow_lifecycle(self):
        self.create()
        for lifecycle_failure in (None, RuntimeError("synthetic lifecycle failure")):
            with self.subTest(lifecycle_failure=str(lifecycle_failure)):
                run = self.queued()
                path = self.execution.run_dir("sample", run) / "run.json"
                failure = PermissionError(errno.EACCES, "synthetic initial save failure")
                attempts = []

                def save(target, record):
                    attempts.append(record["state"])
                    if len(attempts) == 1:
                        raise failure
                    write_json(target, record)

                with patch("runner.execution.write_json", side_effect=save), \
                        patch("runner.execution.signal.signal"), \
                        patch("runner.execution.monitor") as monitor, \
                        patch("runner.lifecycle.Lifecycle.automatic", side_effect=lifecycle_failure) as automatic:
                    self.execution.worker("sample", run, -1)
                record = read_json(path)
                self.assertEqual(record["state"], "failed")
                self.assertIn("synthetic initial save failure", record["error"])
                self.assertTrue(record["finished_at"])
                monitor.assert_not_called()
                automatic.assert_called_once_with("sample")
                if lifecycle_failure:
                    self.assertEqual(record["lifecycle_error"], str(lifecycle_failure))
                    self.assertEqual(attempts, ["running", "failed", "failed"])
                else:
                    self.assertNotIn("lifecycle_error", record)
                    self.assertEqual(attempts, ["running", "failed"])

    def test_final_save_denial_propagates_and_never_reports_success(self):
        self.create()
        run = self.queued()
        path = self.execution.run_dir("sample", run) / "run.json"
        failure = PermissionError(errno.EACCES, "synthetic final save failure")
        attempts = []

        def save(target, record):
            attempts.append(record["state"])
            if record["state"] == "succeeded":
                raise failure
            write_json(target, record)

        with patch("runner.execution.write_json", side_effect=save), \
                patch("runner.execution.signal.signal"), \
                patch("runner.execution.monitor", return_value={"state": "succeeded", "exit_code": 0}), \
                patch("runner.lifecycle.Lifecycle.automatic") as automatic:
            with self.assertRaises(PermissionError) as raised:
                self.execution.worker("sample", run, -1)
        self.assertIs(raised.exception, failure)
        self.assertEqual(attempts, ["running", "succeeded"])
        self.assertEqual(read_json(path)["state"], "running")
        automatic.assert_not_called()
        # Model an expired dead-worker lease without waiting or probing a real PID.
        if os.name == "nt":
            lease = self.store.runtime / "locks/sample.run.active"
            value = read_json(lease)
            write_json(lease, {**value, "created": time.time() - 60})
        with patch("runner.common.windows_pid_alive", return_value=False):
            self.assertEqual(self.execution.get("sample", run)["state"], "interrupted")

    def test_heartbeat_save_failure_is_terminal_failure_with_original_diagnostic(self):
        self.create()
        run = self.queued()
        path = self.execution.run_dir("sample", run) / "run.json"
        failure = PermissionError(errno.EACCES, "synthetic heartbeat save failure")
        attempts = []

        def save(target, record):
            attempts.append(record["state"])
            if record["state"] == "running" and record.get("pid"):
                raise failure
            write_json(target, record)

        def monitor(*args):
            args[6](12345)  # Invoke the real worker heartbeat before any outcome.
            self.fail("heartbeat failure must propagate out of the monitor")

        with patch("runner.execution.write_json", side_effect=save), \
                patch("runner.execution.signal.signal"), \
                patch("runner.execution.monitor", side_effect=monitor), \
                patch("runner.lifecycle.Lifecycle.automatic") as automatic:
            self.execution.worker("sample", run, -1)
        record = read_json(path)
        self.assertEqual(record["state"], "failed")
        self.assertIn("synthetic heartbeat save failure", record["error"])
        self.assertTrue(record["finished_at"])
        self.assertNotIn("exit_code", record)
        self.assertNotIn("lifecycle_error", record)
        self.assertEqual(attempts, ["running", "running", "failed"])
        automatic.assert_called_once_with("sample")

    def test_parameter_runs_save_terminal_states_with_concurrent_observers(self):
        script = """
import json, os, sys, time
from pathlib import Path
values = json.loads(os.environ['SCRIPT_MANAGER_PARAMETERS'])
assert values['count'] == 3
mode = values['mode']
Path(os.environ['SCRIPT_MANAGER_OUTPUT_DIR'], 'ready').touch()
print('parameters accepted', flush=True)
time.sleep(30 if mode in ('cancel', 'timeout') else .3)
sys.exit(7 if mode == 'failure' else 0)
"""
        self.create(command=[sys.executable, "-c", script], parameters={
            "mode": {"type": "string", "required": True,
                     "choices": ["success", "failure", "timeout", "cancel"]},
            "count": {"type": "integer", "default": 3}})
        for mode, expected in (("success", "succeeded"), ("failure", "failed"),
                               ("timeout", "timed_out"), ("cancel", "cancelled")):
            with self.subTest(mode=mode):
                accepted = self.execution.start("sample", parameters={"mode": mode})
                run = accepted["id"]
                path = self.execution.run_dir("sample", run) / "run.json"
                ready = self.store.root / accepted["managed_output"] / "ready"
                stop = threading.Event()
                errors, observed = [], []

                def observe():
                    try:
                        while not stop.is_set():
                            row = self.execution.get("sample", run)
                            rows, warnings = Results(self.store).runs("sample")
                            self.assertFalse(warnings, warnings)
                            self.assertTrue(any(r["id"] == run for r in rows))
                            observed.append(row["state"])
                            stop.wait(.002)
                    except BaseException as exc:
                        errors.append(exc)

                threads = [threading.Thread(target=observe) for _ in range(2)]
                try:
                    with open_atomic_read(path) as held:
                        for thread in threads:
                            thread.start()
                        deadline = time.monotonic() + 12
                        cancelled = False
                        while time.monotonic() < deadline:
                            if mode == "cancel" and ready.exists() and not cancelled:
                                self.execution.cancel("sample", run)
                                cancelled = True
                            record = read_json(path)
                            if (record["state"] not in ("queued", "running")
                                    and self.diagnostics("sample", run)["worker_returncode"] is not None):
                                break
                            time.sleep(.01)
                        self.assertEqual(record["state"], expected, self.diagnostics("sample", run))
                        self.assertEqual(record["parameters"], {"mode": mode, "count": 3})
                        self.assertEqual(record["parameter_contract_version"], 1)
                        self.assertTrue(record["finished_at"])
                        self.assertNotIn("error", record)
                        self.assertNotIn("lifecycle_error", record)
                        self.assertIsInstance(record["exit_code"], int)
                        if mode in ("success", "failure"):
                            self.assertEqual(record["exit_code"], 0 if mode == "success" else 7)
                        else:
                            self.assertNotEqual(record["exit_code"], 0)
                        self.assertEqual(self.diagnostics("sample", run)["worker_returncode"], 0)
                        self.assertEqual(self.diagnostics("sample", run)["lease"], {})
                        self.assertIn(json.load(held)["state"], ("queued", "running", expected))
                finally:
                    stop.set()
                    for thread in threads:
                        if thread.ident is not None:
                            thread.join(timeout=5)
                            self.assertFalse(thread.is_alive())
                    # Cancel only this test-owned Run on an assertion failure.
                    if read_json(path)["state"] in ("queued", "running"):
                        self.execution.cancel("sample", run)
                        deadline = time.monotonic() + 12
                        while time.monotonic() < deadline:
                            if self.execution.get("sample", run)["state"] not in ("queued", "running"):
                                break
                            time.sleep(.05)
                self.assertFalse(errors, errors)
                self.assertTrue(observed)
                self.assertEqual(self.execution.get("sample", run)["state"], expected)
