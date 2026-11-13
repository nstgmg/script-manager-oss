# Validation records

Current public/security status and preserved installation checks: [public readiness](public-readiness.md). Focused CodeQL follow-up and alert handling criteria: [CodeQL triage](codeql-triage.md). The Phase 2A section below is historical; its no-hosting statements describe that phase only. Private registration and the Public transition happened later. Those historical platform results are not new verification of Windows, Linux, native schedules or real SSH/systemd.

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
