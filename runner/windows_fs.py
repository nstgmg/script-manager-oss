"""Confined NTFS I/O. No pathname fallback for unsupported native operations.

Open each component relative to a verified directory handle. Directory handles
deny write/delete sharing until the operation finishes; leaf readers retain
share-delete for atomic publication. Reparse points are never followed.
"""
from contextlib import contextmanager, ExitStack
import ctypes
from ctypes import wintypes
import json
import logging
import os
from pathlib import Path
import stat
from types import SimpleNamespace

from runner.common import ManagerError

if os.name != "nt":
    raise ImportError("Windows filesystem backend is Windows-only")

import msvcrt

REPARSE = 0x400
DIRECTORY = 0x10
APPROVAL_SCHEMA = 2
_EPOCH_TICKS = 116444736000000000
_LOG = logging.getLogger(__name__)


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


class StandardInfo(ctypes.Structure):
    _fields_ = [("allocation_size", ctypes.c_int64), ("size", ctypes.c_int64),
                ("links", wintypes.DWORD), ("delete_pending", ctypes.c_ubyte),
                ("directory", ctypes.c_ubyte)]


class IdInfo(ctypes.Structure):
    _fields_ = [("volume", ctypes.c_uint64), ("file_id", ctypes.c_ubyte * 16)]


kernel = ctypes.WinDLL("kernel32", use_last_error=True)
native = ctypes.WinDLL("ntdll")
kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                              ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
kernel.CreateFileW.restype = wintypes.HANDLE
kernel.CloseHandle.argtypes = [wintypes.HANDLE]
kernel.CloseHandle.restype = wintypes.BOOL
kernel.GetFileInformationByHandle.argtypes = [wintypes.HANDLE, ctypes.POINTER(FileInfo)]
kernel.GetFileInformationByHandle.restype = wintypes.BOOL
kernel.GetFileInformationByHandleEx.argtypes = [wintypes.HANDLE, ctypes.c_int,
                                               ctypes.c_void_p, wintypes.DWORD]
kernel.GetFileInformationByHandleEx.restype = wintypes.BOOL
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
                    or (directory is not None and bool(info.attributes & DIRECTORY) != directory)):
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
        """One handle-based representation, independent of Python stat quirks.

        ctime's compatibility slot means creation time; ChangeTime is separate.
        Native 100ns timestamps and the complete 128-bit ID are never rounded
        or replaced by a pathname/legacy-ID query on failure.
        """
        self.info()
        basic, standard, identity = BasicInfo(), StandardInfo(), IdInfo()
        for info_class, value in ((0, basic), (1, standard), (18, identity)):
            _check(kernel.GetFileInformationByHandleEx(self.handle, info_class,
                                                      ctypes.byref(value), ctypes.sizeof(value)))
        is_dir = bool(basic.attributes & DIRECTORY)
        if basic.attributes & REPARSE or is_dir != bool(standard.directory):
            raise ManagerError("Unsafe or inconsistent handle metadata: " + str(self.path), 409)
        mode = (stat.S_IFDIR | 0o111) if is_dir else stat.S_IFREG
        mode |= 0o444 if basic.attributes & 1 else 0o666
        return SimpleNamespace(st_ino=int.from_bytes(bytes(identity.file_id), "little"),
            st_dev=identity.volume, st_mode=mode, st_size=standard.size,
            st_mtime_ns=_ns(basic.written), st_ctime_ns=_ns(basic.created),
            st_birthtime_ns=_ns(basic.created), st_file_attributes=basic.attributes,
            creation_time=basic.created, change_time=basic.changed, last_write_time=basic.written,
            entry_type="directory" if is_dir else "file", delete_pending=bool(standard.delete_pending))

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
    def child(self, name, directory=False, create=False, delete=False, metadata=False):
        name = _name(name)
        buffer = ctypes.create_unicode_buffer(name)
        length = len(name.encode("utf-16-le"))
        if length > 65532:
            raise ManagerError("Windows path component too long", 409)
        string = UnicodeString(length, length + 2, ctypes.cast(buffer, wintypes.LPWSTR))
        attributes = ObjectAttributes(ctypes.sizeof(ObjectAttributes), self.handle,
                                      ctypes.pointer(string), 0x1040, None, None)
        handle, status = wintypes.HANDLE(), IoStatus()
        access = 0x100080 if directory or delete or metadata else 0x80100000
        if create and not directory:
            access = 0x40100080
        if delete:
            access |= 0x10000
        # Strict sharing pins ancestor names and deletion identities. A normal
        # reader's leaf may be atomically replaced while its old handle survives.
        sharing = 1 if directory or delete or create or metadata else 7
        disposition = (3 if directory else 2) if create else 1
        options = 0x200020 | (0 if directory is None else 1 if directory else 0x40)
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


