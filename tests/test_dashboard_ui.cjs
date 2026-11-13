const assert = require("node:assert/strict");
const test = require("node:test");
const fs = require("node:fs");
const vm = require("node:vm");

function node(tagName = "") {
  return {tagName:tagName.toUpperCase(), hidden:true, value:"", className:"", children:[], attributes:{}, listeners:{},
    get textContent() { return this._text || this.children.map(child => typeof child === "string" ? child : child.textContent).join(""); },
    set textContent(value) { this._text = value; this.children=[]; },
    querySelectorAll(selector) {
      const matches = child => selector.split(",").some(part => {
        const [tag, pseudo] = part.trim().split(":");
        return child.tagName === tag.toUpperCase() && (pseudo !== "checked" || child.checked);
      });
      return this.children.flatMap(child => typeof child === "string" ? [] : [...(matches(child) ? [child] : []), ...child.querySelectorAll(selector)]);
    },
    addEventListener(type, fn) { this.listeners[type]=fn; },
    showModal() { this.open=true; }, close() { this.open=false; }, reset() {},
    append(...children) { this.children.push(...children); },
    replaceChildren(...children) { this._text=""; this.children=[...children]; },
    setAttribute(key,value) { this.attributes[key]=value; },
    insertBefore(child,next) { this.children=this.children.filter(value=>value!==child); const index=this.children.indexOf(next); this.children.splice(index < 0 ? this.children.length : index,0,child); }
  };
}
function dashboard() {
  const elements = new Map(), timers = new Map();
  let time = 0, nextId = 0;
  const element = id => {
    if (!elements.has(id)) elements.set(id, node());
    return elements.get(id);
  };
  const context = vm.createContext({
    document: {getElementById: element, createElement: node, hidden: true},
    window: {addEventListener() {}},
    fetch: () => new Promise(() => {}),
    setInterval() {},
    setTimeout(fn, delay) { const id = ++nextId; timers.set(id, {fn, at: time + delay}); return id; },
    clearTimeout(id) { timers.delete(id); }
  });
  vm.runInContext(fs.readFileSync("dashboard/static/app.js", "utf8"), context);
  return {context, element, tick(ms) {
    time += ms;
    for (const [id, timer] of [...timers]) {
      if (timer.at <= time) { timers.delete(id); timer.fn(); }
    }
  }};
}
test("success notice expires exactly after five seconds", () => {
  const app = dashboard();
  app.context.notice("완료");
  app.tick(4999);
  assert.equal(app.element("notice").hidden, false);
  app.tick(1);
  assert.equal(app.element("notice").hidden, true);
});
test("a new notice starts a new five-second timer", () => {
  const app = dashboard();
  app.context.notice("처음"); app.tick(4000); app.context.notice("새 알림");
  app.tick(1000);
  assert.equal(app.element("notice-message").textContent, "새 알림");
  assert.equal(app.element("notice").hidden, false);
  app.tick(3999); assert.equal(app.element("notice").hidden, false);
  app.tick(1); assert.equal(app.element("notice").hidden, true);
});
test("error cancels prior expiry and persists until manually closed", () => {
  const app = dashboard();
  app.context.notice("성공"); app.tick(1000); app.context.notice("충돌", true); app.tick(20000);
  assert.equal(app.element("notice").hidden, false);
  assert.equal(app.element("notice").className, "error");
  app.element("notice-close").onclick();
  assert.equal(app.element("notice").hidden, true);
});
test("manual dismissal cancels its timer without affecting the next notice", () => {
  const app = dashboard();
  app.context.notice("처음"); app.tick(3000); app.element("notice-close").onclick();
  app.context.notice("다음"); app.tick(2000);
  assert.equal(app.element("notice").hidden, false);
  app.tick(3000); assert.equal(app.element("notice").hidden, true);
});
test("an information notice replacing an error gets normal expiry", () => {
  const app = dashboard();
  app.context.notice("오류", true); app.context.notice("안내"); app.tick(5000);
  assert.equal(app.element("notice").hidden, true);
  assert.equal(app.element("notice").className, "");
});

function card() {
  return {dirty:true, busy:false, element:{setAttribute(){}}, title:{}, status:{},
    yaml:{}, os:{}, problem:{}, form:node(), save:{}, toggle:{}, summaryLink:{}, summaryId:{}, summaryCells:[node(),node(),node(),node()]};
}
const scheduledJob = {id:"demo",etag:"current",config:{
  name:"작업",schedule:{enabled:true,times:["09:00"],weekdays:[1,3]}}};
test("schedule status distinguishes applied from changed YAML", () => {
  const app=dashboard(), row=card();
  const state={supported:true,loaded:true,applied:true,file_exists:true,file_matches:true,etag:"current",desired_matches:true};
  app.context.updateScheduleCard(row,scheduledJob,state);
  assert.equal(row.status.textContent,"적용됨");
  app.context.updateScheduleCard(row,scheduledJob,{...state,etag:"old",desired_matches:false});
  assert.equal(row.status.textContent,"설정 불일치");
  assert.equal(row.summaryCells[3].textContent,"설정 불일치");
});
test("enabled YAML without registration is unapplied; disabled YAML is inactive", () => {
  const app=dashboard(), row=card();
  app.context.updateScheduleCard(row,scheduledJob,{supported:true});
  assert.equal(row.status.textContent,"미적용");
  app.context.updateScheduleCard(row,{...scheduledJob,config:{schedule:{enabled:false}}},{supported:true});
  assert.equal(row.status.textContent,"비활성 · 미등록");
});
test("failed observations are unknown, never falsely reported as absent", () => {
  const app=dashboard(), row=card();
  app.context.updateScheduleCard(row,scheduledJob,{observation_error:"permission denied"});
  assert.equal(row.status.textContent,"오류");
  assert.equal(row.os.textContent,"launchd: 상태를 확인할 수 없습니다.");
  app.context.updateScheduleCard(row,{id:"broken",error:"invalid YAML"});
  assert.equal(row.yaml.textContent,"YAML: 설정을 읽을 수 없습니다.");
  assert.equal(row.summaryCells[2].textContent,"읽기 오류");
});
test("polling preserves the editing base and pending form values", () => {
  const app=dashboard(), row=card();
  row.item={etag:"editing-base"};
  row.enabled={checked:false};
  row.times={value:"pending"};
  app.context.updateScheduleCard(row,scheduledJob,{supported:true});
  assert.equal(row.item.etag,"editing-base");
  assert.equal(row.enabled.checked,false);
  assert.equal(row.times.value,"pending");
});

