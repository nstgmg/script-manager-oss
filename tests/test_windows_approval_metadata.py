"""Native approval regressions; existing security tests/mocks stay unchanged."""
import copy
import ctypes
import json
import os
from pathlib import Path
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from runner.common import ManagerError
from runner.installation import installation
from runner.maintenance import Maintenance
from runner.schedule_doctor import fingerprint
from runner.store import Store


@unittest.skipUnless(os.name == "nt", "Windows handle metadata")
class WindowsApprovalMetadataTests(unittest.TestCase):
    def setUp(self):
        from runner import windows_fs
        self.fs = windows_fs
        self.assertFalse(ctypes.windll.shell32.IsUserAnAdmin())
        temp = tempfile.TemporaryDirectory(prefix="sm-approval-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.store = Store(self.root / "data")
        self.folder = self.store.root / "workspace"
        self.folder.mkdir()
        self.path = self.folder / "victim.bin"
        self.path.write_bytes(b"approved original")
        self.manager = Maintenance(self.store, doctor=object())

    def read_stat(self):
        with self.fs.directory(self.folder) as directory:
            with directory.child(self.path.name, metadata=True) as entry:
                return entry.stat()

    def inventory(self):
        records = self.manager._inventory(self.folder)
        anchors = {str(path.relative_to(self.store.root)): self.fs.anchor_record(self.store.root, path)
                   for path in (self.store.root, self.folder)}
        return records, anchors

    def set_times(self, created=0, changed=0):
        handle = self.fs.kernel.CreateFileW(str(self.path), 0x100, 7, None, 3, 0x02200000, None)
        self.assertNotEqual(handle, ctypes.c_void_p(-1).value)
        try:
            info = self.fs.BasicInfo(created, 0, 0, changed, 0)
            self.fs._check(self.fs.kernel.SetFileInformationByHandle(handle, 0,
                            ctypes.byref(info), ctypes.sizeof(info)))
        finally:
            self.fs.kernel.CloseHandle(handle)

    def test_distinct_creation_change_times_use_the_same_handle_representation(self):
        self.set_times(created=129067776000000000)  # New synthetic file only: 2010-01-01 UTC.
        records, anchors = self.inventory()
        approved = next(record for record in records if record[0].endswith("victim.bin"))
        current = self.read_stat()
        self.assertNotEqual(current.creation_time, current.change_time)
        self.assertEqual(approved, self.fs.approval_record(current, approved[0]))
        with self.fs.directory(self.folder) as directory, directory.child(self.path.name, metadata=True) as entry:
            raw = os.fstat(entry.fd)
            print(json.dumps({"diagnostic_only": True, "lstat_ctime_ns": self.path.lstat().st_ctime_ns,
                "fstat_ctime_ns": raw.st_ctime_ns, "native_CreationTime": current.creation_time,
                "native_ChangeTime": current.change_time}))
        self.manager._delete_tree(self.folder, records, anchors, [])
        self.assertFalse(self.folder.exists())

    def test_real_change_time_mismatch_is_logged_and_preserved(self):
        records, anchors = self.inventory()
        original = self.read_stat()
        self.set_times(changed=original.change_time + 10000000)
        changed = self.read_stat()
        self.assertNotEqual(changed.change_time, original.change_time)
        self.assertEqual(changed.creation_time, original.creation_time)
        self.assertEqual(changed.st_size, original.st_size)
        self.assertEqual(changed.last_write_time, original.last_write_time)
        with self.assertLogs("runner.windows_fs", level="WARNING") as logs:
            with self.assertRaises(ManagerError) as error:
                self.manager._delete_tree(self.folder, records, anchors, [])
        difference = error.exception.approval_diagnostics["differences"]["ChangeTime"]
        self.assertEqual(difference, {"approved": original.change_time, "current": changed.change_time})
        self.assertIn("ChangeTime", "\n".join(logs.output))
        self.assertEqual(self.path.read_bytes(), b"approved original")

    def test_creation_time_mismatch_is_rejected(self):
        records, anchors = self.inventory()
        original = self.read_stat()
        self.set_times(created=original.creation_time - 10000000)
        with self.assertRaises(ManagerError) as error:
            self.manager._delete_tree(self.folder, records, anchors, [])
        self.assertIn("CreationTime", error.exception.approval_diagnostics["differences"])
        self.assertEqual(self.path.read_bytes(), b"approved original")

    def test_all_approved_fields_are_retained_with_exact_one_tick_time_comparison(self):
        records, unused = self.inventory()
        record = next(record for record in records if record[0].endswith("victim.bin"))
        current = self.read_stat()
        changes = (("st_ino", "FileId"), ("st_dev", "Volume"), ("st_mode", "Mode"),
                   ("st_size", "Size"), ("last_write_time", "LastWriteTime"),
                   ("creation_time", "CreationTime"), ("change_time", "ChangeTime"),
                   ("st_file_attributes", "Attributes"), ("entry_type", "Type"))
        for attribute, label in changes:
            with self.subTest(field=label):
                changed = copy.copy(current)
                value = getattr(changed, attribute)
                setattr(changed, attribute, "directory" if attribute == "entry_type" else value + 1)
                with self.assertRaises(ManagerError) as error:
                    self.fs._require_matches(changed, record, False, "Approved entry changed")
                self.assertIn(label, error.exception.approval_diagnostics["differences"])

    def test_every_extended_query_failure_is_closed_without_disposition_or_path_fallback(self):
        records, anchors = self.inventory()
        original = self.fs.kernel.GetFileInformationByHandleEx
        for denied_class in (0, 1, 18):
            def query(handle, info_class, value, size):
                if info_class == denied_class:
                    ctypes.set_last_error(50)
                    return 0
                return original(handle, info_class, value, size)
            with self.subTest(info_class=denied_class), \
                    patch.object(self.fs.kernel, "GetFileInformationByHandleEx", side_effect=query), \
                    patch.object(self.fs.kernel, "SetFileInformationByHandle") as disposition, \
                    patch.object(Path, "unlink") as unsafe:
                with self.assertRaises(OSError) as error:
                    self.manager._delete_tree(self.folder, records, anchors, [])
                self.assertEqual(error.exception.winerror, 50)
                disposition.assert_not_called()
                unsafe.assert_not_called()
            self.assertEqual(self.path.read_bytes(), b"approved original")

    def test_legacy_or_unknown_schema_rejected_before_any_deletion(self):
        records, anchors = self.inventory()
        for schema in (None, 1, 3, "2"):
            legacy = copy.deepcopy(records)
            for record in legacy:
                if schema is None:
                    record.pop()
                else:
                    record[7]["schema"] = schema
            with self.subTest(schema=schema), \
                    patch.object(self.fs, "delete_entry") as delete:
                with self.assertRaises(ManagerError) as error:
                    self.manager._delete_tree(self.folder, legacy, anchors, [])
                self.assertEqual(error.exception.status, 409)
                self.assertIn("schema", error.exception.approval_diagnostics["differences"])
                delete.assert_not_called()
        self.assertEqual(self.path.read_bytes(), b"approved original")

    def test_mixed_legacy_directory_approval_is_rejected_before_valid_file_delete(self):
        records, anchors = self.inventory()
        for record in records:
            if stat.S_ISDIR(record[2]):
                record.pop()
        progress = []
        with self.assertRaises(ManagerError):
            self.manager._delete_tree(self.folder, records, anchors, progress)
        self.assertEqual(progress, [])
        self.assertEqual(self.path.read_bytes(), b"approved original")

    def test_directory_child_removal_does_not_compare_mutable_directory_times(self):
        (self.folder / "second.bin").write_bytes(b"second")
        records, anchors = self.inventory()
        self.manager._delete_tree(self.folder, records, anchors, [])
        self.assertFalse(self.folder.exists())

    def test_inventory_uses_metadata_access_and_never_reads_file_content(self):
        with patch.object(self.fs.Entry, "read", side_effect=AssertionError("must not read content")):
            records, anchors = self.inventory()
        self.assertEqual(len(records), 2)
        self.manager._delete_tree(self.folder, records, anchors, [])
        self.assertFalse(self.folder.exists())

    def test_held_atomic_reader_is_allowed_but_pending_file_cannot_authorize_delete(self):
        from runner.common import write_json
        write_json(self.path, {"version": 1})
        with self.fs.directory(self.folder) as parent, parent.child(self.path.name) as held:
            write_json(self.path, {"version": 2})
            self.assertEqual(json.loads(held.read(1024)), {"version": 1})
            self.assertTrue(held.stat().delete_pending)
            with self.assertRaises(ManagerError) as error:
                self.fs.approval_record(held.stat(), "workspace/victim.bin")
            self.assertIn("DeletePending", error.exception.approval_diagnostics["differences"])

    def test_empty_preview_invalidates_a_legacy_hash_and_requires_confirmation(self):
        store = Store(self.root / "empty")
        # A fresh Store creates four empty managed target directories. Remove
        # only these new fixture directories to exercise the zero-target hash.
        for name in ("runs", "trash", "schedules", "deployments"):
            target = store.runtime / name
            self.assertTrue(self.root in target.parents)
            target.rmdir()
        doctor = SimpleNamespace(scan=lambda: {"schedules": [], "errors": [], "supported": True},
                                 scheduler=SimpleNamespace(namespace="synthetic"), remove=lambda *a, **k: None)
        manager = Maintenance(store, doctor)
        plan = manager.preview()
        self.assertEqual(plan["delete"], [])
        self.assertEqual(plan["blockers"], [])
        self.assertEqual(plan["windows_approval_schema"], 2)
        legacy_hash = fingerprint({"mode": "reset", "identity": installation(store), "inventory": [],
            "root_identity": [store.root.stat().st_dev, store.root.stat().st_ino], "schedules": [], "blockers": []})
        self.assertNotEqual(plan["plan_hash"], legacy_hash)
        with patch.object(doctor, "remove") as remove:
            with self.assertRaises(ManagerError) as error:
                manager.execute("reset", legacy_hash)
            self.assertEqual(error.exception.status, 409)
            remove.assert_not_called()


if __name__ == "__main__":
    unittest.main()
