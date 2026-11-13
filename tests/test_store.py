from pathlib import Path
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor

from runner.common import ManagerError
from runner.store import Store, default_job, dump_yaml, load_yaml, validate


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(self.temp.name)
        self.job = self.store.create(default_job("sample", "샘플"))

    def test_discovery_invalid_job_does_not_hide_valid_jobs(self):
        p = self.store.jobs / "broken"
        p.mkdir()
        (p / "job.yaml").write_text("invalid: [")
        jobs = self.store.list()
        self.assertEqual(len(jobs), 2)
        self.assertIn("error", jobs[0])
        self.assertEqual(jobs[1]["config"]["name"], "샘플")

    def test_update_preserves_comments_and_rejects_stale_etag(self):
        text = "# keep this comment\n" + self.job["yaml"]
        self.store.update("sample", text, self.job["etag"])
        with self.assertRaises(ManagerError) as cm:
            self.store.update("sample", self.job["yaml"], self.job["etag"])
        self.assertEqual(cm.exception.status, 409)
        self.assertTrue(self.store.get("sample")["yaml"].startswith("# keep this comment"))
        self.assertTrue(list((self.store.runtime / "trash").glob("sample-*.yaml")))

    def test_delete_is_recoverable(self):
        result = self.store.delete("sample", self.job["etag"])
        self.assertFalse((self.store.jobs / "sample").exists())
        self.assertTrue((Path(result["recover_from"]) / "main.py").exists())

    def test_duplicate_keys_tags_bad_commands_and_traversal(self):
        for text in ("id: a\nid: b", "!!python/object:foo {}", "a: &x []\nb: *x"):
            with self.assertRaises(ManagerError):
                load_yaml(text)
        for patch in ({"id": "../bad"}, {"command": "echo bad"}, {"cwd": "../"},
                      {"timeout_seconds": True}, {"schedule": {"enabled": True, "times": ["24:00"]}},
                      {"env": {"SECRET": 123}}, {"extra": 1}):
            config = default_job("safe")
            config.update(patch)
            with self.assertRaises(ManagerError):
                validate(config)

    def test_symlink_and_id_mismatch(self):
        (self.store.jobs / "alias").symlink_to(self.store.jobs / "sample")
        with self.assertRaises(ManagerError):
            self.store.get("alias")
        p = self.store.jobs / "other"
        p.mkdir()
        (p / "job.yaml").write_text(self.job["yaml"])
        with self.assertRaises(ManagerError):
            self.store.get("other")

    def test_interval_schema_units_bounds_and_exclusive_modes(self):
        config = default_job("sample")
        for unit, seconds in (("minutes", 60), ("hours", 3600), ("days", 86400)):
            for enabled in (True, False):
                for amount in (1, 2147483647 // seconds):
                    schedule = {"enabled": enabled, "mode": "interval", "interval": {"value": amount, "unit": unit}}
                    config.pop("schedules", None)
                    config["schedule"] = schedule
                    self.assertEqual(validate(config)["schedule"], schedule)
            for amount in (0, -1, True, 1.5, "2", None, 2147483647 // seconds + 1):
                config.pop("schedules", None)
                config["schedule"] = {"enabled": False, "mode": "interval", "interval": {"value": amount, "unit": unit}}
                with self.subTest(unit=unit, amount=amount), self.assertRaises(ManagerError):
                    validate(config)
        interval = {"value": 2, "unit": "hours"}
        for schedule in (
            {"enabled": True, "interval": interval},
            {"enabled": True, "mode": "calendar", "interval": interval, "times": ["09:00"]},
            {"enabled": False, "mode": "interval", "interval": interval, "times": []},
            {"enabled": False, "mode": "interval", "interval": interval, "weekdays": [1]},
            {"enabled": False, "mode": "interval"},
            {"enabled": True, "mode": "interval", "interval": {"value": 1, "unit": "weeks"}},
            {"enabled": True, "mode": "interval", "interval": {"value": 1, "unit": [], "extra": 1}},
            {"enabled": False, "mode": "unknown"},
        ):
            config.pop("schedules", None)
            config["schedule"] = schedule
            with self.subTest(schedule=schedule), self.assertRaises(ManagerError):
                validate(config)

    def test_concurrent_writers_preserve_the_winner(self):
        def write(comment):
            try:
                return self.store.update("sample", self.job["yaml"] + "\n# " + comment + "\n", self.job["etag"])
            except ManagerError as exc:
                return exc.status
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(write, ("one", "two")))
        self.assertEqual(sum(isinstance(r, dict) for r in results), 1)
        self.assertEqual(sum(r == 409 for r in results), 1)
        winner = next(r for r in results if isinstance(r, dict))
        self.assertEqual(self.store.get("sample")["yaml"], winner["yaml"])

    def test_required_env_round_trip_existing_update_path_and_etag(self):
        result = self.store.update_fields("sample", {"required_env": ["ONE_API_KEY", "TWO_API_KEY"]},
                                          self.job["etag"])
        self.assertEqual(load_yaml(result["yaml"])["required_env"], ["ONE_API_KEY", "TWO_API_KEY"])
        self.assertEqual(result["config"]["schedules"], self.job["config"]["schedules"])
        self.assertFalse((self.store.job_dir("sample") / "job.json").exists())
        with self.assertRaises(ManagerError) as raised:
            self.store.update_fields("sample", {"required_env": []}, self.job["etag"])
        self.assertEqual(raised.exception.status, 409)

    def test_required_env_schema_rejects_invalid_names_and_legacy_file_conflict(self):
        for names in (None, "SECRET", ["ONE", "ONE"], ["BAD-NAME"], [12],
                      ["SCRIPT_MANAGER_STATE_DIR"], ["HAS\x00NULL"], ["KEY"] * 101):
            config = {**default_job("sample"), "required_env": names}
            with self.subTest(names=names), self.assertRaises(ManagerError):
                validate(config)
        with self.assertRaisesRegex(ManagerError, "함께"):
            validate({**default_job("sample"), "required_env": ["SECRET"], "env_file": ".env"})
        self.assertEqual(validate({**default_job("sample"), "required_env": []})["required_env"], [])
        self.assertNotIn("required_env", validate(default_job("sample")))
