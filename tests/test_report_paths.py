"""Focused local absolute destination coverage; existing browser E2E is separate."""
import contextlib
import io
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import tempfile
import unittest
from unittest.mock import patch

from runner.__main__ import main
from runner.common import ManagerError
from runner.reports import Reports, destination, output_directory, reject_links, validate_report
from runner.store import Store, default_job


class ExternalReportPathTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.store = Store(self.base / "project")
        self.store.create(default_job("sample"))
        self.external = self.base / "external reports" / "한글"
        self.settings = {"enabled":True,"source":"data.json","output_dir":str(self.external),"filename":"latest.html"}
        self.source = self.base / "input.json"
        self.source.write_text('[{"title":"first","n":1}]')
        self.reports = Reports(self.store)

    def test_native_absolute_default_settings_and_metadata_after_path_change(self):
        old = self.reports.generate("sample",self.source)
        item = self.store.get("sample")
        saved = self.store.update_fields("sample",{"report":self.settings},item["etag"])
        self.assertEqual(saved["config"]["report"],self.settings)
        self.assertEqual(self.store.get("sample")["config"]["report"],self.settings)
        info = self.reports.generate("sample",self.source)
        self.assertEqual(Path(info["path"]),self.external / "latest.html")
        self.assertEqual(self.reports.get("sample")["path"],info["path"])
        self.assertEqual(self.reports.document("sample"),Path(info["path"]).read_bytes())
        self.assertTrue(Path(old["path"]).exists())
        self.assertEqual(Path(old["path"]),self.store.root / "reports/sample.html")
        self.assertEqual(self.store.get("sample")["etag"],saved["etag"])

    def test_external_manual_cli_and_captured_run_generation(self):
        before = self.store.get("sample")
        with contextlib.redirect_stdout(io.StringIO()) as out:
            code = main(["--root",str(self.store.root),"report-render","sample","--source",str(self.source),
                         "--output-dir",str(self.external),"--filename","latest.html"])
        self.assertEqual(code,0)
        self.assertEqual(Path(json.loads(out.getvalue())["path"]),self.external / "latest.html")
        self.assertEqual(self.store.get("sample"),before)
        from runner.lifecycle import Lifecycle
        run_id = "b"*32
        output = Path(Lifecycle(self.store).paths("sample",run_id,create=True)["SCRIPT_MANAGER_OUTPUT_DIR"])
        (output / "data.json").write_text('{"updated":true}')
        captured = {**before["config"],"report":self.settings}
        info = self.reports.generate_run("sample",{"id":run_id,"config":captured})
        self.assertEqual(info["run_id"],run_id)
        self.assertEqual(Path(info["path"]),self.external / "latest.html")

    def test_absolute_path_cannot_bypass_managed_project_protection(self):
        for parent in ("runtime/job-data/sample/state","jobs/sample","workspace","deployments",".git"):
            with self.subTest(parent=parent),self.assertRaises(ManagerError):
                destination(self.store.root,"sample",{"output_dir":str(self.store.root / parent)})
        allowed = destination(self.store.root,"sample",{"output_dir":str(self.store.root / "exports")})
        self.assertEqual(allowed,self.store.root / "exports/sample.html")

    def test_path_syntax_platform_awareness(self):
        for path in ("/example/reports","/example/.local/share/reports","/mnt/reports/",r"C:\Example\Reports", "D:/reports/",r"exports\reports"):
            with self.subTest(path=path):
                validate_report({"output_dir":path})
        self.assertIsInstance(output_directory("/example/reports"),PurePosixPath)
        self.assertIsInstance(output_directory(r"C:\Reports"),PureWindowsPath)
        invalid = ("../reports","/some/../reports","/some/./reports","/some//reports", "C:reports",r"C:\a\..\reports",r"\reports",
                   r"\\server\share\reports", "//server/share/reports", r"\\?\C:\reports", r"\\.\C:\reports",r"C:\NUL\reports", "bad\x00path")
        for path in invalid:
            with self.subTest(path=path),self.assertRaises(ManagerError):
                validate_report({"output_dir":path})
        if os.name != "nt":
            for path in (r"C:\Reports", "C:/Reports",r"exports\reports"):
                with self.subTest(path=path),self.assertRaisesRegex(ManagerError,"운영체제"):
                    destination(self.store.root,"sample",{"output_dir":path})

    def test_external_collision_permissions_and_links(self):
        self.reports.generate("sample",self.source,settings=self.settings)
        self.store.create(default_job("other"))
        with self.assertRaisesRegex(ManagerError,"충돌"):
            self.reports.generate("other",self.source,settings=self.settings)
        with patch("runner.reports.os.access",return_value=False):
            with self.assertRaisesRegex(ManagerError,"쓰기 권한"):
                self.reports.generate("sample",self.source,settings=self.settings)
        self.assertTrue(self.reports.document("sample"))
        if os.name != "nt":
            alias = self.base / "alias"
            alias.symlink_to(self.external,target_is_directory=True)
            with self.assertRaisesRegex(ManagerError,"링크"):
                self.reports.generate("sample",self.source,settings={**self.settings,"output_dir":str(alias)})
            final = self.external / "linked.html"
            final.symlink_to(self.external / "latest.html")
            with self.assertRaisesRegex(ManagerError,"링크"):
                self.reports.generate("sample",self.source,settings={**self.settings,"filename":final.name})
        self.external.joinpath("unowned.html").write_text("original")
        with self.assertRaisesRegex(ManagerError,"충돌"):
            self.reports.generate("sample",self.source,settings={**self.settings,"filename":"unowned.html"})
        self.assertEqual(self.external.joinpath("unowned.html").read_text(),"original")

    def test_windows_reparse_points_are_rejected(self):
        class Info:
            st_mode = 0
            st_file_attributes = 0x400
        with patch.object(Path,"lstat",return_value=Info()):
            with self.assertRaisesRegex(ManagerError,"junction"):
                reject_links(self.external / "latest.html")

    def test_external_atomic_update_and_failed_replace_preserves_html_and_index(self):
        old = self.reports.generate("sample",self.source,settings=self.settings)
        document = self.reports.document("sample")
        self.source.write_text('[{"title":"second"}]')
        replace = os.replace
        observed = []
        def inspect_replace(src,dest):
            if Path(dest).suffix == ".html":
                self.assertEqual(Path(src).parent,self.external)
                observed.append(Path(dest).read_bytes())
            return replace(src,dest)
        with patch("runner.common.os.replace",side_effect=inspect_replace):
            self.reports.generate("sample",self.source,settings=self.settings)
        self.assertEqual(observed,[document])
        document = self.reports.document("sample")
        metadata = self.reports.get("sample")
        self.source.write_text('[{"title":"third"}]')
        def fail_replace(src,dest):
            if Path(dest).suffix == ".html":
                raise PermissionError("external replace denied")
            return replace(src,dest)
        with patch("runner.common.os.replace",side_effect=fail_replace):
            with self.assertRaises(PermissionError):
                self.reports.generate("sample",self.source,settings=self.settings)
        self.assertEqual(self.reports.document("sample"),document)
        self.assertEqual(self.reports.get("sample"),metadata)

    @unittest.skipIf(os.name == "nt", "POSIX directory permissions only")
    def test_real_readonly_external_directory_preserves_last_report(self):
        if os.geteuid()==0:
            self.skipTest("root bypasses POSIX write permissions")
        self.reports.generate("sample",self.source,settings=self.settings)
        original = self.reports.document("sample")
        metadata = self.reports.get("sample")
        self.source.write_text('[{"replacement":true}]')
        self.external.chmod(0o500)
        try:
            with self.assertRaisesRegex(ManagerError,"쓰기 권한"):
                self.reports.generate("sample",self.source,settings=self.settings)
            item = self.store.get("sample")
            with self.assertRaisesRegex(ManagerError,"쓰기 권한"):
                self.store.update_fields("sample",{"report":self.settings},item["etag"])
        finally:
            self.external.chmod(0o700)
        self.assertEqual(self.reports.document("sample"),original)
        self.assertEqual(self.reports.get("sample"),metadata)
