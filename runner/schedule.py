"""Independent macOS LaunchAgents; YAML is the desired state, never a scheduler."""
import hashlib
import os
from pathlib import Path
import platform
import plistlib
import re
import subprocess
import sys
import uuid

from runner.common import ManagerError, atomic_write, contained, digest, identifier, read_json, write_json
from runner.installation import MARKER, metadata
from runner.store import schedules, schedule_hash, migrate_config, load_yaml, dump_yaml, validate, validate_schedule


class Scheduler:
    def __new__(cls, *args, **kwargs):
        if cls is Scheduler and platform.system() == "Windows":
            from runner.windows_schedule import WindowsScheduler
            return super().__new__(WindowsScheduler)
        return super().__new__(cls)

    def __init__(self, store, agents=None, command=None):
        self.store = store
        self.agents = Path(agents) if agents else Path.home() / "Library/LaunchAgents"
        self.command = command or subprocess.run
        self.namespace = hashlib.sha256(str(store.root).encode()).hexdigest()[:12]

    def label(self, job_id, schedule_id=None):
        label = "local.scriptmanager." + self.namespace + "." + identifier(job_id)
        return label + ("." + identifier(schedule_id) if schedule_id is not None else "")

    def state_path(self, job_id, schedule_id=None):
        name = identifier(job_id) + ("." + identifier(schedule_id) if schedule_id is not None else "")
        return contained(self.store.runtime / "schedules", name + ".json")

    def state(self, job_id, schedule_id=None):
        return read_json(self.state_path(job_id, schedule_id), {"applied": False})

    def entry(self, job_id, schedule_id=None, item=None):
        item = item or self.store.get(job_id)
        entries = schedules(item["config"])
        if schedule_id is None and len(entries) != 1:
            raise ManagerError("Schedule ID를 지정하세요.", 400)
        found = next((s for s in entries if schedule_id is None or s["id"] == schedule_id), None)
        if found is None:
            raise ManagerError("Schedule을 찾을 수 없습니다.", 404)
        return found

    def plan(self, job_id, generation=None, schedule_id=None):
        item = self.store.get(job_id)
        entry = self.entry(job_id, schedule_id, item)
        # Old CLI/API remains valid only for legacy YAML. New YAML always uses a Schedule label.
        sid = schedule_id if schedule_id is not None else (None if "schedule" in item["config"] else entry["id"])
        generation = generation or uuid.uuid4().hex
        label = self.label(job_id, sid)
        args = [sys.executable, "-m", "runner", "--root", str(self.store.root), "_scheduled", job_id, generation]
        if sid is not None:
            args.append(sid)
        plist = {
            "Label": label, "ProgramArguments": args,
            "WorkingDirectory": str(Path(__file__).resolve().parent.parent),
            "RunAtLoad": False, "KeepAlive": False, "ProcessType": "Background",
            "EnvironmentVariables": {"PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin")},
            "StandardOutPath": "/dev/null", "StandardErrorPath": "/dev/null",
        }
        plist[MARKER] = metadata(self.store, job_id, sid, generation)
        if entry["type"] == "interval":
            plist["StartInterval"] = entry["interval_seconds"]
        else:
            plist["StartCalendarInterval"] = [
                {"Weekday": day % 7, "Hour": int(t[:2]), "Minute": int(t[3:])}
                for day in entry.get("weekdays", range(1, 8)) for t in entry.get("times", [])]
        plist[MARKER]["definition_sha256"] = digest(plistlib.dumps({k: v for k, v in plist.items() if k != MARKER}))
        return {"enabled": entry["enabled"], "label": label, "schedule_id": sid,
                "generation": generation, "schedule_hash": schedule_hash(entry), "etag": item["etag"],
                "path": str(self.agents / (label + ".plist")), "plist": plistlib.dumps(plist).decode(),
                "timezone": "host-local"}

    def call(self, args, check=True):
        try:
            result = self.command(args, capture_output=True, text=True, timeout=20)
        except (OSError, subprocess.SubprocessError) as exc:
            raise ManagerError("스케줄 명령 실행·관찰 실패: " + str(exc), 502) from exc
        if check and result.returncode:
            raise ManagerError("스케줄 명령 실패: " + result.stderr.strip(), 502)
        return result

    def available(self):
        if platform.system() != "Darwin":
            raise ManagerError("로컬 스케줄 적용은 macOS launchd만 지원합니다.")

    def observed(self, job_id, schedule_id=None):
        state = self.state(job_id, schedule_id)
        path = contained(self.agents, self.label(job_id, schedule_id) + ".plist")
        state.update(file_exists=path.exists(),
                     file_matches=path.is_file() and digest(path.read_bytes()) == state.get("plist_sha256"),
                     supported=platform.system() == "Darwin", loaded=False)
        if state["supported"]:
            result = self.call(["launchctl", "print", "gui/" + str(os.getuid()) + "/" + self.label(job_id, schedule_id)], False)
            state["loaded"] = result.returncode == 0
            if result.returncode not in (0, 113):
                state["observation_error"] = result.stderr.strip() or "launchd 상태를 확인하지 못했습니다."
            disabled = self.call(["launchctl", "print-disabled", "gui/" + str(os.getuid())], False)
            state["os_disabled"] = bool(re.search(r'"' + re.escape(self.label(job_id, schedule_id)) + r'"\s*=>\s*true', disabled.stdout))
            if disabled.returncode:
                state["observation_error"] = disabled.stderr.strip() or "launchd 활성화 상태를 확인하지 못했습니다."
        try:
            item = self.store.get(job_id)
            entry = self.entry(job_id, schedule_id, item)
            state["desired_matches"] = (state.get("schedule_hash") == schedule_hash(entry) if state.get("schedule_hash")
                                          else state.get("etag") == item["etag"]) and not state.get("os_disabled", False)
        except ManagerError:
            state["desired_matches"] = False
        return state

    def known_ids(self, job_id):
        ids = {s["id"] for s in schedules(self.store.get(job_id)["config"])}
        for path in (self.store.runtime / "schedules").glob(identifier(job_id) + ".*.json"):
            sid = path.name[len(job_id) + 1:-5]
            if re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", sid):
                ids.add(sid)
        prefix = self.label(job_id) + "."
        if platform.system() == "Darwin":
            result = self.call(["launchctl", "list"], False)
            if result.returncode:
                raise ManagerError("OS 예약 목록을 확인하지 못했습니다: " + result.stderr.strip(), 502)
            for line in result.stdout.splitlines():
                label = line.split()[-1] if line.split() else ""
                sid = label[len(prefix):] if label.startswith(prefix) else ""
                if re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", sid):
                    ids.add(sid)
        if self.agents.exists():
            for path in self.agents.glob(prefix + "*.plist"):
                sid = path.name[len(prefix):-6]
                if re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", sid):
                    ids.add(sid)
        return ids

    def rows(self, job_id):
        item = self.store.get(job_id)
        entries = {s["id"]: s for s in schedules(item["config"])}
        legacy = self.observed(job_id)
        legacy_present = any(legacy.get(k) for k in ("loaded", "file_exists", "applied", "observation_error"))
        result = []
        for sid in sorted(self.known_ids(job_id)):
            state = self.observed(job_id, sid)
            if sid not in entries and not any(state.get(k) for k in ("loaded", "file_exists", "applied", "observation_error")):
                continue
            if "schedule" in item["config"] and sid == "legacy" and legacy_present:
                state = {**legacy, "legacy_registration": True}
            result.append({"job_id": job_id, "job_name": item["config"]["name"], "etag": item["etag"],
                           "schedule": entries.get(sid, {"id": sid, "name": sid, "enabled": False, "type": "calendar"}),
                           "orphan": sid not in entries, "state": state})
        if legacy_present and "schedule" not in item["config"]:
            result.append({"job_id": job_id, "job_name": item["config"]["name"], "etag": item["etag"],
                           "schedule": {"id": "legacy-registration", "name": "이전 OS 예약", "enabled": False, "type": "calendar"},
                           "orphan": True, "legacy_registration": True, "state": legacy})
        return result

    def has_registration(self, job_id):
        # Include removed YAML entries, old job labels and observation failures.
        for sid in [None, *self.known_ids(job_id)]:
            state = self.observed(job_id, sid)
            if any(state.get(k) for k in ("applied", "file_exists", "loaded", "observation_error")):
                return True
        return False

    def _guard_live(self, path, raw, service):
        """Never bootout a running or differently loaded process, including rollback."""
        result = self.call(["launchctl", "print", service], False)
        if result.returncode == 113:
            return False
        if result.returncode or raw is None:
            raise ManagerError("로드된 예약의 소유권·상태를 확인하지 못했습니다.", 409)
        from runner.schedule_doctor import ScheduleDoctor
        try:
            ScheduleDoctor(self.store, self)._mac_loaded(result, path, plistlib.loads(raw))
        except (ValueError, TypeError, plistlib.InvalidFileException) as exc:
            raise ManagerError("로드된 실행 정의가 달라 예약을 보존합니다.", 409) from exc
        if re.search(r"^\s*pid = [1-9][0-9]*\s*$", result.stdout, re.M):
            raise ManagerError("OS 예약 프로세스가 실행 중입니다. 강제 종료하지 않습니다.", 409)
        return True

    def _preflight(self, job_id, plans):
        """Read-only ownership check, also performed before any migration write."""
        snapshots = {}
        for sid in plans:
            path = contained(self.agents, self.label(job_id, sid) + ".plist")
            state_path = self.state_path(job_id, sid)
            old = path.read_bytes() if path.exists() else None
            state = self.observed(job_id, sid)
            if state.get("observation_error"):
                raise ManagerError(state["observation_error"], 502)
            if old is not None and digest(old) != state.get("plist_sha256"):
                raise ManagerError("외부에서 수정되었거나 소유권을 확인할 수 없는 LaunchAgent를 보존했습니다: " + str(path), 409)
            if state["loaded"] and old is None:
                raise ManagerError("파일 없는 OS 예약의 소유권을 확인할 수 없습니다: " + self.label(job_id, sid), 409)
            if state["loaded"]:
                self._guard_live(path, old, "gui/" + str(os.getuid()) + "/" + self.label(job_id, sid))
            snapshots[sid] = (old, state_path.read_bytes() if state_path.exists() else None, state["loaded"], state.get("os_disabled", False))
        return snapshots

    def _transaction(self, job_id, plans):
        """Restore every touched resource on failure."""
        snapshots = self._preflight(job_id, plans)
        self.agents.mkdir(parents=True, exist_ok=True)
        touched = []
        try:
            # Disable old invocations before installing any replacement.
            for sid, plan in plans.items():
                path = contained(self.agents, self.label(job_id, sid) + ".plist")
                service = "gui/" + str(os.getuid()) + "/" + self.label(job_id, sid)
                current = path.read_bytes() if path.exists() else None
                if current != snapshots[sid][0] or self._guard_live(path, current, service) != snapshots[sid][2]:
                    raise ManagerError("OS 적용 직전 예약 변경 감지; 보존합니다.", 409)
                touched.append(sid)
                if snapshots[sid][2]:
                    self.call(["launchctl", "bootout", service])
                if plan.get("enabled"):
                    atomic_write(path, plan["plist"])
                    self.call(["plutil", "-lint", str(path)])
                    write_json(self.state_path(job_id, sid), {"applied": False, "phase": "applying"})
                    self.call(["launchctl", "enable", service])
                    self.call(["launchctl", "bootstrap", "gui/" + str(os.getuid()), str(path)])
                    self.call(["launchctl", "print", service])
                    state = {"applied": True, "phase": "applied", "etag": plan["etag"],
                             "schedule_hash": plan["schedule_hash"], "generation": plan["generation"],
                             "plist_sha256": digest(path.read_bytes())}
                else:
                    check = self.call(["launchctl", "print", service], False)
                    if check.returncode != 113:
                        raise ManagerError("OS 예약 해제를 검증하지 못했습니다: " + service, 502)
                    path.unlink(missing_ok=True)
                    state = {"applied": False, "phase": "removed"}
                write_json(self.state_path(job_id, sid), state)
        except Exception as exc:
            errors = []
            for sid in reversed(touched):
                try:
                    path = contained(self.agents, self.label(job_id, sid) + ".plist")
                    service = "gui/" + str(os.getuid()) + "/" + self.label(job_id, sid)
                    old, state_data, loaded, disabled = snapshots[sid]
                    current = path.read_bytes() if path.exists() else None
                    allowed = (old, plans[sid].get("plist", "").encode() if plans[sid].get("enabled") else None)
                    if current not in allowed:
                        raise ManagerError("복구 중 외부 예약 변경 감지; 외부 정의를 보존합니다.", 409)
                    if self._guard_live(path, current, service):
                        self.call(["launchctl", "bootout", service])
                    if old is None:
                        path.unlink(missing_ok=True)
                    else:
                        atomic_write(path, old)
                    self.call(["launchctl", "disable" if disabled else "enable", service])
                    if loaded:
                        self.call(["launchctl", "bootstrap", "gui/" + str(os.getuid()), str(path)])
                        self.call(["launchctl", "print", service])
                    if state_data is None:
                        self.state_path(job_id, sid).unlink(missing_ok=True)
                    else:
                        atomic_write(self.state_path(job_id, sid), state_data)
                except Exception as rollback:
                    errors.append(str(rollback))
                    write_json(self.state_path(job_id, sid), {"applied": False, "phase": "degraded",
                        "error": str(exc), "rollback_error": str(rollback)})
            raise ManagerError(str(exc) + ("; OS 복구 실패: " + "; ".join(errors) if errors else "; OS 기존 설정 복구 완료"), 502) from exc
        return {str(sid): self.state(job_id, sid) for sid in plans}

    def apply(self, job_id, etag, schedule_id=None):
        self.available()
        if schedule_id is not None and "schedule" in self.store.get(job_id)["config"]:
            return self.save(job_id, schedule_id, self.entry(job_id, schedule_id), etag)["state"]
        with self.store.job_lock(job_id, "operation"), self.store.job_lock(job_id, "run", False), self.store.job_lock(job_id):
            plan = self.plan(job_id, schedule_id=schedule_id)
            if not etag or etag != plan["etag"]:
                raise ManagerError("설정이 변경되었습니다. 다시 읽은 뒤 적용하세요.", 409)
            sid = plan["schedule_id"]
            if sid is None and any(any(self.observed(job_id, known).get(k) for k in ("loaded", "file_exists", "applied")) for known in self.known_ids(job_id)):
                raise ManagerError("Schedule별 OS 예약이 이미 있습니다. Schedule 저장·적용으로 이전 설정을 전환하세요.", 409)
            if sid is not None and any(self.observed(job_id).get(k) for k in ("loaded", "file_exists", "applied")):
                raise ManagerError("이전 OS 예약이 있습니다. Schedule 저장·적용으로 안전하게 전환하세요.", 409)
            self._transaction(job_id, {sid: plan})
            return self.state(job_id, sid)

    def remove(self, job_id, schedule_id=None, legacy=False):
        self.available()
        with self.store.job_lock(job_id, "operation"), self.store.job_lock(job_id, "run", False), self.store.job_lock(job_id):
            if schedule_id is None and not legacy:
                try:
                    item = self.store.get(job_id)
                    if "schedule" not in item["config"] and schedules(item["config"]):
                        schedule_id = self.entry(job_id, item=item)["id"]
                except ManagerError as exc:
                    if exc.status != 404:
                        raise
            self._transaction(job_id, {schedule_id: {"enabled": False}})
            return self.state(job_id, schedule_id)

    def save(self, job_id, schedule_id, schedule, etag, create=False, legacy_registration=False):
        """One user operation: CAS YAML save + OS apply, with rollback of both on failure."""
        self.available()
        identifier(schedule_id)
        if schedule is not None:
            validate_schedule(schedule)
            if schedule["id"] != schedule_id:
                raise ManagerError("Schedule ID는 변경할 수 없습니다.")
        with self.store.job_lock(job_id, "operation"), self.store.job_lock(job_id, "run", False), self.store.job_lock(job_id):
            current = self.store.get(job_id)
            if not etag:
                raise ManagerError("기존 etag가 필요합니다.", 428)
            if current["etag"] != etag:
                raise ManagerError("파일이 변경되었습니다. 최신 설정을 다시 읽으세요.", 409)
            config = migrate_config(load_yaml(current["yaml"]))
            entries = config["schedules"]
            index = next((i for i, s in enumerate(entries) if s["id"] == schedule_id), None)
            if create and index is not None:
                raise ManagerError("동일한 Schedule ID가 있습니다.", 409)
            if not create and schedule is not None and index is None:
                raise ManagerError("Schedule을 찾을 수 없습니다.", 404)
            if legacy_registration:
                if schedule is not None:
                    raise ManagerError("이전 OS 예약은 삭제만 가능합니다.")
            elif index is not None:
                if schedule is None:
                    entries.pop(index)
                else:
                    # Keep existing comments on the unchanged keys.
                    for key in list(entries[index]):
                        if key not in schedule:
                            del entries[index][key]
                    entries[index].update(schedule)
            elif schedule is not None:
                entries.append(schedule)
            validate(config, job_id)
            text = dump_yaml(config)
            preamble = re.match(r"\A(?:[ \t]*(?:#[^\r\n]*)?\r?\n)*(?=%YAML)", current["yaml"])
            if preamble:
                text = preamble.group() + text
            resources = {} if legacy_registration else {schedule_id: None}
            old = self.observed(job_id)
            if legacy_registration or any(old.get(k) for k in ("loaded", "file_exists", "applied", "observation_error")):
                resources[None] = None
                if not legacy_registration and schedule_id != "legacy" and any(s["id"] == "legacy" for s in entries):
                    resources["legacy"] = None
            self._preflight(job_id, resources)
            updated = self.store._update_locked(job_id, text, etag)
            try:
                plans = {}
                old = self.observed(job_id)
                has_old = any(old.get(k) for k in ("loaded", "file_exists", "applied", "observation_error"))
                if has_old or legacy_registration:
                    plans[None] = {"enabled": False}
                    # Transfer a legacy live reservation even when adding a different schedule.
                    if not legacy_registration and schedule_id != "legacy" and any(s["id"] == "legacy" for s in entries):
                        plans["legacy"] = self.plan(job_id, schedule_id="legacy")
                if not legacy_registration:
                    plans[schedule_id] = self.plan(job_id, schedule_id=schedule_id) if schedule is not None else {"enabled": False}
                self._transaction(job_id, plans)
                if digest((self.store.job_dir(job_id) / "job.yaml").read_bytes()) != updated["etag"]:
                    raise ManagerError("OS 적용 중 외부 YAML 변경을 감지했습니다. 현재 상태를 다시 확인하세요.", 409)
            except Exception as exc:
                # Never overwrite an uncooperative editor's newer content.
                path = self.store.job_dir(job_id) / "job.yaml"
                if digest(path.read_bytes()) == updated["etag"]:
                    atomic_write(path, current["yaml"])
                    detail = "YAML 기존 설정 복구 완료"
                else:
                    detail = "외부 YAML 변경을 보존했습니다. 설정 불일치를 확인하세요."
                raise ManagerError(str(exc) + "; " + detail, getattr(exc, "status", 502)) from exc
            return {"job": updated, "state": self.observed(job_id, schedule_id),
                    "migrated": "schedule" in current["config"], "deleted": schedule is None}
