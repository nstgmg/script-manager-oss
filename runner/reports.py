"""Offline JSON reports. No Dashboard, Job code, network, or third-party dependency."""
import hashlib
import html
import json
import math
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import stat

from runner.common import ManagerError, atomic_write, contained, identifier, lock, now, read_json, write_json

MAX_SOURCE_BYTES = 10 * 1024 * 1024
MAX_DEPTH = 64
MAX_NODES = 200000
# Reports may use project-relative exports or explicit native absolute directories.
WINDOWS_RESERVED = {"CON", "PRN", "AUX", "NUL", *[f"COM{i}" for i in range(1, 10)], *[f"LPT{i}" for i in range(1, 10)]}
PROTECTED = {"jobs", "runtime", "deployments", "workspace", "runner", "dashboard", "tests", "docs", "scripts"}


def relative(value, label):
    if (not isinstance(value, str) or not value or len(value) > 1024
            or any(c in value for c in '\\:<>"|?*') or any(ord(c) < 32 for c in value)
            or Path(value).is_absolute() or any(p in ("", ".", "..") or p.startswith(".")
                or p.endswith((".", " ")) or p.split(".")[0].rstrip().upper() in WINDOWS_RESERVED
                for p in value.split("/"))):
        raise ManagerError(label + "은 숨김 경로·상위 경로 없는 프로젝트 상대 경로여야 합니다.")
    return value


def output_directory(value):
    """Parse a local directory without resolving or expanding user input.

    Recognize foreign absolute paths so they cannot silently become relative
    filenames on another OS. UNC/device namespaces are deliberately not local
    report destinations. Source paths keep the stricter relative-only contract.
    """
    if not isinstance(value, str) or not value or len(value) > 1024 or any(ord(c) < 32 for c in value):
        raise ManagerError("report.output_dir는 유효한 로컬 폴더 경로여야 합니다.")
    if value.startswith(("\\\\", "//")):
        raise ManagerError("보고서에 UNC·네트워크·장치 경로는 사용할 수 없습니다.")
    windows = bool(re.match(r"^[A-Za-z]:", value)) or "\\" in value
    if windows:
        parsed = PureWindowsPath(value)
        if parsed.drive and (not re.fullmatch(r"[A-Za-z]:", parsed.drive) or not parsed.is_absolute()):
            raise ManagerError("Windows 보고서 절대 경로에는 드라이브와 루트가 모두 필요합니다.")
        if parsed.root and not parsed.drive:
            raise ManagerError("드라이브 없는 Windows 루트 경로는 사용할 수 없습니다.")
        tail = value[len(parsed.anchor):] if parsed.is_absolute() else value
        pieces = re.split(r"[\\/]", tail.rstrip("\\/")) if tail.rstrip("\\/") else []
    else:
        parsed = PurePosixPath(value)
        tail = value[1:] if parsed.is_absolute() else value
        pieces = tail.rstrip("/").split("/") if tail.rstrip("/") else []
    if any(p in ("", ".", "..") or p.endswith((".", " "))
           or any(c in p for c in '\\:<>"|?*') or p.split(".")[0].rstrip().upper() in WINDOWS_RESERVED
           or (not parsed.is_absolute() and p.startswith(".")) for p in pieces):
        raise ManagerError("report.output_dir에 상위 경로·모호한 경로·예약 이름을 사용할 수 없습니다.")
    return parsed


def reject_links(path):
    # Check every existing component before resolve(). Windows junctions and
    # other reparse points are links too, including on Python before is_junction.
    for part in (path, *path.parents):
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        except NotADirectoryError:
            raise ManagerError("보고서 저장 경로의 상위 항목이 디렉터리가 아닙니다.") from None
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ManagerError("보고서 경로에 심볼릭 링크·junction을 사용할 수 없습니다.")


def validate_report(value):
    if not isinstance(value, dict) or set(value) - {"enabled", "source", "filename", "output_dir"}:
        raise ManagerError("report에는 enabled, source, filename, output_dir만 허용합니다.")
    if type(value.get("enabled", False)) is not bool:
        raise ManagerError("report.enabled는 boolean이어야 합니다.")
    source = value.get("source")
    if "source" in value:
        relative(source, "report.source")
        if not source.lower().endswith(".json"):
            raise ManagerError("report.source는 Output 내부 JSON 파일이어야 합니다.")
    elif value.get("enabled", False):
        raise ManagerError("보고서를 활성화하려면 report.source를 명시하세요.")
    filename = value.get("filename")
    if "filename" in value:
        if (not isinstance(filename, str) or len(filename.encode("utf-8")) > 200
                or not re.fullmatch(r"[^<>:\"/\\|?*\s][^<>:\"/\\|?*]*\.html", filename)
                or any(ord(c) < 32 for c in filename)
                or filename.startswith(".") or filename.endswith(" ")
                or filename.split(".")[0].rstrip().upper() in WINDOWS_RESERVED):
            raise ManagerError("report.filename은 경로 없는 안전한 .html 파일명(200 bytes 이하)이어야 합니다.")
    output_dir = value.get("output_dir", "default")
    parsed = output_directory(output_dir)
    if not parsed.is_absolute() and parsed.parts[0].lower() in PROTECTED:
        raise ManagerError("보고서는 코드·Output·State·Workspace·배포 경로에 저장할 수 없습니다.")
    return value