def _ns(ticks):
    return (ticks - _EPOCH_TICKS) * 100


def approval_record(value, relative):
    # A held atomic reader may consume its old, delete-pending snapshot. Such
    # a handle must never supply a fresh deletion approval, however.
    if value.delete_pending:
        _reject(relative, {"DeletePending": {"approved": False, "current": True}},
                "Delete-pending entry cannot authorize deletion")
    # Keep the first seven slots for byte counts and POSIX-independent callers.
    return [str(relative), value.st_ino, value.st_mode, value.st_size,
            value.st_mtime_ns, value.st_dev, value.st_ctime_ns,
            {"schema": APPROVAL_SCHEMA, "CreationTime": value.creation_time,
             "ChangeTime": value.change_time, "LastWriteTime": value.last_write_time,
             "Attributes": value.st_file_attributes, "Type": value.entry_type}]


def _reject(path, differences, message):
    detail = {"path": str(path), "differences": differences}
    encoded = json.dumps(detail, ensure_ascii=True, sort_keys=True)
    _LOG.warning("Windows approval rejected: %s", encoded)
    error = ManagerError(message + ": " + encoded, 409)
    error.approval_diagnostics = detail
    raise error


def validate_approval(record):
    """A legacy seven-slot record cannot authorize any deletion, even a dir."""
    extra = record[7] if isinstance(record, (list, tuple)) and len(record) == 8 else None
    observed = extra.get("schema") if isinstance(extra, dict) else None
    path = record[0] if isinstance(record, (list, tuple)) and record else "<unknown>"
    if observed != APPROVAL_SCHEMA or type(observed) is not int:
        _reject(path, {"schema": {"approved": observed, "current": APPROVAL_SCHEMA}},
                "Windows approval schema changed; preview and confirmation required")
    keys = {"schema", "CreationTime", "ChangeTime", "LastWriteTime", "Attributes", "Type"}
    if (set(extra) != keys or not isinstance(record[0], str)
            or any(type(item) is not int for item in record[1:7])
            or any(type(extra[key]) is not int for key in keys - {"Type"})
            or not (stat.S_ISDIR(record[2]) or stat.S_ISREG(record[2]))
            or extra["Type"] not in ("file", "directory")
            or extra["Type"] != ("directory" if stat.S_ISDIR(record[2]) else "file")
            or extra["Attributes"] & REPARSE):
        _reject(path, {"record": {"approved": "invalid", "current": "schema 2 metadata"}},
                "Invalid Windows approval")
    differences = {}
    for label, index in (("LastWriteTime", 4), ("CreationTime", 6)):
        if record[index] != _ns(extra[label]):
            differences[label + "_ns"] = {"approved": record[index], "current": _ns(extra[label])}
    if differences:
        _reject(path, differences, "Inconsistent Windows approval")


