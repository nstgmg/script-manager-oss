# Script Manager — Agent Instructions

Build reusable deterministic scripts; Script Manager operates them. Natural language describes the purpose, and conventional code implements repeatable work. A Job defines what to execute; its Schedules define when. Multiple Schedules may belong to one Job.

## Start and discover

- Read [README](README.md), [INSTALL](INSTALL.md), [CLI](docs/cli.md), [authoring](docs/script-authoring.md), and relevant source before using an interface. Inspect `python -m runner --help` and subcommand help; do not invent Package/lifecycle/service commands.
- Prefer maintained Python 3.13 for a fresh venv; keep the code minimum at 3.9 unless separately authorized. Follow INSTALL for pip/setuptools bootstrap updates, then `python -m pip install -r requirements.txt` from the code root. Windows uses `.venv\Scripts\python.exe`; POSIX uses `.venv/bin/python`. `--root ROOT` precedes the command and selects writable data, not module search paths.
- Empty installations need no credentials. The network-free [hello-output](examples/hello-output/README.md) example explains registration and first verification. Never overwrite an existing ID.
- CLI is the default. Start Dashboard only on an explicit service request, after checking existing services and session root. Reuse a verified same-root service. Do not restart/terminate existing services or Jobs to fix observation errors. The optional [Skill](.agents/skills/sm-dashboard/SKILL.md) documents the workflow.

## Route natural-language requests

Users should not need to locate technical manuals or memorize commands. Read the relevant documents yourself, explain the next step in plain language, and use the supported interfaces for authorized work.

