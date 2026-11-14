"""Explicit preview/confirmation reset and uninstall preparation for one data root."""
from contextlib import ExitStack
import os
from pathlib import Path
import re
import stat
import sys

from runner.common import ManagerError, contained, read_json
from runner.installation import installation
from runner.schedule_doctor import ScheduleDoctor, fingerprint

# These paths are reserved user data. Never remove deployments/ (it also holds code).
DATA_PATHS = ("workspace", "reports", "exports", "deployments/packages", "deployments/history",
              "deployments/targets.yaml", "deployments/targets.local.yaml", ".env")
PRESERVED_RUNTIME = {"locks", "installation.json", "doctor-notice.json"}


class Maintenance:
    def __init__(self, store, doctor=None):
        self.store = store
        self.doctor = doctor or ScheduleDoctor(store)

    def targets(self):
        paths = [p for p in self.store.jobs.iterdir() if p.name != ".gitkeep"]
        paths += [p for p in self.store.runtime.iterdir() if p.name not in PRESERVED_RUNTIME]
        paths += [self.store.root / name for name in DATA_PATHS if os.path.lexists(self.store.root / name)]
        return sorted(paths)

    def _inventory(self, path):
        """Stat only: never read .env or other user content for a deletion preview."""
        records = []
        device = self.store.root.stat().st_dev
        def inspect(entry):
            value = entry.lstat()
            if (stat.S_ISLNK(value.st_mode) or getattr(value, "st_file_attributes", 0) & 0x400
                    or not (stat.S_ISREG(value.st_mode) or stat.S_ISDIR(value.st_mode))):
                raise ManagerError("심볼릭 링크 또는 특수 파일은 초기화할 수 없습니다: " + str(entry), 409)
            if value.st_dev != device or entry.is_mount():
                raise ManagerError("별도 볼륨 데이터는 보존합니다: " + str(entry), 409)
            if entry.is_dir() and any((entry / marker).exists() for marker in
                    ("runner/__main__.py", "runtime/installation.json", ".script-manager-installation.json", ".git")):
                raise ManagerError("중첩된 프로그램 설치본을 보존합니다: " + str(entry), 409)
            records.append([str(entry.relative_to(self.store.root)), value.st_ino, value.st_mode,
                            value.st_size, value.st_mtime_ns, value.st_dev, value.st_ctime_ns])
        contained(self.store.root, str(path.relative_to(self.store.root)), True)
        inspect(path)
        if path.is_dir():
            def failed(exc):
                raise exc
            for base, dirs, files in os.walk(path, followlinks=False, onerror=failed):
                dirs.sort()
                for name in sorted(dirs + files):
                    inspect(Path(base) / name)
        if sys.platform == "linux":
            # ismount() alone misses same-device bind mounts.
            mounts = Path("/proc/self/mountinfo").read_text().splitlines()
            for line in mounts:
                mounted = Path(re.sub(r"\\([0-7]{3})", lambda m: chr(int(m[1], 8)), line.split()[4]))
                if mounted == path or path in mounted.parents:
                    raise ManagerError("마운트된 데이터 경로를 보존합니다: " + str(mounted), 409)
        return records

    def _delete_tree(self, path, records, anchors, progress):
        """Delete only approved entries; never recursively consume newly added children."""
        expected = {r[0]: r for r in records}
        def matches(value, record, directory=False):
            actual = [record[0], value.st_ino, value.st_mode, value.st_size,
                      value.st_mtime_ns, value.st_dev, value.st_ctime_ns]
            if getattr(value, "st_file_attributes", 0) & 0x400:
                return False
            return all(actual[i] == record[i] for i in ((1, 2, 5) if directory else range(1, 7)))
        posix = os.name == "posix"
        with ExitStack() as resources:
            root_fd = None
            if posix:
                root_fd = os.open(self.store.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                resources.callback(os.close, root_fd)
                if not matches(os.fstat(root_fd), anchors["."], True):
                    raise ManagerError("데이터 루트가 승인 이후 교체되었습니다.", 409)
            for relative in sorted(expected, key=lambda p: (len(Path(p).parts), p), reverse=True):
                record = expected[relative]
                directory = stat.S_ISDIR(record[2])
                parent_fd = root_fd
                with ExitStack() as parents:
                    parent = Path(relative).parent
                    if posix:
                        walked = Path()
                        for part in parent.parts:
                            walked /= part
                            parent_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd)
                            parents.callback(os.close, parent_fd)
                            if not matches(os.fstat(parent_fd), anchors[str(walked)], True):
                                raise ManagerError("상위 데이터 경로가 교체되었습니다: " + str(walked), 409)
                        value = os.stat(Path(relative).name, dir_fd=parent_fd, follow_symlinks=False)
                    else:
                        # Windows: reject junctions/reparse points as well as symlinks.
                        target = contained(self.store.root, relative, True)
                        for ancestor in [self.store.root, *reversed(target.parent.parents), target.parent]:
                            if ancestor == self.store.root or self.store.root in ancestor.parents:
                                key = str(ancestor.relative_to(self.store.root))
                                if not matches(ancestor.lstat(), anchors[key], True):
                                    raise ManagerError("상위 데이터 경로가 교체되었습니다.", 409)
                        value = target.lstat()
                    if not matches(value, record, directory):
                        raise ManagerError("승인 이후 데이터 변경 감지: " + relative, 409)
                    if posix:
                        (os.rmdir if directory else os.unlink)(Path(relative).name, dir_fd=parent_fd)
                    else:
                        (target.rmdir if directory else target.unlink)()
                    progress.append(str(self.store.root / relative))

    def _job_ids(self):
        ids = {p.name for p in self.store.jobs.iterdir() if p.is_dir()}
        ids.update(p.name for p in (self.store.runtime / "runs").glob("*") if p.is_dir())
        for path in (self.store.runtime / "locks").glob("*.run*"):
            ids.add(path.name.split(".")[0])
        return sorted(j for j in ids if re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", j))

    def active(self):
        active = []
        for path in sorted((self.store.runtime / "runs").glob("*/*/run.json")):
            record = read_json(contained(self.store.runtime, str(path.relative_to(self.store.runtime)), True))
            if not isinstance(record, dict) or record.get("state") not in ("succeeded", "failed", "cancelled", "timed_out", "interrupted"):
                active.append({"path": str(path), "state": record.get("state", "unknown") if isinstance(record, dict) else "unknown"})
        # Also detect unrecorded work / post-processing after terminal state publication.
        for job_id in self._job_ids():
            try:
                with self.store.job_lock(job_id, "run", False):
                    pass
            except ManagerError:
                active.append({"job_id": job_id, "state": "locked"})
        for path in sorted((self.store.root / "deployments/history").glob("*/*/*.json")):
            receipt = read_json(contained(self.store.root, str(path.relative_to(self.store.root)), True))
            if not isinstance(receipt, dict) or receipt.get("status") != "verified":
                active.append({"path": str(path), "state": "deployment-unconfirmed"})
        for path in sorted((self.store.runtime / "schedules").glob("*.json")):
            state = read_json(contained(self.store.runtime, str(path.relative_to(self.store.runtime)), True))
            if isinstance(state, dict) and state.get("phase") in ("applying", "degraded"):
                active.append({"path": str(path), "state": state["phase"]})
        return active

    def preview(self, mode="reset"):
        if mode not in ("reset", "uninstall"):
            raise ManagerError("지원하지 않는 초기화 종류입니다.")
        with self.store.maintenance_lock(False):
            identity = installation(self.store)
            active = self.active()
            scan = self.doctor.scan()
            current = [r for r in scan["schedules"] if r.get("root") == str(self.store.root) or r["id"].lstrip("\\").startswith(("local.scriptmanager." + self.doctor.scheduler.namespace + ".", "scriptmanager-" + self.doctor.scheduler.namespace + "-"))]
            blockers = list(scan["errors"])
            if active:
                blockers.append("대기·실행 중이거나 상태가 불명확한 Job이 있습니다. 강제 종료하지 않습니다.")
            for row in current:
                if (row.get("kind") == "systemd" or not row["owned"] or row["status"] == "unknown" or row.get("running")
                        or row.get("root") != str(self.store.root)
                        or row.get("installation_id") not in (None, identity["installation_id"])):
                    blockers.append("예약의 소유권/실행 상태를 확인해야 합니다: " + row["id"])
            inventory, paths = [], []
            for path in self.targets():
                try:
                    entries = self._inventory(path)
                    inventory.extend(entries)
                    paths.append({"path": str(path), "entries": len(entries),
                                  "bytes": sum(e[3] for e in entries if stat.S_ISREG(e[2])),
                                  "fingerprint": fingerprint(entries)})
                except (ManagerError, OSError) as exc:
                    blockers.append(str(exc))
            if not scan["supported"]:
                for path in (self.store.runtime / "schedules").glob("*.json"):
                    value = read_json(path, {})
                    if value.get("applied") or value.get("phase") in ("applying", "degraded"):
                        blockers.append("이 OS에서 해제할 수 없는 예약 기록이 있습니다: " + str(path))
            result = {"mode": mode, "root": str(self.store.root), "installation_id": identity["installation_id"],
                      "active_runs": active, "schedules": current, "doctor": scan,
                      "delete": paths, "blockers": blockers,
                      "preserve": ["프로그램 코드·.git·.venv·예제·문서", "설치 ID·안정된 잠금 파일",
                                   "외부/사용자 지정 보고서 경로·미등록 루트 파일", "다른 설치본과 원격 서버·SSH 키"],
                      "warning": ".env 자격증명, Job 소스, Output/State/Workspace, 휴지통, Package 및 배포 이력은 영구 삭제됩니다. 복구할 수 없습니다."}
            result["plan_hash"] = fingerprint({"mode": mode, "identity": identity, "inventory": inventory,
                                               "root_identity": [self.store.root.stat().st_dev, self.store.root.stat().st_ino],
                                               "schedules": current, "blockers": blockers})
            result["confirmation"] = "미리보기를 검토한 후 --confirm " + result["plan_hash"] + " 로 명시적으로 승인하세요."
            return result

    def execute(self, mode, confirmation):
        removed, deleted, deleted_entries = [], [], []
        phase = "preflight"
        with self.store.maintenance_lock(False), ExitStack() as guards:
            plan = self.preview(mode)
            if not confirmation or confirmation != plan["plan_hash"]:
                raise ManagerError("삭제 대상이 변경되었거나 명시적 확인 해시가 없습니다. 미리보기를 다시 확인하세요.", 409)
            if plan["blockers"]:
                raise ManagerError("초기화 중단: " + "; ".join(plan["blockers"]), 409)
            for job_id in self._job_ids():
                guards.enter_context(self.store.job_lock(job_id, "run", False))
            approved = {entry["path"]: self._inventory(Path(entry["path"])) for entry in plan["delete"]}
            anchors = {record[0]: record for records in approved.values() for record in records}
            for target in plan["delete"]:
                for parent in [self.store.root, *Path(target["path"]).parents]:
                    if parent == self.store.root or self.store.root in parent.parents:
                        value = parent.lstat()
                        anchors.setdefault(str(parent.relative_to(self.store.root)), [str(parent.relative_to(self.store.root)),
                            value.st_ino, value.st_mode, value.st_size, value.st_mtime_ns, value.st_dev, value.st_ctime_ns])
            try:
                phase = "remove-schedules"
                for row in plan["schedules"]:
                    removed.append(self.doctor.remove(row["id"], row["fingerprint"], current_installation=True))
                phase = "verify-schedules"
                scan = self.doctor.scan()
                prefix = ("local.scriptmanager." + self.doctor.scheduler.namespace + ".", "scriptmanager-" + self.doctor.scheduler.namespace + "-")
                if scan["errors"] or any(r["id"].lstrip("\\").startswith(prefix) for r in scan["schedules"]):
                    raise ManagerError("OS 예약이 남아 있거나 해제 검증에 실패했습니다. 사용자 데이터 삭제를 중단합니다.", 502)
                phase = "verify-data-plan"
                if {str(p) for p in self.targets()} != set(approved):
                    raise ManagerError("예약 해제 중 삭제 대상이 변경되었습니다. 새 미리보기가 필요합니다.", 409)
                for entry in plan["delete"]:
                    if fingerprint(self._inventory(Path(entry["path"]))) != entry["fingerprint"]:
                        raise ManagerError("예약 해제 중 사용자 데이터가 변경되었습니다: " + entry["path"], 409)
                phase = "delete-data"
                for entry in plan["delete"]:
                    path = Path(entry["path"])
                    if fingerprint(self._inventory(path)) != entry["fingerprint"]:
                        raise ManagerError("삭제 직전 사용자 데이터 변경 감지: " + str(path), 409)
                    self._delete_tree(path, approved[str(path)], anchors, deleted_entries)
                    deleted.append(str(path))
                phase = "verify-data"
                remaining = [str(p) for p in self.targets()]
                if remaining:
                    raise ManagerError("삭제 대상 데이터가 남아 있습니다.", 500)
                # Keep the same Store/Dashboard usable, retaining the existing lock inodes.
                from runner.store import Store
                Store(self.store.root)
                result = {"success": True, "mode": mode, "phase": "complete", "removed_schedules": removed,
                          "deleted": deleted, "deleted_entries": deleted_entries, "remaining": [], "root": str(self.store.root)}
                if mode == "uninstall":
                    result["next_steps"] = ["이 설치본의 Dashboard가 있다면 정상 종료하고 이 터미널 명령이 끝날 때까지 기다리세요.",
                                            "백업과 외부 보고서·원격 배포 데이터를 별도로 확인하세요.",
                                            "그 뒤 파일 탐색기에서 프로젝트 폴더를 삭제하세요. 실행 중인 프로그램은 자신의 코드를 삭제하지 않습니다.",
                                            "--root로 코드와 데이터를 분리했다면 위 root는 데이터 폴더입니다. 코드 폴더는 별도로 확인하세요."]
                return result
            except (ManagerError, OSError, ValueError) as exc:
                return {"success": False, "mode": mode, "phase": phase, "error": str(exc),
                        "removed_schedules": removed, "deleted": deleted, "deleted_entries": deleted_entries,
                        "remaining": [str(p) for p in self.targets()],
                        "recovery": "실패 원인을 해결하고 새 미리보기를 확인하세요. 자동 재실행·강제 종료는 하지 않았습니다."}
