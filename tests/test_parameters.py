import contextlib
import io
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from runner.__main__ import main
from runner.common import ManagerError
from runner.execution import Execution
from runner.parameters import parse_cli_parameters, resolve_parameters, validate_contract
from runner.store import Store, default_job, dump_yaml, validate


def definitions():
    return {
        "text": {"type": "string", "description": "Public text", "required": True,
                 "cli": {"option": "--text"}},
        "count": {"type": "integer", "default": 2, "min": 1, "max": 5,
                  "cli": {"option": "--count"}},
        "ratio": {"type": "number", "default": .5, "min": 0, "max": 1},
        "day": {"type": "date", "min": "2026-01-01", "max": "2026-12-31"},
        "source": {"type": "string", "choices": ["one", "two"], "default": "one"},
        "enabled": {"type": "boolean", "default": False, "cli": {"option": "--enabled"}},
        "verbose": {"type": "boolean", "cli": {"option": "--verbose", "mode": "flag"}},
    }


MOCK_SCRIPT = '''import json, os, sys, time
from pathlib import Path
time.sleep(.1)
values = json.loads(os.environ.get('SCRIPT_MANAGER_PARAMETERS', '{}'))
print(json.dumps({'values': values, 'argv': sys.argv[1:]}, ensure_ascii=False))
Path(os.environ['SCRIPT_MANAGER_OUTPUT_DIR'], 'report.json').write_text(json.dumps({'items': []}))
'''


class ContractTests(unittest.TestCase):
    def config(self):
        return dict(default_job("sample"), parameters=definitions())

    def test_types_defaults_omission_required_and_dates(self):
        config = self.config()
        values = resolve_parameters(config, {"text": "hello", "day": "2026-02-28", "enabled": True})
        self.assertEqual(values, dict(text="hello", count=2, ratio=.5, day="2026-02-28", source="one", enabled=True))
        for supplied in ({}, {"text": ""}, {"text": "x", "count": True},
                         {"text": "x", "count": "2"}, {"text": "x", "count": 2.0},
                         {"text": "x", "ratio": float("nan")}, {"text": "x", "ratio": float("inf")},
                         {"text": "x", "day": "2026-02-30"}, {"text": "x", "day": "2026-2-01"},
                         {"text": "x", "day": "2025-12-31"}, {"text": "x", "source": "other"},
                         {"text": "x", "count": 6}, {"text": "x", "count": 0},
                         {"text": "x", "enabled": "false"}, {"text": "x", "unknown": 1},
                         {"text": None}, {"text": "\x00"}, {"text": "a" * 4097}, []):
            with self.subTest(supplied=repr(supplied)[:120]), self.assertRaises(ManagerError):
                resolve_parameters(config, supplied)
        self.assertEqual(resolve_parameters(default_job("old")), {})
        with self.assertRaises(ManagerError):
            resolve_parameters(default_job("old"), {"new": 1})

    def test_invalid_contracts_and_secret_definitions(self):
        invalid = [None, [], {"x": {}}, {"x": {"type": []}},
                   {"x": {"type": "integer", "default": True}},
                   {"x": {"type": "integer", "min": 5, "max": 1}},
                   {"x": {"type": "string", "min": 1}},
                   {"x": {"type": "string", "required": "yes"}},
                   {"x": {"type": "boolean", "choices": [False, 0]}},
                   {"x": {"type": "integer", "choices": [1, 1]}},
                   {"x": {"type": "integer", "choices": [1], "default": 2}},
                   {"x": {"type": "date", "min": "2026-02-30"}},
                   {"api_key": {"type": "string", "default": "sentinel-do-not-echo"}},
                   {"password": {"type": "string"}},
                   {"x": {"type": "string", "secret": True}},
                   {"SCRIPT_MANAGER_OUTPUT_DIR": {"type": "string"}},
                   {"x": {"type": "string", "cli": {"option": "--x; touch file"}}},
                   {"x": {"type": "string", "cli": {"option": "--x", "mode": "flag"}}},
                   {"x": {"type": "string", "cli": {"option": "--same"}},
                    "y": {"type": "string", "cli": {"option": "--same"}}}]
        for contract in invalid:
            with self.subTest(contract=contract), self.assertRaises(ManagerError) as caught:
                validate(dict(default_job("sample"), parameters=contract))
            self.assertNotIn("sentinel-do-not-echo", str(caught.exception))
        with self.assertRaises(ManagerError):
            validate_contract({"required_env": ["SERVICE_AUTH"], "parameters": {"service_auth": {"type": "string"}}})

    def test_cli_json_errors_do_not_echo_values(self):
        for text in ('{"x":"sentinel-do-not-echo",', '{"x":1,"x":2}', '[]', 'null', '{"x":NaN}'):
            with self.assertRaises(ManagerError) as caught:
                parse_cli_parameters(text)
            self.assertNotIn("sentinel-do-not-echo", str(caught.exception))
        self.assertEqual(parse_cli_parameters('{"x":false,"n":1}'), {"x": False, "n": 1})

    def test_size_limits_empty_contract_and_numeric_limits(self):
        self.assertEqual(resolve_parameters({"parameters": {}}), {})
        config = {"parameters": {"n": {"type": "number"}}}
        for value in (9007199254740992, float('-inf')):
            with self.assertRaises(ManagerError):
                resolve_parameters(config, {"n": value})
        config = {"parameters": {"field" + str(i): {"type": "string", "default": "한" * 4096} for i in range(3)}}
        with self.assertRaises(ManagerError):
            resolve_parameters(config)


class ParameterExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(self.temp.name)
        self.execution = Execution(self.store)
        self.config = dict(default_job("sample"), command=[sys.executable, "main.py"], parameters=definitions())
        self.store.create(self.config)
        (self.store.job_dir("sample") / "main.py").write_text(MOCK_SCRIPT)

    def wait(self, run):
        for _ in range(150):
            result = self.execution.get("sample", run["id"])
            if result["state"] not in ("queued", "running"):
                return result
            time.sleep(.02)
        self.fail("Fixture run did not finish")

    def cli(self, *args):
        output, errors = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            code = main(["--root", self.temp.name, *args])
        return code, json.loads(output.getvalue() or errors.getvalue())

    def test_argv_snapshot_frozen_contract_and_metadata(self):
        text = '$(touch INJECTED); `touch INJECTED` --unsafe <script>'
        old = self.store.get("sample")
        # Real fixture secrets are private, only declared keys enter the child environment.
        secret = Path(self.temp.name) / ".env"
        secret.write_text("SERVICE_AUTH=fixture-private-value\nUNDECLARED=other-private-value\n")
        secret.chmod(0o600)
        config = old["config"]
        config["required_env"] = ["SERVICE_AUTH"]
        old = self.store.update("sample", dump_yaml(config), old["etag"])
        run = self.execution.start("sample", parameters={"text": text, "verbose": True})
        # Change the live contract and code immediately; the accepted Run is frozen.
        config["parameters"]["count"]["default"] = 4
        self.store.update("sample", dump_yaml(config), old["etag"])
        (self.store.job_dir("sample") / "main.py").write_text('raise RuntimeError("changed")')
        result = self.wait(run)
        self.assertEqual((result["state"], result["exit_code"]), ("succeeded", 0), result)
        logged = json.loads(self.execution.logs("sample", run["id"])["text"])
        self.assertEqual(logged["values"], result["parameters"])
        self.assertEqual(logged["argv"], ["--text=" + text, "--count=2", "--enabled=false", "--verbose"])
        self.assertEqual(result["config"]["parameters"]["count"]["default"], 2)
        self.assertEqual(result["parameter_contract_version"], 1)
        directory = self.execution.run_dir("sample", run["id"])
        self.assertFalse((directory / "source/INJECTED").exists())
        self.assertFalse((directory / "source/.env").exists())
        self.assertNotIn("fixture-private-value", (directory / "run.json").read_text())
        self.assertNotIn("other-private-value", (directory / "run.json").read_text())
        self.assertEqual(result["resolved_command"][2:], logged["argv"])

    def test_invalid_inputs_never_spawn_or_create_run(self):
        for supplied in ({}, {"text": "x", "count": 6}, {"api_key": "sentinel-do-not-echo"}):
            with patch("runner.execution.subprocess.Popen") as spawn:
                with self.assertRaises(ManagerError) as caught:
                    self.execution.start("sample", parameters=supplied)
                spawn.assert_not_called()
                self.assertNotIn("sentinel-do-not-echo", str(caught.exception))
        self.assertEqual(self.execution.list("sample"), [])

    def test_cli_discovery_and_execution_without_mutating_yaml(self):
        old = self.store.get("sample")
        code, discovered = self.cli("get", "sample")
        self.assertEqual(code, 0)
        self.assertEqual(discovered["config"]["parameters"], self.config["parameters"])
        code, result = self.cli("run", "sample", "--wait", "--parameters", '{"text":"hello","count":3}')
        self.assertEqual(code, 0, result)
        self.assertEqual(result["parameters"]["count"], 3)
        self.assertEqual(self.store.get("sample")["yaml"], old["yaml"])
        code, error = self.cli("run", "sample", "--parameters", '{"text":"x","count":"3"}')
        self.assertEqual(code, 1)
        self.assertIn("integer", error["error"])

    def test_schedule_defaults_and_missing_required(self):
        with self.assertRaises(ManagerError):
            self.execution.start("sample", trigger="schedule")
        old = self.store.get("sample")
        config = old["config"]
        config["parameters"]["text"]["default"] = "scheduled"
        self.store.update("sample", dump_yaml(config), old["etag"])
        result = self.wait(self.execution.start("sample", trigger="schedule"))
        self.assertEqual(result["state"], "succeeded")
        self.assertEqual(result["parameters"]["text"], "scheduled")

    def test_duplicate_parameter_runs_keep_existing_lock(self):
        (self.store.job_dir("sample") / "main.py").write_text("import time; time.sleep(.3)")
        run = self.execution.start("sample", parameters={"text": "one"})
        try:
            with self.assertRaises(ManagerError) as caught:
                self.execution.start("sample", parameters={"text": "two"})
            self.assertEqual(caught.exception.status, 409)
        finally:
            self.wait(run)
        self.assertEqual(len(self.execution.list("sample")), 1)

    def test_legacy_job_keeps_environment_command_and_record(self):
        old = self.store.get("sample")
        config = old["config"]
        del config["parameters"]
        self.store.update("sample", dump_yaml(config), old["etag"])
        (self.store.job_dir("sample") / "main.py").write_text("import os,sys; assert 'SCRIPT_MANAGER_PARAMETERS' not in os.environ; assert len(sys.argv)==1")
        result = self.wait(self.execution.start("sample"))
        self.assertEqual(result["state"], "succeeded")
        self.assertNotIn("parameters", result)
        self.assertNotIn("resolved_command", result)

    def test_new_package_captures_contract_and_common_runtime(self):
        import zipfile
        from deployments.packages import Packages
        packages = Packages(self.store)
        package = packages.create("sample")
        original = packages.archive(package["id"], "sample")
        with zipfile.ZipFile(io.BytesIO(original)) as archive:
            self.assertIn("manager/runner/parameters.py", archive.namelist())
            self.assertEqual(json.loads(archive.read("package.json"))["config"]["parameters"], self.config["parameters"])
        item = self.store.get("sample")
        config = item["config"]
        config["parameters"]["count"]["default"] = 5
        self.store.update("sample", dump_yaml(config), item["etag"])
        self.assertEqual(packages.archive(package["id"], "sample"), original)

    def test_remote_defaults_use_common_contract_and_fail_without_required_inputs(self):
        from types import SimpleNamespace
        from deployments.remote_runtime import run_locked
        base = Path(self.temp.name) / "remote"
        (base / "source").mkdir(parents=True)
        logs = base / "logs"
        logs.mkdir()
        config = self.config
        config["parameters"]["text"]["default"] = "remote-default"
        state = {}
        with patch("runner.execution.monitor", return_value={"state": "succeeded", "exit_code": 0}) as monitor:
            code = run_locked(SimpleNamespace(shared=base), config, base, logs, state, [False])
            self.assertEqual(code, 0)
            self.assertIn('--text=remote-default', monitor.call_args.args[0])
            values = json.loads(monitor.call_args.args[2]['SCRIPT_MANAGER_PARAMETERS'])
            self.assertEqual(values, state['parameters'])
            self.assertEqual(state['config']['parameters'], config['parameters'])
        del config["parameters"]["text"]["default"]
        with patch("runner.execution.monitor") as monitor:
            code = run_locked(SimpleNamespace(shared=base), config, base, logs, {}, [False])
            self.assertEqual(code, 1)
            monitor.assert_not_called()


if __name__ == "__main__":
    unittest.main()