def _require_matches(value, record, directory, message, identity_anchor=False):
    # Internal root/parent identity anchors are not deletion approvals. Existing
    # callers can supply their seven-slot identity-only anchors; every actual
    # deletion record must still carry schema 2, including directory records.
    if not identity_anchor:
        validate_approval(record)
    elif (not isinstance(record, (list, tuple)) or len(record) not in (7, 8)
          or any(type(item) is not int for item in record[1:7])):
        _reject("<anchor>", {"IdentityAnchor": {"approved": "invalid", "current": "directory identity"}}, message)
    actual = approval_record(value, record[0])
    labels = {1: "FileId", 2: "Mode", 3: "Size", 4: "LastWriteTime_ns",
              5: "Volume", 6: "CreationTime_ns"}
    differences = {labels[i]: {"approved": record[i], "current": actual[i]}
                   for i in ((1, 2, 5) if directory else range(1, 7)) if actual[i] != record[i]}
    if not directory:
        for key in ("Type", "Attributes", "LastWriteTime", "CreationTime", "ChangeTime"):
            if actual[7][key] != record[7][key]:
                differences[key] = {"approved": record[7][key], "current": actual[7][key]}
    if differences:
        _reject(record[0], differences, message)


def inventory(root, target):
    """Metadata-only inventory through pinned handles; no file content reads."""
    relative = Path(target).relative_to(root)
    records = []
    with directory(root) as parent, ExitStack() as parents:
        device = parent.stat().st_dev
        for part in relative.parts[:-1]:
            parent = parents.enter_context(parent.child(part, directory=True, metadata=True))
        with parent.child(relative.name, directory=None, metadata=True) as entry:
            def visit(current, rel):
                value = current.stat()
                if value.st_dev != device:
                    raise ManagerError("Volume boundary refused: " + str(rel), 409)
                if current.path.is_mount():
                    raise ManagerError("Mounted data preserved: " + str(rel), 409)
                records.append(approval_record(value, rel))
                if stat.S_ISDIR(value.st_mode):
                    def failed(exc):
                        raise exc
                    # Consume only the pinned directory's first yield. Never
                    # let pathname os.walk descend into a child: open it
                    # no-reparse and pin it before the next enumeration.
                    walker = os.walk(current.path, followlinks=False, onerror=failed)
                    try:
                        for base, dirs, files in walker:
                            for name in sorted(dirs + files):
                                with current.child(name, directory=None, metadata=True) as child:
                                    visit(child, rel / name)
                            break
                    finally:
                        walker.close()
            visit(entry, relative)
    # All marker names were inspected without following any reparse point.
    names = {record[0] for record in records}
    for record in records:
        if stat.S_ISDIR(record[2]) and any(str(Path(record[0]) / marker) in names for marker in
                ("runner/__main__.py", "runtime/installation.json", ".script-manager-installation.json", ".git")):
            raise ManagerError("Nested installation preserved: " + record[0], 409)
    return records


def anchor_record(root, target):
    relative = Path(target).relative_to(root)
    with directory(root) as entry, ExitStack() as parents:
        for part in relative.parts:
            entry = parents.enter_context(entry.child(part, directory=True, metadata=True))
        return approval_record(entry.stat(), str(relative))


def delete_entry(root, relative, record, anchors):
    validate_approval(record)
    parts = Path(relative).parts
    if Path(relative).is_absolute() or not parts:
        raise ManagerError("Relative deletion path required", 409)
    with directory(root) as parent, ExitStack() as stack:
        _require_matches(parent.stat(), anchors["."], True, "Approved root replaced", identity_anchor=True)
        walked = Path()
        for part in parts[:-1]:
            walked /= part
            parent = stack.enter_context(parent.child(part, directory=True))
            _require_matches(parent.stat(), anchors[str(walked)], True, "Approved parent replaced", identity_anchor=True)
        is_directory = stat.S_ISDIR(record[2])
        with parent.child(parts[-1], directory=is_directory, delete=True) as leaf:
            _require_matches(leaf.stat(), record, is_directory, "Approved entry changed")
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
