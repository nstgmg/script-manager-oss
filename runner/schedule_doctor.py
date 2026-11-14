"""Read-only native inventory; narrowly authorized, verified removal. No daemon."""
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import plistlib
import re
import subprocess
import xml.etree.ElementTree as ET

from runner.common import ManagerError, contained, digest, identifier, read_json
from runner.installation import MARKER, DESCRIPTION
from runner.schedule import Scheduler

PREFIX = "local.scriptmanager."
LABEL = re.compile(r"local\.scriptmanager\.([0-9a-f]{12})\.([a-z0-9][a-z0-9-]{0,62})(?:\.([a-z0-9][a-z0-9-]{0,62}))?")


def fingerprint(value):
    return digest(json.dumps(value, sort_keys=True, ensure_ascii=False).encode())


class ScheduleDoctor:
    def __init__(self, store, scheduler=None, units=None):
        self.store = store
        self.scheduler = scheduler or Scheduler(store)
        self.system = platform.system()
        self.units = Path(units) if units else Path.home() / ".config/systemd/user"

    def _identity(self, row, owner, args, cwd, definition_ok=True):
        match = LABEL.fullmatch(row["id"].lstrip("\\"))
        if not match:
            raise ValueError("예약 이름 형식을 확인할 수 없습니다.")
        ns, job, sid = match.groups()
        # A legacy definition alone is deliberately insufficient evidence.
        if owner is not None and not isinstance(owner, dict):
            raise ValueError("잘못된 소유 메타데이터는 구버전 예약으로 인수하지 않습니다.")
        if owner is None:
            if not isinstance(args, list) or len(args) not in (8, 9) or args[1:4] != ["-m", "runner", "--root"] or args[5] != "_scheduled":
                raise ValueError("이전 예약의 실행 경로를 확인할 수 없습니다.")
            root, generation = args[4], args[7]
            expected = [args[0], "-m", "runner", "--root", root, "_scheduled", job, generation] + ([sid] if sid else [])
            if args != expected:
                raise ValueError("이전 예약의 인자가 일치하지 않습니다.")
            state_name = job + ("." + sid if sid else "") + ".json"
            state = read_json(contained(Path(root), "runtime/schedules/" + state_name), {})
            key = "task_sha256" if self.system == "Windows" else "plist_sha256"
            if state.get(key) != row["definition_hash"]:
                raise ValueError("이전 예약의 원본 체크섬이 없습니다. 임의 변경하지 않습니다.")
            owner = {"root": root, "code_root": cwd, "executable": args[0], "job_id": job,
                     "schedule_id": sid, "generation": generation, "installation_id": None}
            row["legacy"] = True
        else:
            if owner.get("owner") != "script-manager" or owner.get("version") != 1 or not re.fullmatch(r"[0-9a-f]{32}", owner.get("installation_id", "")):
                raise ValueError("Script Manager 소유 메타데이터가 유효하지 않습니다.")
            expected = [owner.get("executable"), "-m", "runner", "--root", owner.get("root"), "_scheduled", job, owner.get("generation")] + ([sid] if sid else [])
            if (owner.get("job_id") != job or (owner.get("schedule_id") or None) != sid or args != expected
                    or cwd != owner.get("code_root") or not definition_ok
                    or not re.fullmatch(r"[0-9a-f]{32}", owner.get("generation", ""))):
                raise ValueError("메타데이터와 실제 실행 정의가 다릅니다.")
        for key in ("root", "code_root", "executable"):
            if not isinstance(owner.get(key), str) or not Path(owner[key]).is_absolute() or ".." in Path(owner[key]).parts:
                raise ValueError("절대 실행 경로를 확인할 수 없습니다.")
        if hashlib.sha256(owner["root"].encode()).hexdigest()[:12] != ns:
            raise ValueError("예약 이름과 원본 프로젝트 경로가 다릅니다.")
        row.update(owned=True, **{k: owner[k] for k in ("root", "code_root", "executable", "installation_id", "job_id", "schedule_id")})
        state_name = job + ("." + sid if sid else "") + ".json"
        required = [Path(owner["root"]), Path(cwd), Path(args[0]), Path(cwd) / "runner/__main__.py",
                    Path(owner["root"]) / "jobs" / job / "job.yaml",
                    Path(owner["root"]) / "runtime/schedules" / state_name]
        required.extend(Path(p) for p in owner.get("required_files", []))
        missing = [str(p) for p in required if not p.exists()]
        if Path(owner["root"]).exists() and Path(owner["root"]).resolve() != Path(owner["root"]):
            raise ValueError("원본 데이터 루트가 다른 경로로 연결되어 있습니다.")
        state_path = contained(Path(owner["root"]), "runtime/schedules/" + state_name)
        state = read_json(state_path, {})
        checksum_key = "task_sha256" if self.system == "Windows" else "plist_sha256"
        if state.get(checksum_key) and state[checksum_key] != row["definition_hash"]:
            raise ValueError("원본 상태 체크섬과 실제 OS 정의가 다릅니다.")
        identity_path = contained(Path(owner["root"]), "runtime/installation.json")
        if state_path.exists() and not row.get("legacy") and identity_path.exists():
            identity = read_json(identity_path)
            if (not isinstance(identity, dict) or identity.get("root") != owner["root"]
                    or identity.get("installation_id") != owner["installation_id"]):
                raise ValueError("원본 설치 ID와 OS 예약의 설치 ID가 다릅니다.")
        retired = not state.get("applied") or state.get("generation") != owner.get("generation")
        row.update(status="orphan" if missing or retired else "healthy", missing=missing,
                   reason="필요한 원본 경로가 없습니다." if missing else "원본 예약 세대가 사라지거나 교체되었습니다." if retired else "원본 실행 경로와 필수 파일이 존재합니다.")

    def _mac_loaded(self, result, path, data):
        source = re.search(r"^\s*path = (.+)$", result.stdout, re.M)
        program = re.search(r"^\s*program = (.+)$", result.stdout, re.M)
        cwd = re.search(r"^\s*working directory = (.+)$", result.stdout, re.M)
        block = re.search(r"^\s*arguments = \{\n(.*?)^\s*\}", result.stdout, re.M | re.S)
        args = [line.strip() for line in block[1].splitlines()] if block else None
        if (result.returncode or not source or Path(source[1]).resolve() != path.resolve()
                or not program or program[1] != data.get("ProgramArguments", [None])[0]
                or not cwd or cwd[1] != data.get("WorkingDirectory") or args != data.get("ProgramArguments")):
            raise ValueError("로드된 launchd 실행 정의와 plist가 다르거나 확인할 수 없습니다.")
        return fingerprint({"path": str(path.resolve()), "program": program[1], "cwd": cwd[1], "args": args})

    def _mac(self):
        scheduler = self.scheduler
        listing = scheduler.call(["launchctl", "list"], False)
        if listing.returncode:
            raise ManagerError("launchd 목록 조회 실패: " + listing.stderr.strip(), 502)
        loaded = {line.split()[-1] for line in listing.stdout.splitlines() if line.split() and line.split()[-1].startswith(PREFIX)}
        paths = {p.stem: p for p in scheduler.agents.iterdir() if p.name.startswith(PREFIX) and p.suffix == ".plist"} if scheduler.agents.exists() else {}
        rows = []
        for label in sorted(loaded | paths.keys()):
            path = paths.get(label, scheduler.agents / (label + ".plist"))
            row = {"id": label, "owned": False, "status": "unknown", "loaded": label in loaded, "path": str(path)}
            try:
                if path.is_symlink() or not path.is_file():
                    raise ValueError("원본 plist가 없거나 심볼릭 링크입니다. 소유권을 확인할 수 없습니다.")
                raw = path.read_bytes()
                row["definition_hash"] = digest(raw)
                data = plistlib.loads(raw)
                if data.get("Label") != label:
                    raise ValueError("파일명과 Label이 다릅니다.")
                owner = data.get(MARKER)
                valid = isinstance(owner, dict) and owner.get("definition_sha256") == digest(plistlib.dumps({k: v for k, v in data.items() if k != MARKER}))
                self._identity(row, owner, data.get("ProgramArguments"), data.get("WorkingDirectory"), valid)
                if row["loaded"]:
                    result = scheduler.call(["launchctl", "print", self._service(label)], False)
                    row["loaded_definition_hash"] = self._mac_loaded(result, path, data)
                    row["running"] = bool(re.search(r"^\s*pid = [1-9][0-9]*\s*$", result.stdout, re.M))
            except (OSError, ValueError, TypeError, KeyError, AttributeError, plistlib.InvalidFileException, ManagerError) as exc:
                row.update(status="unknown", owned=False, reason=str(exc))
            row["fingerprint"] = fingerprint(row)
            rows.append(row)
        return rows

    def _windows(self):
        from runner.windows_schedule import NS, task_definition_hash
        q = "{" + NS + "}"
        listing = self.scheduler.call(["schtasks", "/Query", "/FO", "CSV", "/NH"], False)
        if listing.returncode:
            raise ManagerError("Windows 예약 목록 조회 실패: " + listing.stderr.strip(), 502)
        rows = []
        for values in csv.reader(io.StringIO(listing.stdout)):
            if not values or not values[0].lower().startswith("\\" + PREFIX):
                continue
            name = values[0]
            row = {"id": name, "loaded": True, "owned": False, "status": "unknown"}
            try:
                result = self.scheduler.call(["schtasks", "/Query", "/TN", name, "/XML"])
                row["definition_hash"] = digest(result.stdout.encode("utf-8"))
                xml = ET.fromstring(result.stdout)
                actions = xml.find(q + "Actions")
                if actions is None or len(actions) != 1 or actions[0].tag != q + "Exec":
                    raise ValueError("단일 Script Manager 실행 정의가 아닙니다.")
                action = actions[0]
                text = xml.findtext(q + "RegistrationInfo/" + q + "Description", "")
                owner = json.loads(text[len(DESCRIPTION):]) if text.startswith(DESCRIPTION) else None
                if owner is not None:
                    expected_hash = owner.get("definition_sha256")
                    if expected_hash and expected_hash != task_definition_hash(xml):
                        raise ValueError("Windows 전체 예약 정의 체크섬 불일치")
                    if not expected_hash:
                        match = LABEL.fullmatch(name.lstrip("\\"))
                        if (not match or match[1] != self.scheduler.namespace
                                or self.scheduler.state(match[2], match[3]).get("task_sha256") != row["definition_hash"]):
                            raise ValueError("전체 체크섬 없는 이전 Windows 메타데이터는 원본 상태가 필요합니다.")
                if owner is None:
                    match = LABEL.fullmatch(name.lstrip("\\"))
                    if not match or match[1] != self.scheduler.namespace:
                        raise ValueError("원본 체크섬 없는 이전 Windows 예약을 보존했습니다.")
                    _, job, sid = match.groups()
                    state = self.scheduler.state(job, sid)
                    if state.get("task_sha256") != row["definition_hash"]:
                        raise ValueError("이전 Windows 예약 체크섬을 확인할 수 없습니다.")
                    legacy = {"job_id": job, "schedule_id": sid, "root": str(self.store.root), "generation": state.get("generation")}
                else:
                    legacy = owner
                job, sid = legacy.get("job_id"), legacy.get("schedule_id")
                args = [action.findtext(q + "Command"), "-m", "runner", "--root", legacy.get("root"), "_scheduled", job, legacy.get("generation")] + ([sid] if sid else [])
                if any(not isinstance(v, str) for v in args) or action.findtext(q + "Arguments") != subprocess.list2cmdline(args[1:]):
                    raise ValueError("Windows 예약 인자와 메타데이터가 다릅니다.")
                self._identity(row, owner, args, action.findtext(q + "WorkingDirectory"))
                row["running"] = self._windows_running(name)
            except (ManagerError, ValueError, TypeError, KeyError, AttributeError, OSError, ET.ParseError) as exc:
                row.update(status="unknown", owned=False, reason=str(exc))
            row["fingerprint"] = fingerprint(row)
            rows.append(row)
        return rows

    def _systemctl(self, *args, check=True):
        return self.scheduler.call(["systemctl", "--user", *args], check)

    def _unit_state(self, name):
        result = self._systemctl("show", name, "--property=LoadState,FragmentPath,DropInPaths,NeedDaemonReload,ActiveState,SubState,ExecStart,Unit", check=False)
        data = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
        absent = (data.get("LoadState") == "not-found" and data.get("ActiveState") == "inactive"
                  and not data.get("FragmentPath") and not data.get("DropInPaths"))
        if ((result.returncode != 0 and not (result.returncode == 4 and absent))
                or data.get("LoadState") not in ("loaded", "not-found")):
            raise ManagerError("systemd 유닛 상태를 확인할 수 없습니다: " + name, 502)
        return data

    def _linux(self):
        names = set()
        for action in ("list-unit-files", "list-units"):
            result = self._systemctl(action, "--all", "--no-legend", "--plain", "--no-pager", "scriptmanager-*")
            names.update(line.split()[0] for line in result.stdout.splitlines() if line.split() and line.split()[0].startswith("scriptmanager-"))
        if self.units.exists():
            names.update(p.name for p in self.units.iterdir() if p.name.startswith("scriptmanager-") and p.suffix in (".service", ".timer"))
        rows = []
        for name in sorted(names):
            if not re.fullmatch(r"scriptmanager-[a-z0-9-]+\.(?:service|timer)", name):
                continue
            path = self.units / name
            row = {"id": name, "path": str(path), "kind": "systemd", "owned": False, "status": "unknown"}
            try:
                state = self._unit_state(name)
                if not path.exists() and state["LoadState"] == "not-found" and state.get("ActiveState") == "inactive":
                    continue
                row["loaded"] = state["LoadState"] == "loaded"
                row["running"] = name.endswith(".service") and state.get("ActiveState") not in ("inactive", "failed")
                if (path.is_symlink() or not path.is_file() or state.get("DropInPaths")
                        or state.get("NeedDaemonReload") != "no"
                        or Path(state.get("FragmentPath", "")).resolve() != path.resolve()):
                    raise ValueError("유닛 원본 경로·drop-in·로드 상태를 검증하지 못했습니다.")
                text = path.read_text()
                row["definition_hash"] = digest(path.read_bytes())
                marker, sep, body = text.partition("\n")
                if not marker.startswith("# ScriptManagerMetadata ") or not sep:
                    raise ValueError("메타데이터 없는 기존 systemd 유닛은 수동 확인이 필요합니다.")
                owner = json.loads(marker[len("# ScriptManagerMetadata "):])
                if (owner.get("owner") != "script-manager" or owner.get("version") != 1 or owner.get("kind") != "systemd"
                        or not re.fullmatch(r"[0-9a-f]{32}", owner.get("installation_id", ""))
                        or owner.get("unit") != name or digest(body.encode()) != owner.get("definition_sha256")):
                    raise ValueError("systemd 메타데이터와 원본 정의가 일치하지 않습니다.")
                root, job, sid = owner["root"], identifier(owner["job_id"]), owner.get("schedule_id")
                if sid is not None:
                    identifier(sid)
                for key in ("root", "executable", "code_root"):
                    if not Path(owner[key]).is_absolute() or ".." in Path(owner[key]).parts:
                        raise ValueError("systemd 실행 절대 경로를 확인할 수 없습니다.")
                base = "scriptmanager-" + digest(root.encode())[:12] + "-" + job
                expected = base + ("-schedule-" + sid if sid else "") + path.suffix
                release = owner["release"]
                identifier(release)
                directory = Path(root) / job / "releases" / release
                def quote(value):
                    return '\"' + str(value).replace("\\", "\\\\").replace('\"', '\\\"').replace("%", "%%") + '\"'
                expected_exec = " ".join(quote(v) for v in (owner["executable"], directory / "manager/remote_runtime.py", "run", Path(root) / job, release)) + (" " + quote(sid) if sid else "")
                if expected != name or owner["code_root"] != str(directory / "manager") or owner["exec_start"] != expected_exec:
                    raise ValueError("systemd 이름·실행 경로·메타데이터 불일치")
                if path.suffix == ".service" and [line for line in body.splitlines() if line.startswith("ExecStart=")] != ["ExecStart=" + expected_exec]:
                    raise ValueError("systemd 실제 실행 명령 불일치")
                if path.suffix == ".service":
                    live = re.search(r"\{ path=(.*?) ; argv\[\]=(.*?) ;", state.get("ExecStart", ""))
                    argv = [owner["executable"], str(directory / "manager/remote_runtime.py"), "run", str(Path(root) / job), release] + ([sid] if sid else [])
                    if not live or live[1] != owner["executable"] or live[2] != " ".join(argv):
                        raise ValueError("systemd 실제 로드된 ExecStart 불일치 또는 확인 불가")
                if path.suffix == ".timer":
                    if ([line for line in body.splitlines() if line.startswith("Unit=")] != ["Unit=" + name[:-6] + ".service"]
                            or state.get("Unit") != name[:-6] + ".service"):
                        raise ValueError("systemd timer의 실제 실행 유닛 불일치")
                missing = [str(p) for p in (Path(root), Path(owner["executable"]), directory / "manager/remote_runtime.py", directory / "config.json") if not p.exists()]
                identity_path = Path(root) / ".script-manager-installation.json"
                if identity_path.exists():
                    identity = read_json(identity_path)
                    if (not isinstance(identity, dict) or identity.get("root") != root
                            or identity.get("installation_id") != owner["installation_id"]):
                        raise ValueError("systemd 원본 설치 ID가 다릅니다.")
                row.update(owned=True, root=root, installation_id=owner["installation_id"], job_id=job, schedule_id=sid,
                           status="orphan" if missing else "healthy", missing=missing,
                           reason="원본 배포 실행 경로가 없습니다." if missing else "원본 배포 실행 파일이 존재합니다.")
            except (ManagerError, OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
                row.update(owned=False, status="unknown", reason=str(exc))
            row["fingerprint"] = fingerprint(row)
            rows.append(row)
        return rows

    def scan(self):
        result = {"platform": self.system, "supported": self.system in ("Darwin", "Windows", "Linux"), "schedules": [], "errors": []}
        if not result["supported"]:
            result["notice"] = "Linux 로컬 스케줄 등록은 미지원입니다. 원격 systemd 예약은 SSH 대상에서 별도로 확인하세요."
            return result
        try:
            result["schedules"] = {"Darwin": self._mac, "Windows": self._windows, "Linux": self._linux}[self.system]()
            if self.system == "Linux":
                result["notice"] = "현재 사용자 systemd 배포 유닛을 진단합니다. Linux 로컬 Job 예약 등록은 미지원이며 SSH 조회는 하지 않습니다."
        except (ManagerError, OSError, subprocess.SubprocessError) as exc:
            result["errors"].append(str(exc))
        result["counts"] = {status: sum(r["status"] == status for r in result["schedules"]) for status in ("healthy", "orphan", "unknown")}
        return result

    def _service(self, label):
        return "gui/" + str(os.getuid()) + "/" + label

    def _windows_running(self, label):
        # State=4 is Running. Numeric CIM enum avoids localized schtasks status strings.
        if not LABEL.fullmatch(label.lstrip("\\")):
            raise ManagerError("예약 이름을 확인할 수 없습니다.", 409)
        script = "[int](Get-ScheduledTask -TaskPath '\\' -TaskName '" + label.lstrip("\\") + "' -ErrorAction Stop).State"
        result = self.scheduler.call(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script])
        state = result.stdout.strip()
        if state not in ("1", "2", "3", "4"):
            raise ManagerError("Windows 예약 실행 상태를 확인할 수 없습니다. 종료하지 않고 보존합니다.", 409)
        return state in ("2", "4")

    def _windows_idle(self, label):
        if self._windows_running(label):
            raise ManagerError("대기·실행 중인 Windows 예약을 보존합니다.", 409)

    def remove(self, label, confirmation, *, current_installation=False):
        with self.store.maintenance_lock(False):
            return self._remove(label, confirmation, current_installation=current_installation)

    def _remove(self, label, confirmation, *, current_installation=False):
        scan = self.scan()
        if scan["errors"]:
            raise ManagerError("OS 조회 실패; 제거 중단: " + "; ".join(scan["errors"]), 502)
        row = next((r for r in scan["schedules"] if r["id"] == label), None)
        if not row or not row["owned"] or row["status"] == "unknown":
            raise ManagerError("소유권을 확인할 수 없는 예약은 제거할 수 없습니다.", 409)
        if current_installation:
            from runner.installation import installation
            if row["root"] != str(self.store.root) or row["installation_id"] not in (None, installation(self.store)["installation_id"]):
                raise ManagerError("다른 설치본 예약을 보존했습니다.", 409)
        elif row["status"] != "orphan":
            raise ManagerError("정상 예약은 doctor에서 제거할 수 없습니다. 원본 설치에서 해제하세요.", 409)
        if not confirmation or confirmation != row["fingerprint"]:
            raise ManagerError("진단 결과가 변경되었거나 명시적 확인 해시가 없습니다. 다시 진단하세요.", 409)
        if self.system == "Linux":
            if row.get("running"):
                raise ManagerError("실행 중인 systemd 서비스는 보존합니다. 강제 종료하지 않습니다.", 409)
            path = Path(row["path"])
            if path.is_symlink() or digest(path.read_bytes()) != row["definition_hash"]:
                raise ManagerError("systemd 제거 직전 정의 변경 감지; 예약을 보존합니다.", 409)
            latest = self._unit_state(label)
            if latest.get("DropInPaths") or latest.get("NeedDaemonReload") != "no" or latest.get("FragmentPath") != str(path):
                raise ManagerError("systemd 제거 직전 로드 정의 변경 감지; 보존합니다.", 409)
            if path.is_symlink() or digest(path.read_bytes()) != row["definition_hash"]:
                raise ManagerError("systemd 상태 조회 중 정의 변경 감지; 보존합니다.", 409)
            if label.endswith(".timer"):
                self._systemctl("stop", label)
                self._systemctl("disable", label)
            state = self._unit_state(label)
            if state.get("ActiveState") not in ("inactive", "failed"):
                raise ManagerError("systemd 예약이 아직 활성 상태입니다. 파일과 데이터는 보존합니다.", 502)
            if label.endswith(".timer"):
                enabled = self._systemctl("is-enabled", label, check=False)
                if enabled.returncode != 1 or enabled.stdout.strip() != "disabled":
                    raise ManagerError("systemd timer 비활성화 검증 실패; 파일과 데이터를 보존합니다.", 502)
            path = Path(row["path"])
            if path.is_symlink() or digest(path.read_bytes()) != row["definition_hash"]:
                raise ManagerError("systemd 유닛 변경 감지; 파일을 보존합니다.", 409)
            path.unlink()
            self._systemctl("daemon-reload")
            state = self._unit_state(label)
            if path.exists() or state.get("LoadState") != "not-found" or state.get("ActiveState") not in ("inactive", "failed"):
                raise ManagerError("systemd OS 해제를 검증하지 못했습니다. 데이터를 보존합니다.", 502)
        elif self.system == "Windows":
            self._windows_idle(label)
            latest = self.scheduler.call(["schtasks", "/Query", "/TN", label, "/XML"])
            if digest(latest.stdout.encode("utf-8")) != row["definition_hash"]:
                raise ManagerError("Windows 제거 직전 예약 변경 감지; 보존합니다.", 409)
            self.scheduler.call(["schtasks", "/Delete", "/TN", label, "/F"])
            check = self.scan()
            if check["errors"] or any(r["id"].lower() == label.lower() for r in check["schedules"]):
                raise ManagerError("Windows OS 예약 해제를 검증하지 못했습니다. 데이터는 보존합니다.", 502)
        else:
            if row.get("running"):
                raise ManagerError("예약 프로세스가 실행 중입니다. 강제 종료하지 않고 보존합니다.", 409)
            path = Path(row["path"])
            if path.is_symlink() or digest(path.read_bytes()) != row["definition_hash"]:
                raise ManagerError("제거 직전 plist 변경 감지; 예약을 보존합니다.", 409)
            if row["loaded"]:
                latest = self.scheduler.call(["launchctl", "print", self._service(label)], False)
                try:
                    loaded_hash = self._mac_loaded(latest, path, plistlib.loads(path.read_bytes()))
                except (ValueError, OSError, plistlib.InvalidFileException) as exc:
                    raise ManagerError("제거 직전 launchd 실행 정의 변경 감지; 보존합니다.", 409) from exc
                if loaded_hash != row["loaded_definition_hash"] or latest.returncode != 0 or re.search(r"^\s*pid = [1-9][0-9]*\s*$", latest.stdout, re.M):
                    raise ManagerError("제거 직전 실행 상태가 바뀌었습니다. 예약과 데이터를 보존합니다.", 409)
                if path.is_symlink() or digest(path.read_bytes()) != row["definition_hash"]:
                    raise ManagerError("launchd 상태 조회 중 plist 변경 감지; 보존합니다.", 409)
                self.scheduler.call(["launchctl", "bootout", self._service(label)])
            check = self.scheduler.call(["launchctl", "print", self._service(label)], False)
            if check.returncode != 113:
                raise ManagerError("launchd 예약 해제를 검증하지 못했습니다. plist와 데이터는 보존합니다.", 502)
            if path.is_symlink() or digest(path.read_bytes()) != row["definition_hash"]:
                raise ManagerError("제거 도중 plist 변경 감지; 파일과 데이터는 보존합니다.", 409)
            path.unlink()
            if path.exists():
                raise ManagerError("plist 제거를 확인하지 못했습니다.", 502)
        return {"removed": label, "verified": True}
