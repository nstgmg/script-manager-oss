"""Stable installation identity and self-describing native schedule metadata."""
import json
from pathlib import Path
import re
import sys
import uuid

from runner.common import ManagerError, contained, lock, read_json, write_json

MARKER = "ScriptManagerMetadata"
DESCRIPTION = "Script Manager v1 "


def installation(store):
    path = contained(store.runtime, "installation.json")
    with lock(store.runtime / "locks" / "installation"):
        value = read_json(path)
        if value is None:
            value = {"version": 1, "installation_id": uuid.uuid4().hex, "root": str(store.root)}
            write_json(path, value)
        if (not isinstance(value, dict) or value.get("version") != 1 or value.get("root") != str(store.root)
                or not isinstance(value.get("installation_id"), str)
                or not re.fullmatch(r"[0-9a-f]{32}", value["installation_id"])):
            raise ManagerError("설치 ID가 손상되었거나 다른 경로에서 복사되었습니다. installation.json을 보존하고 확인하세요.", 409)
        return value


def metadata(store, job_id, schedule_id, generation):
    config = store.get(job_id)["config"]
    folder = store.job_dir(job_id) / config.get("cwd", ".")
    required = []
    for index, arg in enumerate(config["command"]):
        path = Path(arg)
        if index == 0 and path.is_absolute():
            required.append(str(path))
        elif not arg.startswith("-") and path.suffix.lower() in (".py", ".sh", ".ps1", ".bat", ".js"):
            required.append(str(path if path.is_absolute() else folder / path))
    return {"owner": "script-manager", "version": 1,
            "installation_id": installation(store)["installation_id"],
            "root": str(store.root), "code_root": str(Path(__file__).resolve().parent.parent),
            "executable": sys.executable, "required_files": required, "job_id": job_id,
            "schedule_id": schedule_id or "", "generation": generation}


def description(value):
    return DESCRIPTION + json.dumps(value, sort_keys=True, separators=(",", ":"))
