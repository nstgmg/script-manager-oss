from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import os
import tempfile
import unittest
import uuid

from runner.common import ManagerError
from runner.store import Store, default_job


class TrashTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(self.temp.name)
        self.job = self.store.create(default_job("sample", "삭제한 작업"))

    def delete(self):
        return self.store.delete("sample", self.store.get("sample")["etag"])

    def test_delete_list_restore_preserves_original_files(self):
        item = self.store.update("sample", self.job["yaml"] + "\n# retained comment\n", self.job["etag"])
        (self.store.job_dir("sample") / "data.bin").write_bytes(b"\x00original")
        result = self.delete()
        entries = self.store.trash()
        self.assertEqual(len(entries), 1)  # YAML edit backups are not deleted Jobs.
        self.assertEqual(entries[0]["trash_id"], result["trash_id"])
        self.assertEqual(entries[0]["job_id"], "sample")
        self.assertEqual(entries[0]["name"], "삭제한 작업")
        self.assertIn("T", entries[0]["deleted_at"])
        self.assertFalse(entries[0]["deleted_at_estimated"])
        restored = self.store.restore(result["trash_id"])
        self.assertEqual(restored["yaml"], item["yaml"])
        self.assertEqual((self.store.job_dir("sample") / "data.bin").read_bytes(), b"\x00original")
        self.assertEqual(self.store.trash(), [])
        self.assertFalse((self.store.runtime / "schedules/sample.json").exists())

    def test_existing_job_is_not_overwritten(self):
        deleted = self.delete()
        existing = self.store.create(default_job("sample", "새 작업"))
        with self.assertRaises(ManagerError) as cm:
            self.store.restore(deleted["trash_id"])
        self.assertEqual(cm.exception.status, 409)
        self.assertEqual(self.store.get("sample")["yaml"], existing["yaml"])
        self.assertTrue(Path(deleted["recover_from"]).exists())
        self.assertEqual(len(self.store.trash()), 1)

    def test_legacy_trash_uses_estimated_timestamp(self):
        trash_id = "sample-" + uuid.uuid4().hex
        os.rename(self.store.job_dir("sample"), self.store.runtime / "trash" / trash_id)
        (self.store.runtime / "trash" / "unrelated.yaml").write_text("backup")
        item = self.store.trash()[0]
        self.assertTrue(item["deleted_at_estimated"])
        self.assertEqual(self.store.restore(trash_id)["config"]["name"], "삭제한 작업")

    def test_invalid_paths_links_and_damaged_yaml_cannot_be_restored(self):
        with self.assertRaises(ManagerError):
            self.store.restore("../sample")
        deleted = self.delete()
        (self.store.runtime / "trash" / ("alias-" + uuid.uuid4().hex)).symlink_to(deleted["recover_from"])
        (Path(deleted["recover_from"]) / "job.yaml").write_text("invalid: [")
        self.assertEqual(len(self.store.trash()), 1)
        self.assertIn("error", self.store.trash()[0])
        with self.assertRaises(ManagerError):
            self.store.restore(deleted["trash_id"])
        self.assertTrue(Path(deleted["recover_from"]).exists())

    def test_concurrent_restore_of_same_job_id_has_one_winner(self):
        first = self.delete()["trash_id"]
        self.store.create(default_job("sample", "다른 버전"))
        second = self.delete()["trash_id"]
        def restore(trash_id):
            try:
                return self.store.restore(trash_id)
            except ManagerError as exc:
                return exc.status
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(restore, (first, second)))
        self.assertEqual(sum(isinstance(result, dict) for result in results), 1)
        self.assertEqual(sum(result == 409 for result in results), 1)
        self.assertEqual(len(self.store.trash()), 1)
