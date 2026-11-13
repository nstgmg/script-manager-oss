"""Real Chrome file:// verification, with no HTTP service or internet dependency."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from runner.reports import render_html

CHROME = shutil.which("google-chrome") or shutil.which("chromium")
if not CHROME and Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome").exists():
    CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


@unittest.skipUnless(CHROME, "Chrome/Chromium is required for the offline browser test")
class OfflineReportBrowserTests(unittest.TestCase):
    def test_file_url_interactions_and_no_script_injection(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            source = folder / "source.json"
            payload = [{"title":"Beta", "amount":10, "nested":{"children":[1,2]}, "formula":"=SUM(A1:A9)", "__proto__":"safe"},
                       {"title":"Alpha", "amount":2, "nested":{"children":[]}, "formula":"+malicious"},
                       {"title":"</script><script>window.injected=true</script><img src=x onerror=window.injected=true>", "amount":30, "nested":None, "formula":"hello,\"quote\"\nline"}]
            original = json.dumps(payload,ensure_ascii=False,indent=2)
            source.write_text(original,encoding="utf-8")
            content, _ = render_html(source,job_id="sample")
            # This harness runs inside a real offline browser and drives the generated controls.
            harness = r'''
<script>
(async()=>{
 const checks=[];
 function assert(ok,name){if(!ok)throw Error(name);checks.push(name);}
 try {
  assert(location.protocol==='file:', 'standalone file URL with server absent');
  assert(!window.injected && document.querySelectorAll('img').length===0,'untrusted HTML is text');
  assert(el('body').children.length===3,'array table count');
  el('search').value='beta';el('search').dispatchEvent(new Event('input'));
  assert(el('body').children.length===1 && el('body').textContent.includes('Beta'),'search');
  el('search').value='';el('search').dispatchEvent(new Event('input'));
  el('filter-key').value='amount';el('filter-key').dispatchEvent(new Event('change'));
  el('filter-value').value='10';el('filter-value').dispatchEvent(new Event('input'));
  assert(el('body').children.length===1,'column filter');
  const nativeCreate=URL.createObjectURL;let capturedBlob;
  URL.createObjectURL=(blob)=>{capturedBlob=blob;return nativeCreate(blob);};
  const nativeClick=HTMLAnchorElement.prototype.click;let downloadClicked=false;
  HTMLAnchorElement.prototype.click=function(){downloadClicked=this.download==='report.csv';};
  el('csv-filtered').click();
  const exportText=await capturedBlob.text();
  assert(downloadClicked && exportText.includes('Beta') && !exportText.includes('Alpha'),'filtered CSV download');
  assert(exportText.includes("'=SUM") && exportText.includes('""children""'),'CSV formula safety and nested JSON');
  el('csv-all').click();
  assert((await capturedBlob.text()).includes('Alpha'),'whole CSV export');
  assert(csvText(rows).includes('"hello,""quote""\nline"'),'CSV quotes commas newlines');
  HTMLAnchorElement.prototype.click=nativeClick;
  el('reset').click();
  const amountHeader=[...el('head').querySelectorAll('button')].find(b=>b.textContent==='amount');
  amountHeader.click();
  assert(el('body').firstChild.textContent.includes('Alpha'),'numeric ascending sort');
  [...el('head').querySelectorAll('button')].find(b=>b.textContent.startsWith('amount')).click();
  assert(el('body').firstChild.textContent.includes('30'),'numeric descending sort');
  navigate(['0','nested','children']);assert(el('body').children.length===2,'nested array navigation');
  el('breadcrumbs').firstChild.click();assert(el('body').children.length===3,'breadcrumb navigation');
  navigate(['1','nested','children']);assert(el('count').textContent.includes('전체 0건'),'empty nested array');
  navigate(['0','amount']);assert(el('scalar').textContent==='10' && !el('scalar').hidden,'scalar detail');
  navigate([]);
  let clipboard;
  Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:async text=>{clipboard=text;}}});
  await copyJSON();assert(clipboard===originalJSON,'clipboard API full original JSON');
  Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:async()=>{throw Error('denied');}}});
  let legacyAttempted=false;
  document.execCommand=()=>{legacyAttempted=true;return false;};
  await copyJSON();
  assert(legacyAttempted && !el('copy-panel').hidden && el('copy-text').value===originalJSON,'local clipboard fallback');
  assert(el('copy-text').selectionEnd===originalJSON.length,'manual selection includes full JSON');
  document.execCommand=()=>true;await copyJSON();assert(el('message').textContent.includes('복사했습니다'),'legacy copy');
  el('copy-close').click();el('copy-manual').click();assert(!el('copy-panel').hidden,'explicit manual copy');
  const savedRows=rows;rows=Array.from({length:205},(_,i)=>({key:String(i),value:{n:i},kind:'fields'}));columns=['n'];page=0;update();
  assert(el('body').children.length===100,'bounded page size');el('next').click();assert(el('body').children.length===100,'second page');el('next').click();assert(el('body').children.length===5,'last page');
  assert(csvText(rows).includes('"204"'),'CSV includes all pages');rows=savedRows;navigate([]);
  const result=document.createElement('pre');result.id='browser-test-result';result.textContent='PASS '+JSON.stringify(checks);document.body.append(result);
 }catch(error){const result=document.createElement('pre');result.id='browser-test-result';result.textContent='FAIL '+error.stack;document.body.append(result);}
})();
</script>'''
            report = folder / "offline.html"
            report.write_bytes(content.replace(b'</body>',harness.encode()+b'</body>'))
            completed = subprocess.run([CHROME,"--headless=new","--disable-gpu","--no-first-run",
                "--no-default-browser-check","--disable-background-networking","--disable-sync",
                "--disable-extensions","--host-resolver-rules=MAP * ~NOTFOUND",
                "--user-data-dir="+str(folder / "profile"),"--dump-dom","--virtual-time-budget=5000",report.as_uri()],
                capture_output=True,text=True,timeout=30)
            self.assertEqual(completed.returncode,0,completed.stderr[-2000:])
            self.assertIn('<pre id="browser-test-result">PASS ',completed.stdout,completed.stdout[-5000:]+completed.stderr[-1000:])
