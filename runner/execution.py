"""Detached, bounded local processes. No task queue or resident agent."""
import json
import os
from pathlib import Path
import re
import selectors
import shutil
import signal
import stat
import subprocess
import sys
import time
import threading
import uuid

from runner.common import ManagerError, contained, digest, identifier, now, read_json, write_json

EXCLUDED = {".git", ".venv", "venv", "node_modules", "__pycache__", ".DS_Store"}
LOG_LIMIT = 5 * 1024 * 1024
SOURCE_LIMIT = 100 * 1024 * 1024


def source_files(folder, env_file=None, exclude=None):
    result = {}
    total = 0
    for base, dirs, files in os.walk(folder, followlinks=False):
        for name in dirs + files:
            p = Path(base) / name
            if p.is_symlink():
                raise ManagerError("Job 스냅샷에 심볼릭 링크를 포함할 수 없습니다: " + str(p))
        dirs[:] = [d for d in dirs if d not in EXCLUDED and not d.startswith(".")
                   and not (exclude and exclude(str((Path(base) / d).relative_to(folder)), True))]
        for name in sorted(files):
            path = Path(base) / name
            rel = str(path.relative_to(folder))
            if exclude and exclude(rel, False):
                continue
            if (name.startswith(".env") or name.endswith((".pem", ".key", ".log", ".pyc")) or
                    rel == env_file or name in EXCLUDED):
                continue
            if not stat.S_ISREG(path.stat().st_mode):
                raise ManagerError("일반 파일만 포함할 수 있습니다.")
            total += path.stat().st_size
            if total > SOURCE_LIMIT or len(result) >= 10000:
                raise ManagerError("Job 스냅샷은 100 MiB·10,000개 파일 이하여야 합니다.")
            result[rel] = {"sha256": digest(path.read_bytes()),
                           "mode": stat.S_IMODE(path.stat().st_mode)}
    return result


def snapshot(folder, dest, env_file=None, exclude=None):
    before = source_files(folder, env_file, exclude)
    dest.mkdir(parents=True, mode=0o700)
    for rel in before:
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(folder / rel, target, follow_symlinks=False)
    if before != source_files(folder, env_file, exclude) or before != source_files(dest, env_file, exclude):
        raise ManagerError("스냅샷 생성 중 Job 파일이 변경되었습니다. 다시 시도하세요.", 409)
    return before


def read_environment_file(path):
    if os.name != "nt" and path.stat().st_mode & 0o077:
        raise ManagerError(".env 권한을 600으로 제한하세요.")
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, sep, value = line.partition("=")
        if not sep or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key) or "\x00" in value:
            raise ManagerError(".env는 KEY=value 형식이어야 합니다.")
        values[key] = value
    return values


def environment(config, secret_base, project_root=None):
    keys = ("HOME", "PATH", "LANG", "TMPDIR")
    if os.name == "nt":
        keys += ("SystemRoot", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP", "USERPROFILE",
                 "APPDATA", "LOCALAPPDATA", "PROGRAMDATA", "HOMEDRIVE", "HOMEPATH")
    env = {k: os.environ[k] for k in keys if k in os.environ}
    env.setdefault("PATH", os.defpath if os.name == "nt" else "/usr/local/bin:/usr/bin:/bin")
    env.update(config.get("env", {}))
    names = config.get("required_env")  # Job parser already validated the captured configuration.
    if names is not None:
        if project_root is None:
            raise ManagerError("required_env에는 프로젝트 루트 경로가 필요합니다.")
        if config.get("env_file"):
            raise ManagerError("required_env와 Job별 env_file은 함께 사용할 수 없습니다.")
        path = contained(project_root, ".env")
        values = read_environment_file(path) if path.exists() else {}
        missing = [name for name in names if not values.get(name, "").strip()]
        if missing:
            raise ManagerError("프로젝트 루트 .env의 필수 환경변수 미설정: " + ", ".join(missing))
        env.update({name: values[name] for name in names})
    elif config.get("env_file"):
        path = contained(secret_base, config["env_file"], True)
        env.update(read_environment_file(path))
    return env


