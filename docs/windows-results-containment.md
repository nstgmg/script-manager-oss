# Windows concurrent saved-result metadata containment

Baseline: `d658a3e7ddc448098818915986cdb677b5a85d57`. The owner's Windows
REPORT and test-results.tsv are diagnostic evidence, not operational
instructions. This follow-up concerns Results discovery, not the earlier
sharing/atomic-publication fix in [Windows Run metadata](windows-run-metadata.md).

## Evidence and validation flow

The supplied native report describes Windows 10 build 19045 / NTFS /
CPython 3.12.14. Its ordinary native full suite passed (313 PASS, 50 SKIP),
but concurrent Parameter Run observation failed in four of ten stress runs.
The independent atomic-reader test passed in all ten. The failures were
`Results.runs` warnings with `unreadable_run` / containment refusal, separate
from successful final state persistence and lease release. A diagnostic probe
observed `Path.resolve()` returning an NTFS `$Extend/$Deleted` final name during
replacement. These are externally supplied observations, not Windows tests
executed on this Mac.

Previously, `Results.runs` validated the Job's runs directory, enumerated
32-character lowercase hex Run IDs, then used
`contained(folder, run_id + '/run.json', True)`. That helper rejects lexical
escape and symlinks, resolves the entire path, and checks its relationship to
the base. Resolving the replaceable leaf conflated its transient final object
name with the containment of the stable directory used for opening it.

The new read-only flow is:

1. Keep the existing runs-directory containment and Run ID checks.
2. `lstat` the stable `runs`, Job and Run directories; require directories and
   reject symlinks and every `FILE_ATTRIBUTE_REPARSE_POINT` (0x400), including
   junctions that target another location inside the allowed tree.
3. Apply `contained(folder, run_id, True)` to the stable Run directory. The
   original Job-specific base remains the containment boundary; a resolution
   into another Job is refused too.
4. Append only the fixed `run.json` leaf. Its `lstat` must describe a regular
   file without reparse attributes. Do not resolve that replaceable leaf.
5. Keep the 2 MiB metadata size check, existing delete-sharing `read_json`,
   object/Run ID/Job ID validation, warning contract and ordering.

No `$Deleted` spelling or prefix is accepted as an exception. A stable
directory resolving outside its Job still fails, even if its result contains
`$Deleted`. No change was made to `contained`, atomic writes/native rename,
reader sharing, Run state transitions, leases, query filtering or recovery.
There are no added retries, sleeps or production timeout changes.

## Regression tests

`tests/test_results_metadata_paths.py` adds nine methods:

- Deterministic leaf-final-name injection reproduces the baseline warning
  for both a deleted name and an arbitrary outside name. In-memory loading
  of the baseline source produced the two expected subtest failures; the
  fixed implementation reads the actual regular file without a warning.
- A real replacement immediately after leaf `lstat` yields the complete new
  snapshot, while a held reader retains the complete old snapshot.
- Three simultaneous Results readers race 40 real atomic replacements,
  checking complete Unicode data, version, parameters and contract version.
- Stable-directory resolutions outside the Job, including another Job and
  a deleted directory name, fail before metadata is read.
- Injected reparse attributes on the leaf and all three stable directories
  fail before reading; this works without `Path.is_junction` (Python 3.9+).
- Real leaf symlinks (internal, external, broken) and directory symlinks
  (all three levels, internal/external targets) fail before reading.
- A Windows-only fixture creates real temporary junctions at the three
  directory levels, with internal/external targets, and requires rejection.
  Junction creation errors fail the test; they are not converted to skips.
- Denial, missing metadata, malformed JSON, wrong object/IDs, oversized
  metadata and a directory in place of a regular leaf remain unreadable.

The existing concurrent Parameter Run test still checks success, failure,
timeout and cancellation, saved parameters/version, terminal exit codes,
finished timestamps, worker exit and lease release. No previous assertion
was removed or timeout extended. Fixtures use temporary synthetic roots.

## macOS results — 2026-11-15 KST

Actual host: macOS 15.6.1 ARM64, existing venv CPython 3.9.6,
Node v20.11.1. No dependency or credential changes. Native scheduling opt-ins
and worker tracing were unset for all full/stress validation. Full Python
uses approved loopback/browser access for the existing temporary HTTP/Chrome
fixtures, without starting an operating Dashboard.

| Validation | Result |
| --- | --- |
| Final full Python, `python -m unittest discover -v` | 372 tests: 363 PASS, 9 SKIP, 0 FAIL/ERROR; 48.697s; exit 0 |
| Node UI, `node --test tests/test_dashboard_ui.cjs` | 71 PASS, 0 FAIL/SKIP; 171.713ms; exit 0 |
| Concurrent Results + Parameter Run tests, ten repetitions | 10/10 iterations PASS, 20 test executions, no skips/failures/errors; exit 0 |
| Baseline source replay | Expected two failing leaf-final-name subtests reproduced; fixed version passes |

