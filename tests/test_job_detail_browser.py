"""Real Chrome UI checks with deterministic API fixtures; never starts Dashboard."""
import os
import shutil
from pathlib import Path
import subprocess
import tempfile
import unittest

from tests.test_report_browser import CHROME

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = r'''
let fixtureJob={id:'demo',etag:'v1',yaml:'name: Daily report\ncommand: [python3, main.py]',config:{name:'지원사업 일일 보고',description:'저장 결과 수집 및 HTML 보고서',command:['python3','main.py'],cwd:'.',env:{LANG:'ko_KR.UTF-8'},timeout_seconds:300,schedules:[],report:{enabled:true,source:'report.json',output_dir:'default'}}};
let conflict=false,reportMode='available',copied='',folderRequests=0;
const fixtureRuns=Array.from({length:45},(_,i)=>({id:'run-'+String(45-i).padStart(2,'0'),state:i===1?'failed':'succeeded',created_at:new Date(Date.UTC(2026,10,13,5,0,45-i)).toISOString(),trigger:i%2?'schedule':'manual',duration_seconds:8,report:i===0?{state:'failed',error:'report source missing'}:undefined}));
const fixtureLifecycle={policy:{package_keep:5,output_days:null,output_runs:null,package_auto:false,output_auto:false,pins:[],rollback_packages:[]},paths:{SCRIPT_MANAGER_OUTPUT_DIR:'/project/runtime/job-data/demo/output',SCRIPT_MANAGER_STATE_DIR:'/project/runtime/job-data/demo/state',SCRIPT_MANAGER_WORKSPACE_DIR:'/project/workspace'},usage:{output:3145728,state:1024,workspace:0},packages:[{id:'package-1',zip_available:true,zip_bytes:1048576,protection:[],cleanup_candidate:true}],outputs:[{id:'run-01',bytes:2097152,cleanup_candidate:true}],package_reclaim_bytes:1048576,output_move_bytes:2097152};
Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:async value=>{copied=value;}}});
window.fetch=async(url,options={})=>{
 const path=String(url).replace('/api/',''),method=options.method||'GET',body=options.body?JSON.parse(options.body):{};
 let value;
 if(path==='session')value={root:'/project',csrf:'fixture-token',os:'Darwin',scheduler:'launchd'};
 else if(path==='targets')value=[];
 else if(path==='jobs')value=[fixtureJob];
 else if(path==='overview')value={jobs:[],summary:{},upcoming:[],uncalculated:[],errors:[],timeline:[]};
 else if(path==='jobs/demo'){
  if(method==='PUT'){
   if(conflict)return {ok:false,status:409,json:async()=>({error:'external edit'})};
   fixtureJob={...fixtureJob,etag:'v2',config:{...fixtureJob.config,...(body.fields||{}),name:body.yaml?'YAML에서 저장':body.fields.name},yaml:body.yaml||'name: '+body.fields.name};
  }
  value=fixtureJob;
 }
 else if(path==='jobs/demo/runs')value=fixtureRuns;
 else if(path==='jobs/demo/schedules'||path==='jobs/demo/deployments')value=[];
 else if(path==='jobs/demo/packages')value=[{id:'package-1',created_at:'2026-11-13T01:00:00Z',manifest:{},zip_available:true,content_hash:'a'.repeat(64)}];
 else if(path.endsWith('/difference'))value={changed:true,added:[],removed:[],modified:['main.py']};
 else if(path==='jobs/demo/lifecycle')value=fixtureLifecycle;
 else if(path==='jobs/demo/report'){
  if(reportMode==='error')return {ok:false,status:500,json:async()=>({error:'metadata unavailable'})};
  value=reportMode==='missing'?{state:'missing'}:{available:true,path:'/project/reports/demo.html',generated_at:'2026-11-12T01:00:00Z',count:12,sha256:'abc',run_id:null};
 }
 else if(path==='jobs/demo/report/destination'){
  if(body.output_dir.includes('..'))return {ok:false,status:400,json:async()=>({error:'상위 경로 금지'})};
  value={path:(body.output_dir==='default'?'/project/reports':body.output_dir.startsWith('/')?body.output_dir:'/project/'+body.output_dir)+'/'+(body.filename||'demo.html')};
 }
 else if(path==='jobs/demo/report/open-directory'){folderRequests++;value={ok:true};}
 else if(path.includes('/logs?'))value={text:path.includes('offset=0')?'log '+path.split('/')[3]+' '+(path.includes('stderr')?'stderr':'stdout'):'',offset:100};
 else if(path.startsWith('jobs/demo/runs/'))value={id:path.split('/')[3],parameters:{count:3},parameter_contract_version:1};
 else throw Error('Unexpected fixture API: '+path+' '+method);
 return {ok:true,status:200,json:async()=>structuredClone(value)};
};
'''
HARNESS = r'''
(async()=>{
 const out=document.createElement('pre');out.id='job-detail-browser-result';out.hidden=true;
 const checks=[];const check=(ok,name)=>{if(!ok)throw Error(name);checks.push(name);};
 const pause=()=>new Promise(resolve=>setTimeout(resolve,350));
 try {
  await pause();await choose('demo');await pause();
  check(document.querySelectorAll('#advanced-settings>.advanced-panel:not([open])').length===4,'advanced tools collapsed by default');
  check([...document.querySelectorAll('#detail>section.panel')].map(el=>el.id).join(',')==='execution-settings,local-runs,html-reports,job-schedules','primary workflow order');
  check($('runs').children.length===20&&$('runs-count').textContent.includes('45건'),'20 newest runs and total count');
  check($('runs').firstChild.querySelector('button').title==='Run ID: run-45','newest run first');
  await $('runs').firstChild.querySelector('button').onclick();
  const selectedLog=$('logs').textContent;$('runs-next').click();
  check($('logs').textContent===selectedLog&&$('selected-run-label').textContent.includes('페이지 밖'),'page change preserves selected log and identifies off-page run');
  $('selected-run-jump').click();check($('runs-page').textContent==='1 / 3','jump to selection');
  $('runs-next').click();$('runs-next').click();check($('runs').children.length===5&&$('runs-next').disabled,'last page bounded');
  $('runs-page-size').value='50';$('runs-page-size').dispatchEvent(new Event('change'));check($('runs').children.length===45,'page size change');
  $('runs-page-size').value='20';$('runs-page-size').dispatchEvent(new Event('change'));
  $('setting-name').value='수정한 작업';$('setting-name').dispatchEvent(new Event('input'));
  check($('yaml').readOnly&&$('save').disabled&&$('run').disabled,'form draft locks YAML and run');
  await refreshDetail();check($('setting-name').value==='수정한 작업'&&dirty,'poll keeps unsaved draft');
  conflict=true;await $('job-settings').onsubmit();check(!$('settings-conflict').hidden&&$('setting-name').value==='수정한 작업'&&current.etag==='v1','conflict preserves draft and etag');
  conflict=false;await $('job-settings').onsubmit();check($('yaml').value.includes('수정한 작업')&&!dirty&&!$('yaml').readOnly,'form save synchronizes YAML');
  $('yaml-section').open=true;$('yaml').value='name: YAML에서 저장';$('yaml').dispatchEvent(new Event('input'));
  check($('setting-name').disabled&&$('settings-save').disabled,'YAML draft locks normal form');
  await $('save').onclick();check($('setting-name').value==='YAML에서 저장'&&!dirty,'YAML save synchronizes form');
  $('setting-report-dir').value='exports/support';$('setting-report-dir').dispatchEvent(new Event('input'));await pause();
  check($('report-destination').textContent.includes('/project/exports/support/demo.html'),'relative report destination');
  $('setting-report-dir').value='/example/reports';$('setting-report-dir').dispatchEvent(new Event('input'));await pause();
  check($('report-destination').textContent.includes('/example/reports/demo.html'),'absolute report destination');
  $('setting-report-dir').value='../bad';$('setting-report-dir').dispatchEvent(new Event('input'));await pause();
  check($('report-destination').classList.contains('error'),'invalid destination distinct from preview');
  $('setting-report-dir').value='default';$('setting-report-dir').dispatchEvent(new Event('input'));await $('job-settings').onsubmit();await pause();
  check($('report-destination').textContent.includes('/project/reports/demo.html'),'default report destination');
  check($('report-run-status').textContent.includes('생성 실패')&&$('report-origin').textContent.includes('별도 생성'),'latest failed Run distinguished from separately published HTML');
  check($('report-open').getAttribute('target')==='_blank'&&$('report-download').getAttribute('download')!==null,'report links retain new tab and download contracts');
  $('report-preview').click();check(!$('report-frame').hidden&&$('report-frame').getAttribute('sandbox')==='allow-scripts allow-downloads','sandboxed report preview');
  await $('report-copy').onclick();await $('report-folder').onclick();check(copied==='/project/reports/demo.html'&&folderRequests===1,'report path copy and fixed folder action');
  reportMode='missing';await refreshReport('demo');check($('report-open').hidden&&$('report-preview').disabled&&$('report-frame').hidden,'missing report disables actions');
  reportMode='error';await refreshReport('demo');check($('report-status').classList.contains('error')&&$('report-status').textContent.includes('조회 실패'),'report error distinct from empty');
  reportMode='available';await refreshReport('demo');
  check(!$('ssh-empty').hidden&&$('ssh-controls').hidden&&$('deployment-plan').hidden,'SSH guidance instead of empty controls');
  $('lifecycle-section').open=true;
  check($('cleanup-packages').disabled&&$('cleanup-output').disabled,'cleanup requires preview');
  await $('lifecycle-preview').onclick();check($('lifecycle-preview-summary').textContent.includes('1건')&&$('lifecycle-preview-summary').textContent.includes('2.00 MiB')&&!$('cleanup-output').disabled,'preview counts bytes and enabled actions');
  $('output-days').value='7';$('output-days').dispatchEvent(new Event('input'));check($('cleanup-output').disabled&&$('lifecycle-preview').disabled,'policy draft invalidates cleanup');
  for(const label of document.querySelectorAll('#detail .checkbox-control')){
   const input=label.querySelector('input'),a=input.getBoundingClientRect(),b=label.getBoundingClientRect();
   if(b.width)check(a.width===16&&a.left-b.left<2&&b.height>=40,'checkbox at left with consistent click target');
  }
  $('packages-section').open=true;check($('package-difference').textContent.includes('main.py')&&!$('package-download').disabled,'package selection and code difference');
  for(const section of document.querySelectorAll('#advanced-settings>.advanced-panel'))section.open=true;
  check(document.documentElement.scrollWidth<=innerWidth,'expanded mobile layout has no horizontal overflow');
  for(const section of document.querySelectorAll('#advanced-settings>.advanced-panel'))section.open=false;
  check(document.documentElement.scrollWidth<=innerWidth,'collapsed layout has no horizontal overflow');
  $('logs').textContent='실행 기록을 선택하세요.';selectedRun=null;renderRunParameters({});renderRuns();closeNotice();window.scrollTo(0,0);
  out.textContent='PASS '+JSON.stringify(checks);
 }catch(error){out.textContent='FAIL '+error.stack;}
 document.body.append(out);
})();
'''


