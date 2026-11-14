"""Atomic metadata contracts; real Windows sharing probes run on Windows only.

Portable tests also exercise held readers and independent reader processes.
Win32 API mocks below verify call/ownership contracts, not native OS behavior.
"""
import contextlib
import ctypes
import errno
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from runner import common


class AtomicMetadataTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="sm metadata 한글 ")
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "run.json"
        self.before = {"state": "running", "text": "한글", "version": 0}
        common.write_json(self.path, self.before)

    def test_held_reader_sees_old_snapshot_new_reader_sees_replacement(self):
        after = {"state": "succeeded", "exit_code": 0, "text": "완료"}
        with common.open_atomic_read(self.path) as reader:
            self.assertFalse(os.get_inheritable(reader.fileno()))
            common.write_json(self.path, after)
            self.assertEqual(json.load(reader), self.before)
            self.assertEqual(common.read_json(self.path), after)
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    def test_independent_readers_during_repeated_replacement(self):
        script = """
import json, sys
from runner.common import open_atomic_read, read_json
with open_atomic_read(sys.argv[1]) as held:
    print('ready', flush=True)
    for line in sys.stdin:
        expected = int(line)
        current = read_json(sys.argv[1])
        assert current['version'] == expected, current
        assert current['text'] == '한글' * 1000, current
        print('ok', flush=True)
    assert json.load(held)['version'] == 0
"""
        common.write_json(self.path, {"version": 0, "text": "한글" * 1000})
        readers = []
        try:
            for _ in range(3):
                proc = subprocess.Popen([sys.executable, "-X", "utf8", "-c", script, str(self.path)],
                                        cwd=Path(__file__).resolve().parents[1], stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                        encoding="utf-8")
                readers.append(proc)
                self.assertEqual(proc.stdout.readline().strip(), "ready")
            for version in range(1, 41):
                common.write_json(self.path, {"version": version, "text": "한글" * 1000})
                for proc in readers:
                    proc.stdin.write(str(version) + "\n")
                    proc.stdin.flush()
                for proc in readers:
                    self.assertEqual(proc.stdout.readline().strip(), "ok")
        finally:
            for proc in readers:
                proc.stdin.close()
            for proc in readers:
                proc.wait(timeout=15)
                error = proc.stderr.read()
                proc.stdout.close()
                proc.stderr.close()
                self.assertEqual(proc.returncode, 0, error)

    def test_failed_replace_preserves_original_and_propagates_without_retry(self):
        failure = PermissionError(errno.EACCES, "synthetic access denied")
        with patch.object(common, "_atomic_replace", side_effect=failure) as replace:
            with self.assertRaises(PermissionError) as raised:
                common.write_json(self.path, {"state": "succeeded"})
        self.assertIs(raised.exception, failure)
        replace.assert_called_once()
        self.assertEqual(common.read_json(self.path), self.before)
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    def test_missing_is_default_but_denial_and_corruption_are_errors(self):
        marker = object()
        self.assertIs(common.read_json(self.path.parent / "missing.json", marker), marker)
        failure = PermissionError(errno.EACCES, "synthetic read denial")
        with patch.object(common, "open_atomic_read", side_effect=failure) as opened:
            with self.assertRaises(PermissionError) as raised:
                common.read_json(self.path, marker)
        self.assertIs(raised.exception, failure)
        opened.assert_called_once()
        self.path.write_bytes(b'{"state":')
        with self.assertRaises(json.JSONDecodeError):
            common.read_json(self.path, marker)

    @unittest.skipUnless(os.name == "nt", "native Windows sharing denial/reverse-open probe")
    def test_native_legacy_reader_blocks_replace_and_delete_handle_blocks_legacy_read(self):
        # Reproduce the old CRT reader failure on a temporary file, never an ACL edit.
        candidate = self.path.parent / "candidate.json"
        candidate.write_text('{}', encoding="utf-8")
        try:
            # Sharing alone is insufficient for legacy replacement of an open target.
            for opener in (lambda: self.path.open("r", encoding="utf-8"),
                           lambda: common.open_atomic_read(self.path)):
                with opener():
                    with self.assertRaises(PermissionError) as denied:
                        os.replace(candidate, self.path)
                    self.assertIn(denied.exception.winerror, (5, 32))
        finally:
            candidate.unlink(missing_ok=True)
        self.assertEqual(common.read_json(self.path), self.before)

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        from ctypes import wintypes
        kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                      ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        kernel.CreateFileW.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        # Model the other half of the conflict: a writer already has DELETE access.
        handle = kernel.CreateFileW(str(self.path), 0x10000, 7, None, 3, 0x80, None)
        self.assertNotEqual(handle, ctypes.c_void_p(-1).value)
        try:
            with self.assertRaises(PermissionError):
                self.path.read_text(encoding="utf-8")
            self.assertEqual(common.read_json(self.path), self.before)
        finally:
            kernel.CloseHandle(handle)
        common.write_json(self.path, {"state": "succeeded"})
        self.assertEqual(common.read_json(self.path)["state"], "succeeded")


