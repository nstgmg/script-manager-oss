"""Offline bootstrap state/failure contracts; native shells are labelled separately."""
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import venv

from scripts import bootstrap


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="sm setup 한글 ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "requirements.txt").write_text("ruamel.yaml==0.18.17\n", encoding="utf-8")

    def fake_venv(self):
        python = bootstrap.venv_python(self.root)
        python.parent.mkdir(parents=True)
        python.touch()
        (self.root / ".venv/pyvenv.cfg").write_text("fixture\n")
        return {"prefix": str(self.root / ".venv"), "base_prefix": str(self.root),
                "version": [3, 14, 3], "pip": True, "versions": {"ruamel.yaml": None}}

    def probe(self, details):
        return subprocess.CompletedProcess([], 0, json.dumps(details), "")

    def test_missing_status_is_read_only_and_creates_no_data(self):
        before = list(self.root.iterdir())
        with patch.object(bootstrap.subprocess, "run") as run:
            status = bootstrap.inspect(self.root)
        self.assertEqual(status["state"], "missing_venv")
        self.assertFalse(status["runtime_ready"])
        run.assert_not_called()
        self.assertEqual(list(self.root.iterdir()), before)

    def test_existing_runtime_is_reused_without_install_or_example(self):
        details = self.fake_venv()
        details["versions"]["ruamel.yaml"] = "0.18.17"
        (self.root / "jobs/operational").mkdir(parents=True)
        original = self.root / "jobs/operational/job.yaml"
        original.write_text("preserved schedule and command")
        with patch.object(bootstrap.subprocess, "run", side_effect=[self.probe(details),
                   subprocess.CompletedProcess([], 0)]), patch.object(bootstrap, "step") as step:
            status = bootstrap.prepare(self.root)
        self.assertTrue(status["runtime_ready"])
        self.assertFalse(status["changed"])
        self.assertEqual(status["example_verification"], "not_performed")
        step.assert_not_called()
        self.assertEqual(original.read_text(), "preserved schedule and command")

    def test_operating_data_blocks_automatic_repairs_without_reading_secrets(self):
        # Inventory-only checks: even a secret directory is not opened/read.
        for name in bootstrap.DATA_PATHS:
            with self.subTest(path=name), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                shutil.copyfile(self.root / "requirements.txt", root / "requirements.txt")
                target = root / name
                target.mkdir(parents=True)
                if name == "jobs":
                    (target / "existing-job").mkdir()
                with patch.object(bootstrap, "step") as step:
                    with self.assertRaisesRegex(ValueError, "Existing data"):
                        bootstrap.prepare(root)
                step.assert_not_called()
                self.assertTrue(target.is_dir())

    def test_empty_jobs_scaffold_is_not_operating_data(self):
        (self.root / "jobs").mkdir()
        (self.root / "jobs/.gitkeep").touch()
        self.assertEqual(bootstrap.inspect(self.root)["data_paths"], [])

    def test_partial_venv_is_preserved_on_repeated_attempts(self):
        folder = self.root / ".venv"
        folder.mkdir()
        (folder / "notes").write_text("do not delete")
        for _ in range(2):
            with patch.object(bootstrap, "step") as step:
                with self.assertRaisesRegex(ValueError, "preserved"):
                    bootstrap.prepare(self.root)
            step.assert_not_called()
        self.assertEqual((folder / "notes").read_text(), "do not delete")

    def test_broken_or_foreign_interpreter_is_not_replaced(self):
        details = self.fake_venv()
        details["prefix"] = details["base_prefix"]
        for outcome in (self.probe(details), OSError("cannot execute"),
                        subprocess.TimeoutExpired("python", 30), self.probe({})):
            with self.subTest(outcome=outcome):
                with patch.object(bootstrap.subprocess, "run", side_effect=[outcome]), \
                        patch.object(bootstrap, "step") as step:
                    with self.assertRaisesRegex(ValueError, "preserved"):
                        bootstrap.prepare(self.root)
                step.assert_not_called()
        self.assertTrue(bootstrap.venv_python(self.root).exists())

    @unittest.skipIf(os.name == "nt", "POSIX link fixture; Windows junction check requires Windows")
    def test_external_venv_link_is_not_followed(self):
        external = self.root / "external"
        external.mkdir()
        (self.root / ".venv").symlink_to(external, target_is_directory=True)
        with patch.object(bootstrap.subprocess, "run") as run:
            self.assertEqual(bootstrap.inspect(self.root)["state"], "unsafe_venv")
            with self.assertRaises(ValueError):
                bootstrap.prepare(self.root)
        run.assert_not_called()
        self.assertTrue((self.root / ".venv").is_symlink())

    def test_windows_junction_refused_even_without_path_is_junction_api(self):
        folder = self.root / ".venv"
        folder.mkdir()
        original = Path.lstat

        def lstat(path):
            if path == folder:
                return SimpleNamespace(st_mode=0o040755, st_file_attributes=0x400)
            return original(path)

        with patch.object(Path, "lstat", lstat), patch.object(bootstrap.subprocess, "run") as run:
            self.assertEqual(bootstrap.inspect(self.root)["state"], "unsafe_venv")
            with self.assertRaisesRegex(ValueError, "preserved"):
                bootstrap.prepare(self.root)
        run.assert_not_called()
        self.assertTrue(folder.exists())

    def test_dependency_failure_stops_and_retry_reuses_same_interpreter(self):
        details = self.fake_venv()
        commands = []
        failed = [False]

        def execute(argv, **kwargs):
            if "-c" in argv:
                return self.probe(details)
            commands.append(argv)
            if "-r" in argv:
                if not failed[0]:
                    failed[0] = True
                    return subprocess.CompletedProcess(argv, 1)
                details["versions"]["ruamel.yaml"] = "0.18.17"
            return subprocess.CompletedProcess(argv, 0)

        python = str(bootstrap.venv_python(self.root))
        with patch.object(bootstrap.subprocess, "run", side_effect=execute), redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, "requirements failed"):
                bootstrap.prepare(self.root)
            self.assertFalse(any("check" in cmd for cmd in commands))
            self.assertTrue(bootstrap.prepare(self.root)["runtime_ready"])
            installed = len(commands)
            self.assertFalse(bootstrap.prepare(self.root)["changed"])
        self.assertTrue(all(cmd[0] == python for cmd in commands))
        self.assertFalse(any("venv" in cmd for cmd in commands))
        self.assertEqual(sum("-r" in cmd for cmd in commands), 2)
        self.assertEqual(len(commands) - installed, 1)  # Read-only pip check only.

    def test_missing_pip_is_bootstrapped_only_inside_valid_new_venv(self):
        details = self.fake_venv()
        details["pip"] = False
        with patch.object(bootstrap, "inspect", side_effect=[dict(state="needs_dependencies",
                   runtime_ready=False, data_paths=[], interpreter=details),
                   dict(state="ready", runtime_ready=True)]), patch.object(bootstrap, "step") as step:
            bootstrap.prepare(self.root)
        first = step.call_args_list[0].args
        self.assertEqual(first[1], "ensurepip")
        self.assertEqual(first[2][0], bootstrap.venv_python(self.root))

    def test_windows_argv_preserves_spaces_and_disables_rendering_without_shell(self):
        python = bootstrap.venv_python(self.root, windows=True)
        self.assertEqual(python.parts[-2:], ("Scripts", "python.exe"))
        argv = [python, "-I", "-m", "pip", "install", "--progress-bar", "off", "--no-color",
                "-r", self.root / "requirements.txt"]
        with patch.object(bootstrap.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)) as run, \
                redirect_stdout(io.StringIO()):
            bootstrap.step(self.root, "requirements", argv)
        args, kwargs = run.call_args
        self.assertEqual(args[0], [str(item) for item in argv])
        self.assertFalse(kwargs.get("shell", False))
        self.assertEqual(kwargs["cwd"], self.root)
        self.assertEqual(kwargs["env"]["PIP_PROGRESS_BAR"], "off")
        self.assertEqual(kwargs["env"]["PIP_NO_COLOR"], "1")
        self.assertEqual(kwargs["env"]["PIP_NO_INPUT"], "1")
        self.assertEqual(subprocess.list2cmdline(args[0]).count('"'), 4)

    def test_packaging_tools_failure_prevents_requirements_and_success(self):
        details = self.fake_venv()
        with patch.object(bootstrap.subprocess, "run", side_effect=[self.probe(details),
                   subprocess.CompletedProcess([], 17)]) as run, redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, "packaging-tools failed.*17"):
                bootstrap.prepare(self.root)
        self.assertEqual(run.call_count, 2)

    def test_existing_environment_with_wrong_pin_or_failed_pip_check_is_not_upgraded(self):
        details = self.fake_venv()
        (self.root / "runtime").mkdir()
        for version in ("0.18.16", "0.18.17"):
            details["versions"]["ruamel.yaml"] = version
            with patch.object(bootstrap.subprocess, "run", side_effect=[self.probe(details),
                       subprocess.CompletedProcess([], 1)]), patch.object(bootstrap, "step") as step:
                with self.assertRaisesRegex(ValueError, "Existing data"):
                    bootstrap.prepare(self.root)
            step.assert_not_called()

    def test_unknown_requirements_fail_before_any_environment_changes(self):
        (self.root / "requirements.txt").write_text("other>=1\n")
        with patch.object(bootstrap.subprocess, "run") as run:
            with self.assertRaisesRegex(ValueError, "Unsupported requirements"):
                bootstrap.prepare(self.root)
        run.assert_not_called()

    def test_real_venv_without_pip_is_detected_without_modification(self):
        venv.EnvBuilder(with_pip=False).create(self.root / ".venv")
        status = bootstrap.inspect(self.root)
        self.assertEqual(status["state"], "needs_dependencies")
        self.assertFalse(status["interpreter"]["pip"])
        self.assertEqual(Path(status["interpreter"]["prefix"]).resolve(), (self.root / ".venv").resolve())
        self.assertFalse((self.root / "runtime").exists())

    def test_actual_dotted_distribution_probe_recognizes_installed_runtime(self):
        # The test suite itself requires this distribution; 3.9's version(name)
        # may miss it even when import and pip check succeed.
        result = subprocess.run([sys.executable, "-I", "-B", "-c", bootstrap.PROBE,
                                 json.dumps(["ruamel.yaml", "ruamel_yaml"])],
                                capture_output=True, text=True, check=True, timeout=30)
        versions = json.loads(result.stdout)["versions"]
        self.assertEqual(versions, {"ruamel.yaml": "0.18.17", "ruamel_yaml": "0.18.17"})

    def test_venv_creation_failure_stops_before_pip_and_preserves_destination(self):
        def fail_creation(argv, **kwargs):
            folder = self.root / ".venv"
            folder.mkdir()
            (folder / "partial-file").write_text("preserve")
            return subprocess.CompletedProcess(argv, 1)

        with patch.object(bootstrap.subprocess, "run", side_effect=fail_creation) as run, \
                redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, "venv failed"):
                bootstrap.prepare(self.root)
            with self.assertRaisesRegex(ValueError, "preserved"):
                bootstrap.prepare(self.root)
        self.assertEqual(run.call_count, 1)
        self.assertEqual((self.root / ".venv/partial-file").read_text(), "preserve")


@unittest.skipUnless(sys.platform == "win32" and shutil.which("powershell.exe"),
                     "Actual Windows PowerShell 5.1 parser unavailable; POSIX tests are not native verification")
class NativePowerShellSyntaxTests(unittest.TestCase):
    def test_install_document_blocks_parse_with_windows_powershell(self):
        source = Path(__file__).resolve().parents[1] / "INSTALL.md"
        blocks = re.findall(r"```powershell\n(.*?)```", source.read_text(encoding="utf-8"), re.S)
        with tempfile.TemporaryDirectory() as temp:
            script = Path(temp) / "commands.ps1"
            script.write_text("\n".join(blocks), encoding="utf-8-sig")
            # Parse only; never clone, install, run Jobs or start Dashboard.
            command = ("$tokens=$null; $errors=$null; "
                       "[void][System.Management.Automation.Language.Parser]::ParseFile("
                       "'" + str(script).replace("'", "''") + "', [ref]$tokens, [ref]$errors); "
                       "if ($errors.Count) { $errors | Out-String | Write-Error; exit 1 }")
            result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
                                    capture_output=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
