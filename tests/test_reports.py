"""Report contracts, real detached runs, and manual CLI without a Dashboard."""
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from runner.__main__ import main
from runner.common import ManagerError, atomic_write
from runner.execution import Execution
from runner.reports import MAX_SOURCE_BYTES, Reports, destination, render_html, validate_report
from runner.store import Store, default_job


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.store = Store(self.root)
        self.store.create(default_job("sample"))
        self.reports = Reports(self.store)
        self.source = self.root / "input.json"
        self.source.write_text('[{"title":"지원사업", "amount":3}]', encoding="utf-8")

    def settings(self, **kwargs):
        item = self.store.get("sample")
        return self.store.update_fields("sample", {"report": {"enabled": True, "source": "data.json", **kwargs}}, item["etag"])

    def run_job(self, script, *, enabled=True, exit_code=0):
        if enabled:
            self.settings()
        job = self.store.job_dir("sample")
        (job / "main.py").write_text("import os, pathlib, sys\n" + script + "\nsys.exit(" + str(exit_code) + ")\n")
        execution = Execution(self.store)
        run = execution.start("sample")
        end = time.monotonic() + 10
        while run["state"] in ("queued", "running") and time.monotonic() < end:
            time.sleep(.05)
            run = execution.get("sample", run["id"])
        self.assertNotIn(run["state"], ("queued", "running"))
        return execution, run

    def test_various_json_and_payload_escape_preserves_original(self):
        payloads = [[], {}, None, True, 3, "", [1,"x",None,{}], {"a":[{"b":2}]},
                    {"</script><script>globalThis.pwned=true</script>": "<img src=x onerror=alert(1)>&\u2028@@TITLE@@", "__proto__": {"bad": 1}}]
        for payload in payloads:
            with self.subTest(payload=payload):
                raw = json.dumps(payload, ensure_ascii=False, indent=2)
                self.source.write_text(raw, encoding="utf-8")
                content, info = render_html(self.source, job_id="sample", title='<script>bad()</script>')
                text = content.decode()
                data = text.split('<script id="report-data" type="application/json">')[1].split('</script>')[0]
                self.assertNotIn('<', data)
                self.assertEqual(json.loads(data), raw)
                self.assertNotIn('<script>bad()', text)
                self.assertNotIn('<img src=x', text)
                self.assertIn("connect-src 'none'", text)
                self.assertNotIn('src="http', text)
                self.assertEqual(info["count"], len(payload) if isinstance(payload, (dict,list)) else 1)

    def test_invalid_configuration(self):
        invalid = [{"enabled":"true"}, {"enabled":True}, {"unknown":True},
                   {"source":None}, {"source":"../data.json"}, {"source":"/data.json"},
                   {"source":"data.txt"}, {"source":".env.json"}, {"source":"a\\b.json"},
                   {"filename":None}, {"filename":"../sample.html"}, {"filename":"a/b.html"}, {"filename":"CON.html"},
                   {"filename":"x\n.html"}, {"filename":"a.json"}, {"filename":"a.html\""},
                   {"output_dir":"runtime./exports"}, {"output_dir":"exports/NUL"}, {"output_dir":"export?"}, {"output_dir":"../exports"}, {"output_dir":"."},
                   {"output_dir":"runtime/reports"}, {"output_dir":"workspace/reports"},
                   {"output_dir":"jobs/foo"}, {"output_dir":".git/reports"}]
        # An omitted source is allowed while disabled, but explicit null is not.
        for config in invalid:
            with self.subTest(config=config), self.assertRaises(ManagerError):
                validate_report(config)
        for config in ({}, {"enabled":False}, {"enabled":True,"source":"nested/data.json"}):
            validate_report(config)

    def test_default_custom_paths_and_other_job_collision(self):
        info = self.reports.generate("sample", self.source)
        self.assertEqual(Path(info["path"]), self.root / "reports/sample.html")
        self.assertEqual(self.reports.document("sample"), Path(info["path"]).read_bytes())
        config = default_job("other")
        self.store.create(config)
        with self.assertRaisesRegex(ManagerError, "충돌"):
            Reports(self.store).generate("other", self.source, settings={"filename":"sample.html"})
        custom = self.reports.generate("sample", self.source, settings={"output_dir":"exports/team", "filename":"한글.html"})
        self.assertEqual(Path(custom["path"]), self.root / "exports/team/한글.html")
        self.assertTrue((self.root / "reports/sample.html").exists())
        self.assertEqual(self.reports.get("sample")["path"], custom["path"])
        self.settings(output_dir="exports/claimed", filename="shared.html")
        other = self.store.get("other")
        with self.assertRaisesRegex(ManagerError, "충돌"):
            self.store.update_fields("other", {"report":{"enabled":True,"source":"a.json","output_dir":"exports/claimed","filename":"shared.html"}}, other["etag"])

    def test_existing_file_and_symlink_protection(self):
        target = self.root / "reports/sample.html"
        target.parent.mkdir()
        target.write_text("user-owned")
        with self.assertRaisesRegex(ManagerError, "충돌"):
            self.reports.generate("sample", self.source)
        self.assertEqual(target.read_text(), "user-owned")
        if os.name == "nt":
            return
        target.unlink()
        target.symlink_to(self.source)
        with self.assertRaises(ManagerError):
            self.reports.generate("sample", self.source)
        target.unlink()
        target.parent.rmdir()
        (self.root / "exports").mkdir()
        target.parent.symlink_to(self.root / "exports", target_is_directory=True)
        with self.assertRaises(ManagerError):
            self.reports.generate("sample", self.source)
        (self.root / "link.json").symlink_to(self.source)
        with self.assertRaises(ManagerError):
            render_html(self.root / "link.json", job_id="sample")

    def test_limits_invalid_json_no_data_leak_and_failure_preserves_report(self):
        original = self.reports.generate("sample", self.source)
        old = self.reports.document("sample")
        for content in ('{"private_data_bad_json":', 'NaN', 'Infinity', '1e999', '[' * 70 + '0' + ']' * 70):
            self.source.write_text(content)
            with self.assertRaises(ManagerError) as error:
                self.reports.generate("sample", self.source)
            self.assertNotIn("private_data", str(error.exception))
            self.assertEqual(self.reports.document("sample"), old)
        self.source.write_bytes(b'"' + b'x' * MAX_SOURCE_BYTES + b'"')
        with self.assertRaisesRegex(ManagerError, "10 MiB"):
            self.reports.generate("sample", self.source)
        self.source.write_bytes(b'"\xff"')
        with self.assertRaisesRegex(ManagerError, "UTF-8"):
            self.reports.generate("sample", self.source)
        self.assertEqual(self.reports.get("sample"), {**original, "available":True})

    def test_atomic_replacement_and_write_failure_preserves_html_and_index(self):
        self.reports.generate("sample", self.source)
        old = self.reports.document("sample")
        self.source.write_text('[{"new":2}]')
        import runner.common
        replace = os.replace
        observed = []
        def inspect_replace(src, dest):
            if Path(dest).suffix == ".html":
                observed.append(Path(dest).read_bytes())
                self.assertEqual(Path(src).parent, Path(dest).parent)
                self.assertTrue(Path(src).read_bytes().endswith(b'</html>\n'))
            return replace(src, dest)
        with patch("runner.common.os.replace", side_effect=inspect_replace):
            self.reports.generate("sample", self.source)
        self.assertEqual(observed, [old])
        current = self.reports.document("sample")
        index = self.reports.get("sample")
        self.source.write_text('[{"third":3}]')
        def fail_html(path, data):
            if Path(path).suffix == ".html":
                raise PermissionError("report write denied")
            return atomic_write(path, data)
        with patch("runner.reports.atomic_write", side_effect=fail_html):
            with self.assertRaises(PermissionError):
                self.reports.generate("sample", self.source)
        self.assertEqual(self.reports.document("sample"), current)
        self.assertEqual(self.reports.get("sample"), index)
        with patch("runner.reports.write_json", side_effect=PermissionError("index write denied")):
            with self.assertRaises(PermissionError):
                self.reports.generate("sample", self.source)
        self.assertEqual(self.reports.document("sample"), current)

    def test_successful_job_auto_report_output_and_state_unchanged(self):
        execution, run = self.run_job("pathlib.Path(os.environ['SCRIPT_MANAGER_OUTPUT_DIR'], 'data.json').write_text('[{\"x\":1}]')\npathlib.Path(os.environ['SCRIPT_MANAGER_STATE_DIR'], 'saved').write_text('state')")
        self.assertEqual((run["state"], run["exit_code"], run["report"]["state"]), ("succeeded",0,"succeeded"))
        self.assertEqual(run["report"]["run_id"], run["id"])
        output = self.root / run["managed_output"]
        self.assertEqual([p.name for p in output.iterdir()], ["data.json"])
        self.assertEqual((output.parent.parent / "state/saved").read_text(), "state")
        self.assertTrue((execution.run_dir("sample", run["id"]) / "source/job.yaml").exists())

    def test_report_failure_keeps_job_success_old_html_and_diagnostic(self):
        self.reports.generate("sample", self.source)
        old = self.reports.document("sample")
        execution, run = self.run_job("print('script succeeded without JSON')")
        self.assertEqual((run["state"],run["exit_code"],run["report"]["state"]), ("succeeded",0,"failed"))
        self.assertIn("[report] HTML 생성 실패", execution.logs("sample", run["id"], "stderr")["text"])
        self.assertEqual(self.reports.document("sample"), old)

    def test_disabled_and_failed_jobs_do_not_render(self):
        _, run = self.run_job("print('disabled')", enabled=False)
        self.assertEqual(run["state"], "succeeded")
        self.assertNotIn("report", run)
        self.assertFalse((self.root / "reports").exists())
        _, failed = self.run_job("pathlib.Path(os.environ['SCRIPT_MANAGER_OUTPUT_DIR'], 'data.json').write_text('[]')", exit_code=1)
        self.assertEqual(failed["state"], "failed")
        self.assertEqual(failed["report"]["state"], "skipped")
        self.assertFalse((self.root / "reports").exists())

    def test_manual_cli_does_not_execute_or_change_config(self):
        item = self.store.get("sample")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = main(["--root",str(self.root),"report-render","sample","--source",str(self.source),"--output-dir","exports","--filename","manual.html"])
        self.assertEqual(code,0)
        self.assertEqual(json.loads(out.getvalue())["state"],"succeeded")
        self.assertEqual(self.store.get("sample"),item)
        self.assertEqual(Execution(self.store).list("sample"),[])
        self.assertTrue((self.root / "exports/manual.html").exists())

    def test_manual_cli_run_uses_captured_source(self):
        _, run = self.run_job("pathlib.Path(os.environ['SCRIPT_MANAGER_OUTPUT_DIR'], 'data.json').write_text('[]')")
        self.settings(source="new.json")
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(main(["--root",str(self.root),"report-render","sample","--run",run["id"]]),0)
        self.assertEqual(json.loads(out.getvalue())["run_id"],run["id"])
        self.assertEqual(len(Execution(self.store).list("sample")),1)

    def test_destination_permissions_and_non_directory_ancestors(self):
        (self.root / "file-parent").write_text("preserve")
        with self.assertRaisesRegex(ManagerError, "디렉터리"):
            self.settings(output_dir="file-parent/nested")
        with patch("runner.reports.os.access", return_value=False):
            with self.assertRaisesRegex(ManagerError, "쓰기 권한"):
                self.settings()
        self.assertNotIn("report",self.store.get("sample")["config"])

    def test_node_limit_and_large_integer_full_json_preserved(self):
        self.source.write_text("["+",".join("0" for _ in range(200000))+"]")
        with self.assertRaisesRegex(ManagerError, "노드"):
            render_html(self.source,job_id="sample")
        raw = '{"large":9007199254740993123456789}'
        self.source.write_text(raw)
        content, _ = render_html(self.source,job_id="sample")
        payload = content.decode().split('<script id="report-data" type="application/json">')[1].split('</script>')[0]
        self.assertEqual(json.loads(payload),raw)

    def test_captured_report_config_and_source_path_escape(self):
        item = self.settings(filename="captured.html")
        run_id = "a" * 32
        from runner.lifecycle import Lifecycle
        output = Path(Lifecycle(self.store).paths("sample",run_id,create=True)["SCRIPT_MANAGER_OUTPUT_DIR"])
        (output / "data.json").write_text("[]")
        record={"id":run_id,"config":item["config"]}
        self.settings(filename="new.html",source="other.json")
        info = self.reports.generate_run("sample",record)
        self.assertEqual(Path(info["path"]).name,"captured.html")
        if os.name != "nt":
            (output / "data.json").unlink()
            (output / "data.json").symlink_to(self.source)
            with self.assertRaises(ManagerError):
                self.reports.generate_run("sample",record)

    def test_different_jobs_use_the_same_renderer(self):
        first = self.reports.generate("sample",self.source)
        self.store.create(default_job("second"))
        self.source.write_text('{"summary":{"nested":[]},"count":0}')
        second = self.reports.generate("second",self.source)
        self.assertEqual(Path(first["path"]).name,"sample.html")
        self.assertEqual(Path(second["path"]).name,"second.html")
        self.assertTrue(self.reports.document("sample"))
        self.assertTrue(self.reports.document("second"))

    def test_post_replace_directory_sync_error_is_a_committed_success_warning(self):
        self.reports.generate("sample",self.source)
        self.source.write_text('[{"new":true}]')
        sync = os.fsync
        calls = []
        def fail_last_directory_sync(fd):
            calls.append(fd)
            if len(calls) == 4:
                raise OSError("directory fsync unavailable")
            return sync(fd)
        if os.name == "nt":
            self.skipTest("Windows does not fsync directories")
        with patch("runner.common.os.fsync",side_effect=fail_last_directory_sync):
            info = self.reports.generate("sample",self.source)
        self.assertEqual(info["state"],"succeeded")
        self.assertIn("동기화",info["warning"])
        self.assertEqual(self.reports.get("sample")["sha256"],info["sha256"])
        self.assertIn(b'new',self.reports.document("sample"))

    def test_observation_rechecks_after_lock_before_marking_interrupted(self):
        from runner.common import write_json
        folder = self.store.runtime / "runs/sample" / ("a" * 32)
        folder.mkdir(parents=True)
        write_json(folder / "run.json",{"id":"a"*32,"state":"running"})
        terminal = {"id":"a"*32,"state":"failed","exit_code":1,
                    "report":{"state":"skipped","reason":"job_not_succeeded"}}
        @contextlib.contextmanager
        def worker_finishes_during_observation(*args):
            write_json(folder / "run.json",terminal)
            yield
        with patch.object(self.store,"job_lock",side_effect=worker_finishes_during_observation):
            result = Execution(self.store).get("sample","a"*32)
        self.assertEqual(result,terminal)
        self.assertEqual(json.loads((folder / "run.json").read_text()),terminal)
