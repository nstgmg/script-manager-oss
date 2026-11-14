"""Windows Task Scheduler contract with schtasks replaced by an in-memory OS."""
import csv
import io
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
import xml.etree.ElementTree as ET

from runner.common import ManagerError
from runner.schedule import Scheduler
from runner.store import Store, default_job
from runner.windows_schedule import WindowsScheduler, NS
from dashboard.server import Handler


class FakeTasks:
    def __init__(self):
        self.tasks = {}
        self.fail_create = False
        self.fail_delete = False

    def __call__(self, args, **_):
        if args[0] == "powershell.exe":
            return subprocess.CompletedProcess(args, 0, "3", "")
        action = args[1].lower()
        if action == "/query" and "/TN" in args:
            name = args[args.index("/TN") + 1]
            return subprocess.CompletedProcess(args, 0, self.tasks[name], "") if name in self.tasks else subprocess.CompletedProcess(args, 1, "", "missing")
        if action == "/query":
            output = io.StringIO()
            writer = csv.writer(output)
            for name in self.tasks:
                writer.writerow([name, "Ready", "N/A"])
            return subprocess.CompletedProcess(args, 0, output.getvalue(), "")
        name = args[args.index("/TN") + 1]
        if action == "/create":
            if self.fail_create:
                self.fail_create = False
                return subprocess.CompletedProcess(args, 1, "", "injected failure")
            self.tasks[name] = Path(args[args.index("/XML") + 1]).read_text(encoding="utf-16")
            return subprocess.CompletedProcess(args, 0, "", "")
        if action == "/delete":
            if self.fail_delete:
                self.fail_delete = False
                return subprocess.CompletedProcess(args, 1, "", "injected delete failure")
            self.tasks.pop(name)
            return subprocess.CompletedProcess(args, 0, "", "")
        raise AssertionError(args)


def schedule(sid, mode="calendar", enabled=True):
    item = {"id": sid, "name": sid, "enabled": enabled, "type": mode}
    if mode == "calendar":
        item.update(times=["08:00", "18:00"], weekdays=[1, 5])
    else:
        item["interval_seconds"] = 90
    return item


class WindowsScheduleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(self.temp.name)
        self.store.create(default_job("sample"))
        self.fake = FakeTasks()
        patcher = patch("runner.schedule.platform.system", return_value="Windows")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.scheduler = Scheduler(self.store, command=self.fake)

    def save(self, entry, create=False):
        return self.scheduler.save("sample", entry["id"], entry, self.store.get("sample")["etag"], create)

    def test_factory_independent_tasks_xml_and_status(self):
        self.assertIsInstance(self.scheduler, WindowsScheduler)
        self.save(schedule("morning"), True)
        self.save(schedule("check", "interval"), True)
        self.assertEqual(len(self.fake.tasks), 2)
        morning = self.scheduler.task_name("sample", "morning")
        root = ET.fromstring(self.fake.tasks[morning])
        self.assertEqual(root.attrib["version"], "1.3")
        self.assertEqual(len(root.findall("{" + NS + "}Triggers/{" + NS + "}CalendarTrigger")), 2)
        self.assertEqual([child.tag.rsplit("}", 1)[-1] for child in root.find("{" + NS + "}Triggers/{" + NS + "}CalendarTrigger")][:2],
                         ["Enabled", "StartBoundary"])
        self.assertEqual(root.findtext("{" + NS + "}Principals/{" + NS + "}Principal/{" + NS + "}LogonType"), "InteractiveToken")
        self.assertEqual(root.findtext("{" + NS + "}Principals/{" + NS + "}Principal/{" + NS + "}RunLevel"), "LeastPrivilege")
        self.assertTrue(self.scheduler.observed("sample", "morning")["file_matches"])
        self.save(schedule("check", "interval", False))
        self.assertEqual(set(self.fake.tasks), {morning})
        self.assertEqual(len(self.scheduler.rows("sample")), 2)

    def test_failed_update_restores_yaml_task_and_state(self):
        self.save(schedule("morning"), True)
        before = self.store.get("sample")
        name = self.scheduler.task_name("sample", "morning")
        old_xml = self.fake.tasks[name]
        old_state = self.scheduler.state("sample", "morning")
        self.fake.fail_create = True
        with self.assertRaisesRegex(ManagerError, "복구 완료"):
            self.save({**schedule("morning"), "times": ["09:00"]})
        self.assertEqual(self.store.get("sample")["yaml"], before["yaml"])
        self.assertEqual(self.fake.tasks[name], old_xml)
        self.assertEqual(self.scheduler.state("sample", "morning"), old_state)

    def test_failed_create_and_delete_restore_yaml_and_other_schedule(self):
        self.save(schedule("morning"), True)
        before = self.store.get("sample")
        morning = self.scheduler.task_name("sample", "morning")
        self.fake.fail_create = True
        with self.assertRaises(ManagerError):
            self.save(schedule("check", "interval"), True)
        self.assertEqual(self.store.get("sample")["yaml"], before["yaml"])
        self.assertEqual(set(self.fake.tasks), {morning})
        self.fake.fail_delete = True
        with self.assertRaises(ManagerError):
            self.scheduler.save("sample", "morning", None, before["etag"])
        self.assertEqual(self.store.get("sample")["yaml"], before["yaml"])
        self.assertEqual(set(self.fake.tasks), {morning})

    def test_external_change_and_missing_task_detected(self):
        self.save(schedule("morning"), True)
        name = self.scheduler.task_name("sample", "morning")
        self.fake.tasks[name] = self.fake.tasks[name].replace("08:00", "09:00")
        self.assertFalse(self.scheduler.observed("sample", "morning")["file_matches"])
        with self.assertRaises(ManagerError) as context:
            self.save(schedule("morning"))
        self.assertEqual(context.exception.status, 409)
        del self.fake.tasks[name]
        state = self.scheduler.observed("sample", "morning")
        self.assertFalse(state["loaded"])
        self.assertTrue(state["applied"])

    def test_interval_below_native_minimum_rejected_before_yaml_save(self):
        before = self.store.get("sample")
        with self.assertRaises(ManagerError):
            self.save({**schedule("fast", "interval"), "interval_seconds": 15}, True)
        self.assertEqual(self.store.get("sample")["yaml"], before["yaml"])

    def test_dashboard_session_detects_windows_scheduler(self):
        handler = Handler.__new__(Handler)
        handler.server = SimpleNamespace(store=self.store, token="test")
        handler.command = "GET"
        result, status = handler.api(["api", "session"], {}, {})
        self.assertEqual(status, 200)
        self.assertEqual((result["os"], result["scheduler"]), ("Windows", "Windows Task Scheduler"))