def monitor(command, cwd, env, timeout, directory, cancelled, heartbeat, lockfd=None):
    """Bound output while draining pipes; kill the entire child process group."""
    if os.name == "nt":
        return monitor_windows(command, cwd, env, timeout, directory, cancelled, heartbeat)
    proc = subprocess.Popen(command, cwd=str(cwd), env=env, stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True,
                            pass_fds=() if lockfd is None else (lockfd,))
    selector = selectors.DefaultSelector()
    outputs = {}
    deadline = time.monotonic() + timeout
    stop_time = None
    reason = None
    last_heartbeat = 0
    try:
        for name, pipe in (("stdout", proc.stdout), ("stderr", proc.stderr)):
            f = (directory / (name + ".log")).open("wb")
            outputs[pipe.fileno()] = [f, 0]
            selector.register(pipe, selectors.EVENT_READ)
        while selector.get_map() or proc.poll() is None:
            current = time.monotonic()
            if current - last_heartbeat > 1:
                heartbeat(proc.pid)
                last_heartbeat = current
            if stop_time is None and (cancelled() or current >= deadline):
                reason = "cancelled" if cancelled() else "timed_out"
                stop_time = current
                try:
                    os.killpg(proc.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
            if stop_time is not None and current - stop_time >= 3:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            for key, _ in selector.select(0.1):
                data = os.read(key.fileobj.fileno(), 65536)
                if not data:
                    selector.unregister(key.fileobj)
                    key.fileobj.close()
                else:
                    output = outputs[key.fd]
                    allowed = max(0, LOG_LIMIT - output[1])
                    output[0].write(data[:allowed])
                    output[0].flush()
                    output[1] += len(data)
            # A script exiting with descendants must not leave background work behind.
            if proc.poll() is not None and stop_time is None:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        code = proc.wait()
        return {"state": reason or ("succeeded" if code == 0 else "failed"),
                "exit_code": code, "logs_truncated": any(x[1] > LOG_LIMIT for x in outputs.values())}
    finally:
        selector.close()
        for output in outputs.values():
            output[0].close()
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait()
        for pipe in (proc.stdout, proc.stderr):
            pipe.close()


def monitor_windows(command, cwd, env, timeout, directory, cancelled, heartbeat):
    """Drain Windows pipes with threads; stop the process tree on cancel or timeout."""
    executable = sys.executable if command[0].lower() == "python3" else command[0]
    if not Path(executable).is_absolute() and (Path(cwd) / executable).is_file():
        executable = str(Path(cwd) / executable)
    command = [executable, *command[1:]]
    proc = subprocess.Popen(command, cwd=str(cwd), env=env, stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
    job = WindowsJob(proc)
    totals = {"stdout": 0, "stderr": 0}
    readers = []
    def drain(name, pipe):
        with (directory / (name + ".log")).open("wb") as output:
            while True:
                data = pipe.read(65536)
                if not data:
                    break
                allowed = max(0, LOG_LIMIT - totals[name])
                output.write(data[:allowed])
                output.flush()
                totals[name] += len(data)
        pipe.close()
    for name, pipe in (("stdout", proc.stdout), ("stderr", proc.stderr)):
        reader = threading.Thread(target=drain, args=(name, pipe), daemon=True)
        reader.start()
        readers.append(reader)
    deadline = time.monotonic() + timeout
    reason = None
    try:
        while proc.poll() is None:
            heartbeat(proc.pid)
            if cancelled() or time.monotonic() >= deadline:
                reason = "cancelled" if cancelled() else "timed_out"
                if job.assigned:
                    job.terminate()
                else:
                    try:
                        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                                       capture_output=True, timeout=20)
                    except (OSError, subprocess.TimeoutExpired):
                        pass
                if proc.poll() is None:
                    proc.kill()
                break
            time.sleep(0.1)
        code = proc.wait()
        job.close()
        for reader in readers:
            reader.join(timeout=10)
        return {"state": reason or ("succeeded" if code == 0 else "failed"),
                "exit_code": code, "logs_truncated": any(size > LOG_LIMIT for size in totals.values())}
    finally:
        if proc.poll() is None:
            if job.assigned:
                job.terminate()
            else:
                try:
                    subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                                   capture_output=True, timeout=20)
                except (OSError, subprocess.TimeoutExpired):
                    pass
                if proc.poll() is None:
                    proc.kill()
            proc.wait()
        job.close()