const job = (id,name,schedule={enabled:false}) => ({id,config:{name,schedule}});
test("Jobs search matches name and ID, case independently", () => {
  const app=dashboard();
  const items=[job("alpha-job","매일 보고"),job("beta-job","주간 백업")];
  assert.equal(app.context.selectJobPage(items,{query:"  ALPHA  "}).items[0].id,"alpha-job");
  assert.equal(app.context.selectJobPage(items,{query:"백업"}).items[0].id,"beta-job");
  assert.equal(app.context.selectJobPage(items,{query:"없음"}).total,0);
});
test("Jobs filters distinguish execution, invalid configuration and unknown state", () => {
  const app=dashboard();
  vm.runInContext('jobStates = new Map([["a","running"],["b","succeeded"],["c","never"]])',app.context);
  const items=[job("a","실행"),job("b","성공"),job("c","대기"),{id:"bad",error:"invalid YAML"},job("unknown","미확인")];
  for (const [filter,id] of [["running","a"],["succeeded","b"],["never","c"],["error","bad"],["unknown","unknown"]]) {
    assert.equal(app.context.selectJobPage(items,{filter}).items[0].id,id);
  }
});
test("Jobs sorting, pagination and shrinking results clamp to a valid page", () => {
  const app=dashboard(), items=Array.from({length:24},(_,i)=>job("job-"+String(i).padStart(2,"0"),"Job "+String(i).padStart(2,"0")));
  let result=app.context.selectJobPage(items,{sort:"name-desc",page:2,size:10});
  assert.equal(result.total,24); assert.equal(result.pages,3); assert.equal(result.items[0].id,"job-13");
  result=app.context.selectJobPage(items,{query:"job-01",page:3,size:10});
  assert.equal(result.page,1); assert.equal(result.pages,1); assert.equal(result.items.length,1);
  result=app.context.selectJobPage(items,{page:3,size:10}); assert.equal(result.items.length,4);
});
test("Schedule ordering puts active before inactive and absent schedules", () => {
  const app=dashboard();
  const active=job("z","Z",{enabled:true,times:["09:00"]}), inactive=job("b","B",{enabled:false,times:["10:00"]}), absent=job("a","A");
  assert.equal([absent,inactive,active].sort((a,b)=>app.context.compareJobs(a,b,"active"))[0].id,"z");
  assert.equal(app.context.scheduleKind(absent),"none");
  assert.equal(app.context.scheduleKind(inactive),"disabled");
  assert.match(app.context.scheduleSummary(active),/활성.*09:00/);
});
test("Page switching exposes exactly the matching main view and navigation state", () => {
  const app=dashboard();
  for(const view of ["jobs","detail","schedules","trash"]) {
    app.context.showView(view);
    for(const [id,target] of [["jobs-view","jobs"],["detail","detail"],["schedules-view","schedules"],["trash-view","trash"]]) assert.equal(app.element(id).hidden,view!==target);
    assert.equal(app.element("jobs-menu").attributes["aria-pressed"],String(["jobs","detail"].includes(view)));
  }
});
test("Navigation cancellation preserves unsaved YAML; acceptance discards it", async () => {
  const app=dashboard();
  vm.runInContext('dirty=true; approve=async()=>false',app.context);
  assert.equal(await app.context.leaveEditor(),false);
  assert.equal(vm.runInContext('dirty',app.context),true);
  vm.runInContext('approve=async()=>true',app.context);
  assert.equal(await app.context.leaveEditor(),true);
  assert.equal(vm.runInContext('dirty',app.context),false);
});
test("Schedule list shows only the selected editor and starts with all editors hidden", () => {
  const app=dashboard();
  app.element("schedules-filter").value="all"; app.element("schedules-sort").value="active";
  const a={item:job("a","A"),summaryRow:node(),summaryLink:node(),element:node()};
  const b={item:job("b","B",{enabled:true,times:["09:00"]}),summaryRow:node(),summaryLink:node(),element:node()};
  app.context.a=a; app.context.b=b;
  vm.runInContext('scheduleCards.set("a",a); scheduleCards.set("b",b)',app.context);
  app.context.renderScheduleOverview();
  assert.equal(a.element.hidden,true); assert.equal(b.element.hidden,true);
  assert.equal(app.element("schedule-overview-rows").children[0],b.summaryRow);
  vm.runInContext('selectedSchedule="a"',app.context); app.element('schedule-edit-dialog').showModal(); app.context.renderScheduleOverview();
  assert.equal(a.element.hidden,false); assert.equal(b.element.hidden,true);
  assert.equal(a.summaryLink.attributes["aria-expanded"],"true");
});

test("Invalid YAML is distinct from a Job without a reservation", () => {
  const app=dashboard();
  assert.equal(app.context.scheduleKind({id:"broken",error:"invalid YAML"}),"error");
  const absent=job("a","A"), invalid={id:"broken",error:"invalid YAML"};
  assert.equal([invalid,absent].sort((a,b)=>app.context.compareJobs(a,b,"active"))[0].id,"a");
});
test("Navigation cancellation preserves a schedule draft and its etag", async () => {
  const app=dashboard(), draft={dirty:true,item:{etag:"base"}};
  app.context.draft=draft;
  vm.runInContext('scheduleCards.set("a",draft); approve=async()=>false',app.context);
  assert.equal(await app.context.leaveEditor(),false);
  assert.equal(draft.dirty,true); assert.equal(draft.item.etag,"base");
  vm.runInContext('approve=async()=>true',app.context);
  assert.equal(await app.context.leaveEditor(),true);
  assert.equal(draft.dirty,false);
});

test("Interval schedules have distinct summaries, filtering and observed state", () => {
  const app=dashboard(), row=card();
  const schedule={enabled:true,mode:"interval",interval:{value:2,unit:"days"}};
  const item={...scheduledJob,config:{name:"간격",schedule}};
  assert.match(app.context.scheduleSummary(item),/활성.*2일 \(24시간 단위\)마다 실행/);
  assert.equal(app.context.scheduleKind({...item,config:{schedule:{...schedule,enabled:false}}}),"disabled");
  app.context.updateScheduleCard(row,item,{supported:true,loaded:true,applied:true,file_matches:true,etag:item.etag,desired_matches:true});
  assert.equal(row.status.textContent,"적용됨");
  assert.equal(row.summaryCells[0].textContent,"—");
  assert.equal(row.summaryCells[1].textContent,"2일 (24시간 단위)마다 실행");
});

