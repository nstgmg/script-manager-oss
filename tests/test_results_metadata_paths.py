"""Stable-directory containment versus atomically replaced Run metadata.

Portable fault injection is not evidence of native NTFS/reparse behavior.
All real files, links and junctions below belong to this temporary fixture.
"""
import errno
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from runner.common import ManagerError, contained, open_atomic_read, write_json
from runner.results import Results
from runner.store import Store
from tests.platform_helpers import symlink_or_skip


class ResultsMetadataPathTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="sm results 한글 ")
        self.addCleanup(self.temp.cleanup)
        self.store = Store(self.temp.name)
        self.results = Results(self.store)
        self.run = "a" * 32
        self.path = self.store.runtime / "runs/sample" / self.run / "run.json"
        self.record = {"id": self.run, "job_id": "sample", "state": "running",
                       "parameters": {"count": 3}, "parameter_contract_version": 1}
        write_json(self.path, self.record)

    def assert_unreadable(self):
        rows, warnings = self.results.runs("sample")
        self.assertEqual(rows, [])
        self.assertEqual(len(warnings), 1, warnings)
        self.assertEqual(warnings[0]["code"], "unreadable_run")
        self.assertEqual(warnings[0]["path"], str(self.path.parent.relative_to(self.store.root)))
        return warnings[0]

    def test_replaced_leaf_final_name_is_not_a_containment_input(self):
        resolve = Path.resolve
        # Reproduce the old failure deterministically on every host. Neither
        # NTFS's deleted name nor an arbitrary outside name is an allowlist.
        for final_name in (self.store.root / "$Extend/$Deleted/old-run.json",
                           self.store.root / "outside/run.json"):
            with self.subTest(final_name=final_name):
                def final_path(path, *args, **kwargs):
                    return final_name if path == self.path else resolve(path, *args, **kwargs)

                with patch.object(Path, "resolve", final_path):
                    with self.assertRaisesRegex(ManagerError, "허용된 디렉터리 밖"):
                        contained(self.path.parent, "run.json", True)
                    self.assertEqual(self.results.runs("sample"), ([self.record], []))

    def test_atomic_replacement_between_lstat_and_read_returns_new_snapshot(self):
        after = {**self.record, "state": "succeeded", "exit_code": 0}
        lstat = Path.lstat
        replaced = []

        def replace_after_stat(path, *args, **kwargs):
            info = lstat(path, *args, **kwargs)
            if path == self.path and not replaced:
                replaced.append(True)
                write_json(path, after)
            return info

        with open_atomic_read(self.path) as held:
            with patch.object(Path, "lstat", replace_after_stat):
                self.assertEqual(self.results.runs("sample"), ([after], []))
            self.assertEqual(json.load(held), self.record)
        self.assertEqual(replaced, [True])

    def test_concurrent_results_readers_during_repeated_metadata_replacement(self):
        barrier = threading.Barrier(4, timeout=10)
        errors = []
        payload = "한글" * 1000
        write_json(self.path, {**self.record, "version": 0, "payload": payload})

        def observe():
            try:
                for version in range(1, 41):
                    barrier.wait()
                    rows, warnings = self.results.runs("sample")
                    self.assertEqual(warnings, [])
                    self.assertEqual(len(rows), 1)
                    self.assertIn(rows[0]["version"], (version - 1, version))
                    self.assertEqual(rows[0]["payload"], payload)
                    self.assertEqual(rows[0]["parameters"], {"count": 3})
                    self.assertEqual(rows[0]["parameter_contract_version"], 1)
                    barrier.wait()
            except BaseException as exc:
                errors.append(exc)
                barrier.abort()

        readers = [threading.Thread(target=observe) for _ in range(3)]
        for reader in readers:
            reader.start()
        try:
            for version in range(1, 41):
                barrier.wait()
                write_json(self.path, {**self.record, "version": version, "payload": payload})
                barrier.wait()
        finally:
            if errors:
                barrier.abort()
            for reader in readers:
                reader.join(timeout=10)
                self.assertFalse(reader.is_alive())
        self.assertEqual(errors, [])

    def test_stable_directory_resolving_outside_is_still_rejected(self):
        resolve = Path.resolve
        for final_name in (self.store.root / "outside", self.store.root / "$Extend/$Deleted/dir",
                           self.store.runtime / "runs/other-job" / self.run):
            with self.subTest(final_name=final_name):
                def outside(path, *args, **kwargs):
                    return final_name if path == self.path.parent else resolve(path, *args, **kwargs)

                with patch.object(Path, "resolve", outside), patch("runner.results.read_json") as read:
                    warning = self.assert_unreadable()
                    self.assertIn("허용된 디렉터리 밖", warning["message"])
                    read.assert_not_called()

    def test_reparse_attributes_on_leaf_or_any_run_directory_block_reads(self):
        lstat = Path.lstat
        for target in (self.path, self.path.parent, self.path.parent.parent, self.path.parent.parent.parent):
            with self.subTest(target=target):
                def reparse(path, *args, **kwargs):
                    info = lstat(path, *args, **kwargs)
                    if path == target:
                        return SimpleNamespace(st_mode=info.st_mode, st_size=info.st_size,
                                               st_file_attributes=0x400)
                    return info

                with patch.object(Path, "lstat", reparse), patch("runner.results.read_json") as read:
                    self.assert_unreadable()
                    read.assert_not_called()

    def test_leaf_symlinks_inside_outside_and_broken_are_not_read(self):
        self.path.unlink()
        inside = self.path.parent / "other.json"
        outside = self.store.root / "outside.json"
        write_json(inside, self.record)
        write_json(outside, self.record)
        for target in (inside, outside, self.store.root / "missing.json"):
            with self.subTest(target=target):
                symlink_or_skip(self, self.path, target)
                try:
                    with patch("runner.results.read_json") as read:
                        self.assert_unreadable()
                        read.assert_not_called()
                finally:
                    self.path.unlink()

    def test_directory_symlinks_inside_and_outside_are_not_read(self):
        for directory in (self.path.parent, self.path.parent.parent, self.path.parent.parent.parent):
            for inside in (True, False):
                with self.subTest(directory=directory, inside=inside):
                    target = directory.with_name(directory.name + "-backing") if inside else self.store.root / "outside"
                    directory.rename(target)
                    try:
                        symlink_or_skip(self, directory, target, directory=True)
                        try:
                            with patch("runner.results.read_json") as read:
                                # Higher-level containment errors may propagate
                                # before per-Run warnings; neither may read data.
                                try:
                                    self.assert_unreadable()
                                except ManagerError:
                                    pass
                                read.assert_not_called()
                        finally:
                            directory.unlink()
                    finally:
                        target.rename(directory)

    @unittest.skipUnless(os.name == "nt", "native Windows junction fixture")
    def test_native_junctions_inside_and_outside_are_not_read(self):
        for directory in (self.path.parent, self.path.parent.parent, self.path.parent.parent.parent):
            for inside in (True, False):
                with self.subTest(directory=directory, inside=inside):
                    target = directory.with_name(directory.name + "-backing") if inside else self.store.root / "outside"
                    directory.rename(target)
                    try:
                        result = subprocess.run(["cmd", "/d", "/c", "mklink", "/J", str(directory), str(target)],
                                                capture_output=True)
                        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                        try:
                            with patch("runner.results.read_json") as read:
                                try:
                                    self.assert_unreadable()
                                except ManagerError:
                                    pass
                                read.assert_not_called()
                        finally:
                            directory.rmdir()  # Remove only the fixture junction.
                    finally:
                        target.rename(directory)

    def test_denied_missing_corrupt_nonregular_oversize_and_wrong_ids_stay_errors(self):
        lstat = Path.lstat
        for error in (PermissionError(errno.EACCES, "synthetic denial"), FileNotFoundError()):
            with self.subTest(error=type(error).__name__):
                def denied(path, *args, **kwargs):
                    if path == self.path:
                        raise error
                    return lstat(path, *args, **kwargs)

                with patch.object(Path, "lstat", denied), patch("runner.results.read_json") as read:
                    self.assert_unreadable()
                    read.assert_not_called()
        for document in ("{broken", "[]", '{"id":"other","job_id":"sample"}',
                         '{"id":"' + self.run + '","job_id":"other"}', " " * (2 * 1024 * 1024 + 1)):
            self.path.write_text(document, encoding="utf-8")
            self.assert_unreadable()
        self.path.unlink()
        self.path.mkdir()
        with patch("runner.results.read_json") as read:
            self.assert_unreadable()
            read.assert_not_called()
