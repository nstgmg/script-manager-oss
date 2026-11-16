"""Real NTFS coverage for lock byte integrity and cross-process exclusion."""
import ctypes
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from runner.common import lock


@unittest.skipUnless(os.name == "nt", "Windows byte-range locking")
class WindowsLockIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.assertFalse(ctypes.windll.shell32.IsUserAnAdmin(),
                         "Run this native regression without elevation")
        self.temp = tempfile.TemporaryDirectory(prefix="sm-lock-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def check_hardlink(self, data):
        original = self.root / "original.bin"
        original.write_bytes(data)
        alias = self.root / "lock"
        os.link(original, alias)
        before = original.stat()
        with lock(alias):
            self.assertEqual(original.stat().st_size, len(data))
        self.assertEqual(original.read_bytes(), data)
        self.assertEqual(alias.read_bytes(), data)
        self.assertEqual(original.stat().st_ino, before.st_ino)
        self.assertEqual(alias.stat().st_ino, before.st_ino)

    def test_empty_hardlink_is_not_initialized(self):
        self.check_hardlink(b"")

    def test_nonempty_hardlink_is_unchanged(self):
        self.check_hardlink(b"original\x00data\xff")

    def test_cross_process_exclusion_and_reacquisition(self):
        path = self.root / "lock"
        script = """
import json, sys
from runner.common import lock, ManagerError
try:
    with lock(sys.argv[1], blocking=False):
        print(json.dumps({'acquired': True}))
except ManagerError as exc:
    print(json.dumps({'acquired': False, 'status': exc.status}))
"""

        def child():
            result = subprocess.run([sys.executable, "-B", "-c", script, str(path)],
                                    cwd=str(Path(__file__).resolve().parents[1]),
                                    capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stderr, "")
            return json.loads(result.stdout)

        with lock(path):
            self.assertEqual(child(), {"acquired": False, "status": 409})
        self.assertEqual(child(), {"acquired": True})
        self.assertEqual(path.read_bytes(), b"")


if __name__ == "__main__":
    unittest.main()
