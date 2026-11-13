"""Installation-only checks: no Dashboard, Jobs, network or global registration."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import sys
import unittest
from unittest.mock import patch

from scripts.register_dashboard_skill import register, SKILL, SOURCE_FILE


class RegistrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name)
        self.repo = self.project / "script-manager-oss"
        self.source = self.repo / SKILL
        (self.source / "agents").mkdir(parents=True)
        (self.source / "SKILL.md").write_text("original", encoding="utf-8")
        (self.source / "agents/openai.yaml").write_text(
            "policy:\n  allow_implicit_invocation: false\n", encoding="utf-8")

    def test_repository_root_uses_original(self):
        self.assertEqual(register(self.repo, self.repo)["mode"], "repository")
        self.assertFalse(self.source.is_symlink())
        self.assertFalse((self.source / SOURCE_FILE).exists())

    def test_cli_registration_and_check_for_both_layouts(self):
        helper = self.repo / "scripts/register_dashboard_skill.py"
        helper.parent.mkdir()
        shutil.copyfile(Path(__file__).resolve().parents[1] / "scripts" / helper.name, helper)
        for project in (self.repo, self.project):
            for option in ([], [], ["--check"]):
                result = subprocess.run(
                    [sys.executable, str(helper), "--project-root", str(project)] + option,
                    capture_output=True, text=True, check=True)
                self.assertTrue(json.loads(result.stdout)["verified"])

    @unittest.skipIf(sys.platform == "win32", "POSIX link check")
    def test_nested_link_repeat_and_read_only_check(self):
        result = register(self.repo, self.project)
        target = Path(result["skill_path"])
        self.assertTrue(target.is_symlink())
        self.assertEqual(target.resolve(), self.source.resolve())
        self.assertEqual(register(self.repo, self.project), result)
        self.assertEqual(register(self.repo, self.project, check=True), result)
        self.assertEqual((target / "SKILL.md").read_text(), "original")

    def test_windows_copy_keeps_source_and_locator(self):
        with patch("scripts.register_dashboard_skill.sys.platform", "win32"):
            result = register(self.repo, self.project)
            self.assertEqual(result["mode"], "copy")
            self.assertEqual(register(self.repo, self.project), result)
        target = Path(result["skill_path"])
        self.assertFalse(target.is_symlink())
        locator = json.loads((target / SOURCE_FILE).read_text())
        self.assertEqual(Path(locator["repository_root"]), self.repo.resolve())
        self.assertEqual((self.source / "SKILL.md").read_text(), "original")
        (target / "SKILL.md").write_text("user edit")
        with self.assertRaises(ValueError):
            register(self.repo, self.project)
        self.assertEqual((target / "SKILL.md").read_text(), "user edit")

    def test_existing_files_and_broken_links_are_preserved(self):
        target = self.project / SKILL
        target.parent.mkdir(parents=True)
        target.write_text("user file")
        with self.assertRaises(ValueError):
            register(self.repo, self.project)
        self.assertEqual(target.read_text(), "user file")
        target.unlink()  # Test fixture only.
        if sys.platform != "win32":
            target.symlink_to("missing")
            with self.assertRaises(ValueError):
                register(self.repo, self.project)
            self.assertTrue(target.is_symlink())

    def test_missing_check_and_unrelated_root_do_not_write(self):
        with self.assertRaises(ValueError):
            register(self.repo, self.project, check=True)
        other = self.project / "other"
        other.mkdir()
        with self.assertRaises(ValueError):
            register(self.repo, other)
        self.assertFalse((self.project / ".agents").exists())
        self.assertFalse((other / ".agents").exists())

    def test_unmanaged_directory_and_stale_copy_are_preserved(self):
        target = self.project / SKILL
        target.mkdir(parents=True)
        (target / "notes.txt").write_text("user notes")
        with self.assertRaises(ValueError):
            register(self.repo, self.project)
        self.assertEqual((target / "notes.txt").read_text(), "user notes")
        (target / "notes.txt").unlink()
        target.rmdir()  # Empty test fixture only.
        with patch("scripts.register_dashboard_skill.sys.platform", "win32"):
            register(self.repo, self.project)
        (self.source / "SKILL.md").write_text("updated source")
        with self.assertRaises(ValueError):
            register(self.repo, self.project)
        self.assertEqual((target / "SKILL.md").read_text(), "original")

    def test_relative_home_and_filesystem_roots_are_rejected(self):
        for project in (Path("."), Path.home(), Path(self.project.anchor)):
            with self.subTest(project=project), self.assertRaises(ValueError):
                register(self.repo, project)

    @unittest.skipIf(sys.platform == "win32", "POSIX symlink boundary")
    def test_external_skill_parent_and_denied_link_do_not_fallback(self):
        with tempfile.TemporaryDirectory() as outside:
            (self.project / ".agents").symlink_to(outside, target_is_directory=True)
            with self.assertRaises(ValueError):
                register(self.repo, self.project)
            self.assertEqual(list(Path(outside).iterdir()), [])
        (self.project / ".agents").unlink()
        with patch.object(Path, "symlink_to", side_effect=PermissionError("denied")):
            with self.assertRaises(PermissionError):
                register(self.repo, self.project)
        self.assertFalse((self.project / SKILL).exists())


if __name__ == "__main__":
    unittest.main()
