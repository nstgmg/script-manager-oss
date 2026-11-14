"""Actual host CLI onboarding in an isolated root, offline and without scheduling."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


class InstallationExampleTests(unittest.TestCase):
    def test_cli_run_saved_file_logs_and_collision_preserve_existing_data(self):
        code = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="sm example 한글 ") as temp:
            root = Path(temp)

            def cli(*args, success=True):
                result = subprocess.run([sys.executable, "-B", "-m", "runner", "--root", str(root), *args],
                                        cwd=code, capture_output=True, text=True, encoding="utf-8", timeout=45,
                                        env=dict(os.environ, PYTHONIOENCODING="utf-8"))
                self.assertEqual(result.returncode, 0 if success else 1, result.stderr)
                return json.loads(result.stdout if success else result.stderr.splitlines()[-1])

            self.assertEqual(cli("list"), [])
            cli("create", "hello-output", "--file", str(code / "examples/hello-output/job.yaml"))
            for name in ("main.py", "README.md"):
                shutil.copyfile(code / "examples/hello-output" / name, root / "jobs/hello-output" / name)
            contract = cli("get", "hello-output")
            self.assertEqual(contract["config"]["schedules"], [])
            run = cli("run", "hello-output", "--wait")
            self.assertEqual((run["state"], run["exit_code"]), ("succeeded", 0))
            run_id = run["id"]
            self.assertIn("Hello Output: wrote 2 synthetic records to result.json",
                          cli("logs", "hello-output", run_id, "--stream", "stdout")["text"])
            self.assertEqual(cli("logs", "hello-output", run_id, "--stream", "stderr")["text"], "")
            output = root / "runtime/job-data/hello-output/output" / run_id / "result.json"
            before = output.read_bytes()
            self.assertTrue(json.loads(before)["complete"])
            self.assertEqual([row["id"] for row in json.loads(before)["records"]], ["alpha", "beta"])
            all_rows = cli("results", "hello-output", "--run", run_id)
            self.assertEqual(all_rows["total"], 2)
            filtered = cli("results", "hello-output", "--run", run_id,
                           "--keyword", "Alpha", "--source", "synthetic", "--status", "ready")
            self.assertEqual(filtered["total"], 1)
            self.assertFalse(filtered["has_more"])
            # Rerunning registration cannot overwrite an existing definition/source/data.
            source_before = (root / "jobs/hello-output/main.py").read_bytes()
            cli("create", "hello-output", "--file", str(code / "examples/hello-output/job.yaml"), success=False)
            self.assertEqual(cli("get", "hello-output")["etag"], contract["etag"])
            self.assertEqual((root / "jobs/hello-output/main.py").read_bytes(), source_before)
            self.assertEqual(output.read_bytes(), before)
            self.assertEqual([item["id"] for item in cli("runs", "hello-output")], [run_id])
