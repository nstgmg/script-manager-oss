# CLI

Use `python -m runner [--root ROOT] COMMAND ...` from the code directory and the installed venv. Global --root comes before COMMAND; it selects data, not Python import search paths. See [installation](../INSTALL.md). Run `python -m runner COMMAND --help` before unfamiliar operations. Results are JSON; handled errors are JSON on stderr. Normal errors/failed runs return 1, argument errors 2. Query success does not mean every listed Run succeeded.

| Command | Supported purpose |
| --- | --- |
| schedule-doctor [--remove LABEL --confirm FINGERPRINT] | read-only native inventory; explicitly confirmed owned orphans only |
| reset [--confirm PLAN_HASH] | preview then permanently clear this installation’s user data after verified OS removal |
| uninstall [--confirm PLAN_HASH] | same safe cleanup, then instructions to exit and manually remove program folder |
| list / get JOB | definitions, normalized config, YAML and etag |
| create JOB [--name NAME] [--file YAML] | reject existing ID, create definition + default main.py/README |
| update JOB --file YAML --etag ETAG | validate and replace complete YAML using latest etag |
| delete JOB --etag ETAG | authorized recoverable Job removal; existing registrations/runs may block |
| run JOB [--wait] [--parameters JSON] | submit once; --wait observes termination |
| runs JOB | history; may recover orphaned records as interrupted |
| logs JOB RUN [--stream stdout\|stderr] [--offset N] | 64 KiB page and next byte offset |
| cancel JOB RUN | authorized cancellation request; observe same Run |
| result-jobs [--keyword TEXT] | discover saved-result purposes and artifacts |
| results JOB | saved-only filters; [query contract](result-queries.md) |
| report-render JOB (--source PATH\|--run RUN) | write standalone HTML; optional --output-dir/--filename |
| schedule-plan JOB [--schedule ID] | offline OS definition plan |
| schedule-status JOB [--schedule ID] | observed platform status |
| schedule-save JOB SID --etag ETAG | --file single-schedule YAML, --create to add, --delete to remove |
| schedule-apply JOB --etag ETAG [--schedule ID] | lower-level authorized OS application |
| schedule-remove JOB [--schedule ID] [--legacy] | authorized OS removal, not YAML edit |
| run-dashboard JOB | client of existing server; --url, --parameters, result filters |
| targets / history JOB | local deployment definitions/receipts, no SSH |
| deploy-plan JOB TARGET --package-id PACKAGE | offline selected-Package plan |
| deploy JOB TARGET --package-id PACKAGE --plan-hash HASH | approved real SSH deployment |
| verify JOB TARGET / rollback JOB TARGET --release RELEASE | real SSH; explicit request required |

There is no dedicated Package create/download, lifecycle, restore or service-management runner CLI. Use the optional Dashboard/existing HTTP API where needed. Do not invent `runner dashboard`, daemon start/stop or an `init` command. `_worker` and `_scheduled` are internal process/OS entry points.

```sh
python -m runner list
python -m runner create my-job --name "My Job"
python -m runner get my-job
python -m runner run my-job --wait
python -m runner runs my-job
python -m runner logs my-job RUN_ID --stream stdout
```

Default create uses empty schedules, cwd `.`, timeout 300 seconds, argv `python3 main.py` on POSIX and the creation interpreter on Windows. --file takes a complete definition matching the ID but still generates default source; place reviewed source separately. Do not overwrite a real Job to install an example. Configuration updates must preserve unrelated fields; use latest etag, not direct writes followed by stale etag. Code/README can be edited directly.

Discover `config.parameters` with get. Only declared public values are allowed; preserve JSON types. POSIX example: `run JOB --wait --parameters '{"count":3}'` only if count is declared. PowerShell quoting differs. Parameters are persisted public metadata, not secrets. See [parameters](run-parameters.md).

For run-dashboard, default URL is http://127.0.0.1:8765, default wait 60 seconds and polling 3 seconds. Verify session root, keep CSRF in memory, submit once. After wait/observation failure use `run-dashboard JOB --run RUN_ID` with saved-result filters; do not combine --run with --parameters. Exit 0 means verified success, 1 failure/observation error, 2 wait limit. Keyword/source/status filter saved results after execution, not script input. See [observation](natural-language-run-latency.md).

Local OS schedule changes require approval. Calendar uses times HH:MM, weekdays Monday=1 through Sunday=7; interval uses interval_seconds instead. Job max 100 schedules, IDs are unique. Windows interval application is 60 seconds–31 days. Linux local application is unsupported. Use schedule-save for YAML+OS together and check loaded/file_matches/desired_matches/observation_error. Host local timezone applies; never infer success from failed OS observation.

## 선택적 Dashboard

Dashboard: `python -m dashboard --root . --port 8765`, only on an explicit service request and after existing service/root checks. Direct HTTP changes require session CSRF and existing Host/Origin policy; never print session responses. Jobs run in captured source and dependencies are not installed automatically.

Queued/202 means accepted. Keep Run ID, verify succeeded/exit 0/logs/Output. Retry observation rather than submission. Restricted agent network limits are inherited by workers; use approved existing resident execution if needed, otherwise report limits. A service is not required for ordinary CLI Jobs, saved results or HTML rendering.

## 초기화와 예약 복구

See [초기화·완전 삭제](uninstall.md) before destructive maintenance. Without --confirm, reset/uninstall are previews. Approval must use the current preview hash; mismatches/blockers abort before native writes. schedule-doctor diagnoses current-user launchd, Windows tasks, or Linux deployment systemd user units without the original project. It never removes healthy/unknown reservations; only one owned orphan is removed with its current fingerprint. First normal CLI use and Dashboard startup report diagnostics without deletion. Linux local Job schedule registration remains unsupported; no SSH is performed for diagnosis or local reset.

Dashboard exposes GET /api/schedule-doctor, GET /api/reset and CSRF-protected POST /api/reset with {"confirm":"PLAN_HASH"}. Failures after approval include phase/deleted/remaining; OS removal failures occur before user data deletion. Locks and installation identity persist through reset. Existing per-Job scheduling APIs retain their checksum/CAS contracts and now verify native removal.

Approved maintenance rechecks the complete target inventory after OS removal (`verify-data-plan`) and removes only approved entries, reporting `deleted_entries` on partial failure. Unconfirmed deployment receipts and applying/degraded schedule operations block cleanup. Current local checksums/installation IDs and actual loaded launchd/systemd invocations are checked; Windows full XML checksums fail closed on export drift. Existing scheduler application/removal/rollback also refuses running native processes and externally replaced definitions. Observer disconnects do not cancel or resubmit reset. See the recovery limitations in [uninstall](uninstall.md).
