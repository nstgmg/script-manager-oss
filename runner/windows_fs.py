"""Confined NTFS I/O. No pathname fallback for unsupported native operations.

Open each component relative to a verified directory handle. Directory handles
deny write/delete sharing until the operation finishes; leaf readers retain
share-delete for atomic publication. Reparse points are never followed.
"""
from contextlib import contextmanager, ExitStack
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import stat

from runner.common import ManagerError

if os.name != "nt":
    raise ImportError("Windows filesystem backend is Windows-only")

import msvcrt

REPARSE = 0x400
DIRECTORY = 0x10


class UnicodeString(ctypes.Structure):
    _fields_ = [("Length", wintypes.USHORT), ("MaximumLength", wintypes.USHORT),
                ("Buffer", wintypes.LPWSTR)]


class ObjectAttributes(ctypes.Structure):
    _fields_ = [("Length", wintypes.ULONG), ("RootDirectory", wintypes.HANDLE),
                ("ObjectName", ctypes.POINTER(UnicodeString)), ("Attributes", wintypes.ULONG),
                ("SecurityDescriptor", ctypes.c_void_p), ("SecurityQualityOfService", ctypes.c_void_p)]


class IoStatus(ctypes.Structure):
    _fields_ = [("Status", ctypes.c_void_p), ("Information", ctypes.c_size_t)]


class FileInfo(ctypes.Structure):
    _fields_ = [("attributes", wintypes.DWORD), ("created", wintypes.FILETIME),
                ("accessed", wintypes.FILETIME), ("written", wintypes.FILETIME),
                ("volume", wintypes.DWORD), ("size_high", wintypes.DWORD),
                ("size_low", wintypes.DWORD), ("links", wintypes.DWORD),
                ("index_high", wintypes.DWORD), ("index_low", wintypes.DWORD)]


class BasicInfo(ctypes.Structure):
    _fields_ = [("created", ctypes.c_int64), ("accessed", ctypes.c_int64),
                ("written", ctypes.c_int64), ("changed", ctypes.c_int64),
                ("attributes", wintypes.DWORD)]


kernel = ctypes.WinDLL("kernel32", use_last_error=True)
native = ctypes.WinDLL("ntdll")
kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                              ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
kernel.CreateFileW.restype = wintypes.HANDLE
kernel.CloseHandle.argtypes = [wintypes.HANDLE]
kernel.CloseHandle.restype = wintypes.BOOL
kernel.GetFileInformationByHandle.argtypes = [wintypes.HANDLE, ctypes.POINTER(FileInfo)]
kernel.GetFileInformationByHandle.restype = wintypes.BOOL
kernel.GetFileType.argtypes = [wintypes.HANDLE]
kernel.GetFileType.restype = wintypes.DWORD
kernel.GetDriveTypeW.argtypes = [wintypes.LPCWSTR]
kernel.GetDriveTypeW.restype = wintypes.UINT
kernel.GetVolumeInformationByHandleW.argtypes = [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD),
    wintypes.LPWSTR, wintypes.DWORD]
kernel.GetVolumeInformationByHandleW.restype = wintypes.BOOL
kernel.SetFileInformationByHandle.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
kernel.SetFileInformationByHandle.restype = wintypes.BOOL
kernel.SetFileTime.argtypes = [wintypes.HANDLE, ctypes.c_void_p,
                              ctypes.POINTER(wintypes.FILETIME), ctypes.POINTER(wintypes.FILETIME)]
kernel.SetFileTime.restype = wintypes.BOOL
native.NtCreateFile.argtypes = [ctypes.POINTER(wintypes.HANDLE), wintypes.DWORD,
    ctypes.POINTER(ObjectAttributes), ctypes.POINTER(IoStatus), ctypes.c_void_p,
    wintypes.ULONG, wintypes.ULONG, wintypes.ULONG, wintypes.ULONG, ctypes.c_void_p, wintypes.ULONG]
native.NtCreateFile.restype = wintypes.LONG
native.RtlNtStatusToDosError.argtypes = [wintypes.LONG]
native.RtlNtStatusToDosError.restype = wintypes.ULONG


def _check(ok):
    if not ok:
        raise ctypes.WinError(ctypes.get_last_error())


def _name(name):
    if (not isinstance(name, str) or not name or name in (".", "..")
            or any(c in name for c in "\\/:\x00") or name.endswith((".", " "))):
        raise ManagerError("Unsafe Windows path component", 409)
    return name