test("Switching draft mode serializes one trigger with its Schedule identity", () => {
  const app=dashboard();
  const row={item:{...scheduledJob,schedule_id:"morning"},name:{value:"아침"},enabled:{checked:true},mode:{value:"interval"},
    intervalValue:{value:"3"},intervalUnit:{value:"hours"},
    times:{querySelectorAll:()=>[{value:"09:00"}]},days:[{checked:true,value:"1"},{checked:false,value:"2"}]};
  assert.deepEqual(JSON.parse(JSON.stringify(app.context.scheduleDraft(row))),{
    id:"morning",name:"아침",enabled:true,type:"interval",interval_seconds:10800});
  row.mode.value="calendar";
  assert.deepEqual(JSON.parse(JSON.stringify(app.context.scheduleDraft(row))),{id:"morning",name:"아침",enabled:true,type:"calendar",times:["09:00"],weekdays:[1]});
  row.mode.value="interval";
  assert.equal(app.context.scheduleDraft(row).interval_seconds,10800);
});

test("Job summaries count mixed schedules and OS status uses per-Schedule matches", () => {
  const app=dashboard();
  assert.equal(app.context.scheduleSummary({config:{schedules:[{enabled:true},{enabled:false}]}}),"2개 예약 · 활성 1개 · 일시중지 1개");
  assert.equal(app.context.scheduleStatus({loaded:true,applied:true,file_matches:true,desired_matches:true},{enabled:true}).label,"적용됨");
  assert.equal(app.context.scheduleStatus({loaded:true,applied:true,file_matches:true,desired_matches:false},{enabled:true}).label,"설정 불일치");
  assert.equal(app.context.scheduleStatus({loaded:true},{enabled:false},true).label,"유령 예약");
});

test("An empty disabled calendar still appears in the inactive Schedule filter", () => {
  const app=dashboard();
  assert.equal(app.context.scheduleKind({config:{schedule:{id:"legacy",enabled:false,type:"calendar",times:[]}}}),"disabled");
});

function selectedDetail(app) {
  vm.runInContext('selected="sample-hello"; current={}; selectedRun="run"; dirty=true; basicDirty=true; view="detail";',app.context);
  app.element('jobs-page-size').value='10'; app.element('jobs-filter').value='all';
}
test('missing Job in refreshed list clears detail selection', async()=>{
  const app=dashboard(); selectedDetail(app);
  vm.runInContext('api=async()=>[]',app.context);
  await app.context.jobs();
  assert.equal(vm.runInContext('selected',app.context),null);
  assert.equal(vm.runInContext('current',app.context),null);
  assert.equal(vm.runInContext('dirty || basicDirty',app.context),false);
  assert.equal(vm.runInContext('view',app.context),'jobs');
});
test('detail 404 confirms missing Job and returns to list',async()=>{
  const app=dashboard(); selectedDetail(app);
  vm.runInContext('api=async p=>{if(p==="jobs")return []; throw Object.assign(new Error("missing"),{status:404});}',app.context);
  await app.context.refreshDetail();
  assert.equal(vm.runInContext('view',app.context),'jobs');
  assert.equal(vm.runInContext('selectedRun',app.context),null);
});
test('route 404 for existing Job remains an error',async()=>{
  const app=dashboard(); selectedDetail(app);
  vm.runInContext('api=async p=>{if(p==="jobs/sample-hello")return {id:"sample-hello"}; throw Object.assign(new Error("route missing"),{status:404});}',app.context);
  await assert.rejects(app.context.refreshDetail(),/route missing/);
  assert.equal(vm.runInContext('selected',app.context),'sample-hello');
});
test('deleted Job during choose is handled normally',async()=>{
  const app=dashboard(); app.element('jobs-page-size').value='10'; app.element('jobs-filter').value='all';
  vm.runInContext('api=async p=>{if(p==="jobs")return []; throw Object.assign(new Error("missing"),{status:404});}',app.context);
  await app.context.choose('sample-hello');
  assert.equal(vm.runInContext('view',app.context),'jobs');
});
test('API error preserves HTTP status',async()=>{
  const app=dashboard(); app.context.fetch=async()=>({ok:false,status:404,json:async()=>({error:'missing'})});
  await assert.rejects(app.context.api('jobs/missing'),error=>error.status===404);
});
test('selection cleanup removes only matching schedule hash',()=>{
  const app=dashboard(); let replacement;
  app.context.window.location={hash:'#schedule-editor-sample-hello/legacy',pathname:'/',search:''};
  app.context.window.history={replaceState(a,b,url){replacement=url;}};
  app.context.clearJobSelection('sample-hello'); assert.equal(replacement,'/');
  replacement=undefined; app.context.window.location.hash='#schedule-editor-sample-hello-other';
  app.context.clearJobSelection('sample-hello'); assert.equal(replacement,undefined);
});
test('list refresh clears a deleted Job hash even without selection',async()=>{
 const app=dashboard(); let url;
 app.element('jobs-page-size').value='10'; app.element('jobs-filter').value='all';
 app.context.window.location={hash:'#schedule-editor-sample-hello',pathname:'/',search:'?a=1'};
 app.context.window.history={replaceState(a,b,value){url=value;}};
 vm.runInContext('api=async()=>[]',app.context);
 await app.context.jobs(); assert.equal(url,'/?a=1');
});

test('cleaned package keeps metadata visible and disables download and deployment',async()=>{
  const app=dashboard(); selectedDetail(app);
  vm.runInContext('api=async()=>[{id:"p-old",created_at:"2026-01-01",zip_available:false,content_hash:"hash",zip_sha256:"zip"}]',app.context);
  app.element('target').value='test';
  await app.context.refreshPackages([], 'sample-hello');
  assert.equal(app.element('package-download').disabled,true);
  assert.equal(app.element('plan').disabled,true);
  assert.match(app.element('package-info').textContent,/p-old/);
});
test('package download preserves the API route and encodes the Package ID',async()=>{
  const app=dashboard(), links=[], actions=[];
  vm.runInContext('selected="demo"',app.context);
  app.context.document.createElement=tag=>{
    const link=node(tag);
    link.click=()=>actions.push('click'); link.remove=()=>actions.push('remove');
    links.push(link); return link;
  };
  app.context.document.body={append:link=>{assert.equal(link,links.at(-1));actions.push('append');}};
  for(const [id,component] of [['p-0123456789abcdef','p-0123456789abcdef'],
                               ['p/a?b#c% "<tag>','p%2Fa%3Fb%23c%25%20%22%3Ctag%3E']]){
    app.element('package-select').value=id;
    await app.element('package-download').onclick();
    const link=links.at(-1);
    assert.equal(link.href,'/api/jobs/demo/packages/'+component+'/download');
    assert.equal(link.download,'demo-'+id+'.zip');
    assert.deepEqual(actions.splice(0),['append','click','remove']);
  }
  const count=links.length;
  app.element('package-select').value='';
  await app.element('package-download').onclick();
  assert.equal(links.length,count);
  assert.equal(app.element('notice').className,'error');
  assert.equal(app.element('notice-message').textContent,'Package를 선택하세요.');
});
test('deployment UI sends the selected Package and confirmed plan hash',async()=>{
  const app=dashboard(), calls=[];
  vm.runInContext('selected="demo"; approve=async()=>true; refreshDetail=async()=>{};',app.context);
  app.element('package-select').value='p-selected';
  app.element('target').value='test';
  app.context.api=async(path,method,body)=>{
    calls.push({path,method,body:JSON.parse(JSON.stringify(body))});
    return path.endsWith('/deploy-plan') ? {package_id:'p-selected',plan_hash:'confirmed-hash'} : {status:'verified'};
  };
  await app.element('plan').onclick();
  assert.equal(app.element('deploy').disabled,false);
  await app.element('deploy').onclick();
  assert.deepEqual(calls,[
    {path:'jobs/demo/deploy-plan',method:'POST',body:{target:'test',package_id:'p-selected'}},
    {path:'jobs/demo/deploy',method:'POST',body:{target:'test',package_id:'p-selected',plan_hash:'confirmed-hash'}}
  ]);
  assert.equal(vm.runInContext('planHash',app.context),null);
  assert.equal(vm.runInContext('plannedPackage',app.context),null);
});
test('lifecycle polling preserves a draft policy',async()=>{
  const app=dashboard(); selectedDetail(app);
  vm.runInContext('api=async()=>({policy:{package_keep:5,output_days:null,output_runs:null,package_auto:false,output_auto:false},paths:{},usage:{},packages:[],outputs:[]})',app.context);
  await app.context.refreshLifecycle('sample-hello');
  app.element('package-keep').value='9'; app.element('package-keep').oninput();
  await app.context.refreshLifecycle('sample-hello');
  assert.equal(app.element('package-keep').value,'9');
});
test('cleanup requires a preview before making a request',async()=>{
  const app=dashboard(); selectedDetail(app);
  await app.element('cleanup-output').onclick();
  assert.match(app.element('notice-message').textContent,/미리보기/);
});

