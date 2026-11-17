# CodeQL Critical #169 and #170 — individual source-to-sink review

Review date: 2026-11-18 (Asia/Seoul). Reviewed product source:
`049e9227d3fad16326d5970c77924440cd5f34b4`, VERSION `0.1.1`.
Both alerts use `py/command-line-injection`; their sinks are
`runner/schedule.py:83` and `runner/windows_schedule.py:129` respectively.
The signed-in GitHub UI showed both **Open / Critical** on that exact commit,
with **83 Open / 95 Closed** overall before disposition. The earlier 66/90
record is historical and is not reused as the current count.

**Classification: both reported input-to-command flows are False Positive.**
This conclusion rests on the actual validation, command positions and dispatch
below, not simply the trusted-local model or the absence of a shell. No product
code change is warranted by these two flows. No rule exclusion, suppression,
security-setting change, VERSION change or Release operation is part of this
review. Native Windows functionality and unrelated filesystem findings are
not certified or dismissed by this decision.

## GitHub paths actually inspected

Each alert's Show paths dialog exposed **four available paths, 27 steps each**:

| Source entry | Shared request-data path |
| --- | --- |
| `dashboard/server.py:64`, `do_GET` | dispatch → request reader/JSON body → `body.schedule.id` → Scheduler.save → observed → label → identifier → command argv |
| `dashboard/server.py:67`, `do_POST` | same body/identifier/argv chain |
| `dashboard/server.py:70`, `do_PUT` | same body/identifier/argv chain |
| `dashboard/server.py:73`, `do_DELETE` | same body/identifier/argv chain |

The displayed intermediate locations are `server.py:112,117,124,136,310,313`,
`schedule.py:300,371,94,101,30,32`, and `common.py:58,61`. The final two steps
are `schedule.py:81,83` for #169 and `windows_schedule.py:126,129` for #170.
All four alternatives for each alert were expanded, not only the default path.

The source is the HTTP handler/request object, leading to parsed request data;
it is **not a Job's external API response**. The displayed GET flow also
overapproximates method feasibility: dispatch reads a body only for
POST/PUT/DELETE, and the displayed schedule-create route requires POST.
Actual PUT/DELETE schedule routes still reach the same identifier guard.

## #169: macOS launchctl flow

1. The Dashboard binds loopback. Dispatch verifies exact loopback Host, and for
   mutations verifies Origin and the session CSRF token before parsing a bounded
   JSON object. These controls do not make every local client trusted: another
   local process can obtain a session, so the command-data validation still
   matters independently.
2. The create route requires a schedule object and passes its ID to
   `Scheduler.save`. `save` calls `identifier(schedule_id)` and
   `validate_schedule` before state changes. Job definitions are parsed and
   validated by Store; URL/CLI IDs also pass through the same identifier boundary.
   Etag and existing ownership/running-work guards remain in force.
3. `identifier` requires a string fully matching
   `[a-z0-9][a-z0-9-]{0,62}` and raises on failure. `label` calls it again for
   both Job and Schedule IDs. Thus spaces, quotes, shell operators, slashes,
   backslashes, wildcards, controls, Unicode and leading option markers cannot
   reach this operand. The optional `None` Schedule ID selects the supported
   legacy Job-only label; it is not an unchecked supplied string.
4. The actual reported command is an argv list:

   ```text
   ["launchctl", "print", "gui/<numeric uid>/local.scriptmanager.<root hash>.<job>[.<schedule>]"]
   ```

   Executable and subcommand are fixed by the implementation. The operand
   starts with a generated `gui/<uid>/local.scriptmanager.` prefix and cannot
   become a new option, extra argument or wildcard. The root contributes a
   12-character SHA-256 prefix, not raw root text, to the label.
5. `Scheduler.call` defaults to `subprocess.run`, receives the list unchanged,
   and does not request a shell or executable override. Other macOS callers
   use fixed launchctl operations or `plutil -lint`; generated absolute plist
   paths occupy one argument. Paths containing spaces or apostrophes are not
   concatenated into shell commands. Registration/rollback still performs
   ownership, loaded-definition and idle-state checks.

