"""Source-to-sink regressions for CodeQL #169/#170; every OS command is fake.

No HTTP server, worker, native registration, ACL change or network collection.
Windows assertions cover dispatch/argv/XML construction, not native parsing.
"""
from contextlib import contextmanager
import io
import json
from pathlib import Path
import plistlib
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from dashboard.server import Handler
from runner.common import ManagerError, write_json
from runner.results import Results, load_rows
from runner.schedule import Scheduler
from runner.schedule_doctor import ScheduleDoctor
from runner.store import Store, default_job
from runner.windows_schedule import WindowsScheduler, NS, task_xml
from tests.test_schedule import LaunchctlFake
from tests.test_windows_schedule import FakeTasks, schedule


BAD_IDS = ("-option", "/Delete", "a b", "a\tb", "a\nb", "a;b", "a&b",
           "a|b", "$(literal)", "`literal`", "a'b", 'a"b', "a/b", "a\\b",
           "..", "a.b", "*", "a\x00b", "é", "a" * 64, "", None, 1)


class ScheduleCommandSecurityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="sm-command-security-")
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(load_rows.cache_clear)
        self.root = Path(self.temp.name)

    @contextmanager
    def backend(self, system):
        with patch("runner.schedule.platform.system", return_value=system), \
                patch("runner.schedule.os.getuid", return_value=501, create=True):
            store = Store(self.root / system / "data & (space) '한글'")
            config = default_job("sample")
            config["command"] = ["trusted-job-program", "literal & ; argument"]
            store.create(config)
            fake = LaunchctlFake() if system == "Darwin" else FakeTasks()
            calls = []

            def command(args, **kwargs):
                calls.append((list(args), kwargs))
                return fake(args, **kwargs)

            scheduler = Scheduler(store, self.root / system / "agents & 'space'", command)
            yield store, scheduler, fake, calls

    def request(self, store, scheduler, method, body, headers=None):
        raw = json.dumps(body).encode("utf-8")
        handler = Handler.__new__(Handler)
        handler.server = SimpleNamespace(store=store, token="synthetic-session",
                                         server_address=("127.0.0.1", 18765))
        handler.command = method
        handler.path = "/api/jobs/sample/schedules"
        handler.headers = {"Host": "127.0.0.1:18765", "Origin": "http://127.0.0.1:18765",
                           "X-CSRF-Token": handler.server.token, "Content-Length": str(len(raw))}
        handler.headers.update(headers or {})
        handler.rfile = io.BytesIO(raw)
        responses = []
        handler.send = lambda status, value, *args, **kwargs: responses.append((status, value))
        with patch("dashboard.server.Scheduler", return_value=scheduler):
            handler.dispatch()
        self.assertEqual(len(responses), 1)
        return responses[0], handler.rfile.tell()

    def test_invalid_ids_cannot_reach_either_native_observer_or_save(self):
        for system in ("Darwin", "Windows"):
            with self.subTest(system=system), self.backend(system) as (store, scheduler, _, calls):
                before = store.get("sample")["yaml"]
                for value in BAD_IDS:
                    with self.subTest(value=repr(value)):
                        for job, sid in ((value, "daily"), ("sample", value)):
                            if sid is None:  # None deliberately selects the legacy Job label.
                                continue
                            with self.assertRaises(ManagerError):
                                scheduler.observed(job, sid)
                        with self.assertRaises(ManagerError):
                            scheduler.save("sample", value, schedule(value), store.get("sample")["etag"], True)
                self.assertEqual(calls, [])
                self.assertEqual(store.get("sample")["yaml"], before)

    def test_valid_id_boundaries_remain_single_literal_service_arguments(self):
        for system in ("Darwin", "Windows"):
            with self.subTest(system=system), self.backend(system) as (_, scheduler, _, calls):
                for sid in (None, "a", "0", "daily-9", "a" * 63):
                    scheduler.observed("sample", sid)
                    args = calls[-2][0]
                    if system == "Darwin":
                        self.assertEqual(args[:2], ["launchctl", "print"])
                        self.assertEqual(len(args), 3)
                        self.assertTrue(args[2].startswith("gui/501/local.scriptmanager."))
                    else:
                        self.assertEqual(args[:3], ["schtasks", "/Query", "/TN"])
                        self.assertEqual(len(args), 5)
                        self.assertEqual(args[4], "/XML")
                        self.assertTrue(args[3].startswith("\\local.scriptmanager."))
                    self.assertTrue(args[2 if system == "Darwin" else 3].endswith(".sample" + ("." + sid if sid else "")))

    def test_http_body_schedule_id_is_rejected_before_os_calls(self):
        for system in ("Darwin", "Windows"):
            with self.subTest(system=system), self.backend(system) as (store, scheduler, _, calls):
                before = store.get("sample")["yaml"]
                for value in BAD_IDS:
                    with self.subTest(value=repr(value)):
                        (status, _), _ = self.request(store, scheduler, "POST", {
                            "schedule": schedule(value), "etag": store.get("sample")["etag"]})
                        self.assertEqual(status, 400)
                self.assertEqual(calls, [])
                self.assertEqual(store.get("sample")["yaml"], before)

    def test_host_origin_csrf_and_get_body_do_not_create_reservations(self):
        for system in ("Darwin", "Windows"):
            with self.subTest(system=system), self.backend(system) as (store, scheduler, fake, calls):
                body = {"schedule": schedule("daily"), "etag": store.get("sample")["etag"]}
                for headers in ({"Host": "evil.test"}, {"Origin": "https://evil.test"}, {"X-CSRF-Token": ""}):
                    (status, _), consumed = self.request(store, scheduler, "POST", body, headers)
                    self.assertEqual((status, consumed), (403, 0))
                self.assertEqual(calls, [])
                (status, _), consumed = self.request(store, scheduler, "GET", body)
                self.assertEqual((status, consumed), (200, 0))
                self.assertEqual(store.get("sample")["config"]["schedules"], [])
                self.assertFalse(fake.services if system == "Darwin" else fake.tasks)

    def test_normal_save_and_observation_keep_job_command_out_of_management_argv(self):
        for system in ("Darwin", "Windows"):
            with self.subTest(system=system), self.backend(system) as (store, scheduler, fake, calls):
                entry = dict(schedule("daily-9"), name="Display 'name' & <text>")
                (status, result), _ = self.request(store, scheduler, "POST", {
                    "schedule": entry, "etag": store.get("sample")["etag"]})
                self.assertEqual(status, 201, result)
                self.assertTrue(scheduler.observed("sample", "daily-9")["file_matches"])
                self.assertTrue(calls)
                for args, kwargs in calls:
                    self.assertIsInstance(args, list)
                    self.assertFalse(kwargs.get("shell", False))
                    self.assertNotIn("trusted-job-program", args)
                    self.assertNotIn("literal & ; argument", args)
                    self.assertNotIn(entry["name"], args)
                    self.assertIn(args[0], {"launchctl", "plutil"} if system == "Darwin" else {"schtasks", "powershell.exe"})
                if system == "Darwin":
                    definition = next(iter(fake.definitions.values()))
                    self.assertEqual(definition["ProgramArguments"], [sys.executable, "-m", "runner", "--root",
                        str(store.root), "_scheduled", "sample", result["state"]["generation"], "daily-9"])
                    bootstrap = next(args for args, _ in calls if args[:2] == ["launchctl", "bootstrap"])
                    self.assertEqual(len(bootstrap), 4)
                    self.assertIn("agents & 'space'", bootstrap[3])
                else:
                    self.assertIsInstance(scheduler, WindowsScheduler)
                    self.assertFalse(any(args[0] == "launchctl" for args, _ in calls))
                    create = next(args for args, _ in calls if args[:2] == ["schtasks", "/Create"])
                    self.assertEqual(len(create), 7)
                    self.assertEqual(create[2], "/TN")
                    self.assertEqual(create[4], "/XML")
                    self.assertTrue(create[5].startswith(str(store.runtime)))

    def test_windows_xml_encodes_paths_and_principal_as_data(self):
        executable = r"C:\Program Files\Python\python.exe"
        root = r"C:\Jobs & Co\plan"
        author = 'synthetic "account" & <tag>'
        xml = task_xml([executable, "-m", "runner", "--root", root, "_scheduled", "sample", "a" * 32, "daily"],
                       r"C:\Manager & Tools", schedule("daily"), author, "a" * 32)
        tree = ET.fromstring(xml)
        q = "{" + NS + "}"
        self.assertEqual(len(tree.findall(q + "Actions/" + q + "Exec")), 1)
        self.assertEqual(tree.findtext(q + "Actions/" + q + "Exec/" + q + "Command"), executable)
        self.assertEqual(tree.findtext(q + "Actions/" + q + "Exec/" + q + "Arguments"),
                         '-m runner --root "C:\\Jobs & Co\\plan" _scheduled sample ' + "a" * 32 + ' daily')
        self.assertEqual(tree.findtext(q + "Principals/" + q + "Principal/" + q + "UserId"), author)
        self.assertEqual(tree.findall(".//tag"), [])

    def test_powershell_expression_refuses_unsafe_labels_before_interpolation(self):
        with self.backend("Windows") as (_, scheduler, _, calls):
            doctor = ScheduleDoctor(scheduler.store, scheduler)
            label = scheduler.task_name("sample", "daily")
            for suffix in ("';literal", "`literal", "$(literal)", " /Delete", "\\child"):
                with self.subTest(suffix=suffix), self.assertRaises(ManagerError):
                    doctor._windows_running(label + suffix)
            self.assertEqual(calls, [])
            self.assertFalse(doctor._windows_running(label))
            self.assertEqual(calls[0][0][:4], ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command"])
            self.assertEqual(calls[0][0][4], "[int](Get-ScheduledTask -TaskPath '\\' -TaskName '" +
                             label.lstrip("\\") + "' -ErrorAction Stop).State")

    def test_default_wrappers_pass_argv_to_subprocess_without_shell_or_executable_override(self):
        for cls, args in ((Scheduler, ["launchctl", "print", "gui/501/local.scriptmanager.abc.sample"]),
                          (WindowsScheduler, ["schtasks", "/Query", "/TN", "\\local.scriptmanager.abc.sample", "/XML"])):
            store = Store(self.root / cls.__name__)
            with patch("runner.schedule.platform.system", return_value="Darwin"), \
                    patch("runner.schedule.subprocess.run", return_value=subprocess.CompletedProcess(args, 0, "", "")) as run:
                scheduler = cls(store)
                scheduler.call(args)
                self.assertEqual(run.call_args.args, (args,))
                self.assertFalse(run.call_args.kwargs.get("shell", False))
                self.assertNotIn("executable", run.call_args.kwargs)

    def test_saved_external_shaped_data_is_not_applied_as_schedule_config(self):
        with self.backend("Darwin") as (store, _, _, calls):
            before = store.get("sample")["yaml"]
            run = "a" * 32
            relative = "runtime/job-data/sample/output/" + run
            payload = {"id": "/Delete", "title": "external-shaped synthetic record",
                       "command": "literal; & text", "schedule": {"id": "-option"}}
            write_json(store.root / relative / "result.json", {"complete": True, "records": [payload]})
            write_json(store.runtime / "runs/sample" / run / "run.json", {
                "id": run, "job_id": "sample", "state": "succeeded", "created_at": "2026-11-18T00:00:00+09:00",
                "finished_at": "2026-11-18T00:00:01+09:00", "managed_output": relative})
            result = Results(store).query("sample")
            self.assertEqual(result["total"], 1)
            self.assertEqual(result["items"][0]["data"]["command"], payload["command"])
            self.assertEqual(store.get("sample")["yaml"], before)
            self.assertEqual(calls, [])