The ten repetitions include 400 atomic publications / 1,200 concurrent
Results reads, plus 40 Parameter Runs covering ten of each terminal outcome.
This is Mac evidence, not an NTFS stress result. The final full suite includes
the new nine methods and existing desktop/mobile browser, CLI/HTTP, atomic
publication, cancellation/timeout, lifecycle and lease checks. An earlier full
pass also succeeded (372 tests, nine skips, 50.742s); the final run followed
the refinement preserving the exact Job-specific containment base.

Nine final skips: native Windows sharing probe, Windows PowerShell parser,
native Windows ACL readback, native Windows Task Scheduler, the new native
Windows junction fixture, three opt-in launchd tests and opt-in native
maintenance. No existing Windows assertion was disabled. The junction
fixture retains command output as bytes so a Windows console code page does
not introduce a Unicode-decoding failure under Python UTF-8 mode.

Verification logs are local temporary artifacts, not source or operating
data: `sm-results-path-full-python-final.log`, `sm-results-path-node.log`,
and `sm-results-path-stress.log`. `git diff --check` passed. No attachments
or operational logs were copied into the repository.

## Windows follow-up

Reuse the reported NTFS checkout and existing venv. Keep ordinary-user and
agent-sandbox execution contexts separately identified. Preserve the first
full/stress failure evidence and capture OS/build, Python/Node versions,
filesystem, commit, exit codes, per-test outcomes and skip reasons. Do not
change ACLs, Developer Mode, dependencies, real Jobs/schedules or resident
services to make tests pass. Native schedule opt-ins must remain unset.

With those opt-ins unset, run in PowerShell:

```powershell
& '.\.venv\Scripts\python.exe' -X utf8 -m unittest -v tests.test_results_metadata_paths tests.test_results tests.test_atomic_metadata tests.test_metadata_execution
$targetedExit = $LASTEXITCODE
Write-Output ('targeted exit=' + $targetedExit)
for ($iteration = 1; $iteration -le 10; $iteration++) {
    Write-Output ('stress iteration=' + $iteration)
    & '.\.venv\Scripts\python.exe' -X utf8 -m unittest -v tests.test_results_metadata_paths.ResultsMetadataPathTests.test_concurrent_results_readers_during_repeated_metadata_replacement tests.test_metadata_execution.MetadataExecutionTests.test_parameter_runs_save_terminal_states_with_concurrent_observers
    $stressExit = $LASTEXITCODE
    Write-Output ('stress exit=' + $stressExit)
    if ($stressExit -ne 0) { break }
}
& '.\.venv\Scripts\python.exe' -X utf8 -m unittest discover -v
$fullExit = $LASTEXITCODE
Write-Output ('full exit=' + $fullExit)
node --test tests/test_dashboard_ui.cjs
$uiExit = $LASTEXITCODE
Write-Output ('UI exit=' + $uiExit)
```

Require zero `unreadable_run` warnings for ordinary concurrent publication,
complete old/new metadata only, and unchanged terminal state/exit/parameter/
lease assertions in every iteration. Require real junction rejection before
reading at all tested levels, and test symlinks under an already available
privileged/Developer Mode environment separately if ordinary creation gets
WinError 1314. That existing privilege-only symlink skip is an unverified
boundary, not a PASS. Check sharing denial, unsupported rename and corruption
remain explicit errors. Do not infer success from one full-suite PASS or
worker exit alone.

## Remaining security verification gaps

- Native Windows execution was unavailable here. The new real-junction
  fixture and NTFS replacement stress still need the Windows run. Mac
  symlinks and injected Windows attribute flags are separate evidence.
- Actual non-junction reparse tags, mount points, native Windows symlinks
  when privilege is unavailable, ACL/token interactions and filter drivers
  are not covered by native evidence in this change. Generic reparse flags
  are rejected, but simulation does not certify every tag/filesystem.
- Validation and opening are still separate pathname operations. Hostile
  same-user directory/leaf substitution between `lstat`/containment and open
  is not made atomic here. No handle-relative traversal, no-follow open or
  descriptor-bound containment guarantee was added. This existing TOCTOU
  limitation also applies to the size observation versus the opened snapshot.
  The fix distinguishes legitimate regular-file publication from statically
  linked/escaping paths; it is not a hostile-filesystem security boundary.
- Configured roots remain trusted, and regular hard links are not rejected,
  as before. SMB/FAT/exFAT, alternate Windows/Python versions and power-loss
  durability are not established by this Mac verification.

Operating data, reservations, state, output, deployment history and existing
services were not modified. No SSH, push, release or upload was performed.
