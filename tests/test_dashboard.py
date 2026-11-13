import http.client
import json
import tempfile
import threading
import unittest
import time
from pathlib import Path
from unittest.mock import patch
from dashboard.server import Dashboard
from deployments.client import Deployment
from deployments.remote_runtime import Controller
from runner.schedule import Scheduler
from runner.store import dump_yaml
from tests.test_deployments import FakeSystemd
from tests.test_schedule import LaunchctlFake


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.server = Dashboard(self.temp.name, 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def request(self, method, path, data=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        body = json.dumps(data) if data is not None else None
        actual = {"Content-Type": "application/json", "X-CSRF-Token": self.server.token}
        actual.update(headers or {})
        connection.request(method, path, body, actual)
        response = connection.getresponse()
        result = response.read()
        connection.close()
        return response.status, result

    def test_run_routes_accept_then_observe_same_run_without_restarting(self):
        run_id = "a" * 32
        queued = {"id": run_id, "job_id": "sample", "state": "queued"}
        completed = dict(queued, state="succeeded", exit_code=0)
        log = {"text": "previous successful result", "offset": 26, "truncated": False}
        with patch("dashboard.server.Execution") as execution:
            engine = execution.return_value
            engine.start.return_value = queued
            engine.get.return_value = completed
            engine.logs.return_value = log
            status, raw = self.request("POST", "/api/jobs/sample/runs", {})
            self.assertEqual(status, 202)
            self.assertEqual(json.loads(raw), queued)
            self.assertNotIn("exit_code", json.loads(raw))
            status, raw = self.request("GET", "/api/jobs/sample/runs/" + run_id)
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(raw), completed)
            status, raw = self.request("GET", "/api/jobs/sample/runs/" + run_id + "/logs?stream=stderr&offset=7")
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(raw), log)
            engine.start.assert_called_once_with("sample")
            engine.get.assert_called_once_with("sample", run_id)
            engine.logs.assert_called_once_with("sample", run_id, "stderr", 7)

    def test_create_edit_conflict_delete_over_http(self):
        status, raw = self.request("POST", "/api/jobs", {"id": "sample", "name": "HTTP sample"})
        self.assertEqual(status, 201)
        job = json.loads(raw)
        status, _ = self.request("PUT", "/api/jobs/sample", {"yaml": job["yaml"] + "\n# edit\n", "etag": job["etag"]})
        self.assertEqual(status, 200)
        status, _ = self.request("PUT", "/api/jobs/sample", {"yaml": job["yaml"], "etag": job["etag"]})
        self.assertEqual(status, 409)
        status, raw = self.request("GET", "/api/jobs/sample")
        status, _ = self.request("DELETE", "/api/jobs/sample", {"etag": json.loads(raw)["etag"]})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(self.request("GET", "/api/jobs")[1]), [])

    def test_security_and_static_assets(self):
        self.assertEqual(self.request("GET", "/", headers={"Host": "evil.test"})[0], 403)
        self.assertEqual(self.request("POST", "/api/jobs", {}, {"X-CSRF-Token": ""})[0], 403)
        self.assertEqual(self.request("POST", "/api/jobs", {}, {"Origin": "https://evil.test"})[0], 403)
        self.assertEqual(self.request("GET", "/api/jobs/%2e%2e")[0], 400)
        for path in ("/", "/app.js", "/style.css"):
            status, raw = self.request("GET", path)
            self.assertEqual(status, 200)
            self.assertTrue(raw)

    def test_open_project_directory_is_fixed_and_protected(self):
        endpoint = "/api/project-directory/open"
        with patch("dashboard.server.subprocess.run") as run:
            for system, executable in [("Darwin", "open"), ("Windows", "explorer"), ("Linux", "xdg-open")]:
                with patch("dashboard.server.platform.system", return_value=system):
                    self.assertEqual(self.request("POST", endpoint, {})[0], 200)
                    self.assertEqual(run.call_args.args[0], [executable, str(self.server.store.root)])
            run.reset_mock()
            self.assertEqual(self.request("POST", endpoint, {"path": "/tmp"})[0], 400)
            self.assertEqual(self.request("POST", endpoint + "?path=/tmp", {})[0], 400)
            self.assertEqual(self.request("POST", endpoint, {}, {"X-CSRF-Token": ""})[0], 403)
            self.assertEqual(self.request("POST", endpoint, {}, {"Origin": "https://evil.test"})[0], 403)
            run.assert_not_called()
            run.side_effect = OSError("실행 실패")
            status, raw = self.request("POST", endpoint, {})
            self.assertEqual(status, 500)
            self.assertIn("프로젝트 폴더를 열지 못했습니다", json.loads(raw)["error"])

    def test_package_api_create_download_difference_and_reuse(self):
        self.request("POST", "/api/jobs", {"id": "sample"})
        status, raw = self.request("POST", "/api/jobs/sample/packages", {})
        self.assertEqual(status, 201, raw)
        package = json.loads(raw)
        package_id = package["id"]
        self.assertEqual(json.loads(self.request("GET", "/api/jobs/sample/packages")[1])[0]["id"], package_id)
        endpoint = "/api/jobs/sample/packages/" + package_id
        self.assertEqual(json.loads(self.request("GET", endpoint)[1])["content_hash"], package["content_hash"])
        first = self.request("GET", endpoint + "/download")
        self.assertEqual(first[0], 200)
        self.assertEqual(first[1], self.request("GET", endpoint + "/download")[1])
        (self.server.store.job_dir("sample") / "main.py").write_text("print('changed')\n")
        difference = json.loads(self.request("GET", endpoint + "/difference")[1])
        self.assertEqual(difference["modified"], ["main.py"])
        self.assertEqual(first[1], self.request("GET", endpoint + "/download")[1])
        self.assertEqual(self.request("GET", "/api/jobs/other/packages/" + package_id + "/download")[0], 409)
        for encoded_id in ("p%2Fa", "p%3Fa", "%2E%2E%2Fescape", "p%252Fa"):
            with self.subTest(encoded_id=encoded_id):
                self.assertEqual(self.request("GET", "/api/jobs/sample/packages/" + encoded_id + "/download")[0], 400)

    def test_trash_delete_list_restore_and_conflict_over_http(self):
        job = json.loads(self.request("POST", "/api/jobs", {"id": "sample", "name": "휴지통 검증"})[1])
        deleted = json.loads(self.request("DELETE", "/api/jobs/sample", {"etag": job["etag"]})[1])
        status, raw = self.request("GET", "/api/trash")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(raw)[0]["name"], "휴지통 검증")
        endpoint = "/api/trash/" + deleted["trash_id"] + "/restore"
        self.assertEqual(self.request("POST", endpoint, {}, {"X-CSRF-Token": ""})[0], 403)
        self.assertEqual(self.request("POST", endpoint, {})[0], 200)
        self.assertEqual(json.loads(self.request("GET", "/api/trash")[1]), [])
        deleted = json.loads(self.request("DELETE", "/api/jobs/sample", {"etag": job["etag"]})[1])
        self.request("POST", "/api/jobs", {"id": "sample", "name": "보존할 작업"})
        self.assertEqual(self.request("POST", "/api/trash/" + deleted["trash_id"] + "/restore", {})[0], 409)
        self.assertEqual(json.loads(self.request("GET", "/api/jobs/sample")[1])["config"]["name"], "보존할 작업")

    def test_package_deployment_http_contract_and_preflight_rejections(self):
        self.request("POST", "/api/jobs", {"id": "sample"})
        self.request("POST", "/api/jobs", {"id": "other"})
        root = self.server.store.root
        targets = root / "deployments/targets.yaml"
        targets.parent.mkdir(exist_ok=True)
        targets.write_text(dump_yaml({"version": 1, "targets": {
            "test": {"ssh_host": "never-contacted", "root": "/srv/script-manager-test"}}}))
        package = json.loads(self.request("POST", "/api/jobs/sample/packages", {})[1])["id"]
        other = json.loads(self.request("POST", "/api/jobs/other/packages", {})[1])["id"]
        endpoint = "/api/jobs/sample/"
        selection = {"target": "test", "package_id": package}
        with patch.object(Deployment, "_ssh", autospec=True, return_value={"ok": True}) as ssh:
            status, raw = self.request("POST", endpoint + "deploy-plan", selection)
            self.assertEqual(status, 200, raw)
            plan = json.loads(raw)
            self.assertEqual(plan["package_id"], package)
            ssh.assert_not_called()
            invalid = [("deploy-plan", {"target": "test"}, 400),
                       ("deploy-plan", dict(selection, package_id="../escape"), 400),
                       ("deploy-plan", dict(selection, package_id=other), 409),
                       ("deploy", dict(selection, plan_hash=plan["plan_hash"], package_id=other), 409),
                       ("deploy", selection, 409),
                       ("deploy", dict(selection, plan_hash="invalid"), 409)]
            for action, body, expected in invalid:
                with self.subTest(action=action, body=body):
                    status, raw = self.request("POST", endpoint + action, body)
                    self.assertEqual(status, expected, raw)
                    self.assertIn("error", json.loads(raw))
            targets.write_text(targets.read_text().replace("never-contacted", "changed-target"))
            status, raw = self.request("POST", endpoint + "deploy", dict(selection, plan_hash=plan["plan_hash"]))
            self.assertEqual(status, 409, raw)
            ssh.assert_not_called()
            self.assertEqual(Deployment(self.server.store).history("sample"), [])
            status, raw = self.request("POST", endpoint + "deploy-plan", selection)
            self.assertEqual(status, 200, raw)
            updated = json.loads(raw)
            self.assertNotEqual(updated["plan_hash"], plan["plan_hash"])
            status, raw = self.request("POST", endpoint + "deploy", dict(selection, plan_hash=updated["plan_hash"]))
            self.assertEqual(status, 200, raw)
            receipt = json.loads(raw)
            self.assertEqual(receipt["status"], "verified")
            self.assertEqual(receipt["package_id"], package)
            ssh.assert_called_once()
            self.assertEqual(ssh.call_args.args[2]["info"]["plan_hash"], updated["plan_hash"])

    def test_schedule_editor_save_conflict_apply_observe_and_restore_failure(self):
        scheduler = Scheduler(self.server.store, self.server.store.root / "agents", LaunchctlFake())
        with patch("dashboard.server.Scheduler", return_value=scheduler):
            job = json.loads(self.request("POST", "/api/jobs", {"id": "sample", "name": "예약"})[1])
            schedule = {"enabled": True, "times": ["10:15", "20:30"], "weekdays": [2, 5]}
            status, raw = self.request("PUT", "/api/jobs/sample", {"schedule": schedule, "etag": job["etag"]})
            self.assertEqual(status, 200)
            updated = json.loads(raw)
            self.assertEqual(updated["config"]["schedule"], schedule)
            self.assertEqual(self.request("PUT", "/api/jobs/sample", {"schedule": {"enabled": False}, "etag": job["etag"]})[0], 409)
            self.assertEqual(self.request("PUT", "/api/jobs/sample", {"schedule": {"enabled": True, "times": ["25:00"]}, "etag": updated["etag"]})[0], 400)
            self.assertEqual(self.request("PUT", "/api/jobs/sample", {"schedule": schedule})[0], 428)
            self.assertEqual(self.request("POST", "/api/jobs/sample/schedule", {"etag": updated["etag"]})[0], 200)
            state = json.loads(self.request("GET", "/api/jobs/sample/schedule")[1])["state"]
            self.assertTrue(state["loaded"])
            self.assertTrue(state["file_matches"])
            schedule["times"] = ["12:00"]
            newer = json.loads(self.request("PUT", "/api/jobs/sample", {"schedule": schedule, "etag": updated["etag"]})[1])
            state = json.loads(self.request("GET", "/api/jobs/sample/schedule")[1])["state"]
            self.assertNotEqual(state["etag"], newer["etag"])
            scheduler.command.fail_next_bootstrap = True
            self.assertEqual(self.request("POST", "/api/jobs/sample/schedule", {"etag": newer["etag"]})[0], 502)
            restored = json.loads(self.request("GET", "/api/jobs/sample/schedule")[1])["state"]
            self.assertEqual(restored["generation"], state["generation"])
            self.assertTrue(restored["loaded"])
            self.assertEqual(self.request("DELETE", "/api/jobs/sample/schedule", {})[0], 200)
            observed = json.loads(self.request("GET", "/api/jobs/sample/schedule")[1])["state"]
            self.assertFalse(observed["loaded"])
            self.assertFalse(observed["file_exists"])
            self.assertTrue(self.server.store.get("sample")["config"]["schedule"]["enabled"])

    def test_interval_calendar_round_trip_over_http(self):
        scheduler = Scheduler(self.server.store, self.server.store.root / "agents", LaunchctlFake())
        with patch("dashboard.server.Scheduler", return_value=scheduler), \
                patch("runner.schedule.platform.system", return_value="Darwin"):
            job = json.loads(self.request("POST", "/api/jobs", {"id": "sample", "name": "간격"})[1])
            original = {k: v for k, v in job["config"].items() if k not in ("schedule", "schedules")}
            for schedule in (
                {"enabled": True, "times": ["09:30"], "weekdays": [1, 7]},
                {"enabled": True, "mode": "interval", "interval": {"value": 3, "unit": "hours"}},
                {"enabled": False, "mode": "interval", "interval": {"value": 1, "unit": "days"}},
                {"enabled": True, "mode": "calendar", "times": ["18:00"], "weekdays": [2]},
            ):
                status, raw = self.request("PUT", "/api/jobs/sample", {"schedule": schedule, "etag": job["etag"]})
                self.assertEqual(status, 200, raw)
                job = json.loads(raw)
                self.assertEqual(job["config"]["schedule"], schedule)
                self.assertEqual({k: v for k, v in job["config"].items() if k != "schedule"}, original)
                self.assertEqual(self.request("POST", "/api/jobs/sample/schedule", {"etag": job["etag"]})[0], 200)
                state = json.loads(self.request("GET", "/api/jobs/sample/schedule")[1])["state"]
                self.assertEqual(state["loaded"], schedule["enabled"])
            invalid = {"enabled": True, "mode": "interval", "interval": {"value": 0, "unit": "minutes"}}
            self.assertEqual(self.request("PUT", "/api/jobs/sample", {"schedule": invalid, "etag": job["etag"]})[0], 400)
            self.assertEqual(self.server.store.get("sample")["etag"], job["etag"])
            self.assertEqual(self.request("DELETE", "/api/jobs/sample/schedule", {})[0], 200)
            self.assertEqual(self.server.store.get("sample")["config"]["schedule"], schedule)

    def test_job_settings_cannot_mutate_schedules_and_preserve_etag_contract(self):
        job = json.loads(self.request("POST", "/api/jobs", {"id": "sample"})[1])
        status, raw = self.request("PUT", "/api/jobs/sample", {"fields": {"command": ["python3", "main.py"], "env": {"MODE": "test"}, "timeout_seconds": 42}, "etag": job["etag"]})
        self.assertEqual(status, 200, raw)
        updated = json.loads(raw)
        self.assertEqual(updated["config"]["timeout_seconds"], 42)
        self.assertEqual(updated["config"]["schedules"], [])
        self.assertEqual(self.request("PUT", "/api/jobs/sample", {"fields": {"name": "stale"}, "etag": job["etag"]})[0], 409)
        self.assertEqual(self.request("PUT", "/api/jobs/sample", {"fields": {"schedules": []}, "etag": updated["etag"]})[0], 400)

    def test_multi_schedule_crud_and_failed_apply_over_http(self):
        from tests.test_multi_schedule import calendar, interval
        scheduler = Scheduler(self.server.store, self.server.store.root / "agents", LaunchctlFake())
        with patch("dashboard.server.Scheduler", return_value=scheduler), patch("runner.schedule.platform.system", return_value="Darwin"):
            job = json.loads(self.request("POST", "/api/jobs", {"id": "sample"})[1])
            self.assertEqual(job["config"]["schedules"], [])
            endpoint = "/api/jobs/sample/schedules"
            for entry in [calendar(), interval()]:
                status, raw = self.request("POST", endpoint, {"schedule": entry, "etag": job["etag"]})
                self.assertEqual(status, 201, raw)
                job = json.loads(raw)["job"]
            rows = json.loads(self.request("GET", "/api/schedules")[1])
            self.assertEqual(len(rows), 2)
            self.assertTrue(all(row["state"]["desired_matches"] for row in rows))
            state = scheduler.state("sample", "morning")
            scheduler.command.fail_next_bootstrap = True
            status, raw = self.request("PUT", endpoint + "/check", {"schedule": {**interval(), "interval_seconds": 10}, "etag": job["etag"]})
            self.assertEqual(status, 502, raw)
            self.assertEqual(self.server.store.get("sample")["etag"], job["etag"])
            self.assertEqual(scheduler.state("sample", "morning"), state)
            for enabled in [False, True]:
                status, raw = self.request("PUT", endpoint + "/check", {"schedule": {**interval(), "enabled": enabled}, "etag": job["etag"]})
                self.assertEqual(status, 200, raw)
                result = json.loads(raw)
                job = result["job"]
                self.assertEqual(result["state"]["loaded"], enabled)
            self.assertEqual(self.request("DELETE", endpoint + "/check", {"etag": "stale"})[0], 409)
            self.assertEqual(self.request("DELETE", endpoint + "/check", {"etag": job["etag"]})[0], 200)
            self.assertTrue(scheduler.observed("sample", "morning")["loaded"])
            self.assertEqual(len(json.loads(self.request("GET", "/api/schedules")[1])), 1)

    def test_integrated_http_manage_run_schedule_deploy_and_remove(self):
        """All public actions, with remote OS/SSH replaced by a temp sandbox."""
        root = self.server.store.root
        remote, home = root / "remote", root / "remote-home"
        home.mkdir()
        fake_remote = FakeSystemd(home / ".config/systemd/user")
        def transport(target, payload):
            controller = Controller(remote, payload["job_id"], home, fake_remote,
                                    create=payload["action"] == "deploy")
            if payload["action"] == "deploy":
                return controller.activate(controller.stage(payload["info"], payload["files"]))
            if payload["action"] == "rollback":
                return controller.activate(payload["release"], recovery=True)
            return controller.verify()
        deployer = Deployment(self.server.store, transport)
        (root / "deployments").mkdir()
        (root / "deployments/targets.yaml").write_text(dump_yaml(
            {"version": 1, "targets": {"test": {"ssh_host": "never-contacted", "root": str(remote)}}}))
        fake_launchctl = LaunchctlFake()
        scheduler = Scheduler(self.server.store, root / "agents", fake_launchctl)
        with patch("dashboard.server.Scheduler", return_value=scheduler), \
                patch("deployments.client.Deployment", return_value=deployer):
            status, raw = self.request("POST", "/api/jobs", {"id": "sample", "name": "통합 검증"})
            self.assertEqual(status, 201)
            job = json.loads(raw)
            config = job["config"]
            config.pop("schedules", None)
            config.update(command=["/bin/sh", "main.sh"], schedule={
                "enabled": True, "times": ["09:00"], "weekdays": [1]})
            (root / "jobs/sample/main.sh").write_text("printf 'integration success\\n'\n")
            status, raw = self.request("PUT", "/api/jobs/sample", {"yaml": dump_yaml(config), "etag": job["etag"]})
            self.assertEqual(status, 200)
            job = json.loads(raw)
            status, raw = self.request("POST", "/api/jobs/sample/runs", {})
            self.assertEqual(status, 202)
            run_id = json.loads(raw)["id"]
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                result = json.loads(self.request("GET", "/api/jobs/sample/runs/" + run_id)[1])
                if result["state"] not in ("queued", "running"):
                    break
                time.sleep(.05)
            self.assertEqual(result["state"], "succeeded")
            self.assertIn("integration success", json.loads(self.request("GET", "/api/jobs/sample/runs/" + run_id + "/logs")[1])["text"])
            self.assertEqual(self.request("POST", "/api/jobs/sample/schedule", {"etag": job["etag"]})[0], 200)
            self.assertTrue(fake_launchctl.loaded)
            self.assertEqual(self.request("DELETE", "/api/jobs/sample", {"etag": job["etag"]})[0], 409)
            status, raw = self.request("POST", "/api/jobs/sample/packages", {})
            self.assertEqual(status, 201, raw)
            package_id = json.loads(raw)["id"]
            status, raw = self.request("POST", "/api/jobs/sample/deploy-plan", {"target": "test", "package_id": package_id})
            self.assertEqual(status, 200)
            plan = json.loads(raw)
            status, raw = self.request("POST", "/api/jobs/sample/deploy", {"target": "test", "package_id": package_id, "plan_hash": plan["plan_hash"]})
            self.assertEqual(status, 200, raw)
            receipt = json.loads(raw)
            self.assertEqual(receipt["status"], "verified")
            self.assertEqual(self.request("POST", "/api/jobs/sample/verify", {"target": "test"})[0], 200)
            self.assertEqual(self.request("POST", "/api/jobs/sample/rollback", {"target": "test", "release": receipt["release"]})[0], 200)
            self.assertEqual(len(json.loads(self.request("GET", "/api/jobs/sample/deployments")[1])), 2)
            self.assertEqual(self.request("DELETE", "/api/jobs/sample/schedule", {})[0], 200)
            self.assertEqual(self.request("DELETE", "/api/jobs/sample", {"etag": job["etag"]})[0], 200)

    def test_lifecycle_http_retains_metadata_and_restores_output(self):
        from runner.lifecycle import Lifecycle
        from runner.common import write_json
        from deployments.packages import Packages
        self.request("POST", "/api/jobs", {"id": "sample"})
        package = Packages(self.server.store).create("sample")
        base = "/api/jobs/sample/lifecycle"
        status, raw = self.request("GET", base)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(raw)["policy"]["package_keep"], 5)
        self.assertEqual(self.request("PUT", base, {"package_keep": 0, "output_runs": 0})[0], 200)
        status, raw = self.request("POST", base+"/cleanup", {"resource":"packages", "expected":[package["id"]]})
        self.assertEqual(status,200,raw)
        self.assertEqual(json.loads(raw)["errors"],[])
        status, raw = self.request("GET", "/api/jobs/sample/packages/"+package["id"])
        self.assertEqual(status,200)
        self.assertFalse(json.loads(raw)["zip_available"])
        self.assertEqual(self.request("GET", "/api/jobs/sample/packages/"+package["id"]+"/download")[0],409)
        life=Lifecycle(self.server.store)
        run="f"*32
        paths=life.paths("sample",run,True)
        Path(paths["SCRIPT_MANAGER_OUTPUT_DIR"],"result").write_text("recover me")
        write_json(self.server.store.runtime/"runs/sample"/run/"run.json",dict(
            id=run,job_id="sample",created_at="2020-01-01T00:00:00+00:00",state="succeeded",
            managed_output="runtime/job-data/sample/output/"+run))
        status, raw=self.request("POST",base+"/cleanup",{"resource":"output","expected":[run]})
        self.assertEqual(status,200,raw)
        self.assertTrue(life.outputs("sample")[0]["trashed"])
        self.assertEqual(self.request("POST",base+"/restore",{"run_id":run})[0],200)
        self.assertEqual(Path(paths["SCRIPT_MANAGER_OUTPUT_DIR"],"result").read_text(),"recover me")
        self.assertEqual(self.request("POST",base+"/cleanup",{"resource":"state"})[0],400)
