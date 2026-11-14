"""Job discovery and cooperative compare-and-swap writes; no database."""
import io
import contextlib
import threading
import os
from pathlib import Path
import re
import shutil
import uuid
from collections.abc import Mapping
from datetime import datetime, timezone

from ruamel.yaml import YAML
from runner.common import ManagerError, atomic_write, contained, digest, identifier, lock, now, private_mkdir, read_json, write_json

INTERVAL_SECONDS = {"minutes": 60, "hours": 3600, "days": 86400}
MAX_INTERVAL_SECONDS = 2147483647


def yaml_engine():
    parser = YAML(typ="rt")
    parser.version = (1, 2)
    parser.allow_duplicate_keys = False
    parser.preserve_quotes = True
    return parser


def load_yaml(text):
    if len(text.encode("utf-8")) > 131072:
        raise ManagerError("YAML은 128 KiB 이하여야 합니다.")
    parser = yaml_engine()
    try:
        # No aliases, custom tags or merge keys: only ordinary JSON-like data.
        for token in parser.scan(text):
            if type(token).__name__ in ("AliasToken", "AnchorToken", "TagToken"):
                raise ManagerError("YAML 별칭·앵커·태그는 허용하지 않습니다.")
        value = parser.load(text)
    except ManagerError:
        raise
    except Exception as exc:
        raise ManagerError("YAML 구문 오류: " + str(exc))
    return value


def dump_yaml(value):
    out = io.StringIO()
    yaml_engine().dump(value, out)
    return out.getvalue()


