"""Standalone SSH transaction helper and OS-invoked runner; never a daemon."""
import base64
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import uuid


def sha(data):
    return hashlib.sha256(data).hexdigest()


def valid_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", value):
        raise ValueError("Invalid identifier")
    return value


def safe(base, rel):
    base = Path(base)
    part = Path(rel)
    if part.is_absolute() or ".." in part.parts:
        raise ValueError("Unsafe relative path")
    result = base / part
    current = result
    while current != base:
        if current.is_symlink():
            raise ValueError("Symlinks are not allowed")
        current = current.parent
    return result


def atomic(path, data):
    path = Path(path)
    if path.is_symlink():
        raise ValueError("Refusing to overwrite symlink")
    if isinstance(data, str):
        data = data.encode()
    fd, temp = tempfile.mkstemp(dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, path)
        fd = os.open(str(path.parent), os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def save(path, value):
    atomic(path, json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n")


def load(path, default=None):
    return json.loads(path.read_text()) if path.exists() else default


@contextlib.contextmanager
def locked(path, blocking=True):
    fd = os.open(str(path), os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        yield
    finally:
        os.close(fd)


class Controller:
    def __init__(self, root, job_id, home=None, command=None, create=False):
        self.root = Path(root)
        if not self.root.is_absolute() or not re.fullmatch(r"/[A-Za-z0-9_./-]+", str(self.root)) or ".." in self.root.parts:
            raise ValueError("Invalid deployment root")
        cursor = self.root
        while cursor != cursor.parent:
            if cursor.is_symlink():
                raise ValueError("Deployment path must not contain symlinks")
            cursor = cursor.parent
        if create:
            self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if not self.root.is_dir() or self.root.stat().st_uid != os.getuid():
            raise ValueError("Deployment root must be owned by the SSH user")
        self.job_id = valid_id(job_id)
        self.job = safe(self.root, self.job_id)
        if create:
            self.job.mkdir(mode=0o700, exist_ok=True)
            for relative in ("releases", "shared", "shared/logs"):
                safe(self.job, relative).mkdir(mode=0o700, exist_ok=True)
        self.releases = safe(self.job, "releases")
        self.shared = safe(self.job, "shared")
        self.home = Path(home) if home else Path.home()
        self.units = safe(self.home, ".config/systemd/user")
        if create:
            self.units.mkdir(parents=True, exist_ok=True)
        self.command = command or subprocess.run
        self.label = "scriptmanager-" + sha(str(self.root).encode())[:12] + "-" + self.job_id
        self.journal = safe(self.job, "activation.json")

    def call(self, args, check=True):
        result = self.command(args, capture_output=True, text=True, timeout=20)
        if check and result.returncode:
            raise RuntimeError("Command failed: " + " ".join(args[:3]) + ": " + result.stderr[:1500])
        return result

    def systemctl(self, *args, check=True):
        return self.call(["systemctl", "--user", *args], check)

    def preflight(self):
        self.systemctl("show-environment")
        linger = self.call(["loginctl", "show-user", str(os.getuid()), "-p", "Linger", "--value"])
        if linger.stdout.strip() != "yes":
            raise ValueError("Enable user lingering once with an administrator before deploying")

    def release_path(self, release):
        return safe(self.releases, valid_id(release))

    def current(self):
        path = self.job / "current"
        if not path.is_symlink():
            if path.exists():
                raise ValueError("current must be a managed symlink")
            return None
        target = path.resolve()
        if target.parent != self.releases.resolve():
            raise ValueError("current points outside releases")
        return valid_id(target.name)

    def link(self, release):
        path = self.job / "current"
        if release is None:
            if path.is_symlink():
                path.unlink()
            return
        temp = self.job / (".current-" + uuid.uuid4().hex)
        temp.symlink_to("releases/" + valid_id(release))
        os.replace(temp, path)

    def unit_text(self, release, config):
        directory = self.release_path(release)
        def quote(value):
            return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%") + '"'
        start = " ".join(quote(v) for v in (sys.executable, directory / "manager/remote_runtime.py",
                                           "run", self.job, release))
        service = ("[Unit]\nDescription=Script Manager " + self.job_id + "\n[Service]\nType=exec\n"
                   "ExecStart=" + start + "\nRestart=no\nKillMode=control-group\nUMask=0077\n"
                   "Environment=PATH=/usr/local/bin:/usr/bin:/bin\n"
                   "TimeoutStopSec=5\nRuntimeMaxSec=" + str(config.get("timeout_seconds", 300) + 10) + "\n")
        units = {self.label + ".service": service}
        entries = config.get("schedules")
        if entries is None:
            legacy = config.get("schedule", {"enabled": False})
            entry = {"id": None, "enabled": legacy["enabled"], "type": legacy.get("mode", "calendar"),
                     "times": legacy.get("times", []), "weekdays": legacy.get("weekdays", list(range(1, 8)))}
            if entry["type"] == "interval":
                entry["interval_seconds"] = legacy["interval"]["value"] * {"minutes": 60, "hours": 3600, "days": 86400}[legacy["interval"]["unit"]]
            entries = [entry]
        for schedule in entries:
            sid = schedule["id"]
            label = self.label + ("-schedule-" + valid_id(sid) if sid else "")
            # One service per schedule keeps monotonic intervals independent. All use run.lock.
            if sid:
                units[label + ".service"] = service.replace("ExecStart=" + start, "ExecStart=" + start + " " + quote(sid))
            timer = None
            if schedule["enabled"]:
                if schedule["type"] == "interval":
                    seconds = str(schedule["interval_seconds"]) + "s"
                    lines = ["OnActiveSec=" + seconds, "OnUnitActiveSec=" + seconds]
                else:
                    days = ",".join(["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][d - 1]
                                    for d in schedule.get("weekdays", range(1, 8)))
                    lines = ["OnCalendar=" + days + " *-*-* " + t + ":00" for t in schedule.get("times", [])]
                timer = ("[Unit]\nDescription=Script Manager timer " + self.job_id + "\n[Timer]\nUnit=" + label + ".service\n" +
                         "\n".join(lines) + "\nPersistent=false\nAccuracySec=1s\n[Install]\nWantedBy=timers.target\n")
            units[label + ".timer"] = timer
        return units

    def stage(self, info, files):
        fields = {k: v for k, v in info.items() if k not in ("plan_hash", "release")}
        if sha(json.dumps(fields, sort_keys=True, ensure_ascii=False).encode()) != info["plan_hash"]:
            raise ValueError("Plan checksum mismatch")
        if info["job_id"] != self.job_id or info["target"]["root"] != str(self.root):
            raise ValueError("Plan destination mismatch")
        if info["release"] != "r-" + info["plan_hash"][:24]:
            raise ValueError("Release ID mismatch")
        release = info["release"]
        dest = self.release_path(release)
        if dest.exists():
            manifest = self.verify_release(release)
            if manifest["plan"] != info:
                raise ValueError("Release collision")
            return release
        staging = safe(self.releases, ".incoming-" + uuid.uuid4().hex)
        staging.mkdir(mode=0o700)
        try:
            if set(files) != set(info["files"]):
                raise ValueError("Payload file list mismatch")
            total = 0
            for relative, meta in files.items():
                if not relative.startswith(("source/", "manager/")):
                    raise ValueError("Invalid release file")
                data = base64.b64decode(meta["data"], validate=True)
                total += len(data)
                if total > 110 * 1024 * 1024 or sha(data) != info["files"][relative]["sha256"]:
                    raise ValueError("File checksum or size mismatch")
                mode = info["files"][relative]["mode"]
                if type(mode) is not int or mode & ~0o777:
                    raise ValueError("Unsafe file mode")
                path = safe(staging, relative)
                path.parent.mkdir(parents=True, exist_ok=True)
                atomic(path, data)
                path.chmod(mode & 0o700)
            atomic(staging / "config.json", json.dumps(info["config"], sort_keys=True))
            units = self.unit_text(release, info["config"])
            (staging / "units").mkdir()
            for name, content in units.items():
                if content is not None:
                    atomic(staging / "units" / name, content)
            save(staging / "manifest.json", {
                "plan": info, "config_sha256": sha((staging / "config.json").read_bytes()),
                "units": {k: sha(v.encode()) if v is not None else None for k, v in units.items()}})
            # Validate units and calendar without running any job script.
            paths = [str(staging / "units" / n) for n, text in units.items() if text is not None]
            self.call(["systemd-analyze", "--user", "verify", *paths])
            for text in units.values():
                if text:
                    for line in text.splitlines():
                        if line.startswith("OnCalendar="):
                            self.call(["systemd-analyze", "calendar", "--iterations=1", line.split("=", 1)[1]])
            os.rename(staging, dest)
            self.verify_release(release)
            return release
        finally:
            if staging.exists():
                shutil.rmtree(staging)

    def verify_release(self, release):
        directory = self.release_path(release)
        manifest = load(safe(directory, "manifest.json"))
        if not manifest:
            raise ValueError("Release manifest not found")
        for relative, meta in manifest["plan"]["files"].items():
            path = safe(directory, relative)
            if not path.is_file() or sha(path.read_bytes()) != meta["sha256"]:
                raise ValueError("Release file mismatch: " + relative)
            if stat.S_IMODE(path.stat().st_mode) != meta["mode"] & 0o700:
                raise ValueError("Release file permission mismatch: " + relative)
        if sha(safe(directory, "config.json").read_bytes()) != manifest["config_sha256"]:
            raise ValueError("Configuration checksum mismatch")
        for name, expected in manifest["units"].items():
            path = safe(directory, "units/" + name)
            if expected and (not path.is_file() or sha(path.read_bytes()) != expected):
                raise ValueError("Release unit mismatch")
        return manifest

    def _verify(self):
        release = self.current()
        if release is None:
            raise ValueError("No active release")
        journal = load(self.journal, {})
        if journal.get("phase") not in ("verified", "verifying"):
            raise ValueError("Activation is incomplete; inspect activation.json and roll back")
        manifest = self.verify_release(release)
        observed = {}
        timers = {}
        for name, expected in manifest["units"].items():
            path = safe(self.units, name)
            if expected is not None:
                if not path.is_file() or sha(path.read_bytes()) != expected:
                    raise ValueError("Installed unit mismatch: " + name)
                data = self.systemctl("show", name, "--property=LoadState,FragmentPath,NeedDaemonReload,ExecStart").stdout
                properties = dict(line.split("=", 1) for line in data.splitlines() if "=" in line)
                if properties.get("LoadState") != "loaded" or properties.get("FragmentPath") != str(path):
                    raise ValueError("Loaded unit mismatch: " + name)
                if properties.get("NeedDaemonReload") != "no":
                    raise ValueError("Unit configuration has not been reloaded: " + name)
                if name.endswith(".service") and str(self.release_path(release) / "manager/remote_runtime.py") not in properties.get("ExecStart", ""):
                    raise ValueError("Loaded executable does not match the release")
            elif path.exists():
                raise ValueError("Disabled timer still installed")
            if name.endswith(".timer"):
                enabled = self.systemctl("is-enabled", name, check=False).returncode == 0
                active = self.systemctl("is-active", name, check=False).returncode == 0
                if enabled != bool(expected) or active != bool(expected):
                    raise ValueError("Timer enabled/active state mismatch")
                timers[name] = {"enabled": enabled, "active": active}
        for name in journal.get("retired_units", []):
            if safe(self.units, name).exists():
                raise ValueError("Retired unit still installed: " + name)
            if name.endswith(".timer") and (self.systemctl("is-enabled", name, check=False).returncode == 0 or
                                             self.systemctl("is-active", name, check=False).returncode == 0):
                raise ValueError("Retired timer still active: " + name)
        return {"release": release, "files_verified": True, "units_verified": True, "timers": timers,
                "timer_enabled": any(t["enabled"] for t in timers.values()),
                "timer_active": any(t["active"] for t in timers.values()), **observed}

    def verify(self):
        with locked(safe(self.job, "operation.lock")):
            return self._verify()

    def activate(self, release, recovery=False):
        with locked(safe(self.job, "operation.lock")), locked(safe(self.job, "run.lock"), False):
            return self._activate(release, recovery)

    def execution_preflight(self, release):
        directory = self.release_path(release)
        config = load(safe(directory, "config.json"))
        cwd = safe(directory / "source", config.get("cwd", "."))
        if not cwd.is_dir():
            raise ValueError("Working directory does not exist")
        if config.get("env_file"):
            secret = safe(self.shared, config["env_file"])
            if not secret.is_file() or secret.stat().st_mode & 0o077:
                raise ValueError("Provision the shared env_file with mode 600 before deployment")
        program = config["command"][0]
        if "/" in program:
            executable = Path(program) if Path(program).is_absolute() else cwd / program
            if not executable.is_file() or not os.access(executable, os.X_OK):
                raise ValueError("Executable is not available")
        elif shutil.which(program, path=config.get("env", {}).get("PATH", "/usr/local/bin:/usr/bin:/bin")) is None:
            raise ValueError("Executable is not available on remote PATH")

    def _activate(self, release, recovery):
        manifest = self.verify_release(release)
        self.execution_preflight(release)
        previous = self.current()
        old_journal = load(self.journal, {})
        if old_journal and old_journal.get("phase") not in ("verified", "rolled_back_empty") and not recovery:
            raise ValueError("An interrupted deployment needs explicit rollback")
        old = {}
        old_manifest = (self.verify_release(previous) if not recovery else load(self.release_path(previous) / "manifest.json", {})) if previous else None
        names = set(manifest["units"]) | set(old_manifest["units"] if old_manifest else {})
        if recovery:
            names.update(old_journal.get("previous_units", {}))
        for name in sorted(names):
            path = safe(self.units, name)
            data = path.read_bytes() if path.exists() else None
            if not recovery:
                expected = old_manifest["units"].get(name) if old_manifest else None
                if (sha(data) if data is not None else None) != expected:
                    raise ValueError("Externally modified unit preserved: " + name)
            old[name] = base64.b64encode(data).decode() if data is not None else None
        timers = sorted(name for name in names if name.endswith(".timer"))
        services = sorted(name for name in names if name.endswith(".service"))
        for service in services:
            if self.systemctl("is-active", service, check=False).returncode == 0:
                raise ValueError("Job service is still running")
        states = {timer: {"enabled": self.systemctl("is-enabled", timer, check=False).returncode == 0,
                          "active": self.systemctl("is-active", timer, check=False).returncode == 0} for timer in timers}
        journal = {"phase": "applying", "previous": previous, "release": release,
                   "previous_units": old, "previous_timers": states,
                   "retired_units": sorted(names - set(manifest["units"]))}
        save(self.journal, journal)
        try:
            for timer, state in states.items():
                self.systemctl("stop", timer, check=state["active"])
                if state["enabled"]:
                    self.systemctl("disable", timer)
            for name in sorted(names):
                path = safe(self.units, name)
                expected = manifest["units"].get(name)
                if expected is None:
                    path.unlink(missing_ok=True)
                else:
                    atomic(path, (self.release_path(release) / "units" / name).read_bytes())
            self.link(release)
            self.systemctl("daemon-reload")
            for timer in timers:
                if manifest["units"].get(timer) is not None:
                    self.systemctl("enable", "--now", timer)
            journal["phase"] = "verifying"
            save(self.journal, journal)
            result = self._verify()
            journal["phase"] = "verified"
            save(self.journal, journal)
            return result
        except Exception as exc:
            journal["error"] = str(exc)
            try:
                for timer in timers:
                    self.systemctl("stop", timer, check=False)
                    self.systemctl("disable", timer, check=False)
                for name, encoded in old.items():
                    path = safe(self.units, name)
                    if encoded is None:
                        path.unlink(missing_ok=True)
                    else:
                        atomic(path, base64.b64decode(encoded))
                self.link(previous)
                self.systemctl("daemon-reload")
                for timer, state in states.items():
                    if state["enabled"]:
                        self.systemctl("enable", timer)
                    if state["active"]:
                        self.systemctl("start", timer)
                if previous:
                    journal.update(phase="verifying", release=previous,
                                   retired_units=sorted(names - set(old_manifest["units"])))
                    save(self.journal, journal)
                    self._verify()
                    journal["phase"] = "verified"
                else:
                    journal["phase"] = "rolled_back_empty"
                save(self.journal, journal)
            except Exception as rollback:
                journal.update(phase="degraded", rollback_error=str(rollback))
                save(self.journal, journal)
            raise


def run_job(job_path, release, schedule_id=None):
    controller = Controller(Path(job_path).parent, Path(job_path).name)
    with contextlib.ExitStack() as running:
        with locked(safe(controller.job, "operation.lock"), False):
            running.enter_context(locked(safe(controller.job, "run.lock"), False))
            if controller.current() != release or load(controller.journal, {}).get("phase") != "verified":
                raise ValueError("Stale or incomplete release invocation")
            controller.verify_release(release)
            directory = controller.release_path(release)
            config = load(directory / "config.json")
            if schedule_id is not None and not any(s["id"] == schedule_id and s["enabled"] for s in config.get("schedules", [])):
                raise ValueError("Stale or disabled Schedule invocation")
            sys.path.insert(0, str(directory / "manager"))
            from runner.common import now, write_json
            from runner.execution import environment, monitor
            import signal
            state = {"id": uuid.uuid4().hex, "job_id": controller.job_id, "release": release,
                     "state": "running", "started_at": now()}
            logs = safe(controller.shared, "logs/" + state["id"])
            logs.mkdir(mode=0o700)
            write_json(logs / "run.json", state)
            stop = [False]
            for sig in (signal.SIGTERM, signal.SIGINT):
                signal.signal(sig, lambda *_: stop.__setitem__(0, True))
        return run_locked(controller, config, directory, logs, state, stop)


def run_locked(controller, config, directory, logs, state, stop):
    from runner.common import now, write_json
    from runner.execution import environment, monitor
    try:
        command = config["command"]
        env = environment(config, controller.shared)
        if config.get("parameters"):
            from runner.parameters import CONTRACT_VERSION, resolve_parameters, parameter_command, encode_parameters
            applied = resolve_parameters(config)
            command = parameter_command(config, applied)
            state.update(parameters=applied, parameter_contract_version=CONTRACT_VERSION,
                         config=config, resolved_command=command)
            env["SCRIPT_MANAGER_PARAMETERS"] = encode_parameters(applied)
        state.update(monitor(command, safe(directory / "source", config.get("cwd", ".")),
                             env,
                             config.get("timeout_seconds", 300), logs,
                             lambda: stop[0], lambda _: None))
    except Exception as exc:
        state.update(state="failed", error=str(exc))
    state["finished_at"] = now()
    write_json(logs / "run.json", state)
    return 0 if state["state"] == "succeeded" else 1


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "run":
        return run_job(sys.argv[2], sys.argv[3], sys.argv[4] if len(sys.argv) > 4 else None)
    try:
        request = json.load(sys.stdin)
        if not sys.platform.startswith("linux") or sys.version_info < (3, 9):
            raise ValueError("Remote runtime requires Linux and Python 3.9+")
        action = request["action"]
        if action not in ("deploy", "rollback", "verify"):
            raise ValueError("Unsupported action")
        controller = Controller(request["root"], request["job_id"], create=action == "deploy")
        controller.preflight()
        if action == "deploy":
            with locked(safe(controller.job, "deployment.lock"), False):
                release = controller.stage(request["info"], request["files"])
                result = controller.activate(release)
        elif action == "rollback":
            with locked(safe(controller.job, "deployment.lock"), False):
                result = controller.activate(request["release"], recovery=True)
        else:
            result = controller.verify()
        print(json.dumps({"ok": True, "result": result}))
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
