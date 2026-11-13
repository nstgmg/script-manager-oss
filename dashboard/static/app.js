"use strict";
const $ = id => document.getElementById(id);
let lifecycleData, lifecycleJob, lifecycleDirty=false, lifecyclePreview=null;
let token, selected, current, selectedRun, planHash, plannedPackage, dirty = false, loadSequence = 0;
let jobsSignature, jobItems = [], jobStates = new Map(), jobsTask, jobsPage = 1;
const latestRuns = new Map(), pendingRuns = new Set();
const activeRun = run => run && ["queued", "running"].includes(run.state);
let trashItems = [], selectedSchedule, basicDirty=false;
let runItems = [], runsPage = 1, logSequence = 0, detailSequence = 0;
let settingsSaving = false, settingsConflict = false, reportPath = "", deploymentHistory = [];
let destinationSequence = 0, destinationTimer;
let planSequence = 0, lifecycleSaving = false;
let runsSignature;
const statusNames = {never: "실행 기록 없음", queued: "대기", running: "실행 중", succeeded: "성공", failed: "실패", timed_out: "시간 초과", cancelled: "취소", interrupted: "실행 끊김", error: "설정 오류", unknown: "조회 오류"};
let view = "home", noticeTimer, trashSignature;
const scheduleCards = new Map();
let scheduleRefreshTask;
let localScheduler = "launchd";
let timelineJobSignature;
const terminal = new Set(["succeeded","failed","timed_out","cancelled","interrupted"]);
function closeNotice() {
  clearTimeout(noticeTimer);
  noticeTimer = undefined;
  $("notice").hidden = true;
  $("notice-message").textContent = "";
}
function notice(text, error = false) {
  clearTimeout(noticeTimer);
  $("notice-message").textContent = text;
  $("notice").className = error ? "error" : "";
  $("notice").hidden = false;
  noticeTimer = error ? undefined : setTimeout(closeNotice, 5000);
}
$("notice-close").onclick = closeNotice;
function showView(next) {
  view = next;
  $("content").focus?.({preventScroll:true});
  window.scrollTo?.({top:0});
  for (const [id, target] of [["home-view", "home"], ["jobs-view", "jobs"], ["detail", "detail"], ["trash-view", "trash"], ["schedules-view", "schedules"]]) $(id).hidden = next !== target;
  for (const [id, active] of [["home-menu", next === "home"], ["jobs-menu", next === "jobs" || next === "detail"], ["trash-menu", next === "trash"], ["schedule-menu", next === "schedules"]]) $(id).setAttribute("aria-pressed", String(active));
  const label = {home:"Dashboard", jobs:"Jobs", detail:"Job 상세", schedules:"Schedule", trash:"Trash"}[next];
  $("page-label").textContent = label;
  document.title = label + " · Script Manager";
}
async function leaveEditor() {
  if (settingsSaving || lifecycleSaving) { notice("설정을 저장하는 중입니다. 완료 후 이동하세요."); return false; }
  const pending = [...scheduleCards.values()].filter(card => card.dirty);
  if ((dirty || lifecycleDirty || pending.length) && !(await approve("저장하지 않은 변경이 있습니다. 변경을 버리고 이동할까요?"))) return false;
  dirty = false; lifecycleDirty=false; lifecyclePreview=null; lifecycleJob=null;
  pending.forEach(card => { card.dirty = false; card.formEtag=undefined; });
  basicDirty=false; updateJobEditMode();
  return true;
}
async function navigate(next) {
  if (view === next) return;
  if (!(await leaveEditor())) return;
  ++loadSequence;
  showView(next);
  await refreshView();
}
function approve(message) {
  return new Promise(resolve => {
    const dialog=$("confirmation"); $("confirmation-message").textContent=message;
    dialog.returnValue="cancel";
    dialog.addEventListener("close",()=>resolve(dialog.returnValue==="yes"),{once:true});
    $("confirmation-no").onclick=()=>dialog.close("cancel");
    $("confirmation-yes").onclick=()=>dialog.close("yes");
    dialog.showModal();
  });
}
async function api(path, method = "GET", body) {
  const response = await fetch("/api/" + path, {method, headers: {"Content-Type":"application/json","X-CSRF-Token":token || ""}, body:body === undefined ? undefined : JSON.stringify(body)});
  const value = await response.json();
  if (!response.ok) { const error = new Error(value.error || "요청 실패"); error.status = response.status; throw error; }
  return value;
}
function safe(action) {
  return async event => {
    event?.preventDefault();
    const control = event?.currentTarget;
    if (control?.getAttribute?.("aria-busy") === "true") return;
    control?.setAttribute?.("aria-busy", "true");
    try { await action(); } catch (e) { notice(e.message, true); }
    finally { control?.setAttribute?.("aria-busy", "false"); }
  };
}
function jobName(item) { return item.config?.name || item.name || item.id || item.job_id; }
function matchesJob(item, query) { return (jobName(item) + " " + (item.id || item.job_id)).toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()); }
function scheduleKind(item) {
  const schedule = item.config?.schedule || item.config?.schedules?.find(s => s.enabled) || item.config?.schedules?.[0];
  if (item.error) return "error";
  if (schedule?.id) return schedule.enabled ? "enabled" : "disabled";
  return schedule?.enabled ? "enabled" : (schedule?.type || schedule?.mode) === "interval" || schedule?.times?.length ? "disabled" : "none";
}
function intervalSummary(schedule) {
  if (schedule.interval_seconds != null) return schedule.interval_seconds + "초마다 실행";
  const interval = schedule.interval;
  return interval.value + ({minutes:"분", hours:"시간", days:"일 (24시간 단위)"}[interval.unit]) + "마다 실행";
}
function scheduleSummary(item) {
  if (item.error) return "설정 확인 필요";
  if (item.config?.schedules) {
    const entries = item.config.schedules;
    return entries.length + "개 예약 · 활성 " + entries.filter(s => s.enabled).length + "개 · 일시중지 " + entries.filter(s => !s.enabled).length + "개";
  }
  const schedule = item.config?.schedule;
  if ((schedule?.type || schedule?.mode) === "interval") return (schedule.enabled ? "활성" : "비활성") + " · " + intervalSummary(schedule);
  if (!schedule?.times?.length) return "예약 없음";
  const days = (schedule.weekdays || [1,2,3,4,5,6,7]).map(day => weekdayNames[day - 1]).join(", ");
  return (schedule.enabled ? "활성" : "비활성") + " · " + days + " · " + schedule.times.join(", ");
}
function jobState(item) { return item.error ? "error" : jobStates.get(item.id) || "unknown"; }
function compareJobs(a, b, sort) {
  const name = jobName(a).localeCompare(jobName(b), "ko") || (a.config?.schedule?.name || "").localeCompare(b.config?.schedule?.name || "", "ko");
  if (sort === "id") return (a.id || a.job_id).localeCompare(b.id || b.job_id);
  if (sort === "name-desc") return -name || a.id.localeCompare(b.id);
  if (sort === "state") return (statusNames[jobState(a)] || "").localeCompare(statusNames[jobState(b)] || "", "ko") || name;
  if (sort === "schedule" || sort === "active") {
    const rank = {enabled:0, disabled:1, none:2, error:3};
    return rank[scheduleKind(a)] - rank[scheduleKind(b)] || name;
  }
  return name || (a.id || a.job_id).localeCompare(b.id || b.job_id);
}
function selectJobPage(items, {query = "", filter = "all", sort = "name", page = 1, size = 10} = {}) {
  const matches = items.filter(item => matchesJob(item, query) && (filter === "all" || jobState(item) === filter)).sort((a,b) => compareJobs(a,b,sort));
  const pages = Math.max(1, Math.ceil(matches.length / size));
  page = Math.min(Math.max(1, page), pages);
  return {items: matches.slice((page - 1) * size, page * size), total: matches.length, pages, page};
}
function statusBadge(text, kind = "inactive") {
  const badge = document.createElement("span"); badge.className = "status " + kind; badge.textContent = text; return badge;
}
function nameCell(item, button) {
  const cell = document.createElement("td");
  if (button) { button.textContent = jobName(item); cell.append(button); }
  else { const name = document.createElement("span"); name.textContent = jobName(item); cell.append(name); }
  const id = document.createElement("small"); id.textContent = item.id || item.job_id; cell.append(id); return cell;
}
function renderJobs() {
  const result = selectJobPage(jobItems, {query:$("jobs-search").value, filter:$("jobs-filter").value, sort:$("jobs-sort").value, page:jobsPage, size:Number($("jobs-page-size").value)});
  jobsPage = result.page;
  const signature = JSON.stringify([result, jobItems.length, result.items.map(item=>[jobState(item), latestRuns.get(item.id), pendingRuns.has(item.id)])]);
  if (signature === jobsSignature) return;
  jobsSignature = signature;
  $("jobs").replaceChildren();
  for (const item of result.items) {
    const row = document.createElement("tr"); row.className = "job-row"; row.tabIndex = 0;
    row.setAttribute("aria-label", jobName(item) + " 상세 열기");
    row.onclick = safe(() => choose(item.id));
    row.onkeydown = event => {
      if (event.target !== row || !["Enter", " "].includes(event.key)) return;
      event.preventDefault(); row.onclick();
    };
    row.append(nameCell(item));
    const state = jobState(item), stateCell = document.createElement("td");
    stateCell.append(statusBadge(statusNames[state], state === "succeeded" ? "good" : ["queued","running"].includes(state) ? "active" : ["error","unknown","failed","timed_out","interrupted"].includes(state) ? "error" : "inactive"));
    const last = document.createElement("small"); last.textContent = latestRuns.has(item.id) ? "마지막 실행 " + localDate(latestRuns.get(item.id).created_at) : state === "never" ? "아직 실행하지 않았습니다." : "마지막 실행 시각 확인 불가"; stateCell.append(last);
    if (item.error) { const error = document.createElement("small"); error.className="error"; error.textContent=item.error; stateCell.append(error); }
    const schedule = document.createElement("td"); schedule.textContent = scheduleSummary(item);
    const action = document.createElement("td"), button = document.createElement("button");
    button.textContent = pendingRuns.has(item.id) ? "요청 중…" : "지금 실행";
    button.disabled = !!item.error || pendingRuns.has(item.id) || ["queued","running"].includes(state);
    button.setAttribute("aria-label",jobName(item)+" 지금 실행");
    button.onclick = event => { event.stopPropagation(); return safe(() => startManualRun(item.id))(event); };
    action.append(button);
    row.append(stateCell, schedule, action); $("jobs").append(row);
  }
  $("jobs-count").textContent = (result.total ? (result.page - 1) * Number($("jobs-page-size").value) + 1 : 0) + "–" + Math.min(result.page * Number($("jobs-page-size").value),result.total) + " 표시 · 검색 결과 " + result.total + "개 / 전체 " + jobItems.length + "개";
  $("jobs-table").hidden = result.total === 0; $("jobs-empty").hidden = result.total !== 0;
  $("jobs-empty-title").textContent = jobItems.length ? "조건에 맞는 Job이 없습니다." : "등록된 Job이 없습니다.";
  $("jobs-empty-text").textContent = jobItems.length ? "검색어나 상태 필터를 변경하세요." : "New Job으로 만들거나 jobs/ 아래에 Job을 추가하세요.";
  $("jobs-page").textContent = result.page + " / " + result.pages;
  $("jobs-prev").disabled = result.page <= 1; $("jobs-next").disabled = result.page >= result.pages;
}
function clearJobSelection(id) {
  if (selected === id) {
    ++loadSequence;
    selected = current = selectedRun = planHash = null;
    dirty = basicDirty = false;
    $("deploy").disabled = true;
    updateJobEditMode();
    if (view === "detail") showView("jobs");
  }
  jobStates.delete(id);
  latestRuns.delete(id);
  for (const [key, card] of scheduleCards) {
    if (card.item.job_id !== id) continue;
    card.element.remove(); card.summaryRow.remove(); scheduleCards.delete(key);
    if (selectedSchedule === key) selectedSchedule = undefined;
  }
  const fragment = window.location?.hash;
  const prefix = "#schedule-editor-" + id;
  if (fragment === prefix || fragment?.startsWith(prefix + "/") || fragment?.startsWith(prefix + "%2F")) {
    window.history.replaceState(null, "", window.location.pathname + window.location.search);
  }
}
async function jobs() {
  if (jobsTask) return jobsTask;
  const task = (async () => {
    const values = await api("jobs");
    if (view === "jobs") {
      // Reuse the existing runs API, with bounded concurrency for large lists.
      let cursor = 0;
      await Promise.all(Array.from({length:Math.min(6,values.length)}, async () => {
        while (cursor < values.length) {
          const item = values[cursor++];
          if (item.error) continue;
          const previous = latestRuns.get(item.id);
          try {
            const runs = newestRuns(await api("jobs/" + encodeURIComponent(item.id) + "/runs"));
            // A poll started before a manual request must not re-enable its button.
            if (pendingRuns.has(item.id) || previous !== latestRuns.get(item.id)) continue;
            if (runs.length) latestRuns.set(item.id, runs[0]); else latestRuns.delete(item.id);
            jobStates.set(item.id, runs[0]?.state || "never");
          }
          catch {
            if (pendingRuns.has(item.id) || previous !== latestRuns.get(item.id)) continue;
            jobStates.set(item.id, "unknown"); latestRuns.delete(item.id);
          }
        }
      }));
    }
    jobItems = values;
    const hashJob = window.location?.hash.match(/^#schedule-editor-([a-z0-9][a-z0-9-]{0,62})(?:\/|%2F|$)/)?.[1];
    if (hashJob && !values.some(item => item.id === hashJob)) clearJobSelection(hashJob);
    if (selected && !values.some(item => item.id === selected)) clearJobSelection(selected);
    renderJobs();
  })();
  jobsTask = task;
  try { await task; } finally { if (jobsTask === task) jobsTask = undefined; }
}
async function choose(id) {
  if (!(await leaveEditor())) return;
  const sequence = ++loadSequence;
  let item;
  try { item = await api("jobs/" + encodeURIComponent(id)); }
  catch (error) {
    if (error.status !== 404 || sequence !== loadSequence) throw error;
    clearJobSelection(id); showView("jobs"); await jobs(); return;
  }
  if (sequence !== loadSequence) return;
  selected = id; current = item; selectedRun = null; dirty = false; planHash = null; $("deploy").disabled = true;
  runItems=[]; runsPage=1; runsSignature=null; settingsConflict=false; reportPath=""; ++logSequence;
  $("runs-page-size").value="20";
  $("package-select").replaceChildren(); $("package-select").value="";
  for (const section of ["yaml-section","packages-section","lifecycle-section","deployment-section"]) $(section).open=false;
  renderRunParameters({});
  closeReportPreview();
  showView("detail"); $("job-id").textContent = id; $("job-name").textContent = item.config.name; $("yaml").value = item.yaml; $("logs").textContent = "실행 기록을 선택하세요."; $("deployment-plan").textContent = "";
  invalidatePlan(); renderRuns(); updateLifecycleActions();
  $("report-status").textContent="보고서를 불러오는 중…";
  $("report-origin").textContent=""; $("report-path").hidden=true;
  for(const name of ["report-open","report-download"]) $(name).hidden=true;
  for(const name of ["report-preview","report-folder","report-copy","package-download","plan"]) $(name).disabled=true;
  populateJobSettings(); await jobs(); await refreshDetail();
}
function renderTimelineJobs(options) {
  const signature=JSON.stringify(options);
  if (signature===timelineJobSignature) return;
  timelineJobSignature=signature;
  const select = $("timeline-job"), previous = select.value;
  select.replaceChildren();
  const all = document.createElement("option"); all.value=""; all.textContent="전체 Job"; select.append(all);
  for (const item of options) {
    const option=document.createElement("option"); option.value=item.id; option.textContent=item.name+(item.note?" ("+item.note+")":""); select.append(option);
  }
  select.value=options.some(item=>item.id===previous) ? previous : "";
}
function localDate(value) {
  if (!value) return "—";
  const date = new Date(value), pad = part => String(part).padStart(2, "0");
  if (!Number.isFinite(date.getTime())) return "—";
  return date.getFullYear() + "." + pad(date.getMonth()+1) + "." + pad(date.getDate()) + " " + pad(date.getHours()) + ":" + pad(date.getMinutes()) + ":" + pad(date.getSeconds());
}
function newestRuns(runs) {
  return [...runs].sort((a,b) => (Date.parse(b.created_at) || 0) - (Date.parse(a.created_at) || 0) || b.id.localeCompare(a.id));
}
function runDuration(run, now = Date.now()) {
  if (run.duration_seconds != null) return run.duration_seconds;
  const start = Date.parse(run.started_at), end = run.finished_at ? Date.parse(run.finished_at) : run.state === "running" ? now : NaN;
  return Number.isFinite(start) && Number.isFinite(end) ? Math.max(0, Math.round((end-start)/1000)) : null;
}
function runBadge(run) {
  return statusBadge(statusNames[run.state] || "알 수 없음", run.state === "succeeded" ? "good" : activeRun(run) ? "active" : "error");
}
function runTime(run) {
  const time = document.createElement("time"); time.dateTime=run.created_at; time.textContent=localDate(run.created_at); return time;
}
const triggerText = run => run.trigger === "schedule" ? "예약" : "수동";
async function startManualRun(id) {
  if (pendingRuns.has(id) || activeRun(latestRuns.get(id))) return;
  if (selected === id && view === "detail" && dirty) throw new Error("먼저 설정을 저장하세요.");
  const item = selected === id && current ? current : jobItems.find(item => item.id === id);
  if (Object.keys(item?.config?.parameters || {}).length) {
    const fresh = await api("jobs/" + encodeURIComponent(id));
    openParameterRun(fresh);
    return;
  }
  await submitManualRun(id);
}
async function submitManualRun(id, parameters) {
  if (pendingRuns.has(id) || activeRun(latestRuns.get(id))) return;
  pendingRuns.add(id); renderJobs(); updateRunButton();
  try {
    const run = await api("jobs/" + encodeURIComponent(id) + "/runs", "POST", parameters === undefined ? {} : {parameters});
    latestRuns.set(id, run); jobStates.set(id, run.state);
    if (parameters !== undefined && parameterRun?.item.id === id) {
      // Acceptance is final even if subsequent observation fails.
      parameterRun=undefined; $("parameter-dialog").close();
    }
    notice("로컬 실행을 요청했습니다. 실행 기록에서 결과를 확인하세요.");
    if (selected === id && view === "detail") { selectedRun=run.id; runsPage=1; await refreshDetail(); }
  } finally { pendingRuns.delete(id); renderJobs(); updateRunButton(); }
}
let parameterRun;
function openParameterRun(item) {
  parameterRun = {item, fields: new Map()};
  $("parameter-submit").disabled=false;
  $("parameter-title").textContent = item.config.name + " 실행 입력";
  $("parameter-error").textContent = "";
  $("parameter-fields").replaceChildren();
  for (const [name, spec] of Object.entries(item.config.parameters || {})) {
    const group = document.createElement("div"), label = document.createElement("label");
    label.textContent = name + (spec.required ? " · 필수" : " · 선택");
    const input = document.createElement(spec.choices ? "select" : "input");
    const hasDefault = Object.hasOwn(spec, "default");
    if (spec.choices) {
      const empty = document.createElement("option"); empty.value=""; empty.textContent="선택하세요"; input.append(empty);
      spec.choices.forEach((value, index) => {
        const option=document.createElement("option"); option.value=String(index); option.textContent=String(value); input.append(option);
      });
      input.value = hasDefault ? String(spec.choices.indexOf(spec.default)) : "";
    } else {
      input.type = {integer:"number",number:"number",date:"date",boolean:"checkbox"}[spec.type] || "text";
      if (input.type === "number") input.step = spec.type === "integer" ? "1" : "any";
      if (spec.type === "boolean") input.checked = hasDefault ? spec.default : false;
      else input.value = hasDefault ? String(spec.default) : "";
      if (spec.type === "string") input.maxLength = 4096;
      if (spec.min !== undefined) input.min=String(spec.min);
      if (spec.max !== undefined) input.max=String(spec.max);
    }
    input.required = !!spec.required && spec.type !== "boolean";
    label.append(input);
    let include;
    if (!spec.required) {
      const toggle=document.createElement("label"); toggle.className="parameter-toggle";
      include=document.createElement("input"); include.type="checkbox"; include.checked=hasDefault;
      input.disabled=!include.checked;
      include.onchange=()=>{input.disabled=!include.checked;};
      toggle.append(include, " 입력값 지정 (해제 시 기본값 또는 생략)"); group.append(toggle);
    }
    const help=document.createElement("p"); help.className="muted";
    help.textContent=(spec.description || "") + (hasDefault ? " · 기본값: " + String(spec.default) : "");
    group.append(label, help); $("parameter-fields").append(group);
    parameterRun.fields.set(name, {spec, input, include});
  }
  $("parameter-dialog").showModal();
}
function readParameterInputs(fields) {
  const parameters = Object.create(null);
  for (const [name, {spec, input, include}] of fields) {
    if (include && !include.checked) continue;
    if (spec.choices) {
      if (input.value === "") throw new Error(name + ": 값을 선택하세요.");
      parameters[name] = spec.choices[Number(input.value)];
    } else if (spec.type === "boolean") parameters[name]=input.checked;
    else if (["integer", "number"].includes(spec.type)) {
      if (input.value.trim() === "" || !Number.isFinite(Number(input.value))) throw new Error(name + ": 숫자를 입력하세요.");
      parameters[name]=Number(input.value);
    } else parameters[name]=input.value;
  }
  return parameters;
}
$("parameter-cancel").onclick=()=>$("parameter-dialog").close();
$("parameter-form").onsubmit=safe(async()=>{
  const draft=parameterRun;
  if (!draft || pendingRuns.has(draft.item.id)) return;
  $("parameter-submit").disabled=true; $("parameter-error").textContent="";
  try {
    if (!$("parameter-form").reportValidity()) return;
    await submitManualRun(draft.item.id, readParameterInputs(draft.fields));
    $("parameter-dialog").close();
  } catch (error) {
    if (parameterRun === draft) $("parameter-error").textContent=error.message;
    else notice("실행 접수 후 조회 오류입니다. 기존 실행 기록을 확인하세요. " + error.message, true);
  }
  finally { $("parameter-submit").disabled=false; }
});
function renderRunParameters(record) {
  const visible = Object.hasOwn(record, "parameters");
  $("run-parameters").hidden=!visible;
  $("run-parameters-values").textContent=visible ? JSON.stringify({
    contract_version:record.parameter_contract_version, values:record.parameters,
    definitions:record.config?.parameters || {}
  }, null, 2) : "";
}
function updateRunButton() {
  $("run").disabled = dirty || settingsSaving || pendingRuns.has(selected) || !!activeRun(latestRuns.get(selected));
  $("run").title = dirty ? "먼저 설정을 저장하세요." : "";
  $("run").textContent = pendingRuns.has(selected) ? "요청 중…" : "지금 실행";
}
function durationText(seconds) {
  if (seconds == null) return "—";
  if (seconds < 60) return seconds + "초";
  const minutes=Math.floor(seconds/60), rest=seconds%60;
  return minutes < 60 ? minutes + "분 " + rest + "초" : Math.floor(minutes/60) + "시간 " + minutes%60 + "분";
}
async function openTimelineRun(run) {
  if (!run.job_exists) {
    archivedRun=run;
    $("archived-run-title").textContent=run.job_name+" · "+run.id.slice(0,8);
    $("archived-stream").value="stdout";
    $("archived-run-dialog").showModal();
    await archivedLogs();
    return;
  }
  await choose(run.job_id);
  if (view !== "detail" || selected !== run.job_id) return;
  selectedRun=run.id;
  showSelectedRunPage();
  await logs();
  $("runs").scrollIntoView?.({block:"start",behavior:"smooth"});
}
let archivedRun;
async function archivedLogs() {
  if (!archivedRun) return;
  let offset=0, output="", value;
  do {
    value=await api("jobs/"+encodeURIComponent(archivedRun.job_id)+"/runs/"+archivedRun.id+"/logs?stream="+$("archived-stream").value+"&offset="+offset);
    output+=value.text; const previous=offset; offset=value.offset;
    if (offset===previous) break;
  } while (offset<5*1024*1024);
  $("archived-logs").textContent=output||"(로그 없음)";
}
$("archived-stream").onchange=safe(archivedLogs);
$("archived-close").onclick=()=>$("archived-run-dialog").close();
async function refreshOverview() {
  if (view !== "home") return;
  const period=$("timeline-period").value, job=$("timeline-job").value;
  const data=await api("overview?period="+encodeURIComponent(period)+"&job="+encodeURIComponent(job));
  renderTimelineJobs(data.jobs);
  if (view !== "home" || period !== $("timeline-period").value || job !== $("timeline-job").value) return;
  for (const key of ["total","succeeded","failed","running"]) $("summary-"+key).textContent=String(data.summary[key]);
  const upcoming=$("upcoming-list"); upcoming.replaceChildren();
  for (const row of data.upcoming) {
    const line=document.createElement("div"); line.className="upcoming-item";
    const title=document.createElement("div"), strong=document.createElement("strong"), sub=document.createElement("small"), when=document.createElement("time");
    strong.textContent=row.job_name; sub.textContent=row.schedule_name; title.append(strong,sub);
    when.dateTime=row.next_at; when.textContent=localDate(row.next_at)+" 예상"; line.append(title,when); upcoming.append(line);
  }
  $("upcoming-empty").hidden=data.upcoming.length!==0;
  $("uncalculated").hidden=data.uncalculated.length===0;
  $("uncalculated").textContent=data.uncalculated.length ? "예상 시각 계산 불가: "+data.uncalculated.map(row=>row.job_name+" · "+row.schedule_name).join(", ") : "";
  const rows=$("timeline-rows"); rows.replaceChildren();
  for (const run of newestRuns(data.timeline)) {
    const tr=document.createElement("tr"), name=document.createElement("td"), button=document.createElement("button");
    button.className="job-link"; button.textContent=run.job_name+(run.job_note?" ("+run.job_note+")":""); button.title="Run ID: "+run.id; button.onclick=safe(()=>openTimelineRun(run)); name.append(button);
    const at=document.createElement("td"); at.append(runTime(run));
    const trigger=document.createElement("td"); trigger.textContent=triggerText(run);
    const state=document.createElement("td"); state.append(runBadge(run));
    const duration=document.createElement("td"); duration.textContent=durationText(runDuration(run))+(run.state==="running" ? " · 진행 중" : "");
    tr.append(name,at,trigger,state,duration); rows.append(tr);
  }
  $("timeline-table").hidden=data.timeline.length===0; $("timeline-empty").hidden=data.timeline.length!==0;
  $("timeline-count").textContent=data.timeline.length+"건";
  $("overview-errors").hidden=data.errors.length===0;
  $("overview-errors").textContent=data.errors.length ? data.errors.length+"개 Job의 기록 또는 예약 상태를 읽지 못했습니다. Jobs와 Schedule 화면을 확인하세요." : "";
}
function path(suffix) { if(!selected) throw new Error("Job을 선택하세요."); return "jobs/" + encodeURIComponent(selected) + "/" + suffix; }
async function refreshDetail() {
  if (!selected || view !== "detail") return;
  const id = selected, sequence = ++detailSequence;
  const isCurrent = () => id === selected && view === "detail" && sequence === detailSequence;
  let runs, schedule, history;
  try { [runs, schedule, history] = await Promise.all([api(path("runs")), api(path("schedules")), api(path("deployments"))]); }
  catch (error) {
    if (!isCurrent()) return;
    if (error.status !== 404) throw error;
    try { await api("jobs/" + encodeURIComponent(id)); }
    catch (jobError) {
      if (jobError.status !== 404) throw jobError;
      if (isCurrent()) { clearJobSelection(id); await jobs(); }
      return;
    }
    throw error;
  }
  if (!isCurrent()) return;
  runItems = newestRuns(runs);
  if (runItems.length) latestRuns.set(id, runItems[0]); else latestRuns.delete(id);
  jobStates.set(id, runItems[0]?.state || "never"); updateRunButton();
  $("detail-run-state").replaceChildren(runItems[0] ? runBadge(runItems[0]) : statusBadge("실행 기록 없음"));
  const scheduleProblems=schedule.filter(row=>!["적용됨","비활성 · 미등록"].includes(scheduleStatus(row.state,row.schedule,row.orphan).label)).length;
  $("detail-schedule-state").textContent = schedule.length ? schedule.length + "개 예약 · 활성 " + schedule.filter(row=>row.schedule.enabled).length + "개 · "+(scheduleProblems ? "OS 상태 확인 필요 "+scheduleProblems+"개" : "OS 상태 일치") : "예약 없음";
  renderRuns();
  const latest = runItems[0], report = latest?.report;
  $("report-run-status").textContent = !latest ? "실행 기록이 없습니다." : "Run " + latest.id + " · " + localDate(latest.created_at) + " · " + (report ? ({succeeded:"보고서 생성 성공",failed:"보고서 생성 실패",disabled:"자동 생성 꺼짐"}[report.state] || report.state) + (report.error ? " · " + report.error : "") + (report.path ? " · " + report.path : "") : "보고서 생성 기록 없음");
  $("schedule-state").replaceChildren();
  $("job-schedule-summary").textContent = schedule.length + "개 예약 · 활성 " + schedule.filter(row => row.schedule.enabled).length + "개";
  if (!schedule.length) $("schedule-state").textContent = "연결된 Schedule이 없습니다. Schedule 관리에서 추가하세요.";
  for (const row of schedule) {
    const line = document.createElement("p");
    line.textContent = row.schedule.name + " · " + scheduleSummary({config:{schedule:row.schedule}}) + " · " + scheduleStatus(row.state, row.schedule, row.orphan).label;
    $("schedule-state").append(line);
  }
  deploymentHistory=history;
  $("history").textContent = history.length ? JSON.stringify(history, null, 2) : "저장된 배포 이력이 없습니다.";
  renderDeploymentSummary();
  // Independent tools should not hide the primary run list when one lookup fails.
  await Promise.all([
    refreshReport(id),
    refreshPackages(history,id).catch(error=>{if(isCurrent()) {$("package-latest").textContent="Package 조회 실패: "+error.message; $("package-download").disabled=$("plan").disabled=true;}}),
    refreshLifecycle(id).catch(error=>{if(isCurrent()) {$("data-usage").textContent="데이터 조회 실패: "+error.message; lifecyclePreview=null; updateLifecycleActions();}}),
    selectedRun ? logs() : Promise.resolve()
  ]);
}
function runPageSize() { return Number($("runs-page-size").value) || 20; }
function renderRuns() {
  const pages=Math.max(1,Math.ceil(runItems.length/runPageSize()));
  runsPage=Math.max(1,Math.min(runsPage,pages));
  const start=(runsPage-1)*runPageSize(), page=runItems.slice(start,start+runPageSize());
  $("runs-count").textContent="전체 "+runItems.length+"건 · "+(runItems.length ? start+1 : 0)+"–"+(start+page.length)+"건 표시";
  $("runs-page").textContent=runsPage+" / "+pages;
  $("runs-prev").disabled=runsPage<=1; $("runs-next").disabled=runsPage>=pages;
  const signature=JSON.stringify([page.map(run=>[run.id,run.created_at,run.state,run.trigger,runDuration(run)]),selectedRun,current.config.name]);
  if(signature!==runsSignature){
    runsSignature=signature;
    const scrollTop=$("runs").scrollTop;
    $("runs").replaceChildren();
    if (!runItems.length) $("runs").textContent="아직 실행 기록이 없습니다.";
    for (const run of page) {
      const row=document.createElement("div"); row.className="run";
      const button=document.createElement("button"); button.className="run-summary"; button.title="Run ID: "+run.id;
      button.setAttribute("aria-pressed",String(selectedRun===run.id));
      const name=document.createElement("strong"); name.textContent=current.config.name;
      const trigger=document.createElement("span"); trigger.textContent="실행 방식: "+triggerText(run);
      const duration=document.createElement("span"); duration.textContent="소요 시간: "+durationText(runDuration(run))+(run.state==="running" ? " · 진행 중" : "");
      button.append(name,runTime(run),trigger,runBadge(run),duration);
      button.onclick=safe(async()=>{selectedRun=run.id; $("logs").textContent="로그를 불러오는 중…"; renderRunParameters({}); renderRuns(); await logs();}); row.append(button);
      if (!terminal.has(run.state)) {
        const cancel=document.createElement("button"); cancel.textContent="중단";
        cancel.onclick=safe(async()=>{if(!(await approve("이 로컬 실행을 중단할까요?")))return; await api(path("runs/"+run.id+"/cancel"),"POST",{}); notice("중단을 요청했습니다. 실행 상태를 확인하세요."); await refreshDetail();}); row.append(cancel);
      }
      $("runs").append(row);
    }
    $("runs").scrollTop=scrollTop;
  }
  const chosen=runItems.find(run=>run.id===selectedRun), outside=!!chosen && !page.some(run=>run.id===selectedRun);
  $("selected-run-label").textContent=chosen ? localDate(chosen.created_at)+" · Run "+chosen.id+(outside ? " · 현재 페이지 밖의 선택 기록" : "") : selectedRun ? "Run "+selectedRun : "실행 기록을 선택하세요.";
  $("selected-run-jump").hidden=!outside;
}
function showSelectedRunPage() {
  const index=runItems.findIndex(run=>run.id===selectedRun);
  if(index>=0) runsPage=Math.floor(index/runPageSize())+1;
  renderRuns();
  $("runs").querySelector?.('[aria-pressed="true"]')?.scrollIntoView?.({block:"nearest"});
}
$("runs-prev").onclick=()=>{runsPage--;$("runs").scrollTop=0;renderRuns();};
$("runs-next").onclick=()=>{runsPage++;$("runs").scrollTop=0;renderRuns();};
$("runs-page-size").onchange=()=>{runsPage=1;$("runs").scrollTop=0;renderRuns();};
$("selected-run-jump").onclick=showSelectedRunPage;
function renderDeploymentSummary() {
  const target=$("target").value, row=deploymentHistory.find(item=>item.target===target);
  $("deployment-summary").textContent=row ? "최근 저장 이력 · "+localDate(row.created_at)+" · "+row.action+" · "+row.status+" · 릴리스 "+(row.release || "—")+" · Package "+(row.package_id || "기록 없음")+". 현재 원격 상태는 적용 검증으로 확인하세요." : "이 대상의 저장된 배포 이력이 없습니다.";
}
async function refreshPackages(history, id) {
  const packages = await api(path("packages"));
  if (id !== selected || view !== "detail") return;
  const select = $("package-select"), previous = select.value;
  select.replaceChildren();
  for (const item of packages) {
    const option=document.createElement("option"); option.value=item.id;
    option.textContent=item.id+" · "+localDate(item.created_at)+(item.zip_available === false ? " · ZIP 정리됨" : " · ZIP 보관"); select.append(option);
  }
  select.value=packages.some(item=>item.id===previous) ? previous : packages[0]?.id || "";
  const available=packages.find(item=>item.id===select.value)?.zip_available !== false;
  $("package-download").disabled=!select.value || !available;
  $("plan").disabled=!select.value || !available || !$("target").value;
  const latest=packages[0];
  $("package-latest").textContent=latest ? "최신 Package: "+latest.id+" · "+localDate(latest.created_at)+" · SHA-256 "+latest.content_hash : "Package 없음";
  const chosen=packages.find(item=>item.id===select.value), chosenId=select.value;
  let chosenDifference;
  $("deployment-package").textContent=chosen ? "선택한 Package: "+chosen.id+" · "+localDate(chosen.created_at)+(available ? "" : " · ZIP 정리됨, 배포 불가") : "Package 영역에서 먼저 생성·선택하세요.";
  if (chosen?.manifest) {
    const diff=await api(path("packages/"+chosen.id+"/difference"));
    chosenDifference=diff;
    if (id !== selected || view !== "detail" || chosenId !== select.value) return;
    $("package-difference").textContent=diff.changed ? "현재 Job과 선택한 Package가 다릅니다. 추가 "+diff.added.join(", ")+" / 삭제 "+diff.removed.join(", ")+" / 수정 "+diff.modified.join(", ")+(diff.reason ? " / "+diff.reason : "") : "현재 Job과 선택한 Package의 콘텐츠가 같습니다.";
  } else $("package-difference").textContent="";
  if (planHash && (!available || plannedPackage!==chosenId)) { planHash=plannedPackage=null; $("deploy").disabled=true; }
  $("package-info").textContent=chosen ? JSON.stringify({id:chosen.id,created_at:chosen.created_at,job_id:chosen.job_id,content_hash:chosen.content_hash,zip_sha256:chosen.zip_sha256,requirements:chosen.requirements,deployments:history.filter(row=>row.package_id===chosen.id)},null,2) : "Package를 생성하세요.";
  const target=$("target").value, deployed=history.find(row=>row.target===target && row.action==="deploy" && row.package_id);
  $("deployment-difference").textContent="";
  if(deployed) {
    try {
      const diff=deployed.package_id===chosenId && chosenDifference ? chosenDifference : await api(path("packages/"+deployed.package_id+"/difference"));
      if(id!==selected || target!==$("target").value)return;
      $("deployment-difference").textContent="마지막 Package 배포 기록 "+deployed.package_id+" ↔ 현재 코드: "+(diff.changed ? "차이 있음 · 추가 "+diff.added.length+" / 삭제 "+diff.removed.length+" / 수정 "+diff.modified.length+(diff.reason ? " · "+diff.reason : "") : "동일")+" (현재 원격 상태는 적용 검증 필요)";
    }catch(error){if(id===selected) $("deployment-difference").textContent="배포 Package의 코드 차이 조회 실패: "+error.message;}
  }
}
async function logs() {
  if (!selectedRun) return;
  const id=selected, run=selectedRun, stream=$("stream").value, sequence=++logSequence;
  const isCurrent=()=>id===selected && run===selectedRun && stream===$("stream").value && sequence===logSequence;
  const base="jobs/"+encodeURIComponent(id)+"/runs/"+encodeURIComponent(run);
  try {
    const record=await api(base);
    if(!isCurrent())return;
    renderRunParameters(record);
    let offset=0, text="", value;
    do { value=await api(base+"/logs?stream="+stream+"&offset="+offset); if(!isCurrent())return; text+=value.text; const previous=offset; offset=value.offset; if(offset===previous) break; } while(offset < 5*1024*1024);
    $("logs").textContent = text || "(로그 없음)";
  } catch(error) { if(isCurrent()) $("logs").textContent="로그 조회 실패: "+error.message; }
}
$("yaml").oninput=()=>{dirty=true; updateJobEditMode(); invalidatePlan();};
$("refresh").onclick=safe(refreshView);
$("new-job").onclick = () => { $("create-error").hidden=true; $("create-dialog").showModal(); };
$("create-cancel").onclick = () => $("create-dialog").close();
$("create").onsubmit = safe(async () => {
  $("create-submit").disabled = true; $("create-error").hidden=true;
  try {
    const item = await api("jobs", "POST", {id:$("new-id").value,name:$("new-name").value});
    $("create-dialog").close(); $("create").reset(); await choose(item.id); notice("Job을 생성했습니다.");
  } catch(error) {
    $("create-error").textContent=error.message; $("create-error").hidden=false;
    notice(error.message,true);
  } finally { $("create-submit").disabled = false; }
});
$("jobs-menu").onclick = safe(() => navigate("jobs"));
$("home-menu").onclick = safe(() => navigate("home"));
$("timeline-period").onchange=safe(refreshOverview);
$("timeline-job").onchange=safe(refreshOverview);
$("back-jobs").onclick = safe(() => navigate("jobs"));
for (const id of ["jobs-search", "jobs-filter", "jobs-sort", "jobs-page-size"]) {
  $(id)[id === "jobs-search" ? "oninput" : "onchange"] = () => { jobsPage=1; renderJobs(); };
}
$("jobs-prev").onclick = () => { jobsPage--; renderJobs(); };
$("jobs-next").onclick = () => { jobsPage++; renderJobs(); };
$("save").onclick=safe(async()=>{await saveJobSettings({yaml:$("yaml").value});});
$("delete").onclick=safe(async()=>{if(!(await approve("Job을 로컬 휴지통으로 이동할까요? 원격 배포는 유지됩니다.")))return; await api("jobs/"+selected,"DELETE",{etag:current.etag}); clearJobSelection(selected); showView("jobs"); await jobs(); notice("Job을 휴지통으로 이동했습니다.");});
$("run").onclick=safe(()=>startManualRun(selected));
$("manage-schedules").onclick=safe(async()=>{ const id=selected; await navigate("schedules"); if(view!=="schedules")return; $("schedules-search").value=id; $("schedules-filter").value="all"; selectedSchedule=undefined; renderScheduleOverview(); });
$("stream").onchange=safe(async()=>{$("logs").textContent="로그를 불러오는 중…"; await logs();});
$("package-create").onclick=safe(async()=>{
  if(dirty || settingsSaving)throw new Error("먼저 설정을 저장하세요.");
  const id=selected,item=await api(path("packages"),"POST",{});
  notice("Package "+item.id+"를 생성했습니다.");
  if(id!==selected)return;
  try { await refreshDetail(); if(id!==selected)return; $("package-select").value=item.id; await refreshPackages(await api(path("deployments")),id); }
  catch(error){notice("Package 생성 완료 · 목록 새로고침 실패: "+error.message,true);}
});
$("package-select").onchange=safe(async()=>{invalidatePlan(); await refreshPackages(await api(path("deployments")),selected);});
$("package-download").onclick=safe(async()=>{const id=$("package-select").value; if(!id)throw new Error("Package를 선택하세요."); const link=document.createElement("a"); link.href="/api/"+path("packages/"+encodeURIComponent(id)+"/download"); link.download=selected+"-"+id+".zip"; document.body.append(link); link.click(); link.remove(); notice("Package ZIP 다운로드를 요청했습니다. 대상 환경의 실행 결과는 별도로 확인하세요.");});
$("target").onchange=safe(async()=>{invalidatePlan();renderDeploymentSummary();await refreshPackages(deploymentHistory,selected);});
$("plan").onclick=safe(async()=>{
  const packageId=$("package-select").value,target=$("target").value,id=selected,sequence=++planSequence;
  if(!packageId)throw new Error("Package를 선택하세요.");
  const plan=await api(path("deploy-plan"),"POST",{target,package_id:packageId});
  if(sequence!==planSequence || selected!==id || target!==$("target").value || packageId!==$("package-select").value)return;
  planHash=plan.plan_hash; plannedPackage=packageId; $("deployment-plan").hidden=false; $("deployment-plan").textContent=JSON.stringify(plan,null,2); $("deploy").disabled=false; notice("네트워크 연결 없이 배포 계획을 생성했습니다.");
});
$("deploy").onclick=safe(async()=>{
  const id=selected,target=$("target").value,packageId=plannedPackage,hash=planHash;
  if(!hash || !packageId)throw new Error("배포 계획을 먼저 확인하세요.");
  if(!(await approve("선택한 Package를 원격 서버에 배포할까요?")))return;
  if(id!==selected || hash!==planHash || target!==$("target").value)throw new Error("배포 선택이 변경되었습니다. 계획을 다시 확인하세요.");
  $("deploy").disabled=true;
  try {
    const result=await api("jobs/"+encodeURIComponent(id)+"/deploy","POST",{target,package_id:packageId,plan_hash:hash});
    if(id===selected){$("deployment-plan").hidden=false;$("deployment-plan").textContent=JSON.stringify(result,null,2);}
    notice("원격 배포와 적용 검증을 완료했습니다.");
  } finally {
    if(id===selected){planHash=plannedPackage=null;try{await refreshDetail();}catch(error){notice("배포 요청 후 상태 새로고침 실패: "+error.message+" · 저장된 배포 이력을 확인하세요.",true);}}
  }
});
$("verify").onclick=safe(async()=>{$("deployment-plan").hidden=false; $("deployment-plan").textContent=JSON.stringify(await api(path("verify"),"POST",{target:$("target").value}),null,2);notice("원격 적용 상태 조회를 완료했습니다. 결과를 확인하세요.");});
$("rollback").onclick=safe(async()=>{if(!(await approve("선택한 원격 릴리스로 롤백할까요?")))return; $("deployment-plan").hidden=false; $("deployment-plan").textContent=JSON.stringify(await api(path("rollback"),"POST",{target:$("target").value,release:$("release").value}),null,2); notice("롤백 요청과 적용 검증을 완료했습니다."); await refreshDetail();});
window.addEventListener("beforeunload", event=>{if(dirty || lifecycleDirty || settingsSaving || lifecycleSaving || [...scheduleCards.values()].some(card=>card.dirty)){event.preventDefault(); event.returnValue="";}});
$("open-root").onclick=safe(async()=>{await api("project-directory/open","POST",{}); notice("프로젝트 폴더 열기를 요청했습니다.");});
$("copy-root").onclick=safe(async()=>{await navigator.clipboard.writeText($("root").textContent); notice("프로젝트 경로를 복사했습니다.");});
safe(async()=>{const session=await api("session"); token=session.csrf; $("root").textContent=session.root;
  $("open-root").disabled=false; $("copy-root").disabled=false;
  localScheduler=session.scheduler; $("schedule-environment").textContent=session.os+" · "+session.scheduler;
  if(session.os==="Windows") { $("schedule-seconds").min="60"; $("schedule-seconds").max=String(31*86400); }
  if(session.os==="Darwin") $("schedule-help").textContent="일시중지는 YAML과 OS 예약에 함께 반영됩니다. Mac 로그아웃·종료 중에는 실행되지 않으며, 절전 중 누락은 OS 정책을 따릅니다.";
  else if(session.os==="Windows") $("schedule-help").textContent="일시중지는 YAML과 OS 예약에 함께 반영됩니다. 현재 사용자 로그인 세션에서 실행됩니다. 간격 예약은 60초~31일이며, 절전 중 누락은 OS 정책을 따릅니다.";
  $("job-schedule-help").textContent="예약 시각은 실행 호스트의 시간대입니다. "+(session.os==="Darwin" ? "Mac 로그아웃·종료 중에는 실행되지 않습니다. " : session.os==="Windows" ? "현재 사용자 로그인 세션에서 실행됩니다. " : "")+"절전 중 누락은 OS 정책을 따릅니다.";
  const targets=await api("targets"); $("ssh-empty").hidden=targets.length>0; $("ssh-controls").hidden=!targets.length; for(const target of targets){const option=document.createElement("option"); option.value=target.id; option.textContent=target.id+" · "+target.ssh_host; $("target").append(option);} if(!targets.length){const option=document.createElement("option"); option.value=""; option.textContent="대상 설정 파일을 먼저 추가하세요"; $("target").append(option); for(const id of ["plan","verify","rollback"])$(id).disabled=true;} await jobs(); await refreshOverview();})();
setInterval(()=>{if(!document.hidden) safe(refreshView)();},3000);

async function refreshView() {
  await jobs();
  if (view === "home") await refreshOverview();
  else if (view === "trash") await refreshTrash();
  else if (view === "schedules") await refreshSchedules();
  else await refreshDetail();
}
$("trash-menu").onclick = safe(() => navigate("trash"));
$("schedule-menu").onclick = safe(() => navigate("schedules"));
$("trash-search").oninput = renderTrash;
$("trash-sort").onchange = renderTrash;
async function refreshTrash() {
  const entries = await api("trash");
  if (view !== "trash") return;
  trashItems = entries; renderTrash();
}
function renderTrash() {
  const entries = trashItems.filter(item => matchesJob(item, $("trash-search").value)).sort((a,b) => $("trash-sort").value === "deleted" ? b.deleted_at.localeCompare(a.deleted_at) : compareJobs(a,b,$("trash-sort").value));
  const signature = JSON.stringify([entries, trashItems.length, $("trash-search").value]);
  if (trashSignature === signature) return;
  trashSignature = signature;
  $("trash-count").textContent = entries.length + "개 표시 / 삭제된 Job " + trashItems.length + "개";
  $("trash-empty").hidden = entries.length !== 0; $("trash-table").hidden = entries.length === 0;
  $("trash-empty").textContent = trashItems.length ? "조건에 맞는 Job이 없습니다." : "휴지통이 비어 있습니다.";
  $("trash-entries").replaceChildren();
  for (const entry of entries) {
    const row = document.createElement("tr"); row.append(nameCell(entry));
    const date = document.createElement("td"); date.textContent = new Date(entry.deleted_at).toLocaleString("ko-KR") + (entry.deleted_at_estimated ? " (추정)" : ""); row.append(date);
    const action = document.createElement("td"), button = document.createElement("button");
    button.textContent = "복구"; button.disabled = !!entry.error; button.setAttribute("aria-label", entry.name + " 복구");
    button.onclick = safe(async () => {
      button.disabled = true;
      try {
        await api("trash/" + encodeURIComponent(entry.trash_id) + "/restore", "POST", {});
        await jobs(); await refreshTrash(); notice(entry.name + " Job을 복구했습니다.");
      } finally { button.disabled = false; }
    });
    action.append(button);
    if (entry.error) { const error = document.createElement("p"); error.className = "error"; error.textContent = entry.error; action.append(error); }
    row.append(action); $("trash-entries").append(row);
  }
}

const weekdayNames = ["월", "화", "수", "목", "금", "토", "일"];
for (const id of ["schedules-search", "schedules-filter", "schedules-sort"]) $(id)[id === "schedules-search" ? "oninput" : "onchange"] = renderScheduleOverview;
async function selectSchedule(id) {
  if (selectedSchedule === id) {
    if (scheduleCards.has(id) && !$("schedule-edit-dialog").open) $("schedule-edit-dialog").showModal();
    renderScheduleOverview();
    return;
  }
  if (!(await leaveEditor())) return;
  selectedSchedule = id;
  await refreshSchedules(true);
  if (scheduleCards.has(id) && !$("schedule-edit-dialog").open) $("schedule-edit-dialog").showModal();
  renderScheduleOverview();
}
async function closeScheduleEditor() {
  if ([...scheduleCards.values()].some(card => card.busy)) return;
  if (!(await leaveEditor())) return;
  selectedSchedule = undefined; $("schedule-edit-dialog").close(); renderScheduleOverview();
}
$("schedule-editor-close").onclick = safe(closeScheduleEditor);
$("schedule-edit-dialog").oncancel = event => { event.preventDefault(); safe(closeScheduleEditor)(); };
function renderScheduleOverview() {
  const cards = [...scheduleCards.values()];
  const filtered = cards.filter(card => (matchesJob(card.latest || card.item,$("schedules-search").value) || ((card.latest || card.item).config?.schedule?.name || "").toLocaleLowerCase().includes($("schedules-search").value.trim().toLocaleLowerCase())) && ($("schedules-filter").value === "all" || ($("schedules-filter").value === "mismatch" ? ["설정 불일치","미적용","오류","유령 예약"].includes(card.status.textContent) : scheduleKind(card.latest || card.item) === $("schedules-filter").value)))
    .sort((a,b) => compareJobs(a.latest || a.item,b.latest || b.item,$("schedules-sort").value));
  const visible = new Set(filtered.map(card => card.item.id));
  for (const card of cards) {
    card.summaryRow.hidden = !visible.has(card.item.id);
    card.summaryRow.className = card.item.id === selectedSchedule ? "selected-row" : "";
    card.element.hidden = card.item.id !== selectedSchedule;
    card.summaryLink.setAttribute("aria-expanded",String(card.item.id === selectedSchedule && !!$("schedule-edit-dialog").open));
  }
  // Reorder only when necessary; preserve keyboard focus during polling.
  const rows = $("schedule-overview-rows");
  const ordered = [...filtered,...cards.filter(card=>!visible.has(card.item.id))];
  ordered.forEach((card,index) => { if (rows.children[index] !== card.summaryRow) rows.insertBefore(card.summaryRow,rows.children[index] || null); });
  $("schedules-empty").hidden = filtered.length !== 0; $("schedule-overview").hidden = filtered.length === 0;
  $("schedules-count").textContent = filtered.length + "개 표시 / 활성 " + cards.filter(card => scheduleKind(card.latest || card.item) === "enabled").length + "개 · 전체 " + cards.length + "개";
  $("schedule-editor-heading").hidden = !scheduleCards.has(selectedSchedule);
  if (!scheduleCards.has(selectedSchedule) && $("schedule-edit-dialog").open) $("schedule-edit-dialog").close();
}
function addScheduleTime(card, value = "") {
  const row = document.createElement("div"); row.className = "schedule-time";
  const input = document.createElement("input"); input.type = "time"; input.step = "60";
  input.value = value; input.setAttribute("aria-label", "실행 시각");
  const remove = document.createElement("button"); remove.type = "button"; remove.textContent = "시각 삭제";
  remove.onclick = () => { row.remove(); markScheduleDirty(card); };
  row.append(input, remove); card.times.append(row);
}
function markScheduleDirty(card) {
  card.dirty = true; card.draft.textContent = "저장하지 않은 변경";
}
const intervalUnits = {seconds:1, minutes:60, hours:3600, days:86400};
function updateScheduleMode(card) {
  const interval = card.mode.value === "interval";
  card.calendarFields.hidden = interval;
  card.intervalFields.hidden = !interval;
  card.calendarFields.querySelectorAll("input,button").forEach(input => input.disabled = card.busy || interval);
  card.intervalFields.querySelectorAll("input,select").forEach(input => input.disabled = card.busy || !interval);
  const limit = localScheduler==="Windows" ? 31*86400 : 2147483647;
  card.intervalValue.min = String(Math.ceil((localScheduler==="Windows" ? 60 : 1) / intervalUnits[card.intervalUnit.value]));
  card.intervalValue.max = String(Math.floor(limit / intervalUnits[card.intervalUnit.value]));
}
function scheduleDraft(card) {
  if (card.mode.value === "interval") return {
    id: card.item.schedule_id, name: card.name.value, enabled: card.enabled.checked, type: "interval",
    interval_seconds: Number(card.intervalValue.value) * intervalUnits[card.intervalUnit.value]
  };
  return {
    id: card.item.schedule_id, name: card.name.value, enabled: card.enabled.checked, type: "calendar",
    times: [...card.times.querySelectorAll("input")].map(input => input.value).filter(Boolean),
    weekdays: card.days.filter(input => input.checked).map(input => Number(input.value))
  };
}
function createScheduleCard(item) {
  const card = {item, dirty: false, busy: false, formEtag:null};
  card.element = document.createElement("article"); card.element.className = "schedule-card";
  card.element.id = "schedule-editor-" + item.id; card.element.hidden = item.id !== selectedSchedule;
  card.summaryRow = document.createElement("tr");
  const jobCell = document.createElement("td");
  card.summaryLink = document.createElement("button"); card.summaryLink.className="job-link";
  card.summaryLink.setAttribute("aria-controls",card.element.id);
  card.summaryLink.onclick = safe(() => selectSchedule(card.item.id));
  card.summaryId = document.createElement("small");
  jobCell.append(card.summaryLink,card.summaryId); card.summaryRow.append(jobCell); card.summaryCells = [];
  for (let index = 0; index < 4; index++) {
    const cell = document.createElement("td"); card.summaryCells.push(cell); card.summaryRow.append(cell);
  }
  const heading = document.createElement("div"); heading.className = "heading";
  card.title = document.createElement("h3"); card.status = document.createElement("span"); card.status.className = "schedule-status";
  heading.append(card.title, card.status);
  card.yaml = document.createElement("p"); card.os = document.createElement("p");
  card.problem = document.createElement("p"); card.problem.className = "error";
  card.form = document.createElement("form"); card.form.className = "schedule-form";
  const enabledLabel = document.createElement("label"); enabledLabel.className="checkbox-control";
  card.enabled = document.createElement("input"); card.enabled.type = "checkbox";
  enabledLabel.append(card.enabled, "예약 활성화");
  const modeLabel = document.createElement("label"); modeLabel.className = "schedule-mode";
  modeLabel.append("실행 방식"); card.mode = document.createElement("select");
  for (const [value, text] of [["calendar", "지정 시각 실행"], ["interval", "일정 간격마다 실행"]]) {
    const option = document.createElement("option"); option.value = value; option.textContent = text; card.mode.append(option);
  }
  modeLabel.append(card.mode);
  card.mode.onchange = () => { updateScheduleMode(card); markScheduleDirty(card); };
  card.calendarFields = document.createElement("div");
  card.intervalFields = document.createElement("div"); card.intervalFields.className = "schedule-interval";
  const valueLabel = document.createElement("label"), unitLabel = document.createElement("label");
  valueLabel.append("실행 간격"); unitLabel.append("간격 단위");
  card.intervalValue = document.createElement("input"); card.intervalValue.type = "number";
  card.intervalValue.min = "1"; card.intervalValue.step = "1"; card.intervalValue.required = true;
  card.intervalUnit = document.createElement("select");
  for (const [value, text] of [["seconds", "초"], ["minutes", "분"], ["hours", "시간"], ["days", "일 (24시간)"]]) {
    const option = document.createElement("option"); option.value = value; option.textContent = text; card.intervalUnit.append(option);
  }
  card.intervalUnit.onchange = () => { updateScheduleMode(card); markScheduleDirty(card); };
  valueLabel.append(card.intervalValue); unitLabel.append(card.intervalUnit);
  card.intervalFields.append(valueLabel, unitLabel);
  const intervalHelp = document.createElement("p"); intervalHelp.className = "muted";
  intervalHelp.textContent = "간격 실행은 절전 중 실행이 누락될 수 있습니다. ‘일’은 24시간 단위이며, 달력 날짜나 매일 같은 시각을 기준으로 반복하지 않습니다.";
  card.intervalFields.append(intervalHelp);
  const weekdays = document.createElement("fieldset"), legend = document.createElement("legend");
  const dayGrid = document.createElement("div"); dayGrid.className="weekday-grid";
  legend.textContent = "실행 요일"; weekdays.append(legend, dayGrid); card.days = [];
  weekdayNames.forEach((name, index) => {
    const label = document.createElement("label"), input = document.createElement("input");
    input.type = "checkbox"; input.value = String(index + 1); card.days.push(input);
    label.className="checkbox-control"; label.append(input, name); dayGrid.append(label);
  });
  const timeLabel = document.createElement("p"); timeLabel.textContent = "실행 시각";
  card.times = document.createElement("div");
  const add = document.createElement("button"); add.type = "button"; add.textContent = "시각 추가";
  add.onclick = () => { addScheduleTime(card); markScheduleDirty(card); };
  card.draft = document.createElement("span"); card.draft.className = "muted";
  const actions = document.createElement("div"); actions.className = "actions dialog-actions";
  const cancel = document.createElement("button"); cancel.type="button"; cancel.textContent="취소"; cancel.onclick=safe(closeScheduleEditor);
  const save = document.createElement("button"); save.type = "submit"; save.textContent = "저장·OS 적용"; save.className = "primary";
  const toggle = document.createElement("button"); toggle.type="button"; toggle.textContent="일시중지 / 재개";
  const remove = document.createElement("button"); remove.type="button"; remove.textContent="Schedule 삭제"; remove.className="danger";
  const reload = document.createElement("button"); reload.type = "button"; reload.textContent = "최신 설정 불러오기";
  actions.append(toggle, remove, reload, cancel, save);
  card.save=save; card.toggle=toggle;
  card.calendarFields.append(weekdays, timeLabel, card.times, add);
  const nameLabel = document.createElement("label"); nameLabel.append("Schedule 이름");
  card.name = document.createElement("input"); card.name.required=true; card.name.maxLength=200; nameLabel.append(card.name);
  const body = document.createElement("div"); body.className="dialog-body";
  body.append(heading, card.yaml, card.os, card.problem, nameLabel, enabledLabel, modeLabel, card.calendarFields, card.intervalFields, card.draft);
  card.form.append(body, actions);
  card.form.addEventListener("input", () => markScheduleDirty(card));
  card.form.onsubmit = safe(async () => {
    const schedule = scheduleDraft(card);
    await scheduleAction(card, async () => {
      await api(schedulePath(card.item), "PUT", {schedule, etag: card.item.etag});
      card.dirty = false;
      notice("Schedule 저장과 OS 적용을 완료했습니다.");
    });
  });
  toggle.onclick = safe(async () => {
    if (card.dirty) throw new Error("변경한 설정을 먼저 저장·적용하세요.");
    const schedule = {...card.item.config.schedule, enabled:!card.item.config.schedule.enabled};
    await scheduleAction(card, async () => {
      await api(schedulePath(card.item), "PUT", {schedule, etag:card.item.etag});
      notice(schedule.enabled ? "Schedule을 재개했습니다." : "Schedule을 일시중지했습니다.");
    });
  });
  remove.onclick = safe(async () => {
    if (!(await approve("이 Schedule을 삭제하고 OS 예약을 해제할까요?"))) return;
    await scheduleAction(card, async () => {
      await api(schedulePath(card.item), "DELETE", {etag:card.item.etag, legacy_registration:card.item.legacy_registration});
      card.dirty = false; notice("Schedule과 OS 예약을 삭제했습니다.");
    });
  });
  reload.onclick = safe(async () => {
    if (card.dirty && !(await approve("수정 중인 스케줄을 버리고 최신 YAML 설정을 불러올까요?"))) return;
    card.dirty = false; card.formEtag=undefined; await refreshSchedules(true);
  });
  card.element.append(card.form);
  return card;
}
async function scheduleAction(card, action) {
  if (card.busy) return;
  card.busy = true;
  $("schedule-editor-close").disabled=true;
  card.form.querySelectorAll("input,button,select").forEach(input => input.disabled = true);
  try { await action(); }
  finally {
    card.busy = false;
    $("schedule-editor-close").disabled=false;
    card.form.querySelectorAll("input,button,select").forEach(input => input.disabled = false);
    updateScheduleMode(card);
    await refreshSchedules(true);
  }
}
function schedulePath(item) { return "jobs/" + encodeURIComponent(item.job_id) + "/schedules/" + encodeURIComponent(item.schedule_id); }
function scheduleStatus(state = {}, schedule = {}, orphan = false, error) {
  error = error || state.observation_error || state.error;
  let label;
  if (error || ["applying","degraded"].includes(state.phase)) label="오류";
  else if (state.supported === false) { label="오류"; error="이 OS에서는 로컬 예약을 적용할 수 없습니다."; }
  else if (orphan) label="유령 예약";
  else if (state.loaded && state.applied && state.file_matches && state.desired_matches && schedule.enabled) label="적용됨";
  else if (state.loaded || state.file_exists || state.applied) label="설정 불일치";
  else label=schedule.enabled ? "미적용" : "비활성 · 미등록";
  return {label,error};
}
function updateScheduleCard(card, item, state = {}, error) {
  card.latest = item;
  const schedule = item.config?.schedule || {enabled:false};
  card.title.textContent = (schedule.name || item.id) + " · " + (item.config?.name || item.id);
  card.element.setAttribute("aria-label", item.id + " 스케줄");
  card.form.hidden = !!item.error;
  const days = schedule.weekdays || [1,2,3,4,5,6,7];
  const unknown = !!(error || item.error || state.observation_error);
  card.yaml.textContent = item.error ? "YAML: 설정을 읽을 수 없습니다." : "YAML: " + scheduleSummary(item);
  card.os.textContent = unknown ? localScheduler + ": 상태를 확인할 수 없습니다." : localScheduler + ": " + (state.loaded ? "등록됨" : "등록 안 됨") + " · " +
    (state.file_exists ? (state.file_matches ? "등록 내용 일치" : "등록 내용 불일치") : "등록 내용 없음") + (state.legacy_registration ? " · 이전 예약 (저장 시 자동 전환)" : "") + (state.os_disabled ? " · OS 비활성화됨" : "");
  const status = scheduleStatus(state, schedule, item.orphan, error || item.error);
  const {label} = status;
  card.status.textContent = label;
  card.status.className = "schedule-status" + (label === "적용됨" ? " good" : label === "오류" ? " error" : ["설정 불일치","미적용","유령 예약"].includes(label) ? " warning" : "");
  card.problem.textContent = status.error || (label === "오류" ? "이전 적용이 완료되지 않았습니다. 상태를 확인하세요." :
    label === "유령 예약" ? "YAML에서 삭제된 OS 예약입니다. 삭제로 정리하세요. 실행은 차단됩니다." :
    label === "설정 불일치" ? "현재 YAML과 OS 적용 상태가 다릅니다. 이 Schedule을 저장·OS 적용하세요." : "");
  card.summaryLink.textContent = item.config?.name || item.id;
  card.summaryId.textContent = item.job_id || item.id;
  const summary = [schedule.name || "—",
    item.error ? "—" : (schedule.type || schedule.mode) === "interval" ? intervalSummary(schedule) : days.map(day => weekdayNames[day - 1]).join(", ") + " · " + ((schedule.times || []).join(", ") || "시각 미지정"),
    item.error ? "읽기 오류" : schedule.enabled ? "활성" : scheduleKind(item) === "disabled" ? "비활성" : "예약 없음", label];
  card.summaryCells.forEach((cell, index) => {
    if (index === 2) cell.replaceChildren(statusBadge(summary[index], item.error ? "error" : schedule.enabled ? "good" : "inactive"));
    else if (index === 3) cell.replaceChildren(statusBadge(label, label === "적용됨" ? "good" : label === "오류" ? "error" : ["설정 불일치","미적용"].includes(label) ? "warning" : "inactive"));
    else {
      cell.textContent = summary[index];
      if (index === 0 && schedule.id) { const id=document.createElement("small"); id.textContent=schedule.id; cell.append(id); }
    }
  });
  if (!card.dirty && !card.busy && card.formEtag !== item.etag) {
    card.formEtag=item.etag; card.item = item; card.name.value = schedule.name || ""; card.enabled.checked = schedule.enabled;
    card.mode.value = schedule.type || schedule.mode || "calendar";
    card.intervalValue.value = schedule.interval_seconds || schedule.interval?.value || 60;
    card.intervalUnit.value = schedule.interval_seconds ? "seconds" : schedule.interval?.unit || "seconds";
    updateScheduleMode(card);
    card.days.forEach((input, index) => input.checked = days.includes(index + 1));
    card.times.replaceChildren();
    for (const time of schedule.times?.length ? schedule.times : [""]) addScheduleTime(card, time);
    card.draft.textContent = "파일에 저장된 설정";
    card.save.disabled=!!item.orphan; card.toggle.disabled=!!item.orphan;
    card.toggle.textContent=schedule.enabled ? "일시중지" : "재개";
  }
  if (item.orphan) card.form.querySelectorAll("input,select").forEach(input=>input.disabled=true);
  card.save.disabled=!!item.orphan || card.busy; card.toggle.disabled=!!item.orphan || card.busy;
}
async function refreshSchedules(force = false) {
  if (scheduleRefreshTask) {
    await scheduleRefreshTask;
    if (!force) return;
  }
  if (view !== "schedules") return;
  const task = (async () => {
    const rows = await api("schedules");
    if (view !== "schedules") return;
    const items = rows.map(row => ({id:row.job_id + "/" + (row.legacy_registration ? "@legacy" : row.schedule?.id || "@error"),
      job_id:row.job_id, schedule_id:row.schedule?.id, etag:row.etag, orphan:row.orphan,
      legacy_registration:row.legacy_registration, config:{name:row.job_name, schedule:row.schedule}, error:row.error, state:row.state}));
    const ids = new Set(items.map(item => item.id));
    for (const [id, card] of scheduleCards) {
      if (!ids.has(id)) { card.element.remove(); card.summaryRow.remove(); scheduleCards.delete(id); if(selectedSchedule === id) selectedSchedule=undefined; }
    }
    for (const item of items) {
      let card = scheduleCards.get(item.id);
      if (!card) {
        card=createScheduleCard(item); scheduleCards.set(item.id,card);
        $("schedule-cards").append(card.element); $("schedule-overview-rows").append(card.summaryRow);
      }
      updateScheduleCard(card,item,item.state,item.error);
    }
    if (view === "schedules") renderScheduleOverview();
  })();
  scheduleRefreshTask = task;
  try { await task; }
  finally { if (scheduleRefreshTask === task) scheduleRefreshTask = undefined; }
}

$("new-schedule").onclick = safe(async()=>{
  if (!(await leaveEditor())) return;
  const items=await api("jobs"); $("schedule-job").replaceChildren();
  for(const item of items.filter(item=>!item.error)) {
    const option=document.createElement("option"); option.value=item.id; option.textContent=item.config.name + " · " + item.id; $("schedule-job").append(option);
  }
  if(!$("schedule-job").children.length) throw new Error("먼저 Job을 생성하세요.");
  $("schedule-create").reset(); $("schedule-create-error").textContent=""; $("schedule-create-dialog").showModal(); updateNewScheduleMode();
});
function updateNewScheduleMode() {
  const interval=$("schedule-type").value==="interval";
  $("new-calendar-fields").hidden=interval; $("new-interval-fields").hidden=!interval;
  $("schedule-times").required=!interval; $("schedule-seconds").required=interval;
}
$("schedule-type").onchange=updateNewScheduleMode;
let scheduleCreateBusy=false;
function closeScheduleCreate() { if (!scheduleCreateBusy) $("schedule-create-dialog").close(); }
$("schedule-create-cancel").onclick=closeScheduleCreate;
$("schedule-create-close").onclick=closeScheduleCreate;
$("schedule-create-dialog").oncancel=event=>{event.preventDefault(); closeScheduleCreate();};
$("schedule-create").onsubmit=safe(async()=>{
  if (scheduleCreateBusy) return;
  scheduleCreateBusy=true;
  $("schedule-create").querySelectorAll("input,select,button").forEach(input=>input.disabled=true);
  for (const id of ["schedule-create-submit","schedule-create-cancel","schedule-create-close"]) $(id).disabled=true;
  $("schedule-create-error").textContent="";
  try {
    const job=await api("jobs/"+encodeURIComponent($("schedule-job").value));
    const schedule={id:$("schedule-new-id").value,name:$("schedule-new-name").value,enabled:$("schedule-enabled").checked,type:$("schedule-type").value};
    if(schedule.type==="interval") schedule.interval_seconds=Number($("schedule-seconds").value);
    else { schedule.times=$("schedule-times").value.split(",").map(s=>s.trim()).filter(Boolean); schedule.weekdays=[...$("schedule-new-days").querySelectorAll("input:checked")].map(input=>Number(input.value)); }
    await api("jobs/"+encodeURIComponent(job.id)+"/schedules","POST",{schedule,etag:job.etag});
    $("schedule-create-dialog").close(); $("schedules-search").value=""; $("schedules-filter").value="all";
    selectedSchedule=job.id+"/"+schedule.id; await refreshSchedules(true); notice("Schedule 생성과 OS 적용을 완료했습니다.");
  } catch(error) { $("schedule-create-error").textContent=error.message; notice(error.message,true); }
  finally {
    scheduleCreateBusy=false;
    $("schedule-create").querySelectorAll("input,select,button").forEach(input=>input.disabled=false);
    for (const id of ["schedule-create-submit","schedule-create-cancel","schedule-create-close"]) $(id).disabled=false;
  }
});

const settingFields=["name","description","command","cwd","env","env-file","timeout","report-enabled","report-source","report-dir","report-filename"];
function updateJobEditMode() {
  $("yaml").readOnly=basicDirty || settingsSaving;
  $("save").disabled=basicDirty || settingsSaving;
  $("settings-save").disabled=(dirty && !basicDirty) || settingsSaving;
  $("settings-save").textContent=settingsSaving ? "저장 중…" : "설정 저장";
  $("settings-reload").disabled=settingsSaving;
  $("job-settings").querySelectorAll("input,textarea,button").forEach(input=>input.disabled=settingsSaving || (dirty && !basicDirty));
  $("edit-status").textContent=settingsSaving ? "저장 중…" : dirty ? (basicDirty ? "일반 설정에 미저장 변경 · YAML 잠김" : "YAML에 미저장 변경 · 일반 설정 잠김") : "저장된 설정과 동기화됨";
  $("settings-conflict").hidden=!settingsConflict;
  $("package-create").disabled=dirty || settingsSaving;
  updateRunButton();
}
function invalidatePlan() {
  ++planSequence;
  planHash=plannedPackage=null;
  $("deploy").disabled=true;
  $("deployment-plan").hidden=true;
  $("deployment-plan").textContent="";
}
function populateJobSettings() {
  basicDirty=false;
  const config=current.config;
  $("setting-name").value=config.name;
  $("setting-description").value=config.description || "";
  $("setting-command").value=config.command.join("\n");
  $("setting-cwd").value=config.cwd || ".";
  $("setting-env").value=JSON.stringify(config.env || {},null,2);
  $("setting-env-file").value=config.env_file || "";
  $("setting-timeout").value=config.timeout_seconds || 300;
  $("setting-report-enabled").checked=config.report?.enabled || false;
  $("setting-report-source").value=config.report?.source || "";
  $("setting-report-dir").value=config.report?.output_dir || "default";
  $("setting-report-filename").value=config.report?.filename || "";
  updateJobEditMode(); queueDestinationPreview();
}
function queueDestinationPreview() {
  clearTimeout(destinationTimer);
  const sequence=++destinationSequence, id=selected;
  $("report-destination").textContent="저장 경로 확인 중…";
  $("report-destination").className="path-preview muted";
  destinationTimer=setTimeout(async()=>{
    const settings={output_dir:$("setting-report-dir").value || "default"};
    if($("setting-report-filename").value)settings.filename=$("setting-report-filename").value;
    try {
      const result=await api("jobs/"+encodeURIComponent(id)+"/report/destination","POST",settings);
      if(id!==selected || sequence!==destinationSequence)return;
      $("report-destination").textContent="실제 저장 경로: "+result.path+" (실행 호스트 기준 · 생성 시 다시 검증)";
    } catch(error) {
      if(id!==selected || sequence!==destinationSequence)return;
      $("report-destination").textContent="저장 경로 확인 실패: "+error.message;
      $("report-destination").className="path-preview error";
    }
  },250);
}
for(const field of settingFields) $("setting-"+field).oninput=()=>{
  basicDirty=true;dirty=true;invalidatePlan();updateJobEditMode();
  if(["report-dir","report-filename"].includes(field))queueDestinationPreview();
};
async function saveJobSettings(payload) {
  if(settingsSaving)return;
  if((payload.yaml!==undefined && basicDirty) || (payload.fields && dirty && !basicDirty))throw new Error("편집 중인 설정을 먼저 저장하세요.");
  settingsSaving=true; updateJobEditMode();
  let saved=false;
  try {
    current=await api("jobs/"+encodeURIComponent(selected),"PUT",{...payload,etag:current.etag});
    saved=true; settingsConflict=false; dirty=false; $("yaml").value=current.yaml;
    $("job-name").textContent=current.config.name; populateJobSettings(); invalidatePlan();
  } catch(error) {
    if(error.status===409){settingsConflict=true; throw new Error("저장 충돌: "+error.message+" 초안을 보존했습니다. 외부 설정 변경 시 최신 설정을 다시 불러온 뒤 변경을 적용하세요.");}
    throw error;
  } finally { settingsSaving=false; updateJobEditMode(); }
  if(saved) {
    notice(payload.yaml!==undefined ? "YAML을 저장하고 일반 설정을 동기화했습니다. 예약 변경은 Schedule에서 OS에 적용하세요." : "실행 설정을 저장하고 YAML을 동기화했습니다.");
    try { await jobs();await refreshDetail(); } catch(error) { notice("설정 저장 완료 · 상태 새로고침 실패: "+error.message,true); }
  }
}
$("settings-reload").onclick=safe(async()=>{
  if(!(await approve("미저장 초안을 버리고 최신 설정을 불러올까요? 필요한 변경은 먼저 복사하세요.")))return;
  const id=selected, fresh=await api("jobs/"+encodeURIComponent(id));
  if(id!==selected)return;
  current=fresh; dirty=false; settingsConflict=false; $("yaml").value=fresh.yaml; $("job-name").textContent=fresh.config.name;
  populateJobSettings();invalidatePlan(); notice("최신 설정을 불러왔습니다.");
});
$("job-settings").onsubmit=safe(async()=>{
  let env;
  try {env=JSON.parse($("setting-env").value || "{}");}catch{throw new Error('환경 변수는 JSON 객체로 입력하세요. 예: {"LANG":"ko_KR.UTF-8"}');}
  if(!env || Array.isArray(env) || typeof env!=="object" || Object.values(env).some(value=>typeof value!=="string"))throw new Error("환경 변수는 값이 문자열인 JSON 객체여야 합니다.");
  const fields={name:$("setting-name").value,description:$("setting-description").value,
    command:$("setting-command").value.split("\n"),cwd:$("setting-cwd").value,
    env,env_file:$("setting-env-file").value || null,
    timeout_seconds:Number($("setting-timeout").value)};
  const report = {enabled:$("setting-report-enabled").checked, output_dir:$("setting-report-dir").value || "default"};
  if ($("setting-report-source").value) report.source=$("setting-report-source").value;
  if ($("setting-report-filename").value) report.filename=$("setting-report-filename").value;
  if (current.config.report || report.enabled || report.source || report.filename || report.output_dir !== "default") fields.report=report;
  await saveJobSettings({fields});
});

function bytes(value) {
  value=value || 0;
  return value<1024 ? value+" B" : value<1048576 ? (value/1024).toFixed(2)+" KiB" : (value/1048576).toFixed(2)+" MiB";
}
function updateLifecycleActions() {
  const ready=lifecyclePreview?.job===selected && !lifecycleDirty && !lifecycleSaving;
  $("cleanup-packages").disabled=!ready || !lifecyclePreview.packages.length;
  $("cleanup-output").disabled=!ready || !lifecyclePreview.output.length;
  $("lifecycle-preview").disabled=lifecycleDirty || lifecycleSaving;
  for(const id of ["package-keep","output-days","output-runs","package-auto","output-auto","lifecycle-save"]) $(id).disabled=lifecycleSaving;
  $("lifecycle-policy-status").textContent=lifecycleSaving ? "보존 정책 저장 중…" : lifecycleDirty ? "미저장 변경 · 저장 후 미리보기" : "저장된 보존 정책";
  if(!lifecyclePreview) $("lifecycle-preview-summary").textContent=lifecycleDirty ? "보존 정책이 변경되었습니다. 저장 후 다시 미리보기를 실행하세요." : "정리 대상 미리보기를 실행하세요.";
}
for(const id of ["package-keep","output-days","output-runs","package-auto","output-auto"]) $(id).oninput=()=>{lifecycleDirty=true; lifecyclePreview=null;updateLifecycleActions();};
async function refreshLifecycle(id) {
  const data=await api("jobs/"+encodeURIComponent(id)+"/lifecycle");
  if(id!==selected || view!=="detail")return;
  lifecycleData=data;
  if(lifecycleJob!==id){lifecycleDirty=false; lifecyclePreview=null; lifecycleJob=id; $("lifecycle-preview-info").textContent="미리보기를 실행하세요.";}
  if(!lifecycleDirty){
    for(const [input,key] of [["package-keep","package_keep"],["output-days","output_days"],["output-runs","output_runs"]]) $(input).value=data.policy[key]??"";
    $("package-auto").checked=data.policy.package_auto; $("output-auto").checked=data.policy.output_auto;
  }
  $("data-paths").textContent=Object.entries(data.paths).map(([key,value])=>key+"="+value).join("\n");
  $("data-usage").textContent=Object.entries(data.usage).map(([key,value])=>key+": "+bytes(value)).join(" · ")+" (Workspace는 프로젝트 전체)";
  $("lifecycle-packages").replaceChildren();
  for(const item of data.packages){
    const row=document.createElement("div"); row.className="run";
    row.append(item.id+" · "+(item.zip_available ? "ZIP 보관 "+bytes(item.zip_bytes) : "ZIP 정리됨")+" · "+(item.protection.join(", ")||"보호 없음")+(item.cleanup_candidate ? " · 정리 대상" : ""));
    for(const [key,label] of [["pins","Pin"],["rollback_packages","롤백 보호"]]){
      const button=document.createElement("button"), active=data.policy[key].includes(item.id); button.textContent=label+(active ? " 해제" : " 설정");
      button.onclick=safe(async()=>{await api(path("lifecycle"),"PUT",{[key]:active ? data.policy[key].filter(id=>id!==item.id) : [...data.policy[key],item.id]}); lifecyclePreview=null; await refreshLifecycle(selected);}); row.append(button);
    }
    $("lifecycle-packages").append(row);
  }
  $("output-trash").replaceChildren();
  for(const item of data.outputs.filter(item=>item.trashed)){
    const row=document.createElement("div"), button=document.createElement("button"); row.className="run"; row.append(item.id+" · "+bytes(item.bytes)); button.textContent="복구";
    button.onclick=safe(async()=>{await api(path("lifecycle/restore"),"POST",{run_id:item.id}); lifecyclePreview=null; await refreshLifecycle(selected); notice("Output을 복구했습니다.");}); row.append(button); $("output-trash").append(row);
  }
  if(!data.packages.length) $("lifecycle-packages").textContent="보관된 Package가 없습니다.";
  if(!data.outputs.some(item=>item.trashed)) $("output-trash").textContent="Output 휴지통이 비어 있습니다.";
  updateLifecycleActions();
}
$("lifecycle-save").onclick=safe(async()=>{
  if(lifecycleSaving)return;
  function number(id,nullable){const raw=$(id).value.trim(); if(raw==="" && nullable)return null; const value=Number(raw); if(raw==="" || !Number.isInteger(value)||value<0)throw new Error("0 이상의 정수를 입력하세요."); return value;}
  const policy={package_keep:number("package-keep",false),output_days:number("output-days",true),output_runs:number("output-runs",true),package_auto:$("package-auto").checked,output_auto:$("output-auto").checked};
  lifecycleSaving=true; updateLifecycleActions();
  try { await api(path("lifecycle"),"PUT",policy); lifecycleDirty=false; lifecyclePreview=null; notice("보존 정책을 저장했습니다."); }
  finally {lifecycleSaving=false; updateLifecycleActions();}
  try {await refreshLifecycle(selected);}catch(error){notice("보존 정책 저장 완료 · 데이터 조회 실패: "+error.message,true);}
});
$("lifecycle-preview").onclick=safe(async()=>{if(lifecycleDirty)throw new Error("보존 정책을 먼저 저장하세요."); const id=selected; await refreshLifecycle(id); if(id!==selected || lifecycleDirty)return; lifecyclePreview={job:selected,packages:lifecycleData.packages.filter(p=>p.cleanup_candidate).map(p=>p.id),output:lifecycleData.outputs.filter(p=>p.cleanup_candidate).map(p=>p.id)}; updateLifecycleActions(); $("lifecycle-preview-summary").textContent="ZIP 영구 삭제 "+lifecyclePreview.packages.length+"건 · 확보 예상 "+bytes(lifecycleData.package_reclaim_bytes)+" / Output 휴지통 이동 "+lifecyclePreview.output.length+"건 · 이동 용량 "+bytes(lifecycleData.output_move_bytes)+" (디스크 확보 없음)"; $("lifecycle-preview-info").textContent=JSON.stringify({ZIP_정리:lifecyclePreview.packages,확보_예상:bytes(lifecycleData.package_reclaim_bytes),Output_휴지통_이동:lifecyclePreview.output,이동_용량:bytes(lifecycleData.output_move_bytes)},null,2);});
for(const resource of ["packages","output"]) $("cleanup-"+resource).onclick=safe(async()=>{
  if(!lifecyclePreview || lifecyclePreview.job!==selected || lifecycleDirty)throw new Error("정리 대상 미리보기를 먼저 실행하세요.");
  if(!(await approve(resource==="packages" ? "미리본 ZIP을 영구 삭제할까요? 메타데이터와 배포 이력은 보존됩니다." : "미리본 Output을 휴지통으로 이동할까요?")))return;
  const result=await api(path("lifecycle/cleanup"),"POST",{resource,expected:lifecyclePreview[resource]}); lifecyclePreview=null; planHash=null; plannedPackage=null; $("deploy").disabled=true;
  updateLifecycleActions(); $("lifecycle-preview-info").textContent=JSON.stringify(result,null,2); await refreshDetail(); $("lifecycle-preview-summary").textContent="정리 완료 "+result.completed.length+"건 · 실패 "+result.errors.length+"건 · 추가 정리는 다시 미리보기 하세요."; notice("정리 완료 "+result.completed.length+"건 · 실패 "+result.errors.length+"건",result.errors.length>0);
});


function closeReportPreview() {
  $("report-frame").hidden=true;
  $("report-frame").removeAttribute?.("src");
  $("report-preview-close").hidden=true;
}
async function refreshReport(id) {
  let info;
  try { info=await api("jobs/"+encodeURIComponent(id)+"/report"); }
  catch (error) { info={error:error.message}; }
  if (id !== selected || view !== "detail") return;
  const available=!!info.available;
  reportPath=info.path || "";
  $("report-status").textContent=info.error ? "보고서 조회 실패: "+info.error : available ? "생성: "+localDate(info.generated_at)+" · "+info.count+"건" : info.path ? "생성 이력은 있지만 HTML 파일이 없습니다. 마지막 생성: "+localDate(info.generated_at) : "아직 생성된 보고서가 없습니다.";
  $("report-status").className=info.error ? "error" : "";
  $("report-origin").textContent=info.path ? (info.run_id ? "Run 기반 생성 (자동 또는 CLI --run) · Run "+info.run_id : "별도 생성 · CLI report-render --source") : "";
  $("report-path").hidden=!reportPath; $("report-path").textContent=reportPath;
  const base="/api/jobs/"+encodeURIComponent(id)+"/report/";
  $("report-open").hidden=$("report-download").hidden=!available;
  $("report-open").href=base+"html?v="+encodeURIComponent(info.sha256 || ""); $("report-download").href=base+"download";
  if (available && !$("report-frame").hidden && $("report-frame").src !== $("report-open").href) $("report-frame").src=$("report-open").href;
  $("report-preview").disabled=!available;
  $("report-folder").disabled=!available; $("report-copy").disabled=!reportPath || !!info.error;
  if (!available) closeReportPreview();
}
$("report-preview").onclick=()=>{
  $("report-frame").src=$("report-open").href;
  $("report-frame").hidden=false; $("report-preview-close").hidden=false;
};
$("report-preview-close").onclick=closeReportPreview;
$("report-folder").onclick=safe(async()=>{await api(path("report/open-directory"),"POST",{});notice("보고서 폴더 열기를 요청했습니다.");});
$("report-copy").onclick=safe(async()=>{await navigator.clipboard.writeText(reportPath);notice("보고서 경로를 복사했습니다.");});