test('local run timestamps use browser timezone, seconds and a 24-hour clock', () => {
  const app=dashboard(), original=process.env.TZ;
  try {
    for (const [zone,expected] of [
      ['UTC','2026.11.12 16:05:09'], ['Asia/Seoul','2026.11.13 01:05:09'],
      ['America/New_York','2026.11.12 11:05:09']
    ]) {
      process.env.TZ=zone;
      assert.equal(app.context.localDate('2026-11-12T16:05:09Z'),expected);
      assert.equal(app.context.localDate('2026-11-12T17:05:09+01:00'),expected);
    }
    process.env.TZ='America/New_York';
    assert.equal(app.context.localDate('2026-07-01T04:00:00Z'),'2026.07.01 00:00:00');
    for (const invalid of [null,undefined,'','bad-date']) assert.equal(app.context.localDate(invalid),'—');
  } finally { if (original===undefined) delete process.env.TZ; else process.env.TZ=original; }
});
test('run sorting compares instants, keeps deterministic ties and leaves input intact', () => {
  const app=dashboard(), runs=[
    {id:'a',created_at:'2026-11-12T16:00:00Z'},
    {id:'b',created_at:'2026-11-13T00:00:00+09:00'},
    {id:'c',created_at:'2026-11-12T16:00:00Z'}
  ];
  assert.equal(app.context.newestRuns(runs).map(r=>r.id).join(','),'c,a,b');
  assert.equal(runs.map(r=>r.id).join(','),'a,b,c');
});
test('run status and elapsed duration distinguish success, failure and active execution', () => {
  const app=dashboard();
  for (const [state,label,kind] of [['succeeded','성공','good'],['failed','실패','error'],['running','실행 중','active'],['queued','대기','active']]) {
    const badge=app.context.runBadge({state});
    assert.equal(badge.textContent,label); assert.equal(badge.className,'status '+kind);
  }
  const started_at='2026-11-12T00:00:00Z';
  assert.equal(app.context.runDuration({started_at,finished_at:'2026-11-12T00:01:05Z',state:'succeeded'}),65);
  assert.equal(app.context.runDuration({started_at,state:'running'},Date.parse(started_at)+3000),3);
  assert.equal(app.context.runDuration({state:'queued'}),null);
  assert.equal(app.context.runDuration({started_at,finished_at:'2026-11-11T00:00:00Z'}),0);
  assert.equal(app.context.durationText(65),'1분 5초');
});
function jobList(app) {
  app.element('jobs-page-size').value='10'; app.element('jobs-filter').value='all';
  vm.runInContext('view="jobs"; jobItems=[{id:"demo",config:{name:"작업",schedules:[{enabled:false}]}}]; jobStates.set("demo","never");',app.context);
  app.context.renderJobs();
  return app.element('jobs').children[0];
}
test('Job rows open by click, Enter or Space while ignoring nested button keys', async () => {
  const app=dashboard(), row=jobList(app), opened=[]; let prevented=0;
  app.context.choose=async id=>opened.push(id);
  await row.onclick();
  for (const key of ['Enter',' ']) row.onkeydown({target:row,key,preventDefault(){prevented++;}});
  row.onkeydown({target:row.children[3].children[0],key:'Enter',preventDefault(){throw Error('nested event consumed');}});
  row.onkeydown({target:row,key:'Tab',preventDefault(){throw Error('Tab consumed');}});
  assert.equal(row.tabIndex,0); assert.equal(prevented,2); assert.deepEqual(opened,['demo','demo','demo']);
});
test('manual run button is isolated from row navigation, blocks duplicates and runs with schedules paused', async () => {
  const app=dashboard(), row=jobList(app), button=row.children[3].children[0];
  let resolve, requests=0, stopped=0;
  app.context.api=async(path,method)=>{assert.equal(path,'jobs/demo/runs'); assert.equal(method,'POST'); requests++; return new Promise(done=>resolve=done);};
  app.context.choose=()=>{throw Error('Unexpected row navigation');};
  const request=button.onclick({stopPropagation(){stopped++;},preventDefault(){}});
  const pending=app.element('jobs').children[0].children[3].children[0];
  assert.equal(pending.disabled,true); assert.equal(pending.textContent,'요청 중…');
  await app.context.startManualRun('demo'); assert.equal(requests,1); assert.equal(stopped,1);
  resolve({id:'new-run',state:'queued',created_at:'2026-11-12T00:00:00Z'}); await request;
  assert.equal(app.element('jobs').children[0].children[3].children[0].disabled,true);
  assert.match(app.element('notice-message').textContent,/실행.*요청/);
  await app.context.startManualRun('demo'); assert.equal(requests,1);
});
test('manual run request errors show feedback and release the pending state for retry', async () => {
  const app=dashboard(); jobList(app); let requests=0;
  app.context.api=async()=>{requests++; throw new Error('실행 요청 실패');};
  for(let attempt=0;attempt<2;attempt++) {
    const button=app.element('jobs').children[0].children[3].children[0];
    await button.onclick({stopPropagation(){},preventDefault(){}});
    assert.equal(app.element('jobs').children[0].children[3].children[0].disabled,false);
    assert.equal(app.element('notice-message').textContent,'실행 요청 실패');
  }
  assert.equal(requests,2);
});
test('Jobs fetch picks the latest instant and shows localized result and last execution time', async () => {
  const app=dashboard(); jobList(app);
  app.context.api=async path=>path==='jobs' ? [{id:'demo',config:{name:'작업'}}] : [
    {id:'old',state:'failed',created_at:'2026-11-13T00:00:00+09:00'},
    {id:'new',state:'succeeded',created_at:'2026-11-12T16:00:00Z'}
  ];
  await app.context.jobs();
  const cell=app.element('jobs').children[0].children[1];
  assert.equal(cell.children[0].textContent,'성공');
  assert.equal(cell.children[1].textContent,'마지막 실행 '+app.context.localDate('2026-11-12T16:00:00Z'));
});
test('timeline renders sorted Korean records and preserves Run IDs in tooltips and log action', async () => {
  const app=dashboard(); let opened;
  app.context.openTimelineRun=async run=>opened=run.id;
  app.context.api=async()=>({jobs:[],summary:{},upcoming:[],uncalculated:[],errors:[],timeline:[
    {id:'old-run',job_name:'이전',created_at:'2026-11-12T00:00:00Z',state:'failed',trigger:'schedule',duration_seconds:2},
    {id:'new-run',job_name:'최근',created_at:'2026-11-12T01:00:00Z',state:'running',trigger:'manual',duration_seconds:3}
  ]});
  await app.context.refreshOverview();
  const rows=app.element('timeline-rows').children;
  assert.equal(rows[0].children[0].textContent,'최근');
  assert.equal(rows[0].children[0].children[0].title,'Run ID: new-run');
  assert.equal(rows[0].children[3].textContent,'실행 중');
  assert.equal(rows[1].children[2].textContent,'예약');
  assert.equal(rows[1].children[3].textContent,'실패');
  assert.doesNotMatch(rows[0].textContent,/T01:00:00Z|new-run/);
  await rows[0].children[0].children[0].onclick(); assert.equal(opened,'new-run');
});
test('detail records reuse local time, newest ordering, duration and log access', async () => {
  const app=dashboard(); let logs=0;
  vm.runInContext('selected="demo"; current={config:{name:"작업"}}; view="detail"; refreshPackages=async()=>{}; refreshLifecycle=async()=>{};',app.context);
  app.context.logs=async()=>logs++;
  app.context.api=async path=>path.endsWith('/runs') ? [
    {id:'old',created_at:'2026-11-12T00:00:00Z',state:'failed',trigger:'schedule'},
    {id:'new',created_at:'2026-11-12T01:00:00Z',state:'succeeded',trigger:'manual',started_at:'2026-11-12T01:00:00Z',finished_at:'2026-11-12T01:00:08Z'}
  ] : [];
  await app.context.refreshDetail();
  const button=app.element('runs').children[0].children[0];
  assert.equal(button.title,'Run ID: new'); assert.match(button.textContent,/작업.*실행 방식: 수동.*성공.*소요 시간: 8초/);
  assert.doesNotMatch(button.textContent,/succeeded|T01:00:00Z/);
  await button.onclick(); assert.equal(logs,1);
});
test('Schedule create X, Cancel and ESC agree and cannot dismiss during save', async () => {
  const app=dashboard(), dialog=app.element('schedule-create-dialog');
  for (const close of [()=>app.element('schedule-create-close').onclick(),()=>app.element('schedule-create-cancel').onclick(),()=>dialog.oncancel({preventDefault(){}})]) {
    dialog.showModal(); close(); assert.equal(dialog.open,false);
  }
  let release;
  app.context.api=()=>new Promise(done=>release=done);
  app.element('schedule-type').value='interval'; app.element('schedule-seconds').value='1800';
  dialog.showModal(); const saving=app.element('schedule-create').onsubmit();
  for (const id of ['schedule-create-close','schedule-create-cancel','schedule-create-submit']) assert.equal(app.element(id).disabled,true);
  app.element('schedule-create-close').onclick(); app.element('schedule-create-cancel').onclick(); dialog.oncancel({preventDefault(){}});
  assert.equal(dialog.open,true);
  // Failure keeps the modal and values available for correction.
  release(null); await saving;
  assert.equal(dialog.open,true); assert.equal(app.element('schedule-seconds').value,'1800');
  assert.equal(app.element('schedule-create-close').disabled,false);
});
test('Schedule create submits selected weekdays and enabled state with the existing etag API', async () => {
  const app=dashboard(), requests=[];
  for(const [id,value] of [['schedule-job','demo'],['schedule-new-id','morning'],['schedule-new-name','아침'],['schedule-type','calendar'],['schedule-times','08:00, 18:00']]) app.element(id).value=value;
  app.element('schedule-enabled').checked=false;
  for(const value of ['1','3','7']) { const input=node('input'); input.checked=true; input.value=value; app.element('schedule-new-days').append(input); }
  app.context.api=async(path,method,body)=>{requests.push({path,method,body}); return path==='jobs/demo' ? {id:'demo',etag:'base'} : {};};
  app.context.refreshSchedules=async()=>{};
  app.element('schedule-create-dialog').showModal(); await app.element('schedule-create').onsubmit();
  assert.equal(app.element('schedule-create-dialog').open,false);
  assert.deepEqual(JSON.parse(JSON.stringify(requests[1])),{path:'jobs/demo/schedules',method:'POST',body:{etag:'base',schedule:{id:'morning',name:'아침',enabled:false,type:'calendar',times:['08:00','18:00'],weekdays:[1,3,7]}}});
});
test('Schedule editor close and ESC preserve dirty drafts when cancelled and block busy closure', async () => {
  const app=dashboard(), dialog=app.element('schedule-edit-dialog');
  const draft={dirty:true,busy:false}; app.context.draft=draft;
  vm.runInContext('scheduleCards.set("demo/morning",draft); selectedSchedule="demo/morning"; approve=async()=>false; renderScheduleOverview=()=>{};',app.context);
  dialog.showModal(); await app.element('schedule-editor-close').onclick(); assert.equal(dialog.open,true); assert.equal(draft.dirty,true);
  draft.busy=true; vm.runInContext('approve=async()=>true',app.context);
  await app.context.closeScheduleEditor(); assert.equal(dialog.open,true);
  draft.busy=false; dialog.oncancel({preventDefault(){}}); await new Promise(resolve=>setImmediate(resolve));
  assert.equal(dialog.open,false); assert.equal(draft.dirty,false);
});
test('Schedule edit retains form values and uses existing save API, identity and etag', async () => {
  const app=dashboard(), requests=[];
  const row=app.context.createScheduleCard({id:'demo/morning',job_id:'demo',schedule_id:'morning',etag:'base',config:{schedule:{}}});
  row.name.value='아침'; row.enabled.checked=true; row.mode.value='calendar'; row.dirty=true;
  app.context.addScheduleTime(row,'09:30'); row.days[0].checked=true; row.days[4].checked=true;
  app.context.api=async(path,method,body)=>requests.push({path,method,body}); app.context.refreshSchedules=async()=>{};
  await row.form.onsubmit();
  assert.deepEqual(JSON.parse(JSON.stringify(requests)),[{path:'jobs/demo/schedules/morning',method:'PUT',body:{etag:'base',schedule:{id:'morning',name:'아침',enabled:true,type:'calendar',times:['09:30'],weekdays:[1,5]}}}]);
  assert.equal(row.dirty,false); assert.equal(row.busy,false); assert.equal(row.days[4].checked,true);
  assert.equal(row.days[0].type,'checkbox');
});
test('an older polling response cannot overwrite a newly accepted manual run', async () => {
  const app=dashboard(); jobList(app); let finishPoll;
  const item={id:'demo',config:{name:'작업'}};
  app.context.api=async(path,method)=>{
    if(path==='jobs') return [item];
    if(method==='POST') return {id:'new',state:'queued',created_at:'2026-11-12T01:00:00Z'};
    return new Promise(resolve=>finishPoll=resolve);
  };
  const polling=app.context.jobs(); await new Promise(resolve=>setImmediate(resolve));
  await app.context.startManualRun('demo');
  finishPoll([{id:'old',state:'succeeded',created_at:'2026-11-12T00:00:00Z'}]); await polling;
  const row=app.element('jobs').children[0];
  assert.equal(row.children[1].children[0].textContent,'대기');
  assert.equal(row.children[3].children[0].disabled,true);
});

