"""Small filesystem primitives shared by the local manager."""
import contextlib
import os
if os.name != "nt":
    import fcntl
else:
    import msvcrt
import hashlib
import json
from pathlib import Path
import re
import shutil
import tempfile
import time
import uuid
from datetime import datetime, timezone


class ManagerError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def private_mkdir(path, *, parents=False, exist_ok=False):
    """Create private data dirs; Windows privacy comes from the parent's ACL.

    Python 3.13's Windows 0700 creates a protected DACL tied to the creator,
    preventing inheritance needed by sandbox and ordinary-user processes.
    Other modes are ignored on Windows: 0777 requests normal ACL inheritance,
    NOT an Everyone grant. Never chmod or repair an existing directory here.
    """
    path = Path(path)
    try:
        path.mkdir(mode=0o777 if os.name == "nt" else 0o700,
                   parents=parents, exist_ok=exist_ok)
    except PermissionError as exc:
        if os.name != "nt":
            raise
        raise ManagerError(
            "디렉터리 접근 거부: " + str(path) +
            ". 기존 데이터와 ACL은 변경하지 않았습니다. 실행 계정과 부모/기존 디렉터리 ACL을 "
            "확인하세요. INSTALL.md의 Windows 런타임 ACL 복구 절차를 따르세요.", 403) from exc


@contextlib.contextmanager
def private_temporary_directory(parent):
    # tempfile.mkdtemp/TemporaryDirectory also use 0700 on Windows Python 3.13.
    # Exclusive creation keeps an existing path out of this cleanup scope.
    path = Path(parent) / (".tmp-" + uuid.uuid4().hex)
    private_mkdir(path)
    try:
        yield path
    finally:
        shutil.rmtree(path)


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", value):
        raise ManagerError("ID는 영문 소문자·숫자·하이픈으로 1~63자여야 합니다.")
    return value


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def contained(base, relative, must_exist=False):
    base = Path(base).resolve()
    p = Path(relative)
    if p.is_absolute() or ".." in p.parts or "\x00" in str(p):
        raise ManagerError("상대 경로만 사용할 수 있습니다.")
    path = base / p
    cursor = path
    while cursor != base:
        if cursor.is_symlink():
            raise ManagerError("심볼릭 링크는 허용하지 않습니다.")
        cursor = cursor.parent
    if not path.resolve().is_relative_to(base):
        raise ManagerError("허용된 디렉터리 밖의 경로입니다.")
    if must_exist and not path.exists():
        raise ManagerError("파일 또는 디렉터리가 없습니다.", 404)
    return path


@contextlib.contextmanager
def lock(path, blocking=True):
    path = Path(path)
    if path.is_symlink():
        raise ManagerError("잠금 파일이 심볼릭 링크입니다.")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(path), os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        if os.name == "nt":
            os.lseek(fd, 0, os.SEEK_SET)
            if os.fstat(fd).st_size == 0:
                os.write(fd, b"\0")
            while True:
                try:
                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                    break
                except OSError as exc:
                    if getattr(exc, "winerror", None) not in (33, 36) and exc.errno not in (11, 13):
                        raise
                    if not blocking:
                        raise ManagerError("작업이 실행 중이거나 다른 작업이 진행 중입니다.", 409) from exc
                    time.sleep(0.05)
        else:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
            except BlockingIOError as exc:
                raise ManagerError("작업이 실행 중이거나 다른 작업이 진행 중입니다.", 409) from exc
        yield fd
    finally:
        if os.name == "nt":
            try:
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
        os.close(fd)


def atomic_write(path, data, mode=0o600):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ManagerError("심볼릭 링크에 저장할 수 없습니다.")
    if isinstance(data, str):
        data = data.encode("utf-8")
    fd, tmp = tempfile.mkstemp(prefix="." + path.name + ".", dir=path.parent)
    try:
        if os.name != "nt":
            os.fchmod(fd, mode)
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        if os.name != "nt":
            parent = os.open(str(path.parent), os.O_RDONLY)
            try:
                os.fsync(parent)
            finally:
                os.close(parent)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def write_json(path, value):
    atomic_write(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text())
    except FileNotFoundError:
        return default


def windows_pid_alive(pid):
    if not isinstance(pid, int) or pid <= 0:
        return False
    import ctypes
    kernel = ctypes.windll.kernel32
    kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        return kernel.GetLastError() == 5  # Access denied: do not remove another process's lease.
    try:
        code = ctypes.c_ulong()
        return bool(kernel.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259
    finally:
        kernel.CloseHandle(handle)


def windows_lease_active(path):
    lease = read_json(path)
    if lease is None:
        return False
    if windows_pid_alive(lease.get("pid")) or time.time() - lease.get("created", 0) < 30:
        return True
    Path(path).unlink(missing_ok=True)
    return False