The CodeQL path visibly carries taint through the full-match guard's returned
value into a fixed-position argv operand. That path does not show a way around
the guard. The specific reason the analysis retains this taint is an inference
about its modeling, not a verified diagnosis of CodeQL internals. Malformed-ID
tests exercise both direct observers and the real Dashboard dispatch/API path
and fail before any native-command callback.

**Decision for #169:** False Positive for the reported command injection.
The caller can request a normal owned schedule operation, but cannot turn its
Schedule ID into an executable, launchctl subcommand or added command option.

## #170: Windows sink and actual Windows dispatch

The four displayed paths are the same as #169 through the **base macOS
`Scheduler.observed` at line 101**, including its `launchctl print` list, but
end in **`WindowsScheduler.call`**. Normal API factory selection returns the
Windows subclass on Windows, where `WindowsScheduler.observed` overrides that
method and uses `_query`. On macOS the factory returns Scheduler and uses its
base call method. The displayed cross-platform edge is not a normal CLI/API
execution path; the tests exercise the actual factory and observed dispatch.

The reachable Windows implementation was also checked independently:

- `_query` constructs
  `["schtasks", "/Query", "/TN", task_name, "/XML"]`. `task_name` independently
  validates both IDs with `identifier` and prefixes them with
  `\local.scriptmanager.<hash>.`. Its user-controlled portion cannot supply
  whitespace, quotes, `/`, `\`, wildcard characters or an option prefix.
  The query fallback uses a fixed CSV listing command.
- Registration constructs
  `["schtasks", "/Create", "/TN", name, "/XML", temporary_path, "/F"]`;
  deletion constructs `["schtasks", "/Delete", "/TN", name, "/F"]`.
  The temporary XML filename is generated under the installation's schedules
  directory; its full path remains one argument. Names come from validated
  generated task names, with receipt/definition comparisons on existing tasks.
- The XML is generated with ElementTree text nodes, not raw XML interpolation.
  Calendar time/day and interval fields are validated, the action is the
  manager interpreter plus fixed `-m runner --root ... _scheduled` arguments,
  and generation is internally generated. The Job's arbitrary command is
  executed later by the reviewed Job runner, not substituted as the manager's
  registration/query executable. `subprocess.list2cmdline` serializes the inner
  Python arguments; paths with spaces remain quoted values. Account/domain
  names are XML text, not schtasks command fragments. Tests preserve literal
  quotation/XML metacharacters without adding XML actions or options.
- The doctor does contain a PowerShell expression for numeric task state.
  Before inserting a task name into its single-quoted literal, it requires a
  **full** `LABEL` match. That grammar allows only the fixed prefix, hex root
  hash and validated ID characters; it excludes quotes, backticks, dollar
  syntax, whitespace and additional path separators. `-TaskPath`, cmdlet and
  switches are fixed. The native tool name is `powershell.exe`, not a supplied
  script. Unsafe names are rejected before the command callback in the test.
- OS-enumerated tasks are queried as names, not evaluated as shell source.
  Unowned/unknown definitions cannot authorize removal; definition/identity
  evidence and final running/ownership checks remain separate requirements.

**Decision for #170:** False Positive for the displayed cross-platform flow;
the real Windows name/argv/XML/PowerShell boundaries also provide no demonstrated
injection from the reported request field. This is a construction/validation
assessment, not a claim that every Windows build's native scheduling behavior
was retested.

## Trust boundaries and executable lookup

| Input | Control and route to management commands |
| --- | --- |
| Direct user CLI/API input | IDs are validated; operations/options are selected by code. Authorized local schedule changes remain normal product functionality |
| Job YAML / Schedule settings | Store validates schema and IDs; trigger values have bounded type/format/range checks. Display names are not command options |
| Dashboard request | Loopback/Host/Origin/CSRF/body checks precede validated Store/Scheduler operations; they are not a multi-user authorization system |
| Job stdout/stderr and saved Output | Read as data/logs/results or report input; no built-in result-to-schedule configuration evaluation was found |
| External API response/file | A Job may explicitly fetch/save it, but the manager does not automatically promote its fields to a scheduler executable, option or reservation ID. The saved-data regression leaves YAML unchanged and makes no scheduler call |
| Internal IDs and arguments | Root hash, numeric UID, fixed tool/subcommand and generated generation; fixed-position IDs pass full-match validation |

Tool **names are fixed but are not pinned to absolute system executable paths**.
The process inherits the operator's environment; PATH and Windows executable
search/current-directory rules therefore remain trust assumptions. A hostile
local actor able to replace a searched executable or control the manager's
working directory can run code with the user's rights. That is a residual
trusted-installation/environment risk, not evidence that an HTTP Schedule ID
or an ordinary external response can change this lookup. The tests do not
certify a hostile PATH or simulate Windows native executable search.

Similarly, a trusted Job deliberately executing response text, modifying the
manager's files or calling its API has the user's OS authority already. Such
explicit Job code needs its own input validation; the manager is not a sandbox.
No new approval enforcement inside arbitrary Python Job code is claimed here.

Relevant primary contracts: [Python subprocess security and argument handling](https://docs.python.org/3.9/library/subprocess.html#security-considerations),
[Microsoft process creation/search](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-createprocessw),
and [Microsoft CRT argument parsing](https://learn.microsoft.com/en-us/cpp/c-language/parsing-c-command-line-arguments).
Windows argument sequences are serialized to a command line; argv plus
`shell=False` alone would not establish safety without the operand restrictions
and tool-specific checks above.

## Verification and disposition record

Actual host: macOS 15.6.1 ARM64, existing CPython 3.9.6 venv. The focused
`tests/test_schedule_command_security.py` adds **nine passing methods** covering
invalid IDs, accepted ID boundaries/legacy labels, Dashboard input rejection,
Host/Origin/CSRF and GET body feasibility, fake native save/observation,
XML/path/account text, PowerShell name validation, default subprocess argv,
and saved external-shaped data without configuration changes.

The related regression command passed **71 tests, 0 failures/errors/skips**:

```sh
env -u SCRIPT_MANAGER_TEST_LAUNCHD -u SCRIPT_MANAGER_TEST_WINDOWS PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B -m unittest -v tests.test_schedule_command_security tests.test_schedule tests.test_multi_schedule tests.test_windows_schedule tests.test_windows_ownership tests.test_windows_ownership_handoff tests.test_schedule_doctor_platforms
```

OS registration/removal calls use in-memory adapters. Existing read-only plist
lint is not native schedule registration. Synthetic temporary data only;
no operating Job, OS schedule, real SSH, resident Dashboard or ACL change.
No full regression/Windows-native campaign was repeated. Windows native
quoting, executable search, Task Scheduler and ACL/filesystem limitations
remain as in [validation](validation.md#v011-pre-release-audit--2026-11-18).

The user authorized evidence-based individual disposition. For each alert,
the appropriate reason is **False positive**, not Won't fix, Used in tests,
or a bulk dismissal. Apply it only after this evidence is committed/pushed
safely and the exact commit's two CodeQL checks finish; if an alert has
automatically become Fixed, do not dismiss it again. The individual GitHub
activity must retain the analyzed SHA, path/guard rationale, test scope and
native/environment limits. The final task report records actual disposition,
the exact pushed SHA and a fresh Critical filter result. This document's
classification alone does not claim that GitHub state has already changed.

No other High finding is reclassified by this review. The two Critical
dispositions can resolve this specific release block once verified, but do
not authorize a Tag/Release or certify zero vulnerabilities.

## Publication status follow-up — 2026-11-18

The preceding investigation and disposition procedure are preserved as the
historical review. During the subsequent publication gate, the signed-in GitHub
UI confirmed [#169](https://github.com/nstgmg/script-manager-oss/security/code-scanning/169)
and [#170](https://github.com/nstgmg/script-manager-oss/security/code-scanning/170)
were **Dismissed**, each with an individual **False positive** activity entry
linking the analysis at `f558ddd95de109227a28275e6e383cc127129373`.
The main-branch Critical filter showed **0 Open / 4 Closed**.
[CodeQL run 44132233156](https://github.com/nstgmg/script-manager-oss/actions/runs/44132233156)
completed successfully for that SHA, with Python and JavaScript/TypeScript
analysis. These observations do not reclassify other open findings or certify
native Windows behavior or zero vulnerabilities. The final documentation
commit's checks and a fresh Critical filter are separate pre-tag gates; this
follow-up does not present historical regressions as final-commit test results.