class WindowsJob:
    """Own descendants so closing the worker also ends its process tree."""
    def __init__(self, proc):
        import ctypes
        from ctypes import wintypes

        class BasicLimits(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong),
                        ("PerJobUserTimeLimit", ctypes.c_longlong), ("LimitFlags", wintypes.DWORD),
                        ("MinimumWorkingSetSize", ctypes.c_size_t), ("MaximumWorkingSetSize", ctypes.c_size_t),
                        ("ActiveProcessLimit", wintypes.DWORD), ("Affinity", ctypes.c_size_t),
                        ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]
        class IoCounters(ctypes.Structure):
            _fields_ = [(name, ctypes.c_ulonglong) for name in
                        ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                         "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]
        class ExtendedLimits(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", BasicLimits), ("IoInfo", IoCounters),
                        ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                        ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]
        self.kernel = ctypes.windll.kernel32
        self.kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        self.kernel.CreateJobObjectW.restype = ctypes.c_void_p
        self.kernel.SetInformationJobObject.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        self.kernel.AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        self.kernel.TerminateJobObject.argtypes = [ctypes.c_void_p, wintypes.UINT]
        self.kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        self.handle = self.kernel.CreateJobObjectW(None, None)
        self.assigned = False
        if self.handle:
            limits = ExtendedLimits()
            limits.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if self.kernel.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
                self.assigned = bool(self.kernel.AssignProcessToJobObject(self.handle, int(proc._handle)))
            if not self.assigned:
                self.close()

    def terminate(self):
        if self.assigned and self.handle:
            self.kernel.TerminateJobObject(self.handle, 1)

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


class Execution:
    def __init__(self, store):
        self.store = store

    def start(self, job_id, trigger="manual", generation=None, schedule_id=None, *, parameters=None):
        with self.store.job_lock(job_id, "operation"), self.store.job_lock(job_id, "run", False) as lockfd:
            with self.store.job_lock(job_id):
                item = self.store.get(job_id)
                config = item["config"]
                from runner.parameters import CONTRACT_VERSION, resolve_parameters, parameter_command
                applied = resolve_parameters(config, parameters)
                command = parameter_command(config, applied)
                if generation:
                    from runner.schedule import Scheduler
                    from runner.store import schedules, schedule_hash
                    state = Scheduler(self.store).state(job_id, schedule_id)
                    if not state.get("applied") or state.get("generation") != generation:
                        raise ManagerError("이전 스케줄 호출이므로 실행하지 않습니다.", 409)
                    entry = next((s for s in schedules(config) if s["id"] == (schedule_id or "legacy")), None)
                    if not entry or not entry["enabled"] or (
                        state.get("schedule_hash") != schedule_hash(entry) if state.get("schedule_hash")
                        else state.get("etag") != item["etag"]
                    ):
                        raise ManagerError("예약 설정이 변경되었습니다. 해당 Schedule을 다시 적용하세요.", 409)
                run_id = uuid.uuid4().hex
                directory = contained(self.store.runtime / "runs", job_id)
                directory.mkdir(exist_ok=True)
                directory = directory / run_id
                directory.mkdir(mode=0o700)
                try:
                    manifest = snapshot(self.store.job_dir(job_id), directory / "source", config.get("env_file"))
                    if manifest.get("job.yaml", {}).get("sha256") != item["etag"]:
                        raise ManagerError("스냅샷 생성 전 설정이 변경되었습니다.", 409)
                    contained(directory / "source", config.get("cwd", "."), True)
                    environment(config, self.store.job_dir(job_id), self.store.root)  # never persist secrets
                    record = {"id": run_id, "job_id": job_id, "state": "queued",
                              "trigger": trigger, "schedule_id": schedule_id, "created_at": now(), "config": config,
                              "config_etag": item["etag"], "manifest": manifest}
                    if config.get("parameters"):
                        record.update(parameters=applied, parameter_contract_version=CONTRACT_VERSION,
                                      resolved_command=command)
                    from runner.lifecycle import Lifecycle
                    Lifecycle(self.store).paths(job_id, run_id, create=True)
                    record["managed_output"] = "runtime/job-data/" + job_id + "/output/" + run_id
                    write_json(directory / "run.json", record)
                    package_root = Path(__file__).resolve().parent.parent
                    if os.name == "nt":
                        lease = self.store.runtime / "locks" / (job_id + ".run.active")
                        fd = os.open(str(lease), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                        with os.fdopen(fd, "w") as file:
                            json.dump({"run_id": run_id, "pid": 0, "created": time.time()}, file)
                    process = subprocess.Popen(
                        [sys.executable, "-m", "runner", "--root", str(self.store.root),
                         "_worker", job_id, run_id, str(-1 if os.name == "nt" else lockfd)],
                        cwd=str(package_root), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL, **({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt"
                                                  else {"start_new_session": True, "pass_fds": (lockfd,)}))
                    if os.name == "nt" and lease.exists():
                        write_json(lease, {"run_id": run_id, "pid": process.pid, "created": time.time()})
                    threading.Thread(target=process.wait, daemon=True).start()
                except Exception:
                    if os.name == "nt":
                        (self.store.runtime / "locks" / (job_id + ".run.active")).unlink(missing_ok=True)
                    shutil.rmtree(directory)
                    raise
        return record

    def worker(self, job_id, run_id, lockfd):
        directory = self.run_dir(job_id, run_id)
        record = read_json(directory / "run.json")
        stopping = [False]
        if os.name != "nt":
            for sig in (signal.SIGTERM, signal.SIGINT):
                signal.signal(sig, lambda *_: stopping.__setitem__(0, True))
        try:
            record.update(state="running", started_at=now(), worker_pid=os.getpid())
            write_json(directory / "run.json", record)
            config = record["config"]

            def heartbeat(pid):
                record.update(heartbeat_at=now(), pid=pid)
                write_json(directory / "run.json", record)

            from runner.lifecycle import Lifecycle
            env = environment(config, self.store.job_dir(job_id), self.store.root)
            env.update(Lifecycle(self.store).paths(job_id, run_id, create=True))
            if record.get("parameter_contract_version") == 1:
                from runner.parameters import encode_parameters
                env["SCRIPT_MANAGER_PARAMETERS"] = encode_parameters(record["parameters"])
            result = monitor(record.get("resolved_command", config["command"]),
                             contained(directory / "source", config.get("cwd", "."), True),
                             env,
                             config.get("timeout_seconds", 300), directory,
                             lambda: stopping[0] or (directory / "cancel").exists(), heartbeat, lockfd)
            record.update(result)
            if (result["state"] == "succeeded" and result.get("exit_code") == 0
                    and config.get("report", {}).get("enabled", False)):
                # Post-processing is independent of the script's exit status. Publish terminal
                # Run state only after this finishes, so CLI/HTTP observers see its outcome.
                from runner.reports import Reports
                try:
                    record["report"] = Reports(self.store).generate_run(job_id, record)
                    if record["report"].get("warning"):
                        try:
                            with (directory / "stderr.log").open("ab") as log:
                                log.write(("\n[report] " + record["report"]["warning"] + "\n").encode("utf-8"))
                        except OSError:
                            pass
                except Exception as exc:
                    record["report"] = {"state": "failed", "error": str(exc), "finished_at": now()}
                    try:
                        with (directory / "stderr.log").open("ab") as log:
                            log.write(("\n[report] HTML 생성 실패: " + str(exc) + "\n").encode("utf-8"))
                    except OSError:
                        pass  # Report diagnostics must never change the Job result.
            elif config.get("report", {}).get("enabled", False):
                record["report"] = {"state": "skipped", "reason": "job_not_succeeded"}
        except Exception as exc:
            record.update(state="failed", error=str(exc))
        finally:
            record["finished_at"] = now()
            write_json(directory / "run.json", record)
            if os.name == "nt":
                lease = self.store.runtime / "locks" / (job_id + ".run.active")
                if read_json(lease, {}).get("run_id") == run_id:
                    lease.unlink(missing_ok=True)
            elif lockfd >= 0:
                os.close(lockfd)
            try:
                Lifecycle(self.store).automatic(job_id)
            except Exception as exc:
                record["lifecycle_error"] = str(exc)
                write_json(directory / "run.json", record)

    def run_dir(self, job_id, run_id):
        identifier(job_id)
        if not isinstance(run_id, str) or len(run_id) != 32 or any(c not in "0123456789abcdef" for c in run_id):
            raise ManagerError("잘못된 실행 ID입니다.")
        return contained(self.store.runtime / "runs", job_id + "/" + run_id, True)

    def get(self, job_id, run_id):
        directory = self.run_dir(job_id, run_id)
        record = read_json(directory / "run.json")
        if record is None:
            raise ManagerError("실행 기록이 없습니다.", 404)
        if record["state"] in ("queued", "running"):
            try:
                with self.store.job_lock(job_id, "run", False):
                    # A worker may have finished between our first read and lock
                    # acquisition. Never overwrite its terminal state with a stale read.
                    record = read_json(directory / "run.json")
                    if record["state"] in ("queued", "running"):
                        record.update(state="interrupted", finished_at=now(),
                                      error="실행 프로세스 종료 후 결과가 기록되지 않았습니다.")
                        write_json(directory / "run.json", record)
            except ManagerError as exc:
                if exc.status != 409:
                    raise
        return record

    def list(self, job_id):
        directory = contained(self.store.runtime / "runs", identifier(job_id))
        if not directory.exists():
            return []
        return sorted([self.get(job_id, p.name) for p in directory.iterdir()
                       if p.is_dir() and (p / "run.json").exists()],
                      key=lambda r: r["created_at"], reverse=True)

    def cancel(self, job_id, run_id):
        record = self.get(job_id, run_id)
        if record["state"] not in ("queued", "running"):
            raise ManagerError("이미 종료된 실행입니다.", 409)
        (self.run_dir(job_id, run_id) / "cancel").touch(mode=0o600)
        return {"cancel_requested": run_id}

    def logs(self, job_id, run_id, stream="stdout", offset=0):
        if stream not in ("stdout", "stderr") or type(offset) is not int or offset < 0:
            raise ManagerError("잘못된 로그 요청입니다.")
        directory = self.run_dir(job_id, run_id)
        path = contained(directory, stream + ".log")
        if not path.exists():
            return {"text": "", "offset": offset, "truncated": False}
        with path.open("rb") as f:
            f.seek(offset)
            data = f.read(65536)
        return {"text": data.decode("utf-8", errors="replace"), "offset": offset + len(data),
                "truncated": path.stat().st_size >= LOG_LIMIT}
