"""Actual offline Chrome DOM/UI verification. No Dashboard server or native OS writes."""
from pathlib import Path
import subprocess
import json
import shutil
import tempfile
import unittest

from tests.test_report_browser import CHROME

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = r'''
const diagnosis={counts:{healthy:1,orphan:1,unknown:1},errors:[],schedules:[{id:'<img src=x onerror=window.injected=true>',status:'unknown',root:'/old',reason:'소유권 확인 불가'},{id:'local.scriptmanager.test',status:'orphan',root:'/deleted',reason:'원본 경로 없음'}]};
let resetPosts=0, failReset=true, blocked=false;
window.fetch=async(url,options={})=>{
 const path=String(url).replace('/api/',''),method=options.method||'GET'; let value;
 if(path==='session')value={root:'/project',csrf:'fixture',os:'Darwin',scheduler:'launchd',schedule_diagnosis:diagnosis};
 else if(path==='targets'||path==='jobs')value=[];
 else if(path.startsWith('overview'))value={summary:{},upcoming:[],uncalculated:[],errors:[],timeline:[]};
 else if(path==='schedule-doctor')value=diagnosis;
 else if(path==='reset'&&method==='GET')value={root:'/project',plan_hash:'reviewed',schedules:[],delete:[{path:'/project/jobs',entries:20,bytes:200},{path:'/project/.env',entries:1,bytes:10}],blockers:blocked?['실행 중인 작업이 있습니다.']:[],doctor:diagnosis};
 else if(path==='reset'&&method==='POST'){
  resetPosts++;
  if(JSON.parse(options.body).confirm!=='reviewed')throw Error('wrong confirmation hash');
  if(failReset)return {ok:false,status:409,json:async()=>({success:false,phase:'remove-schedules',error:'OS 예약 해제 실패',remaining:['/project/jobs'],deleted:[]})};
  value={success:true,deleted:['/project/jobs'],remaining:[]};
 }else throw Error('Unexpected fixture route '+path);
 return {ok:true,status:200,json:async()=>value};
};
'''
HARNESS = r'''
window.addEventListener('load',async()=>{
 const result=document.createElement('pre');result.id='maintenance-browser-result';
 const check=(value,message)=>{if(!value)throw Error(message);};
 try{
 await new Promise(resolve=>setTimeout(resolve,50));
 check(!$('doctor-banner').hidden,'startup diagnosis visible');
 await $('maintenance-menu').onclick();
 check(!$('maintenance-view').hidden&&$('home-view').hidden,'dedicated management navigation');
 check($('doctor-rows').querySelectorAll('tr').length===2&&!window.injected,'OS strings are escaped');
 await $('reset-preview').onclick();
 check($('reset-paths').children.length===2&&$('reset-execute').disabled,'preview and disabled deletion');
 const type=text=>{$('reset-confirm').value=text;$('reset-confirm').dispatchEvent(new Event('input'));};
 type('wrong');$('reset-execute').click();check(resetPosts===0,'wrong typed confirmation protected');
 type('초기화');check(!$('reset-execute').disabled,'typed confirmation enables final approval');
 approve=async()=>false;await $('reset-execute').onclick();check(resetPosts===0,'cancel protects data');
 approve=async()=>true;await $('reset-execute').onclick();
 check(resetPosts===1&&$('reset-result').textContent.includes('remove-schedules')&&$('reset-result').textContent.includes('/project/jobs'),'failure phase and remaining data visible');
 check($('reset-execute').disabled,'failed attempt requires new preview');
 blocked=true;await $('reset-preview').onclick();type('초기화');check($('reset-execute').disabled,'running job blocker');
 blocked=false;failReset=false;await $('reset-preview').onclick();type('초기화');await $('reset-execute').onclick();
 check(resetPosts===2&&$('reset-result').textContent.includes('초기화 완료')&&!$('reset-reload').hidden,'success and usable dashboard guidance');
 check(document.documentElement.scrollWidth<=innerWidth+1,'no page horizontal overflow');
 result.textContent='PASS startup diagnosis preview typed confirmation cancel failure blocker success layout';
 }catch(error){result.textContent='FAIL '+error.stack;}
 document.body.append(result);
});
'''


@unittest.skipUnless(CHROME and shutil.which("node"), "Chrome and Node required for offline management UI verification")
class MaintenanceBrowserTests(unittest.TestCase):
    def test_management_desktop_and_mobile(self):
        cache = ROOT / ".cache/maintenance-ui"
        cache.mkdir(parents=True, exist_ok=True)
        for width in (1280, 390):
            with self.subTest(width=width), tempfile.TemporaryDirectory() as folder:
                html = (ROOT / "dashboard/static/index.html").read_text()
                html = html.replace('<link rel="stylesheet" href="/style.css">', '<style>' + (ROOT / "dashboard/static/style.css").read_text() + '</style>')
                html = html.replace('<script src="/app.js" defer></script>', '')
                html = html.replace('</body>', '<script>' + FIXTURE + '</script><script>' + (ROOT / "dashboard/static/app.js").read_text() + '</script><script>' + HARNESS + '</script></body>')
                fixture = Path(folder) / "maintenance.html"
                fixture.write_text(html)
                result = subprocess.run([shutil.which("node"), str(ROOT / "tests/job_detail_chrome.cjs"), CHROME,
                    str(fixture), str(width), str(Path(folder) / "profile"), str(cache / (str(width) + ".png")),
                    "maintenance-browser-result"], capture_output=True, text=True, timeout=45)
                self.assertEqual(result.returncode, 0, result.stderr[-1500:])
                outcome = json.loads(result.stdout)
                self.assertTrue(outcome["text"].startswith("PASS "), outcome)
                self.assertEqual(outcome["width"], width)
                self.assertLessEqual(outcome["scrollWidth"], width + 1)