def plain(value):
    if isinstance(value, Mapping):
        if any(not isinstance(k, str) for k in value):
            raise ManagerError("YAML 키는 문자열이어야 합니다.")
        return {k: plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [plain(v) for v in value]
    if value is None or type(value) is bool:
        return value
    if isinstance(value, str):
        return str(value)
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        return float(value)
    raise ManagerError("지원하지 않는 YAML 값입니다.")


def required_env_names(config):
    """Optional job.yaml allowlist; absence preserves legacy environment behavior."""
    if "required_env" not in config:
        return None
    names = config["required_env"]
    if (not isinstance(names, list) or len(names) > 100
            or any(not isinstance(name, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name)
                   or name.startswith("SCRIPT_MANAGER_") for name in names)
            or len(names) != len(set(names))):
        raise ManagerError("required_env는 중복 없는 환경변수 이름 배열이어야 합니다.")
    if config.get("env_file"):
        raise ManagerError("required_env와 Job별 env_file은 함께 사용할 수 없습니다.")
    return names


def validate(value, job_id=None):
    if not isinstance(value, Mapping):
        raise ManagerError("Job 정의는 객체여야 합니다.")
    value = plain(value)
    allowed = {"version", "id", "name", "description", "command", "cwd", "env",
               "env_file", "required_env", "timeout_seconds", "schedule", "schedules", "parameters", "report"}
    if set(value) - allowed:
        raise ManagerError("알 수 없는 Job 필드: " + ", ".join(sorted(set(value) - allowed)))
    if type(value.get("version")) is not int or value["version"] != 1:
        raise ManagerError("version은 1이어야 합니다.")
    identifier(value.get("id"))
    if job_id is not None and value["id"] != job_id:
        raise ManagerError("폴더 이름과 Job ID가 일치해야 합니다.")
    if not isinstance(value.get("name"), str) or not 1 <= len(value["name"].strip()) <= 200:
        raise ManagerError("name은 비어 있지 않은 200자 이하 문자열이어야 합니다.")
    if not isinstance(value.get("description", ""), str):
        raise ManagerError("description은 문자열이어야 합니다.")
    cmd = value.get("command")
    if not isinstance(cmd, list) or not cmd or len(cmd) > 100 or any(
        not isinstance(x, str) or "\x00" in x for x in cmd
    ) or not cmd[0]:
        raise ManagerError("command는 실행 파일과 인자의 문자열 배열이어야 합니다.")
    cwd = value.get("cwd", ".")
    if not isinstance(cwd, str) or not cwd or Path(cwd).is_absolute() or ".." in Path(cwd).parts:
        raise ManagerError("cwd는 Job 내부의 상대 경로여야 합니다.")
    timeout = value.get("timeout_seconds", 300)
    if type(timeout) is not int or not 1 <= timeout <= 86400:
        raise ManagerError("timeout_seconds는 1~86400 정수여야 합니다.")
    env = value.get("env", {})
    if not isinstance(env, Mapping) or any(
        not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", k) or
        not isinstance(v, str) or "\x00" in v for k, v in env.items()
    ):
        raise ManagerError("env는 유효한 환경 변수 이름과 문자열 값이어야 합니다.")
    env_file = value.get("env_file")
    if env_file is not None and (
        not isinstance(env_file, str) or not env_file or
        Path(env_file).is_absolute() or ".." in Path(env_file).parts or "\x00" in env_file
    ):
        raise ManagerError("env_file은 Job 내부의 상대 경로여야 합니다.")
    required_env_names(value)
    from runner.parameters import validate_contract
    validate_contract(value)
    if "report" in value:
        from runner.reports import validate_report
        validate_report(value["report"])
    if "schedule" in value and "schedules" in value:
        raise ManagerError("schedule과 schedules를 함께 지정할 수 없습니다.")
    if "schedule" in value:
        validate_legacy_schedule(value["schedule"])
    entries = value.get("schedules", [])
    if not isinstance(entries, list) or len(entries) > 100:
        raise ManagerError("schedules는 최대 100개의 배열이어야 합니다.")
    ids = set()
    for entry in entries:
        validate_schedule(entry)
        if entry["id"] in ids:
            raise ManagerError("Schedule ID는 Job 내에서 고유해야 합니다.")
        ids.add(entry["id"])
    return value


def validate_legacy_schedule(schedule):
    if not isinstance(schedule, Mapping) or set(schedule) - {"enabled", "mode", "times", "weekdays", "interval"}:
        raise ManagerError("schedule에는 enabled, mode, times, weekdays, interval만 허용합니다.")
    if type(schedule.get("enabled")) is not bool:
        raise ManagerError("schedule.enabled는 boolean이어야 합니다.")
    mode = schedule.get("mode", "calendar")
    if mode not in ("calendar", "interval"):
        raise ManagerError("schedule.mode는 calendar 또는 interval이어야 합니다.")
    if mode == "interval":
        if "times" in schedule or "weekdays" in schedule:
            raise ManagerError("간격 실행과 지정 시각 실행은 함께 설정할 수 없습니다.")
        interval = schedule.get("interval")
        if not isinstance(interval, Mapping) or set(interval) != {"value", "unit"}:
            raise ManagerError("schedule.interval에는 value와 unit이 필요합니다.")
        amount, unit = interval["value"], interval["unit"]
        if not isinstance(unit, str) or unit not in INTERVAL_SECONDS:
            raise ManagerError("간격 단위는 minutes, hours, days 중 하나여야 합니다.")
        if type(amount) is not int or not 1 <= amount <= MAX_INTERVAL_SECONDS // INTERVAL_SECONDS[unit]:
            raise ManagerError("간격은 양의 정수이며 초 환산 시 2147483647 이하여야 합니다.")
        return schedule
    if "interval" in schedule:
        raise ManagerError("지정 시각 실행에는 interval을 설정할 수 없습니다.")
    times = schedule.get("times", [])
    if not isinstance(times, list) or len(times) > 24 or any(
        not isinstance(t, str) or not re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", t)
        for t in times
    ) or len(times) != len(set(times)):
        raise ManagerError("times는 중복 없는 HH:MM 배열(최대 24개)이어야 합니다.")
    days = schedule.get("weekdays", [1, 2, 3, 4, 5, 6, 7])
    if not isinstance(days, list) or not days or any(
        type(d) is not int or not 1 <= d <= 7 for d in days
    ) or len(days) != len(set(days)):
        raise ManagerError("weekdays는 1(월)~7(일)의 중복 없는 배열이어야 합니다.")
    if schedule["enabled"] and not times:
        raise ManagerError("예약을 활성화하려면 실행 시간이 필요합니다.")
    return schedule


def validate_schedule(schedule):
    if not isinstance(schedule, Mapping) or set(schedule) - {
        "id", "name", "enabled", "type", "times", "weekdays", "interval_seconds"
    }:
        raise ManagerError("유효한 Schedule 객체가 필요합니다.")
    identifier(schedule.get("id"))
    if not isinstance(schedule.get("name"), str) or not 1 <= len(schedule["name"].strip()) <= 200:
        raise ManagerError("Schedule 이름은 1~200자여야 합니다.")
    trigger = {k: v for k, v in schedule.items() if k not in ("id", "name", "type", "interval_seconds")}
    trigger["mode"] = schedule.get("type")
    if trigger["mode"] == "interval":
        seconds = schedule.get("interval_seconds")
        if type(seconds) is not int or not 1 <= seconds <= MAX_INTERVAL_SECONDS:
            raise ManagerError("interval_seconds는 1~2147483647 정수여야 합니다.")
        # The legacy validator validates exclusivity and calendar values too.
        trigger["interval"] = {"value": 1, "unit": "minutes"}
    elif "interval_seconds" in schedule:
        raise ManagerError("calendar에는 interval_seconds를 지정할 수 없습니다.")
    validate_legacy_schedule(trigger)
    return schedule


def schedules(config):
    """Read compatibility is pure: never write user YAML during discovery."""
    if "schedule" not in config:
        return config.get("schedules", [])
    legacy = config["schedule"]
    entry = {"id": "legacy", "name": "기존 예약", "enabled": legacy["enabled"],
             "type": legacy.get("mode", "calendar")}
    if entry["type"] == "interval":
        entry["interval_seconds"] = legacy["interval"]["value"] * INTERVAL_SECONDS[legacy["interval"]["unit"]]
    else:
        entry["times"] = legacy.get("times", [])
        entry["weekdays"] = legacy.get("weekdays", list(range(1, 8)))
    return [entry]


def schedule_hash(entry):
    import json
    return digest(json.dumps(plain(entry), sort_keys=True, ensure_ascii=False).encode())


def migrate_config(config):
    if "schedule" in config:
        entries = schedules(config)
        # Keep comments attached to the original mapping and unchanged fields.
        legacy = config.pop("schedule")
        legacy.pop("mode", None)
        legacy.pop("interval", None)
        legacy.update(entries[0])
        config["schedules"] = [legacy]
    else:
        config.setdefault("schedules", [])
    return config


def default_job(job_id, name=None):
    import sys
    return {"version": 1, "id": identifier(job_id), "name": name or job_id,
            "description": "", "command": [sys.executable if os.name == "nt" else "python3", "main.py"], "cwd": ".",
            "env": {}, "timeout_seconds": 300, "schedules": []}


class Store:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self._maintenance_local = threading.local()
        self.jobs = contained(self.root, "jobs")
        self.runtime = contained(self.root, "runtime")
        self.jobs.mkdir(parents=True, exist_ok=True)
        private_mkdir(self.runtime, parents=True, exist_ok=True)
        for part in ("locks", "runs", "trash", "schedules", "deployments"):
            private_mkdir(contained(self.runtime, part), exist_ok=True)

    def job_dir(self, job_id):
        return contained(self.jobs, identifier(job_id), True)

    @contextlib.contextmanager
    def maintenance_lock(self, blocking=True):
        # Keep the lock inode through reset; never unlink a held coordination lock.
        depth = getattr(self._maintenance_local, "depth", 0)
        if depth:
            yield
            return
        with lock(contained(self.runtime, "locks/project-maintenance"), blocking):
            self._maintenance_local.depth = 1
            try:
                yield
            finally:
                self._maintenance_local.depth = 0

    @contextlib.contextmanager
    def job_lock(self, job_id, purpose="edit", blocking=True):
        with self.maintenance_lock(blocking):
            with self._job_lock(job_id, purpose, blocking) as fd:
                yield fd

    def _job_lock(self, job_id, purpose="edit", blocking=True):
        path = self.runtime / "locks" / (identifier(job_id) + "." + purpose)
        if os.name != "nt" or purpose != "run":
            return lock(path, blocking)
        import contextlib
        from runner.common import windows_lease_active
        @contextlib.contextmanager
        def guarded():
            with lock(path, blocking) as fd:
                if windows_lease_active(path.with_suffix(".run.active")):
                    raise ManagerError("작업이 실행 중이거나 다른 작업이 진행 중입니다.", 409)
                yield fd
        return guarded()

    def get(self, job_id):
        folder = self.job_dir(job_id)
        path = contained(folder, "job.yaml", True)
        try:
            if path.stat().st_size > 131072:
                raise ManagerError("YAML은 128 KiB 이하여야 합니다.")
            data = path.read_bytes()
            text = data.decode("utf-8")
        except (UnicodeError, OSError) as exc:
            raise ManagerError("Job 설정을 읽을 수 없습니다: " + str(exc))
        config = validate(load_yaml(text), job_id)
        return {"id": job_id, "config": plain(config), "yaml": text, "etag": digest(data)}

    def list(self):
        jobs = []
        for p in sorted(self.jobs.iterdir()):
            if not p.is_dir() or p.name.startswith("."):
                continue
            try:
                jobs.append(self.get(p.name))
            except (ManagerError, OSError) as exc:
                jobs.append({"id": p.name, "error": str(exc)})
        return jobs

    def create(self, config):
        validate(config)
        if "report" in config:
            from runner.reports import Reports
            Reports(self).validate_destination(config["id"], config["report"])
        text = dump_yaml(config)
        validate(load_yaml(text))
        job_id = config["id"]
        with self.job_lock(job_id):
            dest = contained(self.jobs, job_id)
            if dest.exists():
                raise ManagerError("동일한 Job ID가 이미 존재합니다.", 409)
            temp = self.jobs / (".create-" + uuid.uuid4().hex)
            private_mkdir(temp)
            try:
                atomic_write(temp / "job.yaml", text)
                atomic_write(temp / "main.py", 'print("Script Manager sample job completed")\n')
                atomic_write(temp / "README.md", "# " + config["name"] + "\n\nCodex로 스크립트를 수정하세요.\n")
                os.rename(temp, dest)
            finally:
                if temp.exists():
                    shutil.rmtree(temp)
        return self.get(job_id)

    def update(self, job_id, text, etag):
        if not etag:
            raise ManagerError("기존 etag가 필요합니다.", 428)
        validate(load_yaml(text), job_id)
        with self.job_lock(job_id):
            return self._update_locked(job_id, text, etag)

    def _update_locked(self, job_id, text, etag):
        """Caller holds the Job edit lock; preserve CAS and durable backup."""
        validate(load_yaml(text), job_id)
        config = validate(load_yaml(text), job_id)
        if "report" in config:
            from runner.reports import Reports
            Reports(self).validate_destination(job_id, config["report"])
        current = self.get(job_id)
        if current["etag"] != etag:
            raise ManagerError("파일이 변경되었습니다. 현재 파일을 다시 읽어 병합하세요.", 409)
        path = self.job_dir(job_id) / "job.yaml"
        # A durable copy also preserves the last observed external edit.
        backup = self.runtime / "trash" / (job_id + "-" + current["etag"] + ".yaml")
        atomic_write(backup, current["yaml"])
        if digest(path.read_bytes()) != etag:
            raise ManagerError("저장 직전 파일 변경을 감지했습니다.", 409)
        atomic_write(path, text)
        return self.get(job_id)

    def delete(self, job_id, etag):
        from runner.schedule import Scheduler
        with self.job_lock(job_id, "operation"), self.job_lock(job_id, "run", False), self.job_lock(job_id):
            current = self.get(job_id)
            if not etag or current["etag"] != etag:
                raise ManagerError("Job이 변경되었습니다. 다시 읽은 뒤 삭제하세요.", 409)
            if Scheduler(self).has_registration(job_id):
                raise ManagerError("먼저 로컬 스케줄을 해제하세요.", 409)
            # Recoverable removal; never remove remote releases or running data.
            dest = self.runtime / "trash" / (job_id + "-" + uuid.uuid4().hex)
            metadata = dest.with_name(dest.name + ".trash.json")
            write_json(metadata, {"deleted_at": now(), "job_id": job_id, "name": current["config"]["name"]})
            try:
                os.rename(self.job_dir(job_id), dest)
            except Exception:
                metadata.unlink(missing_ok=True)
                raise
            return {"deleted": job_id, "recover_from": str(dest), "trash_id": dest.name}

    def _trash_entry(self, trash_id):
        if not isinstance(trash_id, str):
            raise ManagerError("잘못된 휴지통 ID입니다.")
        match = re.fullmatch(r"([a-z0-9][a-z0-9-]{0,62})-([0-9a-f]{32})", trash_id)
        if not match:
            raise ManagerError("잘못된 휴지통 ID입니다.")
        folder = contained(self.runtime / "trash", trash_id, True)
        if not folder.is_dir():
            raise ManagerError("삭제된 Job 폴더가 없습니다.", 404)
        job_id = match.group(1)
        metadata = {}
        try:
            metadata = read_json(contained(self.runtime / "trash", trash_id + ".trash.json"), {})
            if not isinstance(metadata, dict) or metadata.get("job_id") != job_id:
                metadata = {}
            if metadata:
                datetime.fromisoformat(metadata["deleted_at"])
        except (ValueError, TypeError, KeyError, OSError, ManagerError):
            metadata = {}
        result = {"trash_id": trash_id, "job_id": job_id, "name": job_id,
                  "deleted_at": metadata.get("deleted_at") or datetime.fromtimestamp(
                      folder.stat().st_ctime, timezone.utc).isoformat(),
                  "deleted_at_estimated": not bool(metadata)}
        try:
            path = contained(folder, "job.yaml", True)
            if path.stat().st_size > 131072:
                raise ManagerError("YAML은 128 KiB 이하여야 합니다.")
            config = validate(load_yaml(path.read_text()), job_id)
            result["name"] = config["name"]
        except (ManagerError, OSError, UnicodeError) as exc:
            result["error"] = str(exc)
        return result

    def trash(self):
        entries = []
        for folder in (self.runtime / "trash").iterdir():
            if folder.is_symlink() or not folder.is_dir():
                continue
            try:
                entries.append(self._trash_entry(folder.name))
            except (ManagerError, OSError):
                continue
        return sorted(entries, key=lambda entry: entry["deleted_at"], reverse=True)

    def restore(self, trash_id):
        entry = self._trash_entry(trash_id)
        job_id = entry["job_id"]
        with self.job_lock(job_id, "operation"), self.job_lock(job_id, "run", False), self.job_lock(job_id):
            entry = self._trash_entry(trash_id)
            if entry.get("error"):
                raise ManagerError("삭제된 Job을 검증할 수 없습니다: " + entry["error"])
            dest = contained(self.jobs, job_id)
            if dest.exists():
                raise ManagerError("동일 ID의 Job이 이미 존재합니다. 기존 Job을 보존했으며 복구하지 않았습니다.", 409)
            os.rename(contained(self.runtime / "trash", trash_id, True), dest)
            # A leftover metadata file is harmless and never treated as a deleted Job.
            try:
                contained(self.runtime / "trash", trash_id + ".trash.json").unlink(missing_ok=True)
            except OSError:
                pass
            return self.get(job_id)

    def update_fields(self, job_id, fields, etag):
        if not isinstance(fields, Mapping) or set(fields) - {
            "name", "description", "command", "cwd", "env", "env_file", "required_env", "timeout_seconds", "report"
        }:
            raise ManagerError("Job 실행 설정 필드만 수정할 수 있습니다.")
        current = self.get(job_id)
        config = load_yaml(current["yaml"])
        config.update(fields)
        text = dump_yaml(config)
        preamble = re.match(r"\A(?:[ \t]*(?:#[^\r\n]*)?\r?\n)*(?=%YAML)", current["yaml"])
        if preamble:
            text = preamble.group() + text
        return self.update(job_id, text, etag)

    def update_schedule(self, job_id, schedule, etag):
        if not isinstance(schedule, Mapping):
            raise ManagerError("schedule 객체가 필요합니다.")
        current = self.get(job_id)
        config = load_yaml(current["yaml"])
        if config.get("schedules"):
            raise ManagerError("복수 예약은 Schedule ID로 수정하세요.", 409)
        config.pop("schedules", None)
        config["schedule"] = schedule
        validate(config, job_id)
        text = dump_yaml(config)
        # ruamel retains ordinary comments but drops comments before a YAML directive.
        preamble = re.match(r"\A(?:[ \t]*(?:#[^\r\n]*)?\r?\n)*(?=%YAML)", current["yaml"])
        if preamble:
            text = preamble.group() + text
        # The shared update path performs validation, locking, etag CAS and atomic save.
        return self.update(job_id, text, etag)
