"""Notification DOM, CSS animation and native keyboard checks on offline fixtures."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from tests.test_maintenance_browser import FIXTURE
from tests.test_report_browser import CHROME

ROOT = Path(__file__).resolve().parents[1]
TIMERS = r'''
// Only notification lifetimes use a virtual clock. CSS animation and keyboard
// interaction run in Chrome, with the real 180ms animation and cleanup fallback.
const realTimeout=window.setTimeout.bind(window), realClear=window.clearTimeout.bind(window);
const notificationTimers=new Map();let notificationTimerId=-1;
window.setTimeout=(fn,delay,...args)=>{
 if(delay!==5000)return realTimeout(fn,delay,...args);
 const id=notificationTimerId--;notificationTimers.set(id,fn);return id;
};
window.clearTimeout=id=>{if(!notificationTimers.delete(id))realClear(id);};
const expireNotifications=()=>{for(const [id,fn] of [...notificationTimers]){notificationTimers.delete(id);fn();}};
'''
HARNESS = r'''
window.addEventListener('load',async()=>{
 const result=document.createElement('pre');result.id='notification-browser-result';
 const check=(ok,message)=>{if(!ok)throw Error(message);};
 const pause=ms=>new Promise(resolve=>realTimeout(resolve,ms));
 const until=async fn=>{for(let i=0;i<100;i++){if(fn())return;await pause(25);}throw Error('condition timed out');};
 try{
  await until(()=>$('doctor-banner-open'));
  const rows=$('doctor-rows').textContent,summary=$('doctor-summary').textContent;
  $('doctor-banner-open').focus();window.notificationKeyboardStage=1;
  await until(()=>$('doctor-banner').hidden);
  check(!$('doctor-banner-close'),'Tab and Enter dismiss and remove the doctor notification');
  check($('doctor-rows').textContent===rows&&$('doctor-summary').textContent===summary&&resetPosts===0,'keyboard dismissal preserves diagnosis and sends no reset');
  notice('오류',true);$('notice-close').focus();window.notificationKeyboardStage=2;
  await until(()=>$('notice').hidden);
  check(!$('notice-close'),'Space dismisses the focused native button');
  renderDoctor(diagnosis);notice('동시 알림');
  const doctor=$('doctor-banner').firstElementChild,normal=$('notice').firstElementChild;
  const reduced=window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  expireNotifications();
  if(!reduced){
   check(getComputedStyle(doctor).animationName==='notification-fade-out','fade animation applies');
   await pause(80);
   const opacity=Number(getComputedStyle(doctor).opacity);
   check(opacity>0&&opacity<1,'opacity changes during real animation');
  }
  await until(()=>!doctor.isConnected&&!normal.isConnected);
  check($('doctor-banner').hidden&&$('notice').hidden,'animation removes both notification contents');
  check($('doctor-rows').textContent===rows&&resetPosts===0,'automatic dismissal preserves diagnosis and schedules');
  renderDoctor({...diagnosis,errors:['OS query failed']});expireNotifications();await pause(250);
  check(!$('doctor-banner').hidden&&$('doctor-banner').getAttribute('role')==='alert','diagnosis failure persists');
  check($('doctor-banner-close').getAttribute('aria-label')==='예약 진단 알림 닫기','close has accessible name');
  await $('doctor-banner-open').onclick();
  check(!$('maintenance-view').hidden&&$('doctor-rows').children.length===2,'existing diagnosis detail action works');
  notice('지속 경고',{type:'warning',autoClose:false});expireNotifications();
  check(!$('notice').hidden,'explicit persistent warning stays visible');
  check(document.documentElement.scrollWidth<=innerWidth+1,'notifications fit mobile width');
  window.dispatchEvent(new Event('pagehide'));
  check(notificationTimers.size===0&&!$('notice-close')&&!$('doctor-banner-close'),'page removal clears timers and DOM');
  result.textContent='PASS notification animation DOM keyboard independence persistence detail data safety layout';
 }catch(error){result.textContent='FAIL '+error.stack;}
 document.body.append(result);
});
'''


@unittest.skipUnless(CHROME and shutil.which("node"), "Chrome and Node required for offline notification UI verification")
class NotificationBrowserTests(unittest.TestCase):
    def test_desktop_and_mobile_notification_policy(self):
        html = (ROOT / "dashboard/static/index.html").read_text()
        html = html.replace('<link rel="stylesheet" href="/style.css">', '<style>' + (ROOT / "dashboard/static/style.css").read_text() + '</style>')
        html = html.replace('<script src="/app.js" defer></script>', '')
        html = html.replace('</body>', '<script>' + TIMERS + FIXTURE + '</script><script>' + (ROOT / "dashboard/static/app.js").read_text() + '</script><script>' + HARNESS + '</script></body>')
        for width, motion in ((1280, "no-preference"), (390, "no-preference"), (390, "reduce")):
            with self.subTest(width=width, motion=motion), tempfile.TemporaryDirectory() as temp:
                folder = Path(temp)
                fixture = folder / "notifications.html"
                fixture.write_text(html)
                outcome = subprocess.run([shutil.which("node"), str(ROOT / "tests/job_detail_chrome.cjs"), CHROME,
                    str(fixture), str(width), str(folder / "profile"), "", "notification-browser-result", motion],
                    capture_output=True, text=True, timeout=45)
                self.assertEqual(outcome.returncode, 0, outcome.stderr[-2000:])
                result = json.loads(outcome.stdout)
                self.assertTrue(result["text"].startswith("PASS "), result)
