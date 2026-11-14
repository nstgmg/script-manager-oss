"""Native Windows ACL readback only; no ACL edits, schedules or resident services."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from runner.common import private_temporary_directory
from runner.lifecycle import Lifecycle
from runner.store import Store, default_job


@unittest.skipUnless(os.name == "nt" and shutil.which("powershell.exe"),
                     "Native Windows/PowerShell needed for ACL readback")
class NativeRuntimeACLTests(unittest.TestCase):
    def acl(self, path):
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
             "$ErrorActionPreference = 'Stop'; "
             "$acl = Get-Acl -LiteralPath $env:SCRIPT_MANAGER_ACL_TEST_ROOT; "
             "[pscustomobject]@{sddl=$acl.Sddl; protected=$acl.AreAccessRulesProtected; "
             "inherited=@($acl.Access | Where-Object { $_.IsInherited }).Count} "
             "| ConvertTo-Json -Compress"],
            env=dict(os.environ, SCRIPT_MANAGER_ACL_TEST_ROOT=str(path)),
            capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_new_directories_inherit_and_reopen_keeps_existing_acl_and_data(self):
        # The private TemporaryDirectory belongs to this test account. Production
        # sandbox <-> normal-user tokens still require the manual two-context check.
        with tempfile.TemporaryDirectory(prefix="sm native ACL ") as temporary:
            root = Path(temporary).resolve()
            parent_before = self.acl(root)
            store = Store(root)
            store.create(default_job("sample"))
            paths = Lifecycle(store).paths("sample", "a" * 32, create=True)
            dirs = [store.runtime, store.runtime / "locks", store.job_dir("sample"),
                    Path(paths["SCRIPT_MANAGER_STATE_DIR"]), Path(paths["SCRIPT_MANAGER_OUTPUT_DIR"])]
            with private_temporary_directory(store.runtime / "deployments") as scratch:
                dirs.append(scratch)
                before = {p: self.acl(p) for p in dirs}
                for path, acl in before.items():
                    self.assertFalse(acl["protected"], path)
                    self.assertGreater(acl["inherited"], 0, path)
                marker = Path(paths["SCRIPT_MANAGER_STATE_DIR"]) / "keep.txt"
                marker.write_text("existing data", encoding="utf-8")
                Store(root)
                Lifecycle(store).paths("sample", "a" * 32, create=True)
                self.assertEqual(before, {p: self.acl(p) for p in dirs})
                self.assertEqual(marker.read_text(encoding="utf-8"), "existing data")
            self.assertEqual(self.acl(root), parent_before)
