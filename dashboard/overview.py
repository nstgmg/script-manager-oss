"""Presentation of local executions and OS-backed reservations."""
from datetime import datetime, timedelta, timezone
import time

from runner.common import ManagerError, identifier


FAILURE_STATES = {"failed", "timed_out", "cancelled", "interrupted"}
ACTIVE_STATES = {"queued", "running"}


def timestamp(value):
    try:
        parsed = datetime.fromisoformat(value)
        return parsed.astimezone() if parsed.tzinfo else None
    except (TypeError, ValueError, OverflowError):
        return None


def next_calendar(schedule, current):
    """Find the next host-local wall time, skipping nonexistent DST times."""
    local = datetime.fromtimestamp(current)
    days = schedule.get("weekdays", list(range(1, 8)))
    for offset in range(8):
        day = (local + timedelta(days=offset)).date()
        if day.isoweekday() not in days:
            continue
        for clock in sorted(schedule.get("times", [])):
            try:
                hour, minute = map(int, clock.split(":"))
                candidate = datetime(day.year, day.month, day.day, hour, minute)
                for is_dst in (0, 1):
                    instant = time.mktime((*candidate.timetuple()[:8], is_dst))
                    if instant > current and datetime.fromtimestamp(instant) == candidate:
                        yield instant
            except (TypeError, ValueError, OverflowError):
                continue


def overview(store, execution, scheduler, period="today", job_id="", current=None):
    if period not in ("today", "7d", "30d"):
        raise ManagerError("기간은 today, 7d, 30d 중 하나여야 합니다.")
    current = time.time() if current is None else current
    local_now = datetime.fromtimestamp(current)
    start_day = local_now.date() - timedelta(days={"today": 0, "7d": 6, "30d": 29}[period])
    today = local_now.date()
    items = store.list()
    known = {item["id"]: item for item in items}
    run_root = store.runtime / "runs"
    run_ids = set(known)
    for folder in run_root.iterdir() if run_root.exists() else ():
        if folder.is_dir() and not folder.is_symlink():
            try:
                run_ids.add(identifier(folder.name))
            except ManagerError:
                continue
    if job_id and job_id not in run_ids:
        raise ManagerError("Job을 찾을 수 없습니다.", 404)

    summary = {"total": 0, "succeeded": 0, "failed": 0, "running": 0}
    timeline, upcoming, uncalculated, errors = [], [], [], []
    job_names = {jid: item.get("config", {}).get("name", jid) for jid, item in known.items()}
    for jid in sorted(run_ids):
        item = known.get(jid)
        try:
            runs = execution.list(jid)
        except (ManagerError, OSError, ValueError) as exc:
            errors.append({"job_id": jid, "message": str(exc)})
            runs = []
        for run in runs:
            if (not item or item.get("error")) and job_names.get(jid, jid) == jid:
                job_names[jid] = run.get("config", {}).get("name") or job_names.get(jid, jid)
            created = timestamp(run.get("created_at"))
            if created is None:
                continue
            state = run.get("state")
            if created.date() == today:
                summary["total"] += 1
                if state == "succeeded":
                    summary["succeeded"] += 1
                elif state in FAILURE_STATES:
                    summary["failed"] += 1
                elif state in ACTIVE_STATES:
                    summary["running"] += 1
            if (not job_id or jid == job_id) and created.date() >= start_day:
                started = timestamp(run.get("started_at"))
                finished = timestamp(run.get("finished_at"))
                end = finished or (datetime.fromtimestamp(current, timezone.utc) if state == "running" else None)
                duration = max(0, round((end - started).total_seconds())) if started and end else None
                timeline.append({"id": run["id"], "job_id": jid, "job_name": job_names[jid],
                                 "job_exists": bool(item and not item.get("error")),
                                 "job_note": "설정 오류" if item and item.get("error") else "삭제됨" if not item else "",
                                 "created_at": run["created_at"], "trigger": run.get("trigger", "manual"),
                                 "schedule_id": run.get("schedule_id"), "state": state, "duration_seconds": duration})
    for item in items:
        jid = item["id"]
        if item.get("error"):
            errors.append({"job_id": jid, "message": item["error"]})
            continue
        try:
            rows = scheduler.rows(jid)
        except (ManagerError, OSError, ValueError) as exc:
            errors.append({"job_id": jid, "message": str(exc)})
            continue
        for row in rows:
            schedule, state = row["schedule"], row["state"]
            if row.get("orphan") or not schedule.get("enabled") or not all(state.get(key) for key in
                    ("supported", "loaded", "applied", "file_matches", "desired_matches")) or state.get("os_disabled") or state.get("observation_error"):
                continue
            entry = {"job_id": jid, "job_name": item["config"]["name"],
                     "schedule_id": schedule["id"], "schedule_name": schedule["name"]}
            if schedule.get("type") == "calendar":
                instants = list(next_calendar(schedule, current))
                if instants:
                    next_at = min(instants)
                    upcoming.append({**entry, "next_at": datetime.fromtimestamp(next_at, timezone.utc).isoformat()})
                else:
                    uncalculated.append(entry)
            else:
                # launchd StartInterval has no stable anchor; do not invent one.
                uncalculated.append(entry)
    timeline.sort(key=lambda run: (timestamp(run["created_at"]).timestamp(), run["id"]), reverse=True)
    upcoming.sort(key=lambda row: (row["next_at"], row["job_id"], row["schedule_id"]))
    job_options = [{"id": jid, "name": name,
                    "note": "설정 오류" if known.get(jid, {}).get("error") else "삭제됨" if jid not in known else ""}
                   for jid, name in sorted(job_names.items(), key=lambda pair: (pair[1].casefold(), pair[0]))]
    return {"summary": summary, "timeline": timeline, "upcoming": upcoming[:3],
            "uncalculated": uncalculated, "errors": errors, "jobs": job_options}
