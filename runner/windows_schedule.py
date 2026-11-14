"""Per-Schedule Windows tasks; no stored credentials or resident process."""
import csv
from datetime import datetime
import getpass
import io
import json
import locale
import os
import platform
import re
import subprocess
import tempfile
import xml.etree.ElementTree as ET

from runner.common import ManagerError, atomic_write, digest, identifier, write_json
from runner.schedule import Scheduler
from runner.installation import metadata, description
from runner.store import schedule_hash, schedules

NS = "http://schemas.microsoft.com/windows/2004/02/mit/task"
ET.register_namespace("", NS)


def node(parent, name, value=None):
    child = ET.SubElement(parent, "{" + NS + "}" + name)
    if value is not None:
        child.text = str(value)
    return child


def task_definition_hash(task):
    """Whitespace/namespace-prefix independent checksum of the complete task definition.

    Description carries this checksum and is excluded to avoid a self-reference.
    Unknown OS-added fields are deliberately not ignored. After registration,
    ownership may instead use the original installation's exact recorded OS
    export; see ScheduleDoctor._windows_recorded_definition.
    """
    q = "{" + NS + "}"
    def value(element):
        if element.tag == q + "Description":
            return None
        return [element.tag, sorted(element.attrib.items()),
                element.text if element.text and element.text.strip() else "",
                [value(child) for child in element if child.tag != q + "Description"]]
    return digest(json.dumps(value(task), sort_keys=True, ensure_ascii=False).encode())


def query_error(context, result=None, cause=None):
    """OS observation failure is not evidence that the installation path is gone."""
    detail = str(cause) if cause is not None else (
        "exit=" + str(result.returncode) + ": " + (result.stderr.strip() or "OS 오류 상세 없음"))
    return ManagerError(
        "Windows Task Scheduler " + context + " 조회 실패: " + detail +
        ". OS 접근 권한·sandbox 실행 제한·조회 도구를 확인하세요. "
        "원본 경로/파일 누락으로 판단하지 않으며 예약과 데이터를 보존합니다.", 502)


def task_xml(args, workdir, entry, author, generation, owner=None):
    task = ET.Element("{" + NS + "}Task", {"version": "1.3"})
    registration = node(task, "RegistrationInfo")
    node(registration, "Description", description(owner) if owner else "Script Manager " + generation)
    triggers = node(task, "Triggers")
    if entry["type"] == "interval":
        seconds = entry["interval_seconds"]
        if not 60 <= seconds <= 31 * 86400:
            raise ManagerError("Windows Task Scheduler의 간격 실행은 60초~31일입니다.")
        trigger = node(triggers, "TimeTrigger")
        node(trigger, "Enabled", "true")
        node(trigger, "StartBoundary", datetime.now().strftime("%Y-%m-%dT%H:%M:%S"))
        repetition = node(trigger, "Repetition")
        node(repetition, "Interval", "PT" + str(seconds) + "S")
        node(repetition, "StopAtDurationEnd", "false")
    else:
        day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        for time in entry.get("times", []):
            trigger = node(triggers, "CalendarTrigger")
            node(trigger, "Enabled", "true")
            node(trigger, "StartBoundary", "2020-01-06T" + time + ":00")
            weekly = node(trigger, "ScheduleByWeek")
            node(weekly, "WeeksInterval", 1)
            days = node(weekly, "DaysOfWeek")
            for day in entry.get("weekdays", range(1, 8)):
                node(days, day_names[day - 1])
    principals = node(task, "Principals")
    principal = node(principals, "Principal")
    principal.set("id", "Author")
    node(principal, "UserId", author)
    node(principal, "LogonType", "InteractiveToken")
    node(principal, "RunLevel", "LeastPrivilege")
    settings = node(task, "Settings")
    node(settings, "MultipleInstancesPolicy", "IgnoreNew")
    node(settings, "DisallowStartIfOnBatteries", "false")
    node(settings, "StopIfGoingOnBatteries", "false")
    node(settings, "AllowHardTerminate", "true")
    node(settings, "StartWhenAvailable", "false")
    node(settings, "RunOnlyIfNetworkAvailable", "false")
    node(settings, "Enabled", "true")
    node(settings, "Hidden", "false")
    node(settings, "ExecutionTimeLimit", "PT0S")
    actions = node(task, "Actions")
    actions.set("Context", "Author")
    action = node(actions, "Exec")
    node(action, "Command", args[0])
    node(action, "Arguments", subprocess.list2cmdline(args[1:]))
    node(action, "WorkingDirectory", workdir)
    if owner:
        owner = dict(owner, definition_sha256=task_definition_hash(task))
        registration.find("{" + NS + "}Description").text = description(owner)
    return ET.tostring(task, encoding="utf-16", xml_declaration=True).decode("utf-16")