test('parameter form renders types, defaults, bounds and optional omission without HTML injection', () => {
  const app=dashboard();
  app.context.openParameterRun({id:'demo',config:{name:'<script>',parameters:{
    text:{type:'string',description:'<img src=x>',required:true},
    count:{type:'integer',default:2,min:1,max:5},
    ratio:{type:'number',default:.5},
    day:{type:'date',min:'2026-01-01'},
    source:{type:'string',choices:['one','two'],default:'one'},
    enabled:{type:'boolean',default:false},
    optional:{type:'boolean'}
  }}});
  const fields=vm.runInContext('parameterRun.fields',app.context);
  assert.equal(app.element('parameter-dialog').open,true);
  assert.equal(app.element('parameter-title').textContent,'<script> 실행 입력');
  assert.equal(fields.get('text').input.type,'text');
  assert.equal(fields.get('text').input.required,true);
  assert.equal(fields.get('count').input.type,'number');
  assert.equal(fields.get('count').input.step,'1');
  assert.equal(fields.get('count').input.min,'1');
  assert.equal(fields.get('count').input.max,'5');
  assert.equal(fields.get('ratio').input.step,'any');
  assert.equal(fields.get('day').input.type,'date');
  assert.equal(fields.get('source').input.tagName,'SELECT');
  assert.equal(fields.get('enabled').input.type,'checkbox');
  assert.equal(fields.get('enabled').input.checked,false);
  assert.equal(fields.get('optional').include.checked,false);
  assert.equal(fields.get('optional').input.disabled,true);
  fields.get('text').input.value='literal';
  const values=app.context.readParameterInputs(fields);
  assert.deepEqual(JSON.parse(JSON.stringify(values)),{text:'literal',count:2,ratio:.5,source:'one',enabled:false});
  fields.get('optional').include.checked=true;
  fields.get('optional').include.onchange();
  assert.equal(fields.get('optional').input.disabled,false);
  fields.get('optional').input.checked=false;
  assert.equal(app.context.readParameterInputs(fields).optional,false);
  fields.get('count').include.checked=false;
  assert.equal(Object.hasOwn(app.context.readParameterInputs(fields),'count'),false);
});
test('declared parameter jobs discover the contract before submission; cancelling never submits', async () => {
  const app=dashboard();
  vm.runInContext('jobItems=[{id:"demo",config:{parameters:{count:{type:"integer"}}}}]',app.context);
  const paths=[];
  app.context.api=async(path,method)=>{paths.push([path,method]); return {id:'demo',config:{name:'Demo',parameters:{count:{type:'integer'}}}};};
  await app.context.startManualRun('demo');
  assert.deepEqual(paths,[['jobs/demo',undefined]]);
  assert.equal(app.element('parameter-dialog').open,true);
  app.element('parameter-cancel').onclick();
  assert.equal(app.element('parameter-dialog').open,false);
  assert.equal(paths.length,1);
});
test('parameter form submits typed values to the existing API and retains draft on server error', async () => {
  const app=dashboard();
  app.context.openParameterRun({id:'demo',config:{name:'Demo',parameters:{count:{type:'integer',default:2},enabled:{type:'boolean',default:false}}}});
  app.element('parameter-form').reportValidity=()=>true;
  const fields=vm.runInContext('parameterRun.fields',app.context);
  fields.get('count').input.value='9';
  let calls=0;
  app.context.api=async(path,method,body)=>{
    assert.equal(path,'jobs/demo/runs'); assert.equal(method,'POST');
    assert.equal(body.parameters.count,9); assert.equal(body.parameters.enabled,false);
    calls++; throw new Error('파라미터 count: 허용 범위를 벗어났습니다.');
  };
  await app.element('parameter-form').onsubmit();
  assert.equal(calls,1);
  assert.match(app.element('parameter-error').textContent,/허용 범위/);
  assert.equal(app.element('parameter-dialog').open,true);
  assert.equal(fields.get('count').input.value,'9');
  assert.equal(app.element('parameter-submit').disabled,false);
  assert.equal(vm.runInContext('pendingRuns.size',app.context),0);
  app.context.api=async()=>({id:'run',state:'queued'});
  await app.element('parameter-form').onsubmit();
  assert.equal(app.element('parameter-dialog').open,false);
});
test('run detail uses the stored parameter contract and hides it for legacy history', () => {
  const app=dashboard();
  app.context.renderRunParameters({parameters:{count:2},parameter_contract_version:1,config:{parameters:{count:{type:'integer',default:2}}}});
  assert.equal(app.element('run-parameters').hidden,false);
  const detail=JSON.parse(app.element('run-parameters-values').textContent);
  assert.deepEqual(detail,{contract_version:1,values:{count:2},definitions:{count:{type:'integer',default:2}}});
  app.context.renderRunParameters({config:{}});
  assert.equal(app.element('run-parameters').hidden,true);
  assert.equal(app.element('run-parameters-values').textContent,'');
});
test('accepted parameter run closes the draft before observation failure and cannot resubmit it', async () => {
  const app=dashboard();
  app.context.openParameterRun({id:'demo',config:{name:'Demo',parameters:{text:{type:'string',default:'safe'}}}});
  app.element('parameter-form').reportValidity=()=>true;
  vm.runInContext('selected="demo"; view="detail"; renderJobs=()=>{}; updateRunButton=()=>{}; refreshDetail=async()=>{throw new Error("status unavailable")}',app.context);
  let submissions=0;
  app.context.api=async()=>{submissions++;return {id:'accepted',state:'queued'};};
  await app.element('parameter-form').onsubmit();
  assert.equal(submissions,1);
  assert.equal(app.element('parameter-dialog').open,false);
  assert.equal(vm.runInContext('parameterRun',app.context),undefined);
  assert.match(app.element('notice-message').textContent,/실행 접수 후 조회 오류/);
  await app.element('parameter-form').onsubmit();
  assert.equal(submissions,1);
});

