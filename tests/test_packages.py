import hashlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
import zipfile

from deployments.packages import Packages
from runner.common import ManagerError
from runner.store import Store, default_job, dump_yaml


class PackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(self.temp.name)
        self.store.create(default_job("sample"))
        self.packages = Packages(self.store)
        self.folder = self.store.job_dir("sample")

    def test_zip_is_reusable_and_independent_of_job_changes(self):
        first = self.packages.create("sample")
        original = self.packages.archive(first["id"], "sample")
        self.assertEqual(original, self.packages.archive(first["id"], "sample"))
        self.assertEqual(hashlib.sha256(original).hexdigest(), first["zip_sha256"])
        with zipfile.ZipFile(io.BytesIO(original)) as archive:
            self.assertIsNone(archive.testzip())
            self.assertIn("RUNME.md", archive.namelist())
            self.assertEqual(archive.read("manager/LICENSE"), (Path(__file__).resolve().parents[1] / "LICENSE").read_bytes())
            self.assertIn("Job source may have a separate license", archive.read("RUNME.md").decode())
            self.assertIn("source/main.py", archive.namelist())
            self.assertEqual(json.loads(archive.read("package.json"))["id"], first["id"])
        (self.folder / "main.py").write_text("print('new version')\n")
        difference = self.packages.difference("sample", first["id"])
        self.assertTrue(difference["changed"])
        self.assertEqual(difference["modified"], ["main.py"])
        self.assertEqual(original, self.packages.archive(first["id"], "sample"))
        second = self.packages.create("sample")
        self.assertNotEqual(first["content_hash"], second["content_hash"])
        self.assertFalse(self.packages.difference("sample", second["id"])["changed"])
        self.assertEqual(self.packages.list("sample")[0]["id"], second["id"])

    def test_excludes_generated_secret_and_local_files(self):
        (self.folder / "data").mkdir()
        (self.folder / "data/output.json").write_text("generated")
        (self.folder / "logs").mkdir()
        (self.folder / "logs/run.log").write_text("log")
        (self.folder / "private.pem").write_text("secret")
        (self.folder / "access-token.txt").write_text("secret")
        (self.folder / ".env").write_text("PASSWORD=secret")
        (self.folder / "requirements.txt").write_text("requests==2.0\n")
        item = self.store.get("sample")
        config = item["config"]
        config["env_file"] = ".env"
        self.store.update("sample", dump_yaml(config), item["etag"])
        package = self.packages.create("sample")
        with zipfile.ZipFile(io.BytesIO(self.packages.archive(package["id"], "sample"))) as archive:
            names = archive.namelist()
            self.assertIn("source/requirements.txt", names)
            for name in ("data/output.json", "logs/run.log", "private.pem", "access-token.txt", ".env"):
                self.assertNotIn("source/" + name, names)
            self.assertIn("env_file", archive.read("RUNME.md").decode())

    def test_rejects_symlink_inline_env_and_corrupt_archive(self):
        (self.folder / "escape").symlink_to("/etc/passwd")
        with self.assertRaises(ManagerError):
            self.packages.create("sample")
        (self.folder / "escape").unlink()
        item = self.store.get("sample")
        config = item["config"]
        config["env"] = {"TOKEN": "value"}
        self.store.update("sample", dump_yaml(config), item["etag"])
        with self.assertRaises(ManagerError):
            self.packages.create("sample")
        config["env"] = {}
        self.store.update("sample", dump_yaml(config), self.store.get("sample")["etag"])
        package = self.packages.create("sample")
        archive = self.packages._directory(package["id"]) / "package.zip"
        archive.chmod(0o600)
        archive.write_bytes(b"corrupt")
        with self.assertRaises(ManagerError) as error:
            self.packages.archive(package["id"], "sample")
        self.assertEqual(error.exception.status, 409)

    def test_package_cannot_be_used_for_another_job(self):
        package = self.packages.create("sample")
        self.store.create(default_job("other"))
        with self.assertRaises(ManagerError):
            self.packages.archive(package["id"], "other")

    def test_downloaded_zip_runs_without_script_manager(self):
        package = self.packages.create("sample")
        destination = Path(self.temp.name) / "standalone"
        destination.mkdir()
        with zipfile.ZipFile(io.BytesIO(self.packages.archive(package["id"], "sample"))) as archive:
            archive.extractall(destination)
        result = subprocess.run(["python3", "main.py"], cwd=destination / "source",
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("sample job completed", result.stdout)