class WindowsScheduler(Scheduler):
    def __init__(self, store, agents=None, command=None):
        super().__init__(store, agents, command)
        self.scheduler_name = "Windows Task Scheduler"

    def task_name(self, job_id, schedule_id=None):
        name = identifier(job_id) + ("." + identifier(schedule_id) if schedule_id is not None else "")
        return "\\local.scriptmanager." + self.namespace + "." + name

    def available(self):
        if platform.system() != "Windows":
            raise ManagerError("Windows Task Scheduler는 Windows에서만 사용할 수 있습니다.")

    def call(self, args, check=True):
        querying = args[0].lower() == "powershell.exe" or any(arg.lower() == "/query" for arg in args)
        try:
            result = self.command(args, capture_output=True, stdin=subprocess.DEVNULL, timeout=20)
        except (OSError, subprocess.SubprocessError) as exc:
            if querying:
                raise query_error("명령", cause=exc) from exc
            raise ManagerError("스케줄 명령 실행·관찰 실패: " + str(exc), 502) from exc
        def decoded(value):
            if isinstance(value, str):
                return value
            if value.startswith((b"\xff\xfe", b"\xfe\xff")):
                return value.decode("utf-16")
            if value.startswith(b"\xef\xbb\xbf"):
                return value.decode("utf-8-sig")
            if b"\x00" in value[:80]:
                return value.decode("utf-16-le")
            try:
                return value.decode("utf-8")
            except UnicodeError:
                return value.decode(locale.getpreferredencoding(False), errors="replace")
        result.stdout = decoded(result.stdout)
        result.stderr = decoded(result.stderr)
        if check and result.returncode:
            if querying:
                raise query_error("명령", result)
            raise ManagerError("스케줄 명령 실패: " + result.stderr.strip(), 502)
        return result

    def plan(self, job_id, generation=None, schedule_id=None):
        import sys
        from pathlib import Path
        import uuid
        item = self.store.get(job_id)
        entry = self.entry(job_id, schedule_id, item)
        sid = schedule_id if schedule_id is not None else (None if "schedule" in item["config"] else entry["id"])
        generation = generation or uuid.uuid4().hex
        args = [sys.executable, "-m", "runner", "--root", str(self.store.root), "_scheduled", job_id, generation]
        if sid is not None:
            args.append(sid)
        user = os.environ.get("USERNAME") or getpass.getuser()
        domain = os.environ.get("USERDOMAIN")
        author = domain + "\\" + user if domain and "\\" not in user and "@" not in user else user
        xml = task_xml(args, str(Path(__file__).resolve().parent.parent), entry, author, generation, metadata(self.store, job_id, sid, generation))
        return {"enabled": entry["enabled"], "label": self.task_name(job_id, sid), "schedule_id": sid,
                "generation": generation, "schedule_hash": schedule_hash(entry), "etag": item["etag"],
                "xml": xml, "timezone": "host-local"}

    def _query(self, job_id, schedule_id=None):
        result = self.call(["schtasks", "/Query", "/TN", self.task_name(job_id, schedule_id), "/XML"], False)
        if result.returncode == 0:
            return result.stdout
        listing = self.call(["schtasks", "/Query", "/FO", "CSV", "/NH"], False)
        if listing.returncode:
            raise query_error("예약 상태/목록", listing)
        name = self.task_name(job_id, schedule_id)
        if any(row and row[0].lower() == name.lower() for row in csv.reader(io.StringIO(listing.stdout))):
            raise query_error("예약 정의 " + name, result)
        return None

    def observed(self, job_id, schedule_id=None):
        state = self.state(job_id, schedule_id)
        raw = self._query(job_id, schedule_id)
        loaded = raw is not None
        state.update(supported=platform.system() == "Windows", loaded=loaded, file_exists=loaded,
                     file_matches=loaded and digest(raw.encode("utf-8")) == state.get("task_sha256"))
        if loaded:
            try:
                root = ET.fromstring(raw)
                enabled = root.findtext("{" + NS + "}Settings/{" + NS + "}Enabled", "true")
                state["os_disabled"] = enabled.lower() == "false"
            except ET.ParseError:
                state["observation_error"] = "Windows 예약 정의를 읽을 수 없습니다."
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
        result = self.call(["schtasks", "/Query", "/FO", "CSV", "/NH"], False)
        if result.returncode:
            raise query_error("예약 목록", result)
        prefix = self.task_name(job_id) + "."
        for row in csv.reader(io.StringIO(result.stdout)):
            name = row[0] if row else ""
            sid = name[len(prefix):] if name.lower().startswith(prefix.lower()) else ""
            if re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", sid):
                ids.add(sid)
        return ids

    def _preflight(self, job_id, plans):
        snapshots = {}
        for sid in plans:
            old = self._query(job_id, sid)
            state_path = self.state_path(job_id, sid)
            state = self.state(job_id, sid)
            if old is not None and digest(old.encode("utf-8")) != state.get("task_sha256"):
                raise ManagerError("외부에서 수정되었거나 소유권을 확인할 수 없는 Windows 예약을 보존했습니다: " + self.task_name(job_id, sid), 409)
            if old is not None:
                from runner.schedule_doctor import ScheduleDoctor
                ScheduleDoctor(self.store, self)._windows_idle(self.task_name(job_id, sid))
                if self._query(job_id, sid) != old:
                    raise ManagerError("Windows 소유권 확인 중 예약 변경 감지; 보존합니다.", 409)
            snapshots[sid] = (old, state_path.read_bytes() if state_path.exists() else None)
        return snapshots

    def _register(self, name, xml):
        folder = self.store.runtime / "schedules"
        fd, path = tempfile.mkstemp(suffix=".xml", dir=folder)
        try:
            with os.fdopen(fd, "w", encoding="utf-16") as file:
                file.write(xml)
            self.call(["schtasks", "/Create", "/TN", name, "/XML", path, "/F"])
        finally:
            os.unlink(path)

    def _delete(self, name):
        self.call(["schtasks", "/Delete", "/TN", name, "/F"])

    def _transaction(self, job_id, plans):
        snapshots = self._preflight(job_id, plans)
        touched = []
        try:
            for sid, plan in plans.items():
                name = self.task_name(job_id, sid)
                if snapshots[sid][0] is not None:
                    from runner.schedule_doctor import ScheduleDoctor
                    ScheduleDoctor(self.store, self)._windows_idle(name)
                if self._query(job_id, sid) != snapshots[sid][0]:
                    raise ManagerError("Windows 적용 직전 예약 변경 감지; 보존합니다.", 409)
                touched.append(sid)
                if plan.get("enabled"):
                    write_json(self.state_path(job_id, sid), {"applied": False, "phase": "applying"})
                    self._register(name, plan["xml"])
                    current = self._query(job_id, sid)
                    if current is None:
                        raise ManagerError("Windows 예약 등록을 확인할 수 없습니다.", 502)
                    state = {"applied": True, "phase": "applied", "etag": plan["etag"],
                             "schedule_hash": plan["schedule_hash"], "generation": plan["generation"],
                             "task_sha256": digest(current.encode("utf-8"))}
                else:
                    if snapshots[sid][0] is not None:
                        self._delete(name)
                    if self._query(job_id, sid) is not None:
                        raise ManagerError("Windows 예약 해제를 검증하지 못했습니다: " + name, 502)
                    state = {"applied": False, "phase": "removed"}
                write_json(self.state_path(job_id, sid), state)
        except Exception as exc:
            errors = []
            for sid in reversed(touched):
                try:
                    old, data = snapshots[sid]
                    name = self.task_name(job_id, sid)
                    current = self._query(job_id, sid)
                    allowed = [old, plans[sid].get("xml")]
                    recorded = self.state(job_id, sid)
                    own_applied = (recorded.get("generation") == plans[sid].get("generation")
                                   and current is not None and digest(current.encode()) == recorded.get("task_sha256"))
                    if current is not None:
                        from runner.schedule_doctor import ScheduleDoctor
                        ScheduleDoctor(self.store, self)._windows_idle(name)
                        if current not in allowed and not own_applied:
                            raise ManagerError("Windows 복구 중 외부 정의 변경 감지; 보존합니다.", 409)
                    if old is None:
                        if current is not None:
                            self._delete(name)
                    else:
                        self._register(name, old)
                    if data is None:
                        self.state_path(job_id, sid).unlink(missing_ok=True)
                    else:
                        if old is not None:
                            restored = self._query(job_id, sid)
                            if restored is None:
                                raise ManagerError("복구한 Windows 예약을 확인할 수 없습니다.", 502)
                            previous = json.loads(data)
                            previous["task_sha256"] = digest(restored.encode("utf-8"))
                            write_json(self.state_path(job_id, sid), previous)
                        else:
                            atomic_write(self.state_path(job_id, sid), data)
                except Exception as rollback:
                    errors.append(str(rollback))
                    write_json(self.state_path(job_id, sid), {"applied": False, "phase": "degraded",
                        "error": str(exc), "rollback_error": str(rollback)})
            raise ManagerError(str(exc) + ("; OS 복구 실패: " + "; ".join(errors) if errors else "; OS 기존 설정 복구 완료"), 502) from exc
        return {str(sid): self.state(job_id, sid) for sid in plans}
