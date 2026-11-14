"""Synthetic registration/export differences; not captured Windows XML evidence."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from runner.common import ManagerError, digest, write_json
from runner.installation import DESCRIPTION
from runner.maintenance import Maintenance
from runner.schedule import Scheduler
from runner.schedule_doctor import ScheduleDoctor
from runner.store import Store, default_job
from runner.windows_schedule import NS, task_definition_hash
from tests.test_schedule_doctor_platforms import DoctorTasks
from tests.test_windows_schedule import schedule

Q = "{" + NS + "}"


class NormalizingTasks(DoctorTasks):
    """Model an OS exporting a different complete XML after registration."""
    def __init__(self):
        super().__init__()
        self.submitted = {}
        self.calls = []

    def __call__(self, args, **kwargs):
        self.calls.append(args)
        result = super().__call__(args, **kwargs)
        if args[:2] == ["schtasks", "/Create"] and result.returncode == 0:
            name = args[args.index("/TN") + 1]
            self.submitted[name] = self.tasks[name]
            tree = ET.fromstring(self.tasks[name])
            ET.SubElement(tree.find(Q + "RegistrationInfo"), Q + "URI").text = name
            tree.find(Q + "Principals/" + Q + "Principal/" + Q + "UserId").text = "S-1-5-21-111-222-333-1001"
            settings = tree.find(Q + "Settings")
            ET.SubElement(settings, Q + "Priority").text = "7"
            settings[:] = reversed(list(settings))
            ET.indent(tree)
            self.tasks[name] = ET.tostring(tree, encoding="unicode")
        return result


class WindowsOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.store = Store(self.base / "original")
        self.store.create(default_job("sample"))
        patcher = patch("runner.schedule.platform.system", return_value="Windows")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.fake = NormalizingTasks()
        self.scheduler = Scheduler(self.store, command=self.fake)
        self.scheduler.save("sample", "daily", schedule("daily"), self.store.get("sample")["etag"], True)
        self.name = self.scheduler.task_name("sample", "daily")
        self.doctor = ScheduleDoctor(self.store, self.scheduler)

    def row(self, doctor=None):
        scan = (doctor or self.doctor).scan()
        self.assertFalse(scan["errors"], scan)
        return next(row for row in scan["schedules"] if row["id"] == self.name)

    def mutate_owner(self, tree, mutate):
        description = tree.find(Q + "RegistrationInfo/" + Q + "Description")
        owner = json.loads(description.text[len(DESCRIPTION):])
        mutate(owner)
        description.text = DESCRIPTION + json.dumps(owner)

    def assert_unknown_preserved(self):
        before = self.fake.tasks[self.name]
        row = self.row()
        self.assertEqual(row["status"], "unknown", row)
        self.assertFalse(row["owned"], row)
        with self.assertRaises(ManagerError):
            self.doctor.remove(self.name, row["fingerprint"])
        self.assertEqual(self.fake.tasks[self.name], before)

    def test_normalized_export_uses_existing_complete_baseline_without_writes(self):
        exported = self.fake.tasks[self.name]
        tree = ET.fromstring(exported)
        owner = json.loads(tree.findtext(Q + "RegistrationInfo/" + Q + "Description")[len(DESCRIPTION):])
        self.assertNotEqual(owner["definition_sha256"], task_definition_hash(tree))
        self.assertNotEqual(self.fake.submitted[self.name], exported)
        state_path = self.scheduler.state_path("sample", "daily")
        state_before = state_path.read_bytes()
        yaml_before = self.store.get("sample")["yaml"]
        calls = len(self.fake.calls)
        for _ in range(2):
            row = self.row()
            self.assertEqual(row["status"], "healthy", row)
            self.assertEqual(row["definition_evidence"], "recorded-os-export")
        self.assertTrue(self.scheduler.observed("sample", "daily")["file_matches"])
        self.assertEqual(self.scheduler.state("sample", "daily")["task_sha256"], digest(exported.encode()))
        self.assertEqual(state_path.read_bytes(), state_before)
        self.assertEqual(self.store.get("sample")["yaml"], yaml_before)
        self.assertFalse(any(call[1] in ("/Create", "/Delete") for call in self.fake.calls[calls:]))

    def test_normalized_export_can_be_updated_and_removed_via_original_scheduler(self):
        self.scheduler.save("sample", "daily", {**schedule("daily"), "times": ["10:00"]},
                            self.store.get("sample")["etag"])
        self.assertEqual(self.row()["status"], "healthy")
        self.scheduler.remove("sample", "daily")
        self.assertNotIn(self.name, self.fake.tasks)

    def test_other_installation_uses_original_state_not_observers_state(self):
        other = Store(self.base / "observer")
        doctor = ScheduleDoctor(other, Scheduler(other, command=self.fake))
        row = self.row(doctor)
        self.assertEqual(row["status"], "healthy", row)
        with self.assertRaises(ManagerError):
            doctor.remove(self.name, row["fingerprint"])

    def test_every_critical_xml_change_is_rejected_even_with_metadata_unchanged(self):
        original = self.fake.tasks[self.name]
        changes = {
            "command": ("Actions/Exec/Command", "C:\\foreign\\python.exe"),
            "arguments": ("Actions/Exec/Arguments", "-m foreign"),
            "working_directory": ("Actions/Exec/WorkingDirectory", "C:\\foreign"),
            "trigger_time": ("Triggers/CalendarTrigger/StartBoundary", "2020-01-06T09:00:00"),
            "trigger_enabled": ("Triggers/CalendarTrigger/Enabled", "false"),
            "week_interval": ("Triggers/CalendarTrigger/ScheduleByWeek/WeeksInterval", "2"),
            "principal": ("Principals/Principal/UserId", "S-1-5-18"),
            "logon_type": ("Principals/Principal/LogonType", "ServiceAccount"),
            "run_level": ("Principals/Principal/RunLevel", "HighestAvailable"),
            "settings": ("Settings/ExecutionTimeLimit", "PT1H"),
            "os_added_field": ("Settings/Priority", "8"),
            "task_enabled": ("Settings/Enabled", "false"),
        }
        for label, (path, value) in changes.items():
            with self.subTest(label=label):
                tree = ET.fromstring(original)
                tree.find("/".join(Q + p for p in path.split("/"))).text = value
                self.fake.tasks[self.name] = ET.tostring(tree, encoding="unicode")
                self.assert_unknown_preserved()
                self.assertFalse(self.scheduler.observed("sample", "daily")["file_matches"])
                with self.assertRaises(ManagerError):
                    self.scheduler.remove("sample", "daily")
        self.fake.tasks[self.name] = original

    def test_extra_actions_triggers_principals_and_unknown_fields_are_protected(self):
        original = self.fake.tasks[self.name]
        for parent, tag in (("Actions", "Exec"), ("Actions", "ComHandler"),
                            ("Triggers", "BootTrigger"), ("Principals", "Principal"),
                            ("Settings", "FutureExecutionOption")):
            with self.subTest(parent=parent, tag=tag):
                tree = ET.fromstring(original)
                ET.SubElement(tree.find(Q + parent), Q + tag)
                self.fake.tasks[self.name] = ET.tostring(tree, encoding="unicode")
                self.assert_unknown_preserved()
        self.fake.tasks[self.name] = original

    def test_action_context_principal_id_and_task_attributes_are_protected(self):
        original = self.fake.tasks[self.name]
        for path, key, value in (("Actions", "Context", "Foreign"),
                                 ("Principals/Principal", "id", "Foreign"),
                                 ("", "version", "1.4")):
            with self.subTest(path=path, key=key):
                tree = ET.fromstring(original)
                target = tree.find("/".join(Q + p for p in path.split("/"))) if path else tree
                target.set(key, value)
                self.fake.tasks[self.name] = ET.tostring(tree, encoding="unicode")
                self.assert_unknown_preserved()
        self.fake.tasks[self.name] = original

    def test_corrupt_owner_checksum_cannot_downgrade_to_legacy_even_with_matching_state(self):
        original = self.fake.tasks[self.name]
        state = self.scheduler.state("sample", "daily")
        for value in (None, "", 1, [], {}, "not-a-hash"):
            with self.subTest(value=value):
                tree = ET.fromstring(original)
                self.mutate_owner(tree, lambda owner: owner.update(definition_sha256=value))
                self.fake.tasks[self.name] = ET.tostring(tree, encoding="unicode")
                write_json(self.scheduler.state_path("sample", "daily"),
                           dict(state, task_sha256=digest(self.fake.tasks[self.name].encode())))
                self.assert_unknown_preserved()

    def test_corrupt_description_types_are_not_legacy(self):
        original = self.fake.tasks[self.name]
        state = self.scheduler.state("sample", "daily")
        for text in (DESCRIPTION + "null", DESCRIPTION + "[]", DESCRIPTION + "1", DESCRIPTION + "{", "Script Manager v2 broken"):
            with self.subTest(text=text):
                tree = ET.fromstring(original)
                tree.find(Q + "RegistrationInfo/" + Q + "Description").text = text
                self.fake.tasks[self.name] = ET.tostring(tree, encoding="unicode")
                write_json(self.scheduler.state_path("sample", "daily"),
                           dict(state, task_sha256=digest(self.fake.tasks[self.name].encode())))
                self.assert_unknown_preserved()

    def test_invalid_owner_fields_are_unknown_even_with_matching_export_baseline(self):
        original = self.fake.tasks[self.name]
        state = self.scheduler.state("sample", "daily")
        for fields in ({"version": True}, {"version": 2}, {"owner": "foreign"},
                       {"required_files": "not-a-list"}, {"required_files": ["relative.py"]},
                       {"required_files": [1]}, {"installation_id": "bad"},
                       {"code_root": str(self.base / "other-code")}, {"generation": "bad"}):
            with self.subTest(fields=fields):
                tree = ET.fromstring(original)
                self.mutate_owner(tree, lambda owner: owner.update(fields))
                self.fake.tasks[self.name] = ET.tostring(tree, encoding="unicode")
                write_json(self.scheduler.state_path("sample", "daily"),
                           dict(state, task_sha256=digest(self.fake.tasks[self.name].encode())))
                self.assert_unknown_preserved()

    def test_missing_corrupt_or_retired_post_registration_evidence_is_unknown(self):
        path = self.scheduler.state_path("sample", "daily")
        state = self.scheduler.state("sample", "daily")
        variants = [None, [], {}, dict(state, task_sha256="0" * 64),
                    dict(state, generation="0" * 32), dict(state, applied=False),
                    dict(state, phase="applying"), dict(state, phase="degraded")]
        for value in variants:
            with self.subTest(state=value):
                if value is None:
                    path.unlink(missing_ok=True)
                else:
                    write_json(path, value)
                self.assert_unknown_preserved()
        path.write_text("{")
        self.assert_unknown_preserved()

    def test_original_installation_identity_required_and_not_recreated(self):
        path = self.store.runtime / "installation.json"
        original = json.loads(path.read_text())
        for value in (None, [], {}, dict(original, installation_id="0" * 32),
                      dict(original, root=str(self.base / "copied")), dict(original, version=2)):
            with self.subTest(identity=value):
                if value is None:
                    path.unlink(missing_ok=True)
                else:
                    write_json(path, value)
                self.assert_unknown_preserved()
                self.assertEqual(path.exists(), value is not None)

    def test_normalized_orphan_without_original_export_is_unknown_and_not_removed(self):
        self.scheduler.state_path("sample", "daily").unlink()
        self.assert_unknown_preserved()

    def test_old_metadata_without_embedded_checksum_still_uses_original_export(self):
        tree = ET.fromstring(self.fake.tasks[self.name])
        self.mutate_owner(tree, lambda owner: owner.pop("definition_sha256"))
        self.fake.tasks[self.name] = ET.tostring(tree, encoding="unicode")
        state = self.scheduler.state("sample", "daily")
        write_json(self.scheduler.state_path("sample", "daily"),
                   dict(state, task_sha256=digest(self.fake.tasks[self.name].encode())))
        self.assertEqual(self.row()["status"], "healthy")
        self.scheduler.state_path("sample", "daily").unlink()
        self.assert_unknown_preserved()

    def test_normalized_legacy_without_owner_needs_exact_checksum(self):
        tree = ET.fromstring(self.fake.tasks[self.name])
        state = self.scheduler.state("sample", "daily")
        tree.find(Q + "RegistrationInfo/" + Q + "Description").text = "Script Manager " + state["generation"]
        self.fake.tasks[self.name] = ET.tostring(tree, encoding="unicode")
        write_json(self.scheduler.state_path("sample", "daily"),
                   dict(state, task_sha256=digest(self.fake.tasks[self.name].encode())))
        row = self.row()
        self.assertTrue(row["legacy"])
        self.assertEqual(row["status"], "healthy")
        self.fake.tasks[self.name] = self.fake.tasks[self.name].replace("<Priority>7", "<Priority>8")
        self.assert_unknown_preserved()

    def test_query_denial_is_not_path_missing_and_blocks_reset_before_any_mutation(self):
        original = self.fake.__call__

        def denied(args, **kwargs):
            if args[:2] == ["schtasks", "/Query"]:
                return subprocess.CompletedProcess(args, 1, b"", b"Access is denied")
            return original(args, **kwargs)

        before = self.fake.tasks.copy()
        with patch.object(self.scheduler, "command", side_effect=denied):
            scan = self.doctor.scan()
            self.assertTrue(scan["errors"])
            self.assertIn("sandbox", scan["errors"][0])
            self.assertIn("원본 경로/파일 누락으로 판단하지", scan["errors"][0])
            self.assertFalse(scan["schedules"])
            for action in (lambda: self.scheduler.known_ids("sample"),
                           lambda: self.scheduler.observed("sample", "daily")):
                with self.assertRaisesRegex(ManagerError, "sandbox"):
                    action()
            manager = Maintenance(self.store, self.doctor)
            plan = manager.preview()
            self.assertTrue(plan["blockers"])
            with self.assertRaises(ManagerError):
                manager.execute("reset", plan["plan_hash"])
        self.assertEqual(self.fake.tasks, before)
        self.assertTrue(self.store.job_dir("sample").exists())

    def test_missing_query_tool_or_invalid_running_state_preserves_schedule(self):
        for exc in (FileNotFoundError("schtasks executable unavailable"),
                    PermissionError("sandbox blocked"), subprocess.TimeoutExpired("schtasks", 20)):
            with self.subTest(error=exc), patch.object(self.scheduler, "command", side_effect=exc):
                scan = self.doctor.scan()
                self.assertIn("sandbox", scan["errors"][0])
                self.assertIn("조회 실패", scan["errors"][0])
        original = self.fake.__call__

        def invalid(args, **kwargs):
            return subprocess.CompletedProcess(args, 0, "", "") if args[0] == "powershell.exe" else original(args, **kwargs)

        with patch.object(self.scheduler, "command", side_effect=invalid):
            row = self.row()
            self.assertEqual(row["status"], "unknown")
            self.assertIn("sandbox", row["reason"])
            self.assertEqual(row.get("missing", []), [])
        self.assertIn(self.name, self.fake.tasks)

    def test_individual_xml_or_running_query_denial_is_unknown_not_missing_path(self):
        original = self.fake.__call__
        for target in ("xml", "running"):
            def denied(args, **kwargs):
                if (target == "xml" and "/XML" in args) or (target == "running" and args[0] == "powershell.exe"):
                    return subprocess.CompletedProcess(args, 1, "", "Access is denied")
                return original(args, **kwargs)

            with self.subTest(target=target), patch.object(self.scheduler, "command", side_effect=denied):
                row = self.row()
                self.assertEqual(row["status"], "unknown", row)
                self.assertIn("sandbox", row["reason"])
                self.assertEqual(row.get("missing", []), [])
                self.assert_unknown_preserved()
