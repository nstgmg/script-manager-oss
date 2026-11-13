import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from dashboard.server import Dashboard
from runner.reports import Reports
from runner.store import default_job


class ReportHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.server = Dashboard(self.temp.name, 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.server.store.create(default_job("sample"))
        self.source = Path(self.temp.name) / "input.json"
        self.source.write_text('[{"x":1}]')

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def request(self, method, path, data=None, headers=None):
        port = self.server.server_address[1]
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        actual = {"X-CSRF-Token":self.server.token,"Content-Type":"application/json", **(headers or {})}
        conn.request(method, path, json.dumps(data) if data is not None else None, actual)
        response = conn.getresponse()
        result = (response.status, dict(response.getheaders()), response.read())
        conn.close()
        return result

    def test_metadata_html_download_and_separate_security_policy(self):
        self.assertEqual(json.loads(self.request("GET", "/api/jobs/sample/report")[2])["state"],"missing")
        self.assertEqual(self.request("GET", "/api/jobs/sample/report/html")[0],404)
        Reports(self.server.store).generate("sample", self.source)
        code, _, raw = self.request("GET", "/api/jobs/sample/report")
        self.assertEqual(code,200)
        self.assertTrue(json.loads(raw)["available"])
        code, headers, doc = self.request("GET", "/api/jobs/sample/report/html")
        self.assertEqual(code,200)
        self.assertTrue(headers["Content-Type"].startswith("text/html"))
        self.assertIn("sandbox allow-scripts allow-downloads",headers["Content-Security-Policy"])
        self.assertIn("connect-src 'none'",headers["Content-Security-Policy"])
        self.assertIn("frame-ancestors 'self'",headers["Content-Security-Policy"])
        self.assertNotIn("Content-Disposition",headers)
        code, headers, download = self.request("GET", "/api/jobs/sample/report/download")
        self.assertEqual((code,download),(200,doc))
        self.assertEqual(headers["Content-Disposition"],'attachment; filename="sample.html"')
        _, headers, _ = self.request("GET", "/")
        self.assertIn("script-src 'self'",headers["Content-Security-Policy"])
        self.assertIn("frame-ancestors 'none'",headers["Content-Security-Policy"])

    def test_config_etag_and_security_and_other_fields_preserved(self):
        item = self.server.store.get("sample")
        settings = {"enabled":True,"source":"nested/result.json","output_dir":"exports","filename":"report.html"}
        route = "/api/jobs/sample"
        code, _, raw = self.request("PUT", route, {"fields":{"report":settings},"etag":item["etag"]})
        self.assertEqual(code,200)
        changed = json.loads(raw)
        self.assertEqual(changed["config"]["report"],settings)
        self.assertEqual(changed["config"]["command"],item["config"]["command"])
        self.assertEqual(changed["config"]["schedules"],item["config"]["schedules"])
        self.assertEqual(self.request("PUT",route,{"fields":{"report":settings},"etag":item["etag"]})[0],409)
        for headers in ({"X-CSRF-Token":""},{"Origin":"https://evil.test"},{"Host":"evil.test"}):
            self.assertEqual(self.request("PUT",route,{"fields":{"report":settings},"etag":changed["etag"]},headers)[0],403)
        self.assertEqual(self.request("GET",route+"/report/html",headers={"Host":"evil.test"})[0],403)
        self.assertEqual(self.request("GET","/api/jobs/%2e%2e/report/html")[0],400)
        self.assertEqual(self.request("PUT",route,{"fields":{"report":{"enabled":True,"source":"../a.json"}},"etag":changed["etag"]})[0],400)

    def test_tampered_report_is_not_served_and_missing_file_is_disclosed(self):
        info = Reports(self.server.store).generate("sample",self.source)
        target = Path(info["path"])
        target.write_bytes(target.read_bytes() + b'<script>malicious()</script>')
        self.assertEqual(self.request("GET","/api/jobs/sample/report/html")[0],409)
        target.unlink()
        self.assertFalse(json.loads(self.request("GET","/api/jobs/sample/report")[2])["available"])
        self.assertEqual(self.request("GET","/api/jobs/sample/report/download")[0],404)

    def test_external_configuration_metadata_and_fixed_report_endpoints(self):
        with tempfile.TemporaryDirectory() as external:
            output = str(Path(external).resolve() / "reports")
            config = {"enabled":True,"source":"data.json","output_dir":output,"filename":"outside.html"}
            item = self.server.store.get("sample")
            code, _, raw = self.request("PUT","/api/jobs/sample",{"fields":{"report":config},"etag":item["etag"]})
            self.assertEqual(code,200)
            self.assertEqual(json.loads(raw)["config"]["report"],config)
            self.assertEqual(json.loads(self.request("GET","/api/jobs/sample")[2])["config"]["report"],config)
            info = Reports(self.server.store).generate("sample",self.source)
            self.assertEqual(Path(info["path"]),Path(output) / "outside.html")
            code, _, meta = self.request("GET","/api/jobs/sample/report")
            self.assertEqual(code,200)
            self.assertEqual(json.loads(meta)["path"],info["path"])
            code, _, html = self.request("GET","/api/jobs/sample/report/html")
            self.assertEqual(code,200)
            self.assertEqual(html,Path(info["path"]).read_bytes())
            self.assertEqual(self.request("GET","/api/jobs/sample/report/download")[0],200)
            self.assertEqual(self.request("GET","/api/files?path="+output)[0],404)
            saved = self.server.store.get("sample")
            invalid = {**config,"output_dir":output+"/../escape"}
            self.assertEqual(self.request("PUT","/api/jobs/sample",{"fields":{"report":invalid},"etag":saved["etag"]})[0],400)
            self.assertEqual(self.server.store.get("sample"),saved)

    def test_destination_preview_reuses_validation_without_writes(self):
        route = "/api/jobs/sample/report/destination"
        before = self.server.store.get("sample")
        for settings, suffix in [({}, "reports/sample.html"),
                                 ({"output_dir": "exports/support", "filename": "latest.html"}, "exports/support/latest.html")]:
            status, _, raw = self.request("POST", route, settings)
            self.assertEqual(status, 200, raw)
            target = Path(json.loads(raw)["path"])
            self.assertEqual(target, self.server.store.root / suffix)
            self.assertFalse(target.parent.exists())
        with tempfile.TemporaryDirectory() as external:
            status, _, raw = self.request("POST", route, {"output_dir": str(Path(external).resolve())})
            self.assertEqual(status, 200, raw)
            self.assertEqual(Path(json.loads(raw)["path"]), Path(external).resolve() / "sample.html")
        for settings in [{"output_dir": "../escape"}, {"output_dir": "runtime/reports"},
                         {"output_dir": str(self.server.store.root / "jobs")},
                         {"filename": "../x.html"}, {"path": "/tmp"}]:
            self.assertEqual(self.request("POST", route, settings)[0], 400)
        for headers in ({"X-CSRF-Token": ""}, {"Host": "evil.test"}, {"Origin": "https://evil.test"}):
            self.assertEqual(self.request("POST", route, {}, headers)[0], 403)
        self.assertEqual(self.request("POST", route+"?path=/tmp", {})[0], 400)
        self.assertEqual(self.request("POST", "/api/jobs/missing/report/destination", {})[0], 404)
        self.assertEqual(self.server.store.get("sample"), before)

    def test_preview_rejects_links_foreign_files_and_other_job_collisions(self):
        route = "/api/jobs/sample/report/destination"
        root = self.server.store.root
        (root / "existing").mkdir()
        (root / "existing/sample.html").write_text("unowned")
        self.assertEqual(self.request("POST", route, {"output_dir": "existing"})[0], 409)
        (root / "linked").symlink_to(root / "existing", target_is_directory=True)
        self.assertEqual(self.request("POST", route, {"output_dir": "linked"})[0], 400)
        config = default_job("other")
        config["report"] = {"enabled": True, "source": "data.json", "output_dir": "exports", "filename": "same.html"}
        self.server.store.create(config)
        self.assertEqual(self.request("POST", route, {"output_dir": "exports", "filename": "same.html"})[0], 409)

    def test_report_folder_open_is_fixed_to_validated_published_report(self):
        route = "/api/jobs/sample/report/open-directory"
        with patch("dashboard.server.subprocess.run") as run:
            self.assertEqual(self.request("POST", route, {})[0], 404)
            run.assert_not_called()
            info = Reports(self.server.store).generate("sample", self.source)
            for system, command in [("Darwin", "open"), ("Windows", "explorer"), ("Linux", "xdg-open")]:
                with patch("dashboard.server.platform.system", return_value=system):
                    self.assertEqual(self.request("POST", route, {})[0], 200)
                    self.assertEqual(run.call_args.args[0], [command, str(Path(info["path"]).parent)])
            run.reset_mock()
            for headers in ({"X-CSRF-Token": ""}, {"Host": "evil.test"}, {"Origin": "https://evil.test"}):
                self.assertEqual(self.request("POST", route, {}, headers)[0], 403)
            self.assertEqual(self.request("POST", route, {"path": "/tmp"})[0], 400)
            self.assertEqual(self.request("POST", route+"?path=/tmp", {})[0], 400)
            run.assert_not_called()
            Path(info["path"]).unlink()
            self.assertEqual(self.request("POST", route, {})[0], 404)
