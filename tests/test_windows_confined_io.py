"""Non-elevated NTFS checks for confined reads, snapshots and deletion."""
import ctypes
from contextlib import ExitStack
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from runner.common import ManagerError, write_json
from runner.execution import snapshot, source_files
from runner.maintenance import Maintenance
from runner.results import Results
from runner.store import Store


@unittest.skipUnless(os.name == "nt", "Native Windows NTFS I/O")
class WindowsConfinedIOTests(unittest.TestCase):
    def setUp(self):
        self.assertFalse(ctypes.windll.shell32.IsUserAnAdmin())
        self.temp = tempfile.TemporaryDirectory(prefix="sm-bound-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def junction(self, path, target):
        result = subprocess.run(["cmd.exe", "/d", "/c", "mklink", "/J", str(path), str(target)],
                                capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(path.lstat().st_file_attributes & 0x400)
        self.addCleanup(lambda: path.rmdir() if os.path.lexists(path) else None)

    def test_01_bound_reader_and_atomic_publication(self):
        from runner.windows_fs import directory, read_beneath
        path = self.root / "run.json"
        write_json(path, {"version": 1})
        with directory(self.root) as parent, parent.child(path.name) as held:
            write_json(path, {"version": 2})
            self.assertEqual(json.loads(held.read(1024)), {"version": 1})
            self.assertEqual(json.loads(read_beneath(self.root, path.name, 1024)), {"version": 2})

    def test_02_snapshot_regular_exclusions_and_manifest(self):
        source = self.root / "source"
        (source / "nested").mkdir(parents=True)
        (source / "main.py").write_bytes(b"print('synthetic')\n")
        (source / "nested/data.txt").write_bytes(b"saved\x00bytes")
        (source / ".env.test").write_bytes(b"SYNTHETIC=")
        destination = self.root / "snapshot"
        before = source_files(source)
        self.assertEqual(snapshot(source, destination), before)
        self.assertEqual(source_files(destination), before)
        self.assertEqual(set(before), {"main.py", str(Path("nested/data.txt"))})
        self.assertEqual((destination / "nested/data.txt").read_bytes(), b"saved\x00bytes")
        self.assertFalse((destination / ".env.test").exists())

    def test_03_snapshot_rejects_junction_root_and_child(self):
        source = self.root / "source"
        outside = self.root / "outside"
        source.mkdir()
        outside.mkdir()
        sentinel = outside / "sentinel.bin"
        sentinel.write_bytes(b"OUTSIDE-SENTINEL")
        self.junction(source / "redirected", outside)
        self.junction(self.root / "root-link", outside)
        for folder in (source, self.root / "root-link"):
            with self.assertRaises((ManagerError, OSError)):
                snapshot(folder, self.root / "snapshot")
        self.assertFalse((self.root / "snapshot").exists())
        self.assertEqual(sentinel.read_bytes(), b"OUTSIDE-SENTINEL")

    def test_04_snapshot_parent_rename_is_denied_while_pinned(self):
        from runner import windows_fs
        source = self.root / "source"
        source.mkdir()
        original = source / "data.bin"
        original.write_bytes(b"original")
        real_read = windows_fs.Entry.read
        attempted = []

        def race(entry, limit):
            if entry.path == original:
                attempted.append(True)
                with self.assertRaises(OSError):
                    source.rename(self.root / "moved")
            return real_read(entry, limit)

        with patch.object(windows_fs.Entry, "read", race):
            snapshot(source, self.root / "snapshot")
        self.assertTrue(attempted)
        self.assertEqual(original.read_bytes(), b"original")

    def test_05_results_parent_junction_swap_is_not_read(self):
        store = Store(self.root / "data")
        run = "a" * 32
        path = store.runtime / "runs/sample" / run / "run.json"
        row = {"id": run, "job_id": "sample", "value": "original"}
        write_json(path, row)
        outside = self.root / "outside"
        outside.mkdir()
        write_json(outside / "run.json", dict(row, value="OUTSIDE-SENTINEL"))
        saved = self.root / "saved"
        real_lstat, swapped = Path.lstat, []

        def race(item, *args, **kwargs):
            info = real_lstat(item, *args, **kwargs)
            if item == path and not swapped:
                path.parent.rename(saved)
                self.junction(path.parent, outside)
                swapped.append(True)
            return info

        with patch.object(Path, "lstat", race):
            rows, warnings = Results(store).runs("sample")
        self.assertTrue(swapped)
        self.assertEqual(rows, [])
        self.assertTrue(warnings)
        self.assertEqual(json.loads((saved / "run.json").read_bytes()), row)

    def inventory(self):
        store = Store(self.root / "data")
        victim = store.root / "workspace"
        victim.mkdir()
        (victim / "victim.bin").write_bytes(b"approved original")
        manager = Maintenance(store, doctor=object())
        records = manager._inventory(victim)
        anchors = {}
        for directory in (store.root, victim):
            info = directory.lstat()
            rel = str(directory.relative_to(store.root))
            anchors[rel] = [rel, info.st_ino, info.st_mode, info.st_size,
                            info.st_mtime_ns, info.st_dev, info.st_ctime_ns]
        return manager, victim, records, anchors

    def test_06_delete_approved_entries_by_handle(self):
        manager, victim, records, anchors = self.inventory()
        progress = []
        manager._delete_tree(victim, records, anchors, progress)
        self.assertFalse(victim.exists())
        self.assertEqual(len(progress), 2)

    def test_07_delete_parent_junction_swap_preserves_both_originals(self):
        from runner import windows_fs
        manager, victim, records, anchors = self.inventory()
        outside = self.root / "outside"
        outside.mkdir()
        sentinel = outside / "victim.bin"
        sentinel.write_bytes(b"outside deletion sentinel")
        saved = self.root / "saved"
        original_delete, swapped = windows_fs.delete_entry, []

        def race(*args):
            if not swapped:
                victim.rename(saved)
                self.junction(victim, outside)
                swapped.append(True)
            return original_delete(*args)

        progress = []
        with patch.object(windows_fs, "delete_entry", race):
            with self.assertRaises((ManagerError, OSError)):
                manager._delete_tree(victim, records, anchors, progress)
        self.assertTrue(swapped)
        self.assertEqual(progress, [])
        self.assertEqual(sentinel.read_bytes(), b"outside deletion sentinel")
        self.assertEqual((saved / "victim.bin").read_bytes(), b"approved original")

    def test_08_delete_commit_pins_parent_and_file(self):
        from runner import windows_fs
        manager, victim, records, anchors = self.inventory()
        original_stat, attempted = windows_fs.Entry.stat, []

        def race(entry):
            result = original_stat(entry)
            if entry.path == victim / "victim.bin":
                attempted.append(True)
                with self.assertRaises(OSError):
                    victim.rename(self.root / "moved")
                with self.assertRaises(OSError):
                    entry.path.write_bytes(b"unapproved overwrite")
            return result

        with patch.object(windows_fs.Entry, "stat", race):
            manager._delete_tree(victim, records, anchors, [])
        self.assertTrue(attempted)
        self.assertFalse(victim.exists())

    def test_09_read_limit_and_unsafe_paths_fail_closed(self):
        from runner.windows_fs import read_beneath
        (self.root / "large.json").write_bytes(b"x" * 1025)
        with self.assertRaises(ValueError):
            read_beneath(self.root, "large.json", 1024)
        for relative in ("../large.json", "large.json:stream", "large.json."):
            with self.assertRaises(ManagerError):
                read_beneath(self.root, relative, 2048)

    def test_10_unsupported_disposition_has_no_pathname_fallback(self):
        from runner import windows_fs
        manager, victim, records, anchors = self.inventory()
        with patch.object(windows_fs.kernel, "SetFileInformationByHandle", return_value=0), \
                patch.object(ctypes, "get_last_error", return_value=50), \
                patch.object(Path, "unlink") as unsafe:
            with self.assertRaises(OSError):
                manager._delete_tree(victim, records, anchors, [])
            unsafe.assert_not_called()
        self.assertEqual((victim / "victim.bin").read_bytes(), b"approved original")


if __name__ == "__main__":
    unittest.main()
