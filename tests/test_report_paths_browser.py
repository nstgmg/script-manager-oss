"""Only an external-folder file:// copy/CSV smoke; do not repeat full browser E2E."""
from pathlib import Path
import subprocess
import tempfile
import unittest

from runner.reports import Reports
from runner.store import Store, default_job
from tests.test_report_browser import CHROME


@unittest.skipUnless(CHROME,"Chrome/Chromium is required for the external path smoke")
class ExternalReportBrowserSmoke(unittest.TestCase):
    def test_external_file_copy_and_csv_smoke(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp).resolve()
            store = Store(folder / "project")
            store.create(default_job("sample"))
            source = folder / "input.json"
            source.write_text('[{"title":"외부 보고서", "amount":3}]',encoding="utf-8")
            info = Reports(store).generate("sample",source,settings={"output_dir":str(folder / "external reports")})
            report = Path(info["path"])
            self.assertFalse(report.is_relative_to(store.root))
            harness = r'''
<script>
(async()=>{const out=document.createElement('pre');out.id='external-smoke-result';
try {
 if(location.protocol!=='file:' || el('body').children.length!==1)throw Error('external file not rendered');
 let copied;
 Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:async value=>{copied=value;}}});
 await copyJSON();if(copied!==originalJSON)throw Error('JSON copy mismatch');
 el('copy-manual').click();if(el('copy-text').value!==originalJSON || el('copy-text').selectionEnd!==originalJSON.length)throw Error('manual copy unavailable');
 let blob;const makeURL=URL.createObjectURL;
 URL.createObjectURL=value=>{blob=value;return makeURL(value);};
 HTMLAnchorElement.prototype.click=function(){};
 el('csv-all').click();const csv=await blob.text();
 if(!csv.includes('외부 보고서') || !csv.includes('"amount"'))throw Error('CSV unavailable');
 out.textContent='PASS external file JSON copy manual selection CSV';
}catch(error){out.textContent='FAIL '+error.stack;}document.body.append(out);})();
</script>'''
            smoke = report.with_name("smoke.html")
            smoke.write_bytes(report.read_bytes().replace(b'</body>',harness.encode()+b'</body>'))
            result = subprocess.run([CHROME,"--headless=new","--disable-gpu","--no-first-run",
                "--no-default-browser-check","--disable-background-networking","--disable-sync","--disable-extensions",
                "--host-resolver-rules=MAP * ~NOTFOUND","--user-data-dir="+str(folder / "profile"),
                "--dump-dom","--virtual-time-budget=3000",smoke.as_uri()],capture_output=True,text=True,timeout=30)
            self.assertEqual(result.returncode,0,result.stderr[-1500:])
            self.assertIn('<pre id="external-smoke-result">PASS ',result.stdout,result.stdout[-2500:])