test('report settings preserve omitted defaults and use the existing etag update', async () => {
  const app=dashboard(), requests=[];
  vm.runInContext('selected="demo";current={etag:"base",yaml:"original",config:{name:"Demo",command:["python3","main.py"]}};jobs=async()=>{};refreshDetail=async()=>{};',app.context);
  app.context.populateJobSettings();
  assert.equal(app.element('setting-report-enabled').checked,false);
  assert.equal(app.element('setting-report-dir').value,'default');
  assert.equal(app.element('setting-report-filename').value,'');
  app.context.api=async(path,method,body)=>{
    requests.push({path,method,body});
    return {etag:'next',yaml:'saved',config:{...body.fields}};
  };
  await app.element('job-settings').onsubmit();
  assert.equal(Object.hasOwn(requests[0].body.fields,'report'),false);
  app.element('setting-report-enabled').checked=true;
  app.element('setting-report-source').value='nested/report.json';
  app.element('setting-report-dir').value='exports/team';
  app.element('setting-report-filename').value='latest.html';
  app.element('setting-report-source').oninput();
  assert.equal(app.element('yaml').readOnly,true);
  await app.element('job-settings').onsubmit();
  assert.deepEqual(JSON.parse(JSON.stringify(requests[1])),{path:'jobs/demo',method:'PUT',body:{etag:'next',fields:{
    name:'Demo',description:'',command:['python3','main.py'],cwd:'.',env:{},env_file:null,timeout_seconds:300,
    report:{enabled:true,source:'nested/report.json',output_dir:'exports/team',filename:'latest.html'}
  }}});
  assert.equal(app.element('setting-report-enabled').checked,true);
  assert.equal(app.element('setting-report-source').value,'nested/report.json');
});
test('report links preview and status handle successful and failed lookups without hiding job data', async () => {
  const app=dashboard();
  vm.runInContext('selected="demo";view="detail"',app.context);
  app.context.api=async()=>({available:true,path:'/project/reports/demo.html',generated_at:'2026-11-13T01:00:00Z',count:3,sha256:'abc'});
  await app.context.refreshReport('demo');
  assert.equal(app.element('report-open').hidden,false);
  assert.equal(app.element('report-open').href,'/api/jobs/demo/report/html?v=abc');
  assert.equal(app.element('report-download').href,'/api/jobs/demo/report/download');
  assert.match(app.element('report-status').textContent,/3건/);
  assert.equal(app.element('report-frame').hidden,true);
  app.element('report-preview').onclick();
  assert.equal(app.element('report-frame').hidden,false);
  assert.equal(app.element('report-frame').src,'/api/jobs/demo/report/html?v=abc');
  app.element('report-preview-close').onclick();
  assert.equal(app.element('report-frame').hidden,true);
  app.context.api=async()=>{throw new Error('report unavailable');};
  await app.context.refreshReport('demo');
  assert.match(app.element('report-status').textContent,/조회 실패/);
  assert.equal(app.element('report-open').hidden,true);
  assert.equal(app.element('report-preview').disabled,true);
});
test('stale report responses cannot expose another selected job report', async () => {
  const app=dashboard();let finish;
  vm.runInContext('selected="old";view="detail"',app.context);
  app.context.api=()=>new Promise(resolve=>finish=resolve);
  const task=app.context.refreshReport('old');
  vm.runInContext('selected="new"',app.context);
  finish({available:true,path:'old.html',count:1});await task;
  assert.equal(app.element('report-open').hidden,true);
});

