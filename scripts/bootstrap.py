"""Inspect or prepare a checkout-local runtime; never operate Jobs or services.

Standard library only, Python 3.9+. Run without --prepare before any changes.
An incomplete venv without a working interpreter is preserved for diagnosis.
"""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys


DATA_PATHS = ("jobs", "runtime", "workspace", "reports", "exports", ".env",
              "deployments/targets.yaml", "deployments/targets.local.yaml",
              "deployments/packages", "deployments/history")
PROBE = """
import importlib.util, json, re, sys
from importlib.metadata import distributions
# Python 3.9 metadata lookup can miss dotted names stored with underscores.
def normalize(name):
    return re.sub(r'[-_.]+', '-', name).lower()
installed = {normalize(d.metadata['Name']): d.version for d in distributions() if d.metadata['Name']}
versions = {name: installed.get(normalize(name)) for name in json.loads(sys.argv[1])}
print(json.dumps(dict(prefix=sys.prefix, base_prefix=sys.base_prefix,
                     version=list(sys.version_info[:3]),
                     pip=importlib.util.find_spec('pip') is not None,
                     versions=versions)))
"""


def venv_python(root, windows=None):
    windows = sys.platform == "win32" if windows is None else windows
    return root / ".venv" / ("Scripts/python.exe" if windows else "bin/python")


def requirements(root):
    """Only exact runtime pins are supported; fail closed on contract changes."""
    pins = {}
    for line in (root / "requirements.txt").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)==([A-Za-z0-9_.+!-]+)", line)
        if not match or match[1] in pins:
            raise ValueError("Unsupported requirements format; review bootstrap before installing")
        pins[match[1]] = match[2]
    if not pins:
        raise ValueError("No runtime pins found")
    return pins


def inspect(root):
    root = Path(root).absolute()
    pins = requirements(root)
    data = []
    for name in DATA_PATHS:
        path = root / name
        if path.exists() or path.is_symlink():
            # An empty tracked Jobs scaffold is not operating data.
            if name == "jobs" and path.is_dir() and not path.is_symlink():
                if all(item.name == ".gitkeep" for item in path.iterdir()):
                    continue
            data.append(name)
    python = venv_python(root)
    result = {"root": str(root), "python": str(python), "data_paths": data,
              "runtime_ready": False, "example_verification": "not_performed"}
    folder = root / ".venv"
    try:
        # Windows junctions are reparse points even on Python <3.12, where
        # Path.is_junction is unavailable. Never prepare an external environment.
        redirected = folder.is_symlink() or bool(getattr(folder.lstat(), "st_file_attributes", 0) & 0x400)
    except FileNotFoundError:
        redirected = False
    if redirected:
        return dict(result, state="unsafe_venv")
    if not folder.exists():
        return dict(result, state="missing_venv")
    if not python.is_file() or not (folder / "pyvenv.cfg").is_file():
        return dict(result, state="partial_venv")
    try:
        probe = subprocess.run([str(python), "-I", "-B", "-c", PROBE, json.dumps(list(pins))],
                               cwd=root, capture_output=True, text=True, timeout=30, check=True)
        details = json.loads(probe.stdout)
        if (Path(details["prefix"]).resolve() != folder.resolve()
                or details["prefix"] == details["base_prefix"]
                or details["version"][:2] < [3, 9]):
            return dict(result, state="unsafe_venv")
        ready = details["pip"] and details["versions"] == pins
        if ready:
            ready = subprocess.run([str(python), "-I", "-B", "-m", "pip", "--disable-pip-version-check", "check"],
                                   cwd=root, capture_output=True, timeout=30).returncode == 0
        return dict(result, state="ready" if ready else "needs_dependencies",
                    runtime_ready=bool(ready), interpreter=details)
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError):
        return dict(result, state="broken_venv")


def step(root, phase, argv):
    print(json.dumps({"phase": phase}), flush=True)
    # argv and shell=False avoid PS 5.1 quoting/JSON/space-path differences.
    # No progress/cursor rendering; no profile or global pip configuration changes.
    environment = dict(os.environ, PIP_PROGRESS_BAR="off", PIP_NO_COLOR="1", PIP_DISABLE_PIP_VERSION_CHECK="1",
                       PIP_NO_INPUT="1", PYTHONDONTWRITEBYTECODE="1")
    completed = subprocess.run([str(arg) for arg in argv], cwd=root, env=environment)
    if completed.returncode:
        raise RuntimeError("%s failed (exit %s); inspect and resume this checkout, do not reclone"
                           % (phase, completed.returncode))


def prepare(root):
    root = Path(root).absolute()
    status = inspect(root)
    if status["runtime_ready"]:
        return dict(status, changed=False)
    if status["data_paths"]:
        raise ValueError("Existing data detected; inspect with the CLI/UPDATE.md, no automatic repair")
    if status["state"] == "missing_venv":
        step(root, "venv", [sys.executable, "-m", "venv", root / ".venv"])
        status = inspect(root)
    if status["state"] not in ("ready", "needs_dependencies"):
        raise ValueError("Incomplete or unsafe .venv preserved; review its interpreter/config before recovery")
    python = venv_python(root)
    if not status["interpreter"]["pip"]:
        step(root, "ensurepip", [python, "-I", "-m", "ensurepip", "--upgrade"])
    step(root, "packaging-tools", [python, "-I", "-m", "pip", "install", "--upgrade",
                                   "--progress-bar", "off", "--no-color", "pip", "setuptools"])
    step(root, "requirements", [python, "-I", "-m", "pip", "install", "--progress-bar", "off",
                               "--no-color", "-r", root / "requirements.txt"])
    step(root, "pip-check", [python, "-I", "-m", "pip", "check"])
    status = inspect(root)
    if not status["runtime_ready"]:
        raise RuntimeError("Runtime verification failed; installation is incomplete")
    return dict(status, changed=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare", action="store_true", help="prepare only a new/partial runtime without data")
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    try:
        if sys.version_info < (3, 9):
            raise ValueError("Python 3.9+ is required")
        status = prepare(root) if args.prepare else inspect(root)
        print(json.dumps(status, ensure_ascii=True, indent=2))
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        print(json.dumps({"error": str(exc), "installation_complete": False}, ensure_ascii=True), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
