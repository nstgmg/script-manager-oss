"""Owner-supplied Windows evidence, replayed against isolated host-side fixtures."""
import base64
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from runner.common import digest, write_json
from runner.installation import DESCRIPTION
from runner.schedule import Scheduler
from runner.schedule_doctor import ScheduleDoctor
from runner.store import Store, default_job
from runner.windows_schedule import task_definition_hash
from tests.test_schedule_doctor_platforms import DoctorTasks
from tests import test_windows_ownership as ownership

FIXTURE = Path(__file__).parent / "fixtures/windows-task-scheduler/handoff.json"
Q = ownership.Q


def evidence():
    pack = json.loads(FIXTURE.read_text(encoding="utf-8"))
    result = {}
    for name, item in pack["files"].items():
        data = base64.b64decode(item["base64"], validate=True)
        if len(data) != item["bytes"] or digest(data) != item["sha256"]:
            raise ValueError("Handoff fixture bytes changed: " + name)
        result[name] = data
    return result


class WindowsHandoffTests(unittest.TestCase):
    row = ownership.WindowsOwnershipTests.row
    assert_unknown_preserved = ownership.WindowsOwnershipTests.assert_unknown_preserved

    def setUp(self):
        self.evidence = evidence()
        self.reported = json.loads(self.evidence["registration-state-extract.json"])
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.store = Store(self.base / "isolated-data")
        self.store.create(default_job("native-probe"))
        patcher = patch("runner.schedule.platform.system", return_value="Windows")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.fake = DoctorTasks()
        self.scheduler = Scheduler(self.store, command=self.fake)
        self.name = self.scheduler.task_name("native-probe", "temporary")
        self.doctor = ScheduleDoctor(self.store, self.scheduler)
        code = str(Path(__file__).resolve().parents[1])
        self.generated = ET.fromstring(self.evidence["generated-task.xml"].decode("utf-8"))
        registered = ET.fromstring(self.evidence["registered-task.xml"].decode("utf-8"))
        owner = json.loads(self.generated.findtext(Q + "RegistrationInfo/" + Q + "Description")[len(DESCRIPTION):])
        owner.update(root=str(self.store.root), code_root=code, executable=sys.executable,
                     required_files=[sys.executable, str(self.store.job_dir("native-probe") / "main.py")])
        args = ["-m", "runner", "--root", str(self.store.root), "_scheduled",
                "native-probe", owner["generation"], "temporary"]
        for tree in (self.generated, registered):
            action = tree.find(Q + "Actions/" + Q + "Exec")
            action.find(Q + "Command").text = sys.executable
            action.find(Q + "Arguments").text = subprocess.list2cmdline(args)
            action.find(Q + "WorkingDirectory").text = code
        owner["definition_sha256"] = task_definition_hash(self.generated)
        for tree in (self.generated, registered):
            tree.find(Q + "RegistrationInfo/" + Q + "Description").text = DESCRIPTION + json.dumps(owner)
        registered.find(Q + "RegistrationInfo/" + Q + "URI").text = self.name
        self.fake.tasks[self.name] = ET.tostring(registered, encoding="unicode")
        self.state = dict(self.reported["registration_state"],
                          task_sha256=digest(self.fake.tasks[self.name].encode("utf-8")))
        self.state_path = self.scheduler.state_path("native-probe", "temporary")
        write_json(self.state_path, self.state)
        write_json(self.store.runtime / "installation.json",
                   {"version": 1, "root": str(self.store.root), "installation_id": owner["installation_id"]})

    def test_exact_anonymized_bytes_and_distinct_reported_hash_domains(self):
        generated = self.evidence["generated-task.xml"]
        registered = self.evidence["registered-task.xml"]
        self.assertEqual((len(generated), len(registered)), (2051, 2381))
        self.assertEqual(registered.count(b"\r\r\r\n"), 41)
        self.assertIn(b'encoding="UTF-16"', registered)
        self.assertEqual(digest(generated), "7998dd7a7ceb00796568fda76f565f242dff2ad007e91a33b8745c2e33fbf668")
        self.assertEqual(digest(registered), "e5af11adb6e3f527be7b4b600331fc297b153c5bbb659be752383339305d36b1")
        state = self.reported["registration_state"]
        doctor = self.reported["doctor_before_cleanup"]["schedules"][0]
        self.assertEqual(state["task_sha256"], doctor["definition_hash"])
        self.assertNotEqual(state["task_sha256"], digest(registered))
        self.assertEqual((doctor["owned"], doctor["status"]), (False, "unknown"))
        before, after = (ET.fromstring(data.decode("utf-8")) for data in (generated, registered))
        self.assertNotEqual(task_definition_hash(before), task_definition_hash(after))
        description = before.findtext(Q + "RegistrationInfo/" + Q + "Description")
        self.assertNotEqual(json.loads(description[len(DESCRIPTION):])["definition_sha256"], task_definition_hash(before))

    def test_captured_normalization_shape_is_preserved(self):
        before = ET.fromstring(self.evidence["generated-task.xml"].decode("utf-8"))
        after = ET.fromstring(self.evidence["registered-task.xml"].decode("utf-8"))
        self.assertNotEqual([p.tag for p in before], [p.tag for p in after])
        self.assertIsNone(before.find(Q + "RegistrationInfo/" + Q + "URI"))
        self.assertIsNotNone(after.find(Q + "RegistrationInfo/" + Q + "URI"))
        self.assertEqual(after.findtext(Q + "Settings/" + Q + "UseUnifiedSchedulingEngine"), "true")
        self.assertEqual(after.findtext(Q + "Settings/" + Q + "IdleSettings/" + Q + "StopOnIdleEnd"), "true")
        self.assertIsNone(after.find(Q + "Principals/" + Q + "Principal/" + Q + "RunLevel"))
        self.assertIsNone(after.find(Q + "Triggers/" + Q + "CalendarTrigger/" + Q + "Enabled"))
        self.assertEqual(after.findtext(Q + "Principals/" + Q + "Principal/" + Q + "UserId"),
                         "S-1-5-21-111111111-222222222-333333333-1001")

    def test_evidence_replay_accepts_recorded_normalized_export_without_registration(self):
        owner = json.loads(self.generated.findtext(Q + "RegistrationInfo/" + Q + "Description")[len(DESCRIPTION):])
        self.assertEqual(owner["definition_sha256"], task_definition_hash(self.generated))
        self.assertNotEqual(owner["definition_sha256"], task_definition_hash(ET.fromstring(self.fake.tasks[self.name])))
        before = self.state_path.read_bytes()
        xml = self.fake.tasks[self.name]
        row = self.row()
        self.assertEqual(row["status"], "healthy", row)
        self.assertEqual(row["definition_evidence"], "recorded-os-export")
        self.assertEqual(self.state_path.read_bytes(), before)
        self.assertEqual(self.fake.tasks[self.name], xml)

    def test_observed_os_fields_and_omitted_defaults_remain_tamper_sensitive(self):
        original = self.fake.tasks[self.name]
        changes = (("Settings/UseUnifiedSchedulingEngine", "false"),
                   ("Settings/IdleSettings/StopOnIdleEnd", "false"),
                   ("Principals/Principal/UserId", "S-1-5-18"),
                   ("Principals/Principal/RunLevel", "HighestAvailable"),
                   ("Settings/Enabled", "false"), ("Triggers/CalendarTrigger/Enabled", "false"),
                   ("Triggers/CalendarTrigger/StartBoundary", "2020-01-06T02:12:00"),
                   ("Actions/Exec/WorkingDirectory", str(self.base / "foreign")))
        for path, value in changes:
            with self.subTest(path=path):
                tree = ET.fromstring(original)
                parts = path.split("/")
                parent = tree.find("/".join(Q + p for p in parts[:-1]))
                node = parent.find(Q + parts[-1])
                if node is None:
                    node = ET.SubElement(parent, Q + parts[-1])
                node.text = value
                self.fake.tasks[self.name] = ET.tostring(tree, encoding="unicode")
                self.assert_unknown_preserved()
        self.fake.tasks[self.name] = original

    def test_saved_file_or_original_report_hash_is_not_a_replay_baseline(self):
        for wrong in (digest(self.evidence["registered-task.xml"]), self.reported["registration_state"]["task_sha256"]):
            with self.subTest(checksum=wrong):
                write_json(self.state_path, dict(self.state, task_sha256=wrong))
                self.assert_unknown_preserved()

    def test_removed_cleanup_state_is_not_used_as_registration_proof(self):
        write_json(self.state_path, self.reported["cleanup_state"])
        self.assert_unknown_preserved()

    def test_old_applied_state_without_phase_still_matches_recorded_export(self):
        state = dict(self.state)
        state.pop("phase")
        write_json(self.state_path, state)
        self.assertEqual(self.row()["status"], "healthy")