test('detail pagination defaults to 20, preserves selected logs across pages and can jump back',async()=>{
  const app=dashboard(); let logCalls=0;
  vm.runInContext('selected="demo";current={config:{name:"작업"}};view="detail";runItems=Array.from({length:45},(_,i)=>({id:"r"+i,created_at:"2026-11-12T01:00:00Z",state:"succeeded"}));',app.context);
  app.context.logs=async()=>logCalls++;
  app.context.renderRuns();
  assert.equal(app.element('runs').children.length,20);
  assert.match(app.element('runs-count').textContent,/전체 45건.*1–20/);
  await app.element('runs').children[0].children[0].onclick();
  app.element('logs').textContent='selected r0 log';
  app.element('runs-next').onclick();
  assert.equal(app.element('runs').children[0].children[0].title,'Run ID: r20');
  assert.equal(app.element('logs').textContent,'selected r0 log');
  assert.match(app.element('selected-run-label').textContent,/r0.*페이지 밖/);
  assert.equal(logCalls,1); assert.equal(app.element('selected-run-jump').hidden,false);
  app.element('selected-run-jump').onclick();
  assert.equal(app.element('runs').children[0].children[0].attributes['aria-pressed'],'true');
  assert.equal(app.element('runs-page').textContent,'1 / 3');
  app.element('runs-next').onclick();app.element('runs-next').onclick();
  assert.equal(app.element('runs').children.length,5);assert.equal(app.element('runs-next').disabled,true);
  vm.runInContext('runItems=runItems.slice(0,1)',app.context); app.context.renderRuns();
  assert.equal(app.element('runs-page').textContent,'1 / 1');
});
test('settings conflict preserves draft and original etag; success synchronizes both editors',async()=>{
  const app=dashboard();
  vm.runInContext('selected="demo";current={etag:"base",yaml:"original",config:{name:"Original",command:["python3","main.py"]}};dirty=true;basicDirty=true;view="detail";jobs=async()=>{};refreshDetail=async()=>{}',app.context);
  app.element('setting-name').value='draft';app.element('yaml').value='original';
  app.context.api=async()=>{throw Object.assign(new Error('conflict'),{status:409});};
  await assert.rejects(app.context.saveJobSettings({fields:{name:'draft'}}),/충돌/);
  assert.equal(app.element('setting-name').value,'draft');assert.equal(app.element('settings-conflict').hidden,false);
  assert.equal(vm.runInContext('current.etag',app.context),'base');
  assert.equal(app.element('yaml').readOnly,true); assert.equal(app.element('run').disabled,true);
  app.context.api=async(path,method,body)=>{assert.equal(body.etag,'base');return {etag:'new',yaml:'saved yaml',config:{name:'Saved',command:['python3','main.py']}};};
  await app.context.saveJobSettings({fields:{name:'draft'}});
  assert.equal(app.element('yaml').value,'saved yaml');assert.equal(app.element('setting-name').value,'Saved');
  assert.equal(app.element('settings-conflict').hidden,true);assert.equal(app.element('yaml').readOnly,false);
  assert.equal(vm.runInContext('dirty || basicDirty',app.context),false);
});
test('YAML edits lock the form, save through etag and retain YAML on validation failure',async()=>{
  const app=dashboard();
  vm.runInContext('selected="demo";current={etag:"base",config:{name:"Job",command:["python3"]}};jobs=async()=>{};refreshDetail=async()=>{}',app.context);
  app.element('yaml').value='draft yaml';app.element('yaml').oninput();
  assert.equal(app.element('settings-save').disabled,true);assert.equal(app.element('save').disabled,false);
  let request;
  app.context.api=async(path,method,body)=>{request=body;throw Object.assign(new Error('invalid YAML'),{status:400});};
  await app.element('save').onclick();
  assert.equal(request.yaml,'draft yaml');assert.equal(request.etag,'base');
  assert.equal(app.element('yaml').value,'draft yaml'); assert.equal(vm.runInContext('dirty',app.context),true);
  assert.equal(app.element('settings-save').disabled,true);
});
test('rapid stream switch ignores late stdout and shows only the chosen stderr',async()=>{
  const app=dashboard(); let finish;
  vm.runInContext('selected="demo";selectedRun="r1";',app.context);
  app.element('stream').value='stdout';
  app.context.api=async path=>path.includes('/logs') ? new Promise(resolve=>finish=resolve) : {};
  const old=app.context.logs();await new Promise(resolve=>setImmediate(resolve));
  app.element('stream').value='stderr';
  app.context.api=async path=>path.includes('/logs') ? {text:path.endsWith('offset=0') ? 'stderr only' : '',offset:11} : {};
  await app.context.logs();finish({text:'stale stdout',offset:12});await old;
  assert.equal(app.element('logs').textContent,'stderr only');
});
test('lifecycle preview summarizes counts and bytes, gates actions and invalidates on draft change',async()=>{
  const app=dashboard();
  vm.runInContext('selected="demo";view="detail"',app.context);
  app.context.api=async()=>({policy:{package_keep:5,pins:[],rollback_packages:[]},paths:{},usage:{},packages:[{id:'p1',zip_available:true,zip_bytes:1048576,protection:[],cleanup_candidate:true}],outputs:[{id:'r1',bytes:2097152,cleanup_candidate:true}],package_reclaim_bytes:1048576,output_move_bytes:2097152});
  await app.element('lifecycle-preview').onclick();
  assert.match(app.element('lifecycle-preview-summary').textContent,/ZIP 영구 삭제 1건.*1.00 MiB.*Output 휴지통 이동 1건.*2.00 MiB/);
  assert.equal(app.element('cleanup-packages').disabled,false);assert.equal(app.element('cleanup-output').disabled,false);
  app.element('output-days').oninput();
  assert.equal(app.element('cleanup-packages').disabled,true);assert.equal(app.element('cleanup-output').disabled,true);
});
test('destination preview uses server validation and ignores stale replies',async()=>{
  const app=dashboard();let finish;
  vm.runInContext('selected="demo"',app.context);
  app.element('setting-report-dir').value='default';
  app.context.api=()=>new Promise(resolve=>finish=resolve);
  app.context.queueDestinationPreview();app.tick(250);
  app.element('setting-report-dir').value='exports';
  app.context.api=async(path,method,body)=>{assert.equal(body.output_dir,'exports');return {path:'/project/exports/demo.html'};};
  app.context.queueDestinationPreview();app.tick(250);await new Promise(resolve=>setImmediate(resolve));
  finish({path:'/project/reports/demo.html'});await new Promise(resolve=>setImmediate(resolve));
  assert.match(app.element('report-destination').textContent,/exports\/demo.html/);
});

