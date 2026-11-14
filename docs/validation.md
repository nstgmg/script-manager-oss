# Validation records

## Main publication verification — 2026-11-14

The owner explicitly authorized one feature commit and a normal push to `origin/main`, without a VERSION change, new tag, GitHub Release or deployment. Origin was verified as the public, unarchived [nstgmg/script-manager-oss repository](https://github.com/nstgmg/script-manager-oss), with default branch main. Local main started at `5f9b597`; fetched origin/main was `e9fd9de3fb6b533c9729457b708522992aca5c66`, two README-only commits ahead with no divergent local commit. Preserved the local README patch in a task-specific stash/file backup, fast-forwarded main without a merge commit, and reapplied the patch. Both remote additions and feature instructions were retained; the other 29 candidate files were verified unchanged by SHA-256.

Final checks from the synchronized source:

| Check | Observed result |
| --- | --- |
| Full Python regression | **270 tests: 265 passed, 5 opt-in native skips, no failures/errors**, 42.329s. Includes offline Chrome management/report/detail checks. `.cache/publish-python-tests.txt` |
| Node Dashboard UI | **71 passed**, no skips/failures. `.cache/publish-node-tests.txt` |
| Syntax | All 20 candidate Python files parsed with Python 3.9 grammar; Dashboard JavaScript and Chrome helper passed Node syntax checks |
| Documentation | README, CLI, architecture, uninstall and validation links/anchors checked with no missing targets; deletion scope, local/remote boundaries and platform limitations agree |
| Candidate scope and sensitive-content review | Explicit allowlist of **30 feature/audit source, test and documentation files**; no private-key, recognized token/access-key, credential-bearing URL or unintended private-path patterns found; no symlink/binary/runtime files selected |
| Git hygiene | `git diff --check` passed; VERSION unchanged. `.cache/`, `.venv/`, bytecode, logs/screenshots, runtime/Job data and credentials remain excluded. |
| Existing macOS actual-OS evidence | Rechecked the audit's four distinct native PASS records, the natural-wrapper-exit retry and zero-test-reservation cleanup evidence. Native schedules were not created again for publication. |

The 5 Python skips are the 4 macOS opt-in cases already tested natively during the audit and 1 Windows native case. Actual Windows/Linux scheduling, Windows XML export normalization/path deletion, actual Linux mounts/systemd and real SSH remain unverified; publication does not change those limits. Pattern scanning is evidence of this candidate review, not a claim that all possible secret formats can be detected. Original .env values were not read.

GitHub reports active default-setup CodeQL and Dependency Graph workflows; there are no repository-defined workflow files in this checkout. The pushed commit SHA, exact remote/local HEAD comparison and Actions outcomes are checked and reported after publication, avoiding a self-referential commit hash in this document. Only main is updated; the temporary README stash is removed only after the verified content has been committed. Ignored verification artifacts remain local.


## Final maintenance safety audit — 2026-11-14

This section records a separate audit of the preceding uncommitted implementation. Starting HEAD was `5f9b597`, with **26 existing changed/untracked files**. Those files and their SHA-256 manifest were preserved under ignored `.cache/final-audit-baseline/` before edits; no reset/clean/stash/commit/push/deployment was performed. Changes stayed in `script-manager-oss-clean`. No real user reset, credentials read, existing service control, actual SSH, dependency extension or background monitor was introduced.

### Confirmed defects and corrections

| Finding | Correction and evidence |
| --- | --- |
| Approved data was not rechecked after native removal; recursive removal could consume newly added children | Per-target approved inventory fingerprints, complete target-set recheck in `verify-data-plan`, individual approved-entry deletion and progress reporting. POSIX uses rooted directory descriptors, O_NOFOLLOW and inode/device/type checks. New children are retained; directory removal fails rather than recursively consuming them. `DataAuditTests` reproduced the original lost-child defect before the fix; `FinalDataRaceTests` verifies an addition even after deletion begins survives until a new approval. |
| Inaccessible traversal could silently omit files; code-free nested installations, Git projects and unfinished operations were not guarded | Walk errors propagate; nested installation markers and Git roots, reparse points/junctions, mounts and Linux bind mounts block maintenance. `pending`/`unconfirmed` or unreadable deployment receipts and applying/degraded schedule state block cleanup. Original nested-installation and unconfirmed-deployment cases failed before the fix. Bind mount/reparse handling is simulated on macOS; no real mount operation was performed. |
| Original state/native checksums and installation IDs were not consistently compared; Windows trigger changes could pass as healthy | Compare existing local state checksums and identity; reject malformed ownership metadata. New Windows definitions carry a complete canonical XML checksum. Old metadata without it requires original state evidence; missing evidence remains unknown. The modified-trigger case failed before the fix. XML fields/defaults added by a real Windows export may conservatively make a task unknown; real Windows normalization compatibility remains unverified. |
| A plist/unit file path alone did not prove what the OS had loaded | Compare actual loaded launchd program/argv/working directory; compare systemd service ExecStart and timer target, source/drop-ins/reload state and deployment identity. Actual launchd format and normal/orphan flows were verified on macOS. Linux loaded-definition and failed-query cases use simulated systemd. No prefix-only ownership acceptance was found or added; prefixes only enumerate candidates or conservatively block ambiguous current-namespace entries. |
| A native definition could change in the last state query, and old schedule transaction/rollback paths could force bootout or overwrite an external replacement | Recheck raw definitions adjacent to mutation; require idle, matching loaded invocations in schedule apply/remove/preflight/rollback, and preserve foreign replacements during rollback with degraded-state reporting. Tests inject post-observation replacement, active tasks/processes and rollback-time foreign definitions. These are best-effort checks, not an OS compare-and-delete primitive. |
| Linux show errors with plausible stdout could be accepted | Reject failed `show` results. Explicit no-unit code 4 is accepted only with consistent not-found/inactive/empty-source properties; other error output is not a success. Exit status reference: [official systemctl manual](https://www.freedesktop.org/software/systemd/man/256/systemctl.html). Both branches are simulated; this reference is not a native Linux test. |
| Dashboard approval could refer to a changed preview; lost responses were described as a definite abort | Bind the approval to the captured preview, guard competing reset/preview actions, invalidate after errors, preserve cancellation behavior, and report uncertain completion on connection loss with no automatic retry. Disconnected response handling does not perform a second mutation. Actual ephemeral HTTP tests cover overlapping requests, stale replay after new Job creation, and socket disconnection while cleanup continues once. |

The initial focused red run executed five cases and reproduced **four failures**, retained in `.cache/audit-red.txt`. They all pass after correction. An initial actual-OS regression refused an update after a terminal Run because its launchd CLI wrapper had not yet exited. The production guard was retained; native tests now wait for the wrapper's natural exit, without forcing it out. The failed native case passed on re-execution, and there are **no unresolved test failures**.

### Verification results and limits

Host remained macOS ARM64, Python 3.9.6, existing ruamel.yaml dependency, Node 20.11.1 and installed Chrome.

| Check | Observed result |
| --- | --- |
| Final ordinary full suite | `python -m unittest discover -s tests -q`: **270 tests, 265 passed, 5 opt-in skips, 0 failures/errors**, 41.687s; `.cache/audit-regression-final.txt` |
| Audit regressions | **25 passed**; new `tests/test_maintenance_audit.py` covers scope drift, partial deletion/retry, code/data separation, external paths, traversal failure, path escape, nested installation, mounts/bind mount, loaded-definition drift, identity mismatch, unconfirmed records, active native processes, last-query drift and rollback preservation |
| Native macOS plus real HTTP | Initial 8-test run: **7 passed, 1 wrapper-timing error**. Final targeted re-execution: **2 passed**, including the previously failing multi-agent case and reset/reinstall recovery. Across these runs all **4 distinct native macOS tests passed**; actual interval firing, invocation, legacy/native reapplication, safe removal, reset/reuse/uninstall preparation and orphan recovery were covered. Logs: `.cache/audit-native-http.txt`, `.cache/audit-native-final.txt`. |
| Dashboard HTTP | **4 passed**, including the two new overlap/replay and disconnect cases; ephemeral loopback servers were shut down |
| Dashboard Node UI | **71 passed**; `.cache/audit-ui.txt`. Actual Chrome desktop 1280px/mobile 390px management and existing UI/report regressions passed within the final Python suite. |
| Final OS cleanup | `launchctl list` and test plist inventory showed **zero remaining test services/plists**, `.cache/audit-native-cleanup.txt`. No normal reservation was modified. |
| Documents/source hygiene | Local links checked, no missing targets; `git diff --check` and changed-module compilation passed. |

Across the final suite and explicit native runs, **269 of 270 unique Python tests passed**. The remaining test is the real Windows opt-in test, **not executed**. The 5 skips in the ordinary suite are the 4 separately tested macOS cases and that Windows case. Windows and Linux ownership/removal/state-error behavior use in-memory OS adapters; native Windows Task Scheduler/XML normalization/PowerShell and Windows path deletion, native Linux systemd/proc mount enumeration and actual mounts are **not verified on those OSes**. Do not treat simulated coverage as native PASS.

The eight requested recovery scenarios have evidence: native/unit normal reset and uninstall preparation; native project deletion/reinstalled individual orphan cleanup and foreign-install protection; injected multi-schedule failure with no data deletion and successful reapproval; injected partial entry deletion with `deleted_entries` and successful fresh-preview recovery; existing job execution/native schedule reapplication/deployment regressions; and actual HTTP duplicate/disconnect behavior. Ordinary OS entries, legacy/metadata-free/unknown entries and healthy foreign entries are protected by the native adapters' simulated tests; macOS also verified a second live native installation.

Remaining operational limits: data deletion is irreversible and not an all-or-nothing transaction; changes may stop after some approved entries or reservations are already removed. Incomplete deployment evidence blocks reset and needs separate operator recovery—existing verify does not automatically rewrite old receipts. Windows export drift can require original-install schedule removal or manual review. Native tools do not offer atomic definition-compare-and-remove; concurrent external OS edits, older processes ignoring the gate, malicious same-user filesystem replacement and Windows path races are not claimed fully solved. POSIX descriptor checks protect directory traversal boundaries, and additions are preserved, but this is not a multi-user security boundary or secure storage erasure. No SSH or remote cleanup is inferred from a local reset.

Audit-touched files relative to the preserved implementation (19): `runner/maintenance.py`, `runner/schedule_doctor.py`, `runner/schedule.py`, `runner/windows_schedule.py`, `runner/installation.py`; `dashboard/server.py`, `dashboard/static/app.js`; `tests/test_maintenance.py`, `tests/test_maintenance_audit.py` (new), `tests/test_maintenance_http.py`, `tests/test_schedule_doctor_platforms.py`, `tests/test_schedule.py`, `tests/test_windows_schedule.py`, `tests/test_native_launchd.py`, `tests/test_dashboard_ui.cjs`; `README.md`, `docs/cli.md`, `docs/uninstall.md`, `docs/validation.md`. The entire worktree includes the earlier changes: **20 tracked modified files and 10 untracked files**. Existing changes were preserved; no files were staged, committed, pushed or deployed. See [the updated user instructions](uninstall.md) for the exact preservation/deletion scope and recovery policy.


## Reset, uninstall and schedule recovery — 2026-11-14

Work was confined to the `script-manager-oss-clean` checkout, initially clean at `5f9b597`; no commit, push, deployment, real user reset, existing service restart or SSH operation was performed. Tests used isolated roots and synthetic data. The checkout-local Python environment was created from the existing requirements; runtime dependencies were not extended. Host: macOS ARM64, Python 3.9.6, ruamel.yaml 0.18.17, Node 20.11.1, installed Chrome. This records test execution on the minimum supported Python, not a recommendation for a new installation.

| Verification | Result |
| --- | --- |
| Final ordinary Python suite: `python -m unittest discover -s tests -q` | **243 tests: 238 passed, 5 opt-in native skips, 0 failures/errors** |
| Earlier full suite with `SCRIPT_MANAGER_TEST_LAUNCHD=1` | **239 tests: 238 passed, 1 Windows-native skip**; includes all 4 macOS native tests |
| Final native maintenance smoke with `SCRIPT_MANAGER_TEST_LAUNCHD=1` | **1 passed** after the final immediate process-state recheck; temporary LaunchAgents absent/unloaded after cleanup |
| Node Dashboard UI suite | **69 passed**, including typed confirmation, final cancellation, stale preview invalidation, blockers, error phase/remaining paths and safe text rendering |
| Actual Chrome management UI | Desktop 1280px and mobile 390px via DevTools pipe; diagnosis, preview, typed confirmation, cancellation, OS failure, running blocker, successful reset/reload guidance, no page horizontal overflow; screenshots visually inspected |
| Existing Chrome report/detail regressions | Passed in final ordinary suite; no Dashboard or network service needed for browser fixtures |
| CLI help and documents | New commands parsed; 47 local links across README/CLI/architecture/uninstall checked, zero missing targets; `git diff --check` passed |

Across these runs, **242 of the final 243 unique Python tests were exercised successfully**; the remaining test requires a real Windows host. The final ordinary suite intentionally leaves macOS native opt-in disabled after its separate actual-OS coverage. The three existing native schedule tests covered interval firing, OS invocation, independent registrations, updates and removal; the new native maintenance test covered reset, subsequent Job/schedule creation, uninstall preparation, protection of another live installation, project deletion and orphan removal from a reinstall. Only uniquely namespaced synthetic reservations were modified, and tests cleaned their native registrations. No calendar date arrival, login/reboot/sleep recovery or actual Windows/Linux OS behavior is claimed.

New deterministic tests also cover all reserved data categories including synthetic .env without reading it during preview, preservation of program/external files and installation IDs, existing legacy job-only and per-Schedule checksum compatibility, copied/corrupt IDs, same-path reinstall, unknown/modified/loaded-only registrations, healthy foreign installations and ordinary OS reservations, actual running Job refusal without cancellation, silent/explicit/timeout/partially completed unregister failures before any data deletion, partial data-deletion error reporting, confirmation scoping and managed-operation exclusion. Worker protection transfers from the live run lock/Windows lease to the project gate before automatic retention cleanup; the existing automatic Output cleanup regression passes.

Windows Task Scheduler and Linux systemd discovery/ownership/removal/failure paths used in-memory OS adapters. Windows current-user task XML/metadata/arguments, numeric waiting/running states, deletion verification, legacy checksums and foreign/ordinary task protection were tested. Linux remote helper metadata, read-only systemd inventory, missing deployment roots, timer-first orphan cleanup, active service/drop-in/legacy protection and stop failure were tested. Local Linux Job scheduling remains unsupported; diagnosis never opens SSH, and local reset does not clean remote deployments. Older systemd units and local native definitions without sufficient ownership evidence remain unknown; migration is only through an explicitly approved future schedule application/deployment, never a diagnostic rewrite.

Artifacts from this verification are local and ignored under `.cache/`: `regression-final.txt`, `regression.txt`, `native-maintenance-final.txt`, `dashboard-ui-final.tap` and `maintenance-ui/*.png`. They contain synthetic fixtures/summary data and are not part of the source distribution. See [the user-facing removal/recovery procedure](uninstall.md).

Changed files for this feature (26):

| Area | Files |
| --- | --- |
| Ownership, diagnosis, maintenance | `runner/installation.py`, `runner/schedule_doctor.py`, `runner/maintenance.py` (new) |
| Existing CLI/runtime adapters | `runner/__main__.py`, `runner/schedule.py`, `runner/windows_schedule.py`, `runner/store.py`, `runner/execution.py`, `runner/reports.py` |
| Linux deployment metadata | `deployments/remote_runtime.py` |
| Dashboard | `dashboard/server.py`, `dashboard/static/index.html`, `dashboard/static/app.js`, `dashboard/static/style.css` |
| New tests | `tests/test_maintenance.py`, `tests/test_maintenance_http.py`, `tests/test_maintenance_native.py`, `tests/test_schedule_doctor_platforms.py`, `tests/test_maintenance_browser.py` |
| Existing UI test helpers | `tests/test_dashboard_ui.cjs`, `tests/job_detail_chrome.cjs` |
| User/developer docs | `README.md`, `docs/uninstall.md` (new), `docs/cli.md`, `docs/architecture.md`, `docs/validation.md` |



Current public/security status and preserved installation checks: [public readiness](public-readiness.md). Focused CodeQL follow-up and alert handling criteria: [CodeQL triage](codeql-triage.md). The Phase 2A section below is historical; its no-hosting statements describe that phase only. Private registration and the Public transition happened later. Those historical platform results are not new verification of Windows, Linux, native schedules or real SSH/systemd.

## v0.1.0 publication gate — 2026-11-14

Reviewed source commit `730de25b09791a99532a8320f6d43b0986351eaf` on macOS ARM64. Reused the independent Python 3.13 installation/smoke, dependency audit, secret scans, full regression and browser results recorded below and in [public readiness](public-readiness.md); those suites and E2E checks were not repeated. Product code, tests and the supplied [Release Notes body](releases/v0.1.0.md) were not changed.

### Native launchd evidence

The historical full-suite result explicitly skipped all three `tests.test_native_launchd` tests; mocked scheduling and plist validation did not establish native application. The release task authorized the missing focused check. From this checkout, using the preserved installed CPython **3.13.18** environment, ran `SCRIPT_MANAGER_TEST_LAUNCHD=1 python -m unittest tests.test_native_launchd -v`: **3 passed, 0 skips/failures/errors, 67.091 seconds, exit 0**.

| Existing native test | Actual scope verified |
| --- | --- |
| `test_interval_fires_then_switches_to_calendar_and_removes` | Real temporary LaunchAgent bootstrap/observation and matching plist; 60-second StartInterval invoked Runner to `succeeded`; calendar replacement loaded; removal observed unloaded and plist absent |
| `test_multiple_native_agents_are_independent_and_share_run_guard` | Separate calendar/interval labels; real interval invocation records the expected schedule ID; updating/disabling/re-enabling/removing one preserves the other; kickstarted scheduled invocations respect a manual Run's shared lock; final registrations removed |
| `test_register_invoke_verify_remove` | Legacy calendar registration loaded; real `launchctl kickstart` invoked Runner to `succeeded`; removal observed unloaded |

These tests own isolated temporary roots and root-derived labels, use the current source and real OS transport, and clean up only their own registrations. No operational Job/Schedule, resident Dashboard or SSH target was operated. This establishes native application, interval firing and OS-invoked execution on this macOS ARM64 host. Calendar wall-clock firing at the configured weekday/time, sleep/wake/login/reboot persistence, other macOS versions and hostile-filesystem behavior were not tested. Windows native scheduling and real Linux/SSH/systemd remain unverified; Linux local scheduling remains unsupported. The earlier skip records remain historical, not retroactively passing results.

### Security and publication decision

GitHub's [checks for the reviewed SHA](https://github.com/nstgmg/script-manager-oss/actions/runs/43463243719) completed successfully for Python and JavaScript/TypeScript. Signed-in Security Overview still showed Private Vulnerability Reporting Enabled; Dependabot and secret scanning each showed **0 open alerts**. These observations do not prove every dependency or secret safe, notification delivery, non-admin reporting, mailbox monitoring, or detailed push-protection/update settings.

Reconciled the preserved individual CodeQL disposition record with GitHub's current **66 Open / 90 Closed**: 80 prior False Positive dismissals + eight prior Won't Fix dismissals + two automatic fixes account for the 90 closed alerts. The 66 open findings comprise 44 remote-runtime, 17 shared-filesystem and five Windows findings, including Critical #154. They remain open because actual platform/alternate-path evidence is incomplete, not because all were proved false positives. Reviewed the existing root/identifier, fixed argv/XML and local filesystem guards against the unchanged runtime source; did not dismiss alerts, change scanning/security settings or repeat a full audit. See [current CodeQL follow-up](codeql-triage.md#release-gate-observation--2026-11-14).

**Decision: no confirmed unresolved security issue that blocks this release was identified within the documented trusted local single-user scope.** This is a scoped release decision, not security certification or a zero-alert claim. Shared-filesystem caller/root tracing, Windows quoting/ACL/reparse verification and real SSH/Linux boundaries remain follow-up work. Public Dashboard exposure, multi-user use, untrusted Jobs and hostile concurrent filesystem replacement remain outside the safety contract. Existing remote execution/data-management limits and security operations follow-ups remain disclosed.

Before documentation changes, local `main` and the observed remote `main` both pointed to the reviewed SHA, the worktree was clean, and the remote had no `v0.1.0` tag. The public Releases API returned an empty list; the signed-in Releases page also showed no published or draft entries. Initial sandbox DNS failure was an environment limitation; the remote check succeeded with approved network access. Final documentation-commit checks, exact tag target and publication outcome must be verified after the commit rather than inferred from this pre-publication record.

## v0.1.0 Release Notes review — 2026-11-14

Reviewed the owner-supplied [Release Notes](releases/v0.1.0.md) against source commit `d3de2481a930d0c372cc9caad17506a06f8ea150`, README, INSTALL, UPDATE, capability/operations/Package documentation and existing validation records. No existing Release Notes path or naming convention was found; the supplied body is preserved in `docs/releases/v0.1.0.md`. README and UPDATE link to this preparation document while retaining the accurate unpublished-version status. VERSION remains `0.1.0`; no product code or existing implementation was changed.

| Release Notes claim | Evidence and assessment |
| --- | --- |
| Jobs, CLI execution, history/logs and local Dashboard | CLI parser/dispatch in `runner/__main__.py`, execution in `runner/execution.py`, HTTP management in `dashboard/server.py`; consistent |
| OS scheduling without continuous agent inference | macOS launchd and Windows Task Scheduler implementations invoke the internal scheduled runner; Linux local application is unsupported; consistent |
| Saved-result search and HTML generation | `runner/results.py`, `runner/reports.py`, `results`/`report-render` commands and Dashboard routes; consistent. Business collectors and custom analysis remain separately authored scripts/agent work |
| macOS ARM64 major features verified | Existing Python 3.13.18 independent-install records cover CLI, synthetic execution, logs, saved results, HTML and temporary Dashboard. Native launchd application was not tested; the major-feature statement must not be read as verification of every feature or OS scheduling |
| Windows/Linux and remote support limits | Windows execution/Task Scheduler and Linux systemd-user SSH paths exist; real Windows/Linux installations and real SSH/systemd remain unverified. Remote `required_env` construction fails without `project_root`; standard local data-path injection, report generation and Output/log synchronization are absent, as recorded in [Package limits](packages.md#current-remote-limitations) |
| No bundled AI model; local single-user trust | The manager executes conventional user-authorized programs without a model inference engine. Individual scripts/agents may call paid AI APIs; Jobs run with user OS rights, not sandbox isolation; consistent |

No direct feature/platform contradiction was found; the supplied wording was not rewritten. The broad macOS verification wording and summarized remote limits retain the qualifications above. This review reuses historical execution evidence and does not establish new platform verification or a measured cost/latency improvement.

Read-only GitHub checks on 2026-11-14 (Asia/Seoul) confirmed repository `nstgmg/script-manager-oss` is Public, with default branch `main` matching the source commit above. Local tags were empty; `git ls-remote` returned no `v0.1.0` tag, and the public Releases API returned an empty list (HTTP 200). Because that unauthenticated list cannot establish whether a draft exists, the signed-in repository management view was also checked: Releases displayed “There aren’t any releases here”, with no published or draft entries visible. Both CodeQL checks on that source commit completed successfully; this is not a zero-alert claim or a result for a future documentation commit. Initial sandbox DNS failures were resolved using approved network access, not treated as evidence of absent releases.

Current checks: nine help invocations (runner root, create, run, runs, logs, results, report-render, schedule-save and Dashboard) all exited 0 using an existing Python 3.9.6 environment with this checkout as cwd; no venv/dependency changes or runtime initialization here. Markdown validation covered 25 files, 182 local links and 25 fragments with zero errors; `git diff --check` passed. No full regression suite, new installation, Job execution, native scheduling, Dashboard service or real SSH operation was performed. Tag creation and GitHub Release publication are deferred to a separate request. Existing security follow-ups in [public readiness](public-readiness.md#현재-운영-확인) remain recorded rather than claimed complete.

## Project-local Dashboard Skill registration — 2026-11-13

Added the installation-only `scripts/register_dashboard_skill.py`, INSTALL/AGENTS registration and discovery instructions, and source-root resolution in the Dashboard Skill. Product code, APIs, Jobs, schedules, operational data and the explicit-only invocation policy were not changed. The installer requires a confirmed absolute project root containing the checkout; it does not infer that root from Git/cwd or register globally. Existing destinations are preserved, including broken links, user files, unmanaged directories and modified/stale copies. Parent links resolving outside the project are rejected.

Compared discovery with the [official Skill rules](https://learn.chatgpt.com/docs/build-skills#where-codex-loads-local-skills) and [App Server API](https://learn.chatgpt.com/docs/app-server#api-overview). Actual discovery checks used macOS, Python 3.9.6 and the installed Codex CLI `0.167.0-alpha.4.1`. Isolated temporary layouts contained the current Skill/policy and fresh Git metadata, without Jobs, credentials or runtime data. Each layout used a fresh Codex App Server process with its own empty temporary `CODEX_HOME`, `initialize`, an ephemeral read-only `thread/start` at the project root, then the real `skills/list` with `forceReload: false`. No model turn, manual Skill read/registration in Codex, extra search roots or folder reopening was used to obtain the discovery result. This tests real Codex session discovery, not the desktop UI picker or a complete clone/dependency installation.

| Layout | Registration | Fresh Codex session result |
| --- | --- | --- |
| A. project root = checkout | Existing `.agents/skills/sm-dashboard`, mode `repository`; no extra copy/link | Exactly one enabled repo Skill, path resolves to original `SKILL.md`; no discovery errors |
| B. project root contains `script-manager-oss/` | Project `.agents/skills/sm-dashboard` is a valid relative symlink to checkout original | Exactly one enabled repo Skill, canonical path resolves to checkout `SKILL.md`; no discovery errors |

Both layouts passed repeat registration and read-only `--check`. A separate live-session check started before the parent project's `.agents/skills` existed: no Skill was initially found, and 20 normal list polls over approximately five seconds after registration still returned none. On that same session/server, `skills/list` with `forceReload: true` immediately returned the expected one Skill. Therefore fresh-session discovery is verified, but automatic reflection into every already-open host cannot be guaranteed. A client must expose a supported refresh on its current server when automatic watching misses the new directory. Starting a different server cannot refresh the running desktop app. The current desktop chat does not expose that refresh/list interface, so its live picker/context update remains unverified. INSTALL describes this limitation and direct reading of the original Skill for an explicit Dashboard request; it does not require user folder reopening or manual registration.

Focused checks: `python3 -m unittest tests.test_skill_registration -v` passed **9 tests**, including actual helper CLI calls for both layouts, valid links, repeat installs, the simulated Windows copy/locator branch, modified/stale copy rejection, existing file/directory/broken-link preservation, external-parent/relative/home/root rejection, read-only checks and permission denial without fallback. Windows copying was exercised on macOS by selecting the Windows branch; actual Windows and Linux Codex discovery remain unverified. Skill frontmatter and unchanged `allow_implicit_invocation: false` were parsed with installed `ruamel.yaml`; the bundled Skill Creator `quick_validate.py` could not run because PyYAML is absent, and no dependency/environment was changed to run it.

Dashboard procedure was reviewed against `dashboard/__main__.py`, `dashboard/server.py`, `runner/__main__.py` and CLI docs. Runner/Dashboard help exited 0 using an existing installed Python environment with this checkout as cwd (this checkout has no `.venv`). Both layouts resolve the original code root before commands, reuse a session-root-verified existing service, submit one approved foreground start only after successful absence/port checks, and verify the actual URL plus data root. Help/document rereads are conditional on an unfamiliar/changed interface or errors. No Dashboard was started, reused or stopped for this task, and no live service execution is claimed. No full regression suite, Job execution, OS scheduling, SSH, commit, push or release was performed. `git diff --check` passed.

## Onboarding document review — 2026-11-13

Reviewed README/INSTALL/AGENTS and the linked technical docs against `runner/__main__.py`, `dashboard/__main__.py`, `dashboard/server.py`, Dashboard UI and relevant runner modules. Added [capabilities](capabilities.md) and a [user guide](../USER_GUIDE.md); README now starts with purposes and a repository-URL installation request, and AGENTS routes questions to documentation or actual runtime inspection. Existing technical contracts and platform/security restrictions remain in force.

Gaps addressed: no purpose-based feature index; no end-user natural-language request guide; no explicit question-routing table for agents; installation instructions assumed cloning a new child directory rather than an already-created empty project folder. The generic distribution includes no business collector or personal data, and Dashboard does not author scripts. Existing Package/lifecycle runner-CLI gaps, Linux local scheduling limits and remote execution limitations were confirmed and documented, not implemented or fixed.

The five scenarios were walked through using repository documents and implementation contracts. This is a document review, not a fresh-agent execution trial or a claim of successful installation/collection/service startup.

| Request | Agent reads first | Expected guidance and supported path | Inputs / authorization boundary | Review |
| --- | --- | --- | --- | --- |
| “이 GitHub 프로젝트 설치해 줘.” | README → INSTALL + AGENTS | New writable checkout/venv, declared dependencies, help/list, offline hello-output once, logs/results/HTML verification and actual paths | Repository URL, destination, Git/Python and approved download access. Install request covers only the documented synthetic check. Preserve existing files; no real collection, OS scheduling, Dashboard or SSH. | Covered |
| “이걸로 뭘 할 수 있어?” | AGENTS → capabilities → user guide | Purpose examples, built-in management versus scripts to author, platform and verification limits | No execution permission needed for guidance; do not invent existing Jobs or start work. Offer easy choices if purpose is unclear. | Covered |
| “매일 지원사업 공고를 모으고 싶어.” | User guide → authoring/operations/parameters/CLI; actual list/get | Discover reuse, define collector and JSON result contract, prepare Job and inactive schedule proposal; explain local scheduling support | Resolve sources/scope, desired output, time and host timezone. User registers secrets. Real collection and active schedule application require authorization; credentials-dependent schedules stay off until preflight and authorized real success. General daily intent alone does not resolve these choices. | Covered, inputs required |
| “만든 작업들과 실행 결과를 보여줘.” | AGENTS → CLI + result queries | Actual list/get, runs/logs, result-jobs → results; report Run/path/time/warnings/pagination or absence of data | Read existing runtime in the selected root; no recollection, source visits, web search or automatic older-data substitution. Documentation is not current runtime evidence. | Covered |
| “대시보드에서 관리하고 싶어.” | User guide → INSTALL service procedure; explicit startup uses optional Dashboard Skill | Explain UI, inspect services/ports and session root, reuse matching service; start only on explicit service request and verify actual URL/root | Clarify startup only if intent is unclear; explicit startup needs no duplicate permission. Host discovery, approved loopback access and maintained session required. Uncertain discovery blocks a new instance. No Job run/schedule/deploy implied. | Covered, startup intent/access dependent |

Verification was limited to local Markdown targets/anchors (23 files, 155 local links, 19 fragments; zero errors), 27 representative argument contracts accepted by the implementation's parser, and 21 runner help invocations plus Dashboard help (all exit 0). `git diff --check` passed. The target checkout has no `.venv`; help was checked from this code root with an existing installed Python environment, without installing dependencies or initializing runtime here. Product code, Jobs and operational data were not changed. No full regression suite, actual Job run, native scheduling, service startup or real SSH operation was performed. Prior platform verification below remains historical evidence only.

## Historical local candidate validation — Phase 2A

Verified on 2026-11-13 (Asia/Seoul), macOS ARM64, Python 3.9.6, Node 20.11.1. This is a local source candidate, with no Git directory/history, initialization, commit, remote repository, upload or public release. Private hosting is a separate owner action.

## Independent setup and smoke

- Created a new venv outside the source distribution, without the original venv/site-packages/PYTHONPATH, Jobs, env or saved data. Installed only declared manager dependencies from PyPI: ruamel.yaml 0.18.17 and ruamel.yaml.clib 0.2.15. Checked the new environment's metadata/LICENSE files; both are MIT. No dependency binaries are bundled.
- CLI/Dashboard help parsed successfully. A fresh isolated writable root listed 0 Jobs. Registered the original synthetic hello-output example, copied its source, then submitted exactly one Run: succeeded, exit 0, expected stdout, empty stderr, 2 verified records. Filtered saved query returned Alpha total 1; generated standalone HTML from that Output.
- Started only a temporary loopback Dashboard bound to an OS-selected free port and the synthetic root. Verified matching session root, static UI files, Jobs/results/report retrieval, foreign Host and missing-CSRF rejection, Package creation/download/ZIP integrity and manager/LICENSE inclusion. Closed only that test server. Session tokens were held in memory and not persisted.
- A verifier import-scope error interrupted the first Dashboard check after the Job had already succeeded. Fixed the test harness and resumed observation of that same Run; did not resubmit the Job. A new Package after license-notice changes did not overwrite the earlier immutable snapshot.
- No real SSH/remote deployment, native schedule application or external business API call was performed. Tests used fake remote/OS transports, isolated data roots/profiles and offline browser fixtures. Manager/Job credentials were not needed.

## Tests and failures resolved

| Verification | Actual result |
| --- | --- |
| Full Python suite, run once | 201 tests; initially 2 fixture errors, 2 Chrome-environment failures, 5 skips |
| Relevant results/browser modules after fixes | 29 passed, no skips/failures/errors |
| Package/remote mocks/lifecycle/HTTP after license-notice addition | 46 passed |
| Neutral absolute-path fixture follow-up | 8 passed |
| Final status across the same 201 unique Python tests | 197 passed, 4 intentional native opt-in skips, 0 unresolved failures/errors |
| Node UI test suite, run once | 64 passed, 0 skipped/failed |
| Local Markdown link and source allowlist checks | 0 broken links, missing/extra files, symlinks or unexpected binaries |

The fixture errors came from catalog search terms left behind after purpose text was generalized; updated both terms. The initial Chrome checks used a substituted HOME and incomplete Node search path. Rechecking with normal macOS HOME, a direct Node path and fresh temporary Chrome profiles passed all three browser tests, including desktop/narrow UI behavior. No product security check was disabled. These are a full initial run plus targeted follow-ups, not a claim that a second full suite was executed.

The four remaining skips are three native launchd tests and one native Windows Task Scheduler test. Both native opt-in flags remained disabled. Windows behavior uses mocked tests only; Linux local scheduling is unsupported. Actual Windows, Linux installations, other Python versions, real SSH/systemd servers and Safari/Firefox were not tested.

## Security and license checks

The exact 80-file candidate is 71 reviewed source files plus 9 new public files; 31 of the original tracked files were excluded (16 personal Job files, 4 related tests/tools, 11 private development documents/images). Of the 71 retained paths, 49 are unchanged and 22 were generalized or updated. Internal source paths, source hashes, corresponding hashes and reasons are kept outside this public tree.

Gitleaks 8.30.1 was downloaded from its [official release](https://github.com/gitleaks/gitleaks/releases/tag/v8.30.1), with the macOS ARM64 archive SHA-256 checked against the publisher's [asset listing](https://github.com/gitleaks/gitleaks/releases/expanded_assets/v8.30.1). Directory mode with full redaction, decoding and nested archive inspection found 0 items in the candidate, generated synthetic HTML and both synthetic Package archives. A generated noncredential canary triggered detection in a plain file and ZIP, verifying the scanner and archive path; canaries/reports/tools were not copied into this tree.

Additional checks covered all source/docs/tests/HTML/templates, private names and original operational identifiers, home/temporary paths, symlinks, file types, exact allowlist and links. Four credential-assignment candidates were reviewed as synthetic isolated test fixtures (tests/test_execution.py:136,155; tests/test_parameters.py:160; tests/test_parameters_http.py:84). No values are reproduced here. No actual personal Jobs/env/targets/history/runtime/Output/State, old Git metadata, images, binary dependencies or source archives are present. The final synthetic ZIP includes the helper MIT notice. No unresolved P0 finding was identified by these checks.

The owner confirmed publication authority for own code/docs/UI, no additional external rights restrictions, MIT selection and holder name genew. LICENSE reflects that confirmation. Dependency notices are in [THIRD_PARTY_NOTICES](../THIRD_PARTY_NOTICES.md). This is a recorded rights-holder confirmation and dependency license review, not an independent provenance/legal certification of all past authorship.

## Remaining limits and hosting gate

Pattern scanning cannot prove absence of every secret or vulnerability. No dependency vulnerability advisory audit, hostile-local-user penetration test, binary bundle certification or real remote/native platform certification was performed. [SECURITY](../SECURITY.md) describes the single-user arbitrary-code trust model and resource limits.

Linux local scheduling remains unsupported. Remote required_env lacks project_root and fails environment construction; local standard data-path injection/report processing/log-result synchronization are not remotely equivalent. These limits were documented rather than declared fixed. See [remote constraints](packages.md).

The source candidate is ready for owner-reviewed Phase 2B Private registration. Before hosting, recheck the exact files/hashes and choose the repository's private security reporting channel. Before any Public transition, establish that channel, re-scan the then-current tree and obtain explicit owner approval. No Git command that initializes, commits, uploads or rewrites history was run in Phase 2A.
