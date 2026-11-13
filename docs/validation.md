# Validation records

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
