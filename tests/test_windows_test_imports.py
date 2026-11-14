"""Keep Windows test collection independent of the POSIX SSH-target helper."""
from pathlib import Path
import subprocess
import sys
import unittest


class WindowsTestImportTests(unittest.TestCase):
    def test_modules_collect_without_posix_remote_imports(self):
        # A fresh interpreter prevents prior discovery imports from hiding this
        # dependency. On POSIX only, preload common's legitimate local flock
        # implementation before rejecting subsequent fcntl imports. Native
        # Windows instead selects msvcrt there; this guard is not a Windows OS test.
        script = """
import builtins
import importlib
import sys
import unittest
import runner.common

original = builtins.__import__
def guarded(name, *args, **kwargs):
    if name in ('fcntl', 'deployments.remote_runtime'):
        raise ModuleNotFoundError('Windows test imported POSIX dependency: ' + name)
    return original(name, *args, **kwargs)

builtins.__import__ = guarded
module = importlib.import_module(sys.argv[1])
assert 'deployments.remote_runtime' not in sys.modules
suite = unittest.defaultTestLoader.loadTestsFromModule(module)
assert suite.countTestCases() > 0
if sys.argv[1] == 'tests.test_deployments':
    clients = unittest.defaultTestLoader.loadTestsFromName(sys.argv[1] + '.DeploymentClientTests')
    result = unittest.TextTestRunner().run(clients)
    assert result.wasSuccessful() and not result.skipped
"""
        for module in ("tests.test_windows_ownership", "tests.test_windows_ownership_handoff",
                       "tests.test_dashboard", "tests.test_deployments", "tests.test_multi_schedule"):
            with self.subTest(module=module):
                result = subprocess.run([sys.executable, "-B", "-c", script, module],
                                        cwd=Path(__file__).resolve().parents[1],
                                        capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_launchd_fixture_selects_adapter_without_host_getuid(self):
        script = """
import os
import unittest
from unittest.mock import patch
if hasattr(os, 'getuid'):
    del os.getuid
suite = unittest.defaultTestLoader.loadTestsFromNames([
    'tests.test_schedule.ScheduleTests.test_calendar_mapping_and_apply_remove',
    'tests.test_multi_schedule.MultiScheduleTests.test_mixed_schedules_independent_edit_pause_resume_delete_and_other_job',
    'tests.test_maintenance.MaintenanceTests.test_unknown_modified_loaded_only_and_running_are_never_removed',
])
with patch('runner.schedule.platform.system', return_value='Windows'):
    result = unittest.TextTestRunner().run(suite)
assert result.wasSuccessful()
assert not result.skipped
assert not hasattr(os, 'getuid'), 'synthetic UID leaked out of fixture'
"""
        result = subprocess.run([sys.executable, "-B", "-c", script],
                                cwd=Path(__file__).resolve().parents[1],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