test('late deployment plans never enable deployment after the selection changes',async()=>{
  const app=dashboard();let finish;
  vm.runInContext('selected="demo"',app.context);
  app.element('package-select').value='p1';app.element('target').value='first';
  app.context.api=()=>new Promise(resolve=>finish=resolve);
  const task=app.element('plan').onclick();
  app.element('target').value='second';app.context.invalidatePlan();
  finish({plan_hash:'stale'});await task;
  assert.equal(app.element('deploy').disabled,true);
  assert.equal(vm.runInContext('planHash',app.context),null);
  assert.equal(app.element('deployment-plan').hidden,true);
});
test('deployment summary compares the recorded deployed Package instead of the selected one',async()=>{
  const app=dashboard();vm.runInContext('selected="demo";view="detail"',app.context);
  app.element('target').value='prod';app.element('package-select').value='p-selected';
  const calls=[];
  app.context.api=async path=>{
    calls.push(path);
    if(path.endsWith('/packages'))return [{id:'p-selected',manifest:{},zip_available:true}];
    return {changed:path.includes('p-deployed'),added:[],removed:[],modified:path.includes('p-deployed')?['main.py']:[]};
  };
  await app.context.refreshPackages([{target:'prod',action:'deploy',package_id:'p-deployed',created_at:'2026-11-13'}],'demo');
  assert.match(app.element('package-difference').textContent,/같습니다/);
  assert.match(app.element('deployment-difference').textContent,/p-deployed.*차이 있음.*수정 1/);
  assert.equal(calls.includes('jobs/demo/packages/p-deployed/difference'),true);
});
test('unchanged polling keeps run buttons, keyboard focus and list scroll position stable',()=>{
  const app=dashboard();vm.runInContext('current={config:{name:"Demo"}};runItems=[{id:"r1",state:"succeeded",created_at:"2026-11-13"}]',app.context);
  app.context.renderRuns();const button=app.element('runs').children[0].children[0];
  app.element('runs').scrollTop=120;app.context.renderRuns();
  assert.equal(app.element('runs').children[0].children[0],button);
  assert.equal(app.element('runs').scrollTop,120);
});