@unittest.skipUnless(CHROME and shutil.which("node"), "Chrome/Chromium and Node are required for Job detail browser tests")
class JobDetailBrowserTests(unittest.TestCase):
    def test_desktop_and_narrow_responsive_workflows(self):
        html = (ROOT / "dashboard/static/index.html").read_text()
        css = (ROOT / "dashboard/static/style.css").read_text()
        app = (ROOT / "dashboard/static/app.js").read_text()
        html = html.replace('<link rel="stylesheet" href="/style.css">', '<style>'+css+'</style>')
        html = html.replace('<script src="/app.js" defer></script>', '')
        html = html.replace('</body>', '<script>'+FIXTURE+'</script><script>'+app+'</script><script>'+HARNESS+'</script></body>')
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            page = folder / "job-detail.html"
            page.write_text(html)
            for width in (1440, 390, 320):
                with self.subTest(width=width):
                    command = ["node", str(ROOT / "tests/job_detail_chrome.cjs"), CHROME, str(page), str(width), str(folder / str(width))]
                    if os.environ.get("SCRIPT_MANAGER_UI_QA_DIR"):
                        screenshots = Path(os.environ["SCRIPT_MANAGER_UI_QA_DIR"])
                        screenshots.mkdir(parents=True, exist_ok=True)
                        command.append(str(screenshots / ("detail-"+str(width)+".png")))
                        (screenshots / "fixture.html").write_text(html)
                    result = subprocess.run(command, capture_output=True, text=True, timeout=45)
                    self.assertEqual(result.returncode, 0, result.stderr[-2000:])
                    marker = '"text":"PASS '
                    self.assertIn(marker, result.stdout, result.stdout[-5000:]+result.stderr[-1000:])
                    self.assertIn('"width":'+str(width), result.stdout)