def destination(root, job_id, settings):
    identifier(job_id)
    validate_report(settings)
    directory = settings.get("output_dir", "default")
    parsed = output_directory("reports" if directory == "default" else directory)
    if (isinstance(parsed, PureWindowsPath) and os.name != "nt"
            or isinstance(parsed, PurePosixPath) and parsed.is_absolute() and os.name == "nt"):
        raise ManagerError("report.output_dir의 절대 경로 형식이 현재 운영체제와 다릅니다.")
    root = Path(root).resolve()
    folder = Path(str(parsed)) if parsed.is_absolute() else root / str(parsed)
    target = folder / settings.get("filename", job_id + ".html")
    reject_links(target)
    # An absolute spelling must not bypass protection for project-managed data.
    root_parts = tuple(p.casefold() for p in root.parts)
    target_parts = tuple(p.casefold() for p in target.parts)
    if target_parts[:len(root_parts)] == root_parts:
        first = target_parts[len(root_parts)]
        if first in PROTECTED or first.startswith("."):
            raise ManagerError("보고서는 코드·Output·State·Workspace·배포 경로에 저장할 수 없습니다.")
    return target


def marker(job_id):
    return ("<!-- script-manager-report:" + identifier(job_id) + " -->\n").encode()


def check_target(path, job_id):
    if path.exists():
        if not path.is_file() or path.stat().st_nlink != 1:
            raise ManagerError("보고서 대상은 링크 없는 일반 파일이어야 합니다.", 409)
        with path.open("rb") as file:
            if file.read(len(marker(job_id))) != marker(job_id):
                raise ManagerError("보고서 경로가 다른 Job 또는 기존 파일과 충돌합니다.", 409)