class Entry:
    def __init__(self, handle, path, directory, writable=False):
        self.path = path
        self.fd = None
        try:
            info = FileInfo()
            _check(kernel.GetFileInformationByHandle(handle, ctypes.byref(info)))
            if (kernel.GetFileType(handle) != 1 or info.attributes & REPARSE
                    or bool(info.attributes & DIRECTORY) != directory):
                raise ManagerError("Reparse point or unexpected file type refused: " + str(path), 409)
            self.fd = msvcrt.open_osfhandle(handle, (os.O_WRONLY if writable else os.O_RDONLY)
                                          | os.O_BINARY | os.O_NOINHERIT)
        except BaseException:
            kernel.CloseHandle(handle)
            raise

    @property
    def handle(self):
        return msvcrt.get_osfhandle(self.fd)

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def info(self):
        info = FileInfo()
        _check(kernel.GetFileInformationByHandle(self.handle, ctypes.byref(info)))
        if info.attributes & REPARSE:
            raise ManagerError("Reparse point refused", 409)
        return info

    def stat(self):
        self.info()
        return os.fstat(self.fd)

    def read(self, limit):
        if self.stat().st_size > limit:
            raise ValueError("File size limit exceeded")
        chunks, length = [], 0
        while True:
            chunk = os.read(self.fd, min(65536, limit + 1 - length))
            if not chunk:
                return b"".join(chunks)
            chunks.append(chunk)
            length += len(chunk)
            if length > limit:
                raise ValueError("File size limit exceeded")

    def write(self, data):
        view = memoryview(data)
        while view:
            count = os.write(self.fd, view)
            if not count:
                raise OSError("Short snapshot write")
            view = view[count:]

    @contextmanager
    def child(self, name, directory=False, create=False, delete=False):
        name = _name(name)
        buffer = ctypes.create_unicode_buffer(name)
        length = len(name.encode("utf-16-le"))
        if length > 65532:
            raise ManagerError("Windows path component too long", 409)
        string = UnicodeString(length, length + 2, ctypes.cast(buffer, wintypes.LPWSTR))
        attributes = ObjectAttributes(ctypes.sizeof(ObjectAttributes), self.handle,
                                      ctypes.pointer(string), 0x1040, None, None)
        handle, status = wintypes.HANDLE(), IoStatus()
        access = 0x100080 if directory or delete else 0x80100000
        if create and not directory:
            access = 0x40100080
        if delete:
            access |= 0x10000
        # Strict sharing pins ancestor names and deletion identities. A normal
        # reader's leaf may be atomically replaced while its old handle survives.
        sharing = 1 if directory or delete or create else 7
        disposition = (3 if directory else 2) if create else 1
        options = 0x200020 | (1 if directory else 0x40)
        result = native.NtCreateFile(ctypes.byref(handle), access, ctypes.byref(attributes),
            ctypes.byref(status), None, 0, sharing, disposition, options, None, 0)
        if result < 0:
            raise ctypes.WinError(native.RtlNtStatusToDosError(result))
        entry = Entry(handle.value, self.path / name, directory, writable=create and not directory)
        try:
            if entry.info().volume != self.info().volume:
                raise ManagerError("Volume boundary refused", 409)
            yield entry
        finally:
            entry.close()


@contextmanager
def directory(path, create=False):
    path = Path(os.path.abspath(path))
    if not path.drive or path.drive.startswith("\\") or len(path.drive) != 2:
        raise ManagerError("Only local fixed NTFS drive paths are supported", 409)
    if kernel.GetDriveTypeW(path.anchor) != 3:
        raise ManagerError("Fixed NTFS volume required", 409)
    handle = kernel.CreateFileW(path.anchor, 0x100080, 7, None, 3, 0x02200000, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    with ExitStack() as stack:
        anchor = Entry(handle, Path(path.anchor), True)
        stack.callback(anchor.close)
        fs = ctypes.create_unicode_buffer(32)
        _check(kernel.GetVolumeInformationByHandleW(anchor.handle, None, 0, None, None, None, fs, len(fs)))
        if fs.value != "NTFS":
            raise ManagerError("NTFS required; no pathname fallback", 409)
        current = anchor
        for part in path.parts[1:]:
            current = stack.enter_context(current.child(part, directory=True, create=create))
        yield current


def read_beneath(root, relative, limit):
    parts = Path(relative).parts
    if Path(relative).is_absolute() or not parts:
        raise ManagerError("Relative file path required", 409)
    with directory(root) as parent, ExitStack() as stack:
        for part in parts[:-1]:
            parent = stack.enter_context(parent.child(part, directory=True))
        with parent.child(parts[-1]) as leaf:
            return leaf.read(limit)


def _matches(value, record, directory):
    actual = [record[0], value.st_ino, value.st_mode, value.st_size,
              value.st_mtime_ns, value.st_dev, value.st_ctime_ns]
    return all(actual[i] == record[i] for i in ((1, 2, 5) if directory else range(1, 7)))


def delete_entry(root, relative, record, anchors):
    parts = Path(relative).parts
    if Path(relative).is_absolute() or not parts:
        raise ManagerError("Relative deletion path required", 409)
    with directory(root) as parent, ExitStack() as stack:
        if not _matches(parent.stat(), anchors["."], True):
            raise ManagerError("Approved root replaced", 409)
        walked = Path()
        for part in parts[:-1]:
            walked /= part
            parent = stack.enter_context(parent.child(part, directory=True))
            if not _matches(parent.stat(), anchors[str(walked)], True):
                raise ManagerError("Approved parent replaced", 409)
        is_directory = stat.S_ISDIR(record[2])
        with parent.child(parts[-1], directory=is_directory, delete=True) as leaf:
            if not _matches(leaf.stat(), record, is_directory):
                raise ManagerError("Approved entry changed", 409)
            disposition = ctypes.c_ubyte(1)
            _check(kernel.SetFileInformationByHandle(leaf.handle, 4, ctypes.byref(disposition), 1))


def copy_file(source, destination, limit):
    data = source.read(limit)
    destination.write(data)
    info = source.info()
    _check(kernel.SetFileTime(destination.handle, None, ctypes.byref(info.accessed), ctypes.byref(info.written)))
    attributes = BasicInfo(0, 0, 0, 0, 1 if info.attributes & 1 else 0x80)
    _check(kernel.SetFileInformationByHandle(destination.handle, 0, ctypes.byref(attributes), ctypes.sizeof(attributes)))
    return data