class WindowsReadOpenerContractTests(unittest.TestCase):
    def setUp(self):
        self.handle = 0x123456789  # Catch accidental 32-bit HANDLE truncation.
        self.kernel = SimpleNamespace(CreateFileW=Mock(return_value=self.handle), CloseHandle=Mock())
        self.crt = SimpleNamespace(open_osfhandle=Mock(return_value=42))
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(ctypes, "WinDLL", return_value=self.kernel, create=True))
        self.stack.enter_context(patch.dict(sys.modules, {"msvcrt": self.crt}))
        self.stack.enter_context(patch.object(common, "os", SimpleNamespace(O_RDONLY=0, O_BINARY=0x8000,
                                                                          O_NOINHERIT=0x80)))

    def test_sharing_access_unicode_and_handle_ownership(self):
        self.assertEqual(common._windows_read_opener("C:\\한글\\run.json", 0), 42)
        self.kernel.CreateFileW.assert_called_once_with("C:\\한글\\run.json", 0x80000000, 7,
                                                       None, 3, 0x80, None)
        self.assertIs(self.kernel.CreateFileW.restype, ctypes.c_void_p)
        self.crt.open_osfhandle.assert_called_once_with(self.handle, 0x8080)
        self.kernel.CloseHandle.assert_not_called()

    def test_failed_fd_transfer_closes_handle_and_propagates(self):
        failure = OSError("synthetic fd allocation failure")
        self.crt.open_osfhandle.side_effect = failure
        with self.assertRaises(OSError) as raised:
            common._windows_read_opener("run.json", 0)
        self.assertIs(raised.exception, failure)
        self.kernel.CloseHandle.assert_called_once_with(self.handle)

    def test_open_error_is_preserved_without_fd_or_close_or_retry(self):
        self.kernel.CreateFileW.return_value = ctypes.c_void_p(-1).value
        for failure in (FileNotFoundError(errno.ENOENT, "missing"),
                        PermissionError(errno.EACCES, "denied")):
            self.kernel.CreateFileW.reset_mock()
            with self.subTest(error=type(failure).__name__), \
                    patch.object(ctypes, "get_last_error", return_value=5, create=True), \
                    patch.object(ctypes, "WinError", return_value=failure, create=True):
                with self.assertRaises(type(failure)) as raised:
                    common._windows_read_opener("run.json", 0)
                self.assertIs(raised.exception, failure)
                self.assertEqual(raised.exception.filename, "run.json")
                self.kernel.CreateFileW.assert_called_once()
        self.crt.open_osfhandle.assert_not_called()
        self.kernel.CloseHandle.assert_not_called()


