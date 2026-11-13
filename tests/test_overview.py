import os
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from dashboard.overview import next_calendar, overview


class FakeStore:
    runtime = Path(__file__).parent / "_nonexistent_runtime"

    def list(self):
        return [{"id": "alpha", "config": {"name": "Alpha"}},
                {"id": "beta", "config": {"name": "Beta"}}]


class FakeExecution:
    def __init__(self, records):
        self.records = records

    def list(self, job_id):
        return self.records.get(job_id, [])


class FakeScheduler:
    def __init__(self, rows):
        self.entries = rows

    def rows(self, job_id):
        return self.entries.get(job_id, [])


def run(run_id, date, state, trigger="manual", **extra):
    return {"id": run_id, "created_at": date.isoformat(), "state": state,
            "trigger": trigger, **extra}


def reservation(job, sid, clock, **state_changes):
    state = {"supported": True, "loaded": True, "applied": True,
             "file_matches": True, "desired_matches": True}
    state.update(state_changes)
    return {"job_id": job, "schedule": {"id": sid, "name": sid, "enabled": True,
            "type": "calendar", "times": [clock], "weekdays": list(range(1, 8))}, "state": state}


class OverviewTests(unittest.TestCase):
    def test_deleted_job_history_remains_counted_and_filterable(self):
        with tempfile.TemporaryDirectory() as temp:
            store = FakeStore()
            store.runtime = Path(temp)
            (store.runtime / "runs" / "retired").mkdir(parents=True)
            now = datetime.now(timezone.utc)
            records = {"retired": [run("old", now, "succeeded", config={"name": "이전 작업"})]}
            data = overview(store, FakeExecution(records), FakeScheduler({}), job_id="retired", current=now.timestamp())
            self.assertEqual(data["summary"]["total"], 1)
            self.assertEqual(data["timeline"][0]["job_name"], "이전 작업")
            self.assertFalse(data["timeline"][0]["job_exists"])
            self.assertIn({"id": "retired", "name": "이전 작업", "note": "삭제됨"}, data["jobs"])

    def test_today_counts_states_and_filters_timeline_without_filtering_summary(self):
        now = datetime.now(timezone.utc).astimezone().replace(hour=12, minute=0, second=0, microsecond=0)
        previous = now - timedelta(days=1)
        runs = {"alpha": [run("a", now, "succeeded", started_at=(now-timedelta(seconds=5)).isoformat(), finished_at=now.isoformat()),
                          run("b", now, "running"), run("c", previous, "failed")],
                "beta": [run("d", now, "failed", "schedule"), run("e", now, "queued"),
                         run("f", now, "timed_out"), run("g", now, "cancelled"), run("h", now, "interrupted") ]}
        current = now.timestamp()
        data = overview(FakeStore(), FakeExecution(runs), FakeScheduler({}), "today", "alpha", current)
        self.assertEqual(data["summary"], {"total": 7, "succeeded": 1, "failed": 4, "running": 2})
        self.assertEqual({row["id"] for row in data["timeline"]}, {"a", "b"})
        self.assertEqual(next(row for row in data["timeline"] if row["id"] == "a")["duration_seconds"], 5)
        self.assertEqual(len(overview(FakeStore(), FakeExecution(runs), FakeScheduler({}), "7d", current=current)["timeline"]), 8)
        self.assertEqual(len(overview(FakeStore(), FakeExecution(runs), FakeScheduler({}), "30d", current=current)["timeline"]), 8)
        self.assertEqual(data["upcoming"], [])

    def test_multiple_reservations_sort_and_exclude_unapplied_or_mismatched(self):
        now = datetime.now().replace(hour=7, minute=0, second=0, microsecond=0)
        rows = {"alpha": [reservation("alpha", "late", "11:00"), reservation("alpha", "early", "09:00"),
                          reservation("alpha", "bad", "08:00", desired_matches=False),
                          reservation("alpha", "inactive", "08:30")],
                "beta": [reservation("beta", "middle", "10:00"), reservation("beta", "fourth", "12:00"),
                         reservation("beta", "unloaded", "08:00", loaded=False),
                         reservation("beta", "disabled-os", "08:00", os_disabled=True),
                         reservation("beta", "file-mismatch", "08:00", file_matches=False)]}
        rows["beta"].append(reservation("beta", "orphan", "08:00"))
        rows["beta"][-1]["orphan"] = True
        rows["alpha"][3]["schedule"]["enabled"] = False
        rows["beta"].append({"job_id": "beta", "schedule": {"id": "interval", "name": "interval",
                             "enabled": True, "type": "interval", "interval_seconds": 60},
                             "state": rows["beta"][0]["state"].copy()})
        data = overview(FakeStore(), FakeExecution({}), FakeScheduler(rows), current=now.timestamp())
        self.assertEqual([r["schedule_id"] for r in data["upcoming"]], ["early", "middle", "late"])
        self.assertEqual([r["schedule_id"] for r in data["uncalculated"]], ["interval"])

    @unittest.skipUnless(hasattr(time, "tzset"), "host timezone override unavailable")
    def test_local_midnight_and_calendar_weekday_boundary(self):
        try:
            with patch.dict(os.environ, {"TZ": "Asia/Seoul"}):
                time.tzset()
                monday = datetime(2026, 11, 9, 23, 59).timestamp()
                entry = {"times": ["00:01"], "weekdays": [2]}
                self.assertEqual(datetime.fromtimestamp(min(next_calendar(entry, monday))), datetime(2026, 11, 10, 0, 1))
                tuesday = datetime(2026, 11, 10, 0, 2).timestamp()
                self.assertEqual(datetime.fromtimestamp(min(next_calendar(entry, tuesday))), datetime(2026, 11, 17, 0, 1))
        finally:
            time.tzset()

    @unittest.skipUnless(hasattr(time, "tzset"), "host timezone override unavailable")
    def test_nonexistent_dst_clock_is_skipped(self):
        try:
            with patch.dict(os.environ, {"TZ": "America/New_York"}):
                time.tzset()
                before = datetime(2026, 3, 8, 1, 59).timestamp()
                entry = {"times": ["02:30"], "weekdays": [7]}
                self.assertEqual(datetime.fromtimestamp(min(next_calendar(entry, before))), datetime(2026, 3, 15, 2, 30))
        finally:
            time.tzset()

    @unittest.skipUnless(hasattr(time, "tzset"), "host timezone override unavailable")
    def test_repeated_dst_clock_uses_remaining_occurrence(self):
        try:
            with patch.dict(os.environ, {"TZ": "America/New_York"}):
                time.tzset()
                first = time.mktime((2026, 11, 1, 1, 30, 0, 0, 0, 1))
                second = time.mktime((2026, 11, 1, 1, 30, 0, 0, 0, 0))
                self.assertGreater(second, first)
                entry = {"times": ["01:30"], "weekdays": [7]}
                self.assertEqual(min(next_calendar(entry, first + 60)), second)
        finally:
            time.tzset()


if __name__ == "__main__":
    unittest.main()