def load_source(source):
    """Bound reads as well as stat checks; never include source data in errors."""
    source = Path(source)
    if source.is_symlink() or not source.is_file():
        raise ManagerError("보고서 원본은 링크 없는 일반 JSON 파일이어야 합니다.")
    fd = os.open(str(source), os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    with os.fdopen(fd, "rb") as file:
        info = os.fstat(file.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_SOURCE_BYTES:
            raise ManagerError("보고서 JSON은 일반 파일이며 10 MiB 이하여야 합니다.", 413)
        raw = file.read(MAX_SOURCE_BYTES + 1)
    if len(raw) > MAX_SOURCE_BYTES:
        raise ManagerError("보고서 JSON은 10 MiB 이하여야 합니다.", 413)
    try:
        text = raw.decode("utf-8-sig")
        def invalid_constant(_):
            raise ValueError()
        data = json.loads(text, parse_constant=invalid_constant)
        stack, count = [(data, 0)], 0
        while stack:
            value, depth = stack.pop()
            count += 1
            if count > MAX_NODES or depth > MAX_DEPTH:
                raise ManagerError("보고서 JSON은 깊이 64·노드 200,000개 이하여야 합니다.", 413)
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError()
            if isinstance(value, dict):
                stack.extend((v, depth + 1) for v in value.values())
            elif isinstance(value, list):
                stack.extend((v, depth + 1) for v in value)
    except (ValueError, UnicodeError, RecursionError):
        raise ManagerError("보고서 원본은 유효한 UTF-8 JSON이어야 합니다.") from None
    return text, data


def render_html(source, *, job_id, title=None, run_id=None, generated_at=None):
    """Return a complete standalone document; original JSON copy retains number precision."""
    raw, data = load_source(source)
    timestamp = generated_at or now()
    template = Path(__file__).with_name("report_template.html").read_text(encoding="utf-8")
    # The payload is a JSON string, not executable JS or HTML. Escape HTML parser delimiters.
    payload = json.dumps(raw, ensure_ascii=True).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    values = {"TITLE": html.escape(title or job_id), "JOB": html.escape(job_id),
              "RUN": html.escape(run_id or "manual"), "SOURCE": html.escape(Path(source).name),
              "TIME": html.escape(timestamp), "PAYLOAD": payload}
    # Single substitution: data containing template tokens must remain untouched.
    body = re.sub(r"@@(TITLE|JOB|RUN|SOURCE|TIME|PAYLOAD)@@", lambda m: values[m[1]], template)
    return marker(job_id) + body.encode("utf-8"), {"generated_at": timestamp,
        "count": len(data) if isinstance(data, (list, dict)) else 1,
        "source_bytes": len(raw.encode("utf-8"))}


class Reports:
    def __init__(self, store):
        self.store = store

    def validate_destination(self, job_id, settings):
        target = destination(self.store.root, job_id, settings)
        check_target(target, job_id)
        parent = target.parent
        while not parent.exists():
            parent = parent.parent
        if not parent.is_dir():
            raise ManagerError("보고서 저장 경로의 상위 항목이 디렉터리가 아닙니다.")
        if not os.access(parent, os.W_OK | os.X_OK):
            raise ManagerError("보고서 저장 폴더에 쓰기 권한이 없습니다.")
        for item in self.store.list():
            other = item.get("config", {}).get("report", {})
            if item["id"] != job_id and other.get("enabled", False):
                if str(destination(self.store.root, item["id"], other)).casefold() == str(target).casefold():
                    raise ManagerError("보고서 경로가 다른 활성 Job과 충돌합니다.", 409)
        return target

    def metadata_path(self, job_id):
        return contained(self.store.root, "runtime/reports/" + identifier(job_id) + ".json")

    def generate(self, job_id, source, *, settings=None, run_id=None, title=None):
        config = self.store.get(job_id)["config"] if settings is None or title is None else {}
        settings = config.get("report", {}) if settings is None else settings
        target = destination(self.store.root, job_id, settings)
        content, info = render_html(source, job_id=job_id, title=title or config.get("name", job_id), run_id=run_id)
        info.update(state="succeeded", job_id=job_id, run_id=run_id,
                    path=str(target), source=str(source), sha256=hashlib.sha256(content).hexdigest())
        with lock(contained(self.store.root, "runtime/locks/reports.render")):
            self.validate_destination(job_id, settings)
            target.parent.mkdir(parents=True, exist_ok=True)
            # Recheck after mkdir; reject symlinked ancestors and unowned destination files.
            target = destination(self.store.root, job_id, settings)
            check_target(target, job_id)
            metadata = self.metadata_path(job_id)
            old_metadata = metadata.read_bytes() if metadata.exists() else None
            publishing = False
            try:
                # Save the index first. If this fails, the last HTML is untouched.
                # Readers share this lock and cannot observe the intermediate index.
                write_json(metadata, info)
                publishing = True
                atomic_write(target, content)
            except Exception as exc:
                # atomic_write fsyncs the directory *after* os.replace. A directory
                # fsync error at that point is a durability warning, not a failed
                # conversion: the complete new HTML has already been committed.
                if publishing and isinstance(exc, OSError):
                    try:
                        if target.read_bytes() == content:
                            info["warning"] = "HTML 교체 완료 후 디렉터리 동기화에 실패했습니다: " + str(exc)
                            return info
                    except OSError:
                        pass
                if old_metadata is not None:
                    atomic_write(metadata, old_metadata)
                elif metadata.exists():
                    metadata.unlink()
                raise
        return info

    def generate_run(self, job_id, record):
        from runner.lifecycle import Lifecycle
        settings = record["config"].get("report", {})
        validate_report(settings)
        if not settings.get("enabled", False):
            return {"state": "disabled"}
        output = Lifecycle(self.store).paths(job_id, record["id"])["SCRIPT_MANAGER_OUTPUT_DIR"]
        source = contained(output, settings["source"], True)
        return self.generate(job_id, source, settings=settings, run_id=record["id"], title=record["config"]["name"])

    def get(self, job_id):
        with lock(contained(self.store.root, "runtime/locks/reports.render")):
            return self._get(job_id)

    def _get(self, job_id):
        self.store.get(job_id)
        info = read_json(self.metadata_path(job_id))
        if info is None:
            return {"state": "missing", "job_id": job_id}
        path = Path(info["path"])
        checked = destination(self.store.root, job_id, {"output_dir": str(path.parent), "filename": path.name})
        check_target(checked, job_id)
        return {**info, "available": checked.is_file()}

    def document(self, job_id):
        with lock(contained(self.store.root, "runtime/locks/reports.render")):
            info = self._get(job_id)
            if not info.get("available"):
                raise ManagerError("생성된 보고서가 없습니다.", 404)
            path = Path(info["path"])
            if path.stat().st_size > MAX_SOURCE_BYTES * 7 + 1024 * 1024:
                raise ManagerError("보고서 파일 크기 제한을 초과했습니다.", 413)
            data = path.read_bytes()
            if hashlib.sha256(data).hexdigest() != info["sha256"]:
                raise ManagerError("보고서 파일이 외부에서 변경되었습니다. 다시 생성하세요.", 409)
            return data