class WindowsReplaceContractTests(unittest.TestCase):
    def setUp(self):
        self.handle = 0x123456789
        self.kernel = SimpleNamespace(CreateFileW=Mock(return_value=self.handle), CloseHandle=Mock(),
                                      SetFileInformationByHandle=Mock(return_value=1))
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.dll = self.stack.enter_context(patch.object(ctypes, "WinDLL", return_value=self.kernel,
                                                       create=True))

    def test_posix_replace_flags_pointer_alignment_and_utf16_name(self):
        target = Path(tempfile.gettempdir()) / "한글-😀.json"
        name = str(target.absolute()).encode("utf-16-le")
        common._windows_replace("temporary.json", target)
        self.dll.assert_called_once_with("kernel32", use_last_error=True)
        self.kernel.CreateFileW.assert_called_once_with("temporary.json", 0x10000, 7, None, 3, 0x80, None)
        handle, info_class, buffer, size = self.kernel.SetFileInformationByHandle.call_args.args
        self.assertEqual((handle, info_class, size), (self.handle, 22, len(buffer)))
        # Win32 layout: DWORD, aligned HANDLE, DWORD byte length, UTF-16 name.
        root_offset = 8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 4
        length_offset = root_offset + ctypes.sizeof(ctypes.c_void_p)
        name_offset = length_offset + 4
        self.assertEqual(ctypes.c_uint32.from_buffer(buffer).value, 3)
        self.assertIsNone(ctypes.c_void_p.from_buffer(buffer, root_offset).value)
        self.assertEqual(ctypes.c_uint32.from_buffer(buffer, length_offset).value, len(name))
        self.assertEqual(buffer.raw[name_offset:name_offset + len(name)], name)
        self.assertEqual(buffer.raw[name_offset + len(name):name_offset + len(name) + 2], b'\0\0')
        self.kernel.CloseHandle.assert_called_once_with(self.handle)

    def test_access_sharing_and_unsupported_errors_propagate_without_fallback(self):
        self.kernel.SetFileInformationByHandle.return_value = 0
        for code in (5, 32, 50, 87, 120):
            failure = OSError("synthetic Win32 failure")
            failure.winerror = code
            self.kernel.CreateFileW.reset_mock()
            self.kernel.SetFileInformationByHandle.reset_mock()
            self.kernel.CloseHandle.reset_mock()
            with self.subTest(winerror=code), \
                    patch.object(ctypes, "get_last_error", return_value=code, create=True), \
                    patch.object(ctypes, "WinError", return_value=failure, create=True) as error, \
                    patch.object(common.os, "replace") as legacy:
                with self.assertRaises(OSError) as raised:
                    common._windows_replace("temporary.json", "target.json")
                self.assertIs(raised.exception, failure)
                self.assertEqual((failure.filename, failure.filename2), ("temporary.json", "target.json"))
                error.assert_called_once_with(code)
                self.kernel.CreateFileW.assert_called_once()
                self.kernel.SetFileInformationByHandle.assert_called_once()
                self.kernel.CloseHandle.assert_called_once_with(self.handle)
                legacy.assert_not_called()

    def test_source_open_failure_does_not_close_invalid_handle_or_rename(self):
        self.kernel.CreateFileW.return_value = ctypes.c_void_p(-1).value
        failure = PermissionError(errno.EACCES, "synthetic source denied")
        with patch.object(ctypes, "get_last_error", return_value=5, create=True), \
                patch.object(ctypes, "WinError", return_value=failure, create=True):
            with self.assertRaises(PermissionError) as raised:
                common._windows_replace("temporary.json", "target.json")
        self.assertIs(raised.exception, failure)
        self.kernel.CreateFileW.assert_called_once()
        self.kernel.SetFileInformationByHandle.assert_not_called()
        self.kernel.CloseHandle.assert_not_called()

    def test_platform_dispatch_keeps_posix_replace_and_selects_native_windows(self):
        for platform in ("nt", "posix"):
            legacy = Mock()
            with self.subTest(platform=platform), \
                    patch.object(common, "os", SimpleNamespace(name=platform, replace=legacy)), \
                    patch.object(common, "_windows_replace") as native:
                common._atomic_replace("source", "target")
                if platform == "nt":
                    native.assert_called_once_with("source", "target")
                    legacy.assert_not_called()
                else:
                    legacy.assert_called_once_with("source", "target")
                    native.assert_not_called()