| User intent | Read or inspect first | Response and action boundary |
| --- | --- | --- |
| “What can this do?” | [Capabilities](docs/capabilities.md) | Explain purpose-based examples, built-in management versus scripts to author, and platform limits. Do not create or run work from a capability question. |
| “How do I use it?” or a desired workflow | [User guide](USER_GUIDE.md), then the linked technical contract | Give a copyable request and propose inputs/results. For new automation, inspect existing Jobs first and follow authoring guidance. |
| Repository URL + installation request | [INSTALL](INSTALL.md), then the installation workflow below | Use an isolated writable location and verify the offline example only within the documented installation scope. |
| Current Jobs, runs, schedules or saved results | [CLI](docs/cli.md), [result queries](docs/result-queries.md), actual local runtime | Use `list`/`get`, `runs`/`logs`, `schedule-status`, or `result-jobs` → `results` as appropriate. Documentation and the public example are not evidence of the user's current Jobs or data. |
| Dashboard management | [User guide](USER_GUIDE.md#dashboard에서-관리하기), [INSTALL service procedure](INSTALL.md#4-선택적-dashboard-시작과-종료) | Explain the UI; inspect and reuse a verified service. Start only on an explicit service request. Read the optional Skill for that request if the host does not discover it. |

If the purpose is unclear, offer a few easy choices such as “create a recurring task”, “see saved results”, or “manage in a browser”; continue independent read-only discovery. Ask only for consequential ambiguity or missing required inputs without safe defaults. “I want daily announcements” leaves source and time unresolved: prepare the script/disabled schedule proposal, then obtain the required execution and activation authorization. Do not infer real collection, active scheduling, service startup or SSH permission from a general goal or a question. An explicit execution/service request is authorization within its scope; do not ask again for already authorized actions. Keep all existing approval, secrets, network and process-preservation rules below.

## Installation request workflow (agent-neutral)

- A repository URL plus an installation request authorizes a new isolated checkout/venv, declared dependencies, lazy initialization with list, and one offline synthetic hello-output registration/run/result check per [INSTALL](INSTALL.md). It does not authorize real Jobs, external collection, native schedules, SSH deployment or Dashboard startup.
- Read INSTALL even when the host does not auto-discover this file. No agent-specific Skill, copied development venv, API key or shell activation is required. Choose a new user-owned directory; preserve existing installations. If required Git authentication, tools or approved network access are missing, report the missing prerequisite; never inspect credentials or bypass restrictions.
- Inspect help and implementation, verify the empty root, copy reviewed example source after create, submit once and retain the Run ID. Verify terminal state/exit code, both logs and two synthetic Output rows (Alpha query total 1). Report actual paths, platform and warnings. Observation failures resume the same Run; do not resubmit.
- Dashboard requires a separate explicit service request; inspect existing services/root and use INSTALL start/stop instructions. Close only a temporary test server whose lifecycle was explicitly authorized. Do not infer service permission from an install request or HTML rendering.

## Author Jobs

- Keep executable code, dependency declarations, README and `job.yaml` in `jobs/{id}/`. Real Jobs are Git-ignored; public examples belong in `examples/` and must use synthetic data.
- Use supported `create`/etag `update` for YAML and edit scripts directly. Preserve existing contracts and worktree changes. Job metadata uses only validated fields; no separate management JSON.
- Propose safe defaults: manual schedules `[]`, 300-second timeout, argv array, standard Output/State paths, bounded input and retries, nonzero exit for required failures. Ask only for consequential ambiguity or required missing inputs.
- Follow [script-authoring](docs/script-authoring.md) for atomic writes, idempotence, logs, failure recovery and verification. Record decisions in existing metadata and the Job README.
- Discover execution inputs only from `get JOB_ID` → `config.parameters`, not script source. Pass declared public types through `--parameters`; never put secrets there. Report the accepted Run's parameters/contract version.

## Execute and observe

- An explicit existing-Job execution request authorizes one submission. Use `run JOB_ID --wait` in a suitable execution environment. Save the Run ID; queued/202 is acceptance, not success.
- Success requires `state: succeeded`, exit code 0, stdout/stderr inspection and expected saved Output. Resume observation of the same Run after a timeout or transport error; do not blindly submit again.
- Restricted agent networking is inherited by detached workers. For network Jobs, use an approved existing resident Dashboard through `run-dashboard` only after session root verification. If unavailable, report access limits; do not start a service or switch to browser automation as a workaround.
- `run-dashboard --run RUN_ID` observes an existing Run. Keep CSRF only in memory, preserve Host/Origin checks and never print session responses/tokens.
- Saved-data questions use `result-jobs` then `results`, with supported filters and pagination. Do not recollect, visit source URLs or search the web without an explicit refresh request. Report collection time, source/Run/path, stale/partial/unknown warnings; do not silently use older data or merge rows.

## Data and secrets

- Use `SCRIPT_MANAGER_OUTPUT_DIR`, `SCRIPT_MANAGER_STATE_DIR`, `SCRIPT_MANAGER_WORKSPACE_DIR` and `SCRIPT_MANAGER_JOB_DATA_ROOT`. Output, durable State and shared Workspace have distinct ownership. Do not edit another Job's results without authorization.
- Read root `.env.example` for names; reuse names where applicable. Real values are registered directly by the user in root `.env`; agents must not read, copy, print or persist them. Declare required names in `required_env`. Do not combine it with legacy `env_file` or create new Job-specific env files.
- `.env.example` contains empty assignments only. Secrets never belong in command/YAML env/parameters, source, logs, fixture, Package or report. stdout/stderr are not automatically redacted. POSIX secret permissions must be 600; Windows needs suitable ACLs.
- Keep credentials-dependent schedules disabled until preflight and an authorized real success verify setup. Never copy runtime, real targets, generated reports, Package/history or user Jobs into the source distribution.

## Approval and boundaries

- Never delete or overwrite an existing Job/Schedule without explicit authorization. Obtain approval for active Schedule changes, destructive cleanup, SSH deployment/rollback and other consequential external writes. Supported Schedule management applies YAML and OS together; inspect observed OS status.
- Package download is an immutable export, not install/run. Use an existing Package ID and matching offline `plan_hash` for authorized SSH deployment. Never replace Packages or erase deployment history. Preview lifecycle candidates; preserve protected releases. Output cleanup moves to trash and does not reclaim disk space.
- No automatic OS scheduling, SSH, deployment, native integration tests or services during routine setup. Tests use isolated roots; native Schedule tests require explicit opt-in and approval. Preserve unrelated processes and data.
- Dashboard is loopback-only, single-user and not a sandbox. Keep security checks intact. Linux local Schedule application is unsupported. Windows and real remote Linux are unverified. Remote `required_env` and standard local runtime paths are not supported; read [packages](docs/packages.md).
- Do not claim unverified platforms or work as successful. Record actual tests/skips and unresolved risks. Source updates use manual reviewed changes per [CONTRIBUTING](CONTRIBUTING.md).
