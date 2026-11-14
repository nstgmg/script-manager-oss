"""Keep Windows test collection independent of the POSIX SSH-target helper."""
from pathlib import Path
import subprocess
import sys
import unittest


class WindowsTestImportTests(unittest.TestCase):
    def test_ownership_modules_collect_without_posix_remote_imports(self):
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
"""
        for module in ("tests.test_windows_ownership", "tests.test_windows_ownership_handoff"):
            with self.subTest(module=module):
                result = subprocess.run([sys.executable, "-B", "-c", script, module],
                                        cwd=Path(__file__).resolve().parents[1],
                                        capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
