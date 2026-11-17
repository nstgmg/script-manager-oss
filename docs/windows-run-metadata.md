# Windows Run metadata: sharing and atomic replacement

**Scope of this historical record:** the sharing/atomic-publication change
below predates the handle-relative NTFS backend in `c4a616d` and approval
metadata follow-up in `75b4539`. The current Results reader uses that backend;
the common atomic reader/publisher still has the sharing/rename contract
described here. See [current Windows requirements](../INSTALL.md#windows-파일시스템과-원자-저장-요구-사항)
and [validation scope](validation.md#v011-pre-release-audit--2026-11-18).
Original failures, counts and pending native checks are preserved below and
are not evidence of a latest-commit Windows pass.

## Evidence

Baseline: `1cc0d369ce54a6bfeedc9288e9af378548f88090`. The supplied Windows phase 2
report and full/trace logs describe Windows 10 build 19045, CPython 3.12.14.
They are diagnostic evidence, not instructions to execute their commands or
change the host environment.

The trace shows `PermissionError: [WinError 5]` at `os.replace()` during
running/heartbeat and terminal `run.json` saves. Another observer fails inside
`read_json` with `PermissionError`. Dead workers can leave a last saved
`running` record; others save `failed` without a script exit code after a
heartbeat error. Worker exit 0, parameter acceptance and script stdout alone
do not prove terminal Job success.

The supplied held-reader probe reproduces replacement denial. This establishes
a sharing conflict, but does not identify the original blocking process/handle
or exclude ACLs, antivirus or third-party handles. Other full-log failures are
not all proven to have this cause.

## Filesystem contract

| Platform | Read | Write/publish |
| --- | --- | --- |
| macOS/POSIX | Ordinary UTF-8 read; open descriptors retain the old inode after replacement | Same-directory unique temporary file, permissions, flush/fsync, close, `os.replace`, directory fsync |
| Windows | `CreateFileW`: `GENERIC_READ`, `FILE_SHARE_READ \| FILE_SHARE_WRITE \| FILE_SHARE_DELETE`, `OPEN_EXISTING`; non-inheritable handle transferred to a CRT descriptor | Same-directory unique temporary file, flush/fsync, close, `SetFileInformationByHandle(FileRenameInfoEx)` with `REPLACE_IF_EXISTS \| POSIX_SEMANTICS` |

In [CPython 3.12.14](https://raw.githubusercontent.com/python/cpython/v3.12.14/Modules/posixmodule.c),
Windows `os.replace` calls `MoveFileExW` with `MOVEFILE_REPLACE_EXISTING`.
The ordinary CRT reader omits delete sharing. Sharing checks are bilateral:
an existing reader can deny a rename's delete access, and an incoming reader
must allow any delete access already held by a writer.
[Microsoft's CreateFileW contract](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew)
includes rename in delete access. Reader sharing must allow this access in
both directions without granting write/delete access to the reader or
bypassing ACLs.

Sharing alone is insufficient: legacy replacement can deny an already-open
target even when it allows delete sharing. Microsoft's
[extended rename contract](https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/ntifs/ns-ntifs-_file_rename_information)
explicitly supports replacing an open target with POSIX semantics while old
handles retain their data and new opens see the replacement. Windows writes
therefore use that native operation as well as compatible reader sharing.
The native rename opens the closed, fsynced temporary source with DELETE
access and closes that handle on success or failure. The buffer uses fixed
32-bit fields, native HANDLE alignment, an absolute UTF-16 destination and
byte length, including correct surrogate-pair handling. Neither ignore-readonly
nor ignore-sharing/security flags are used.

`runner.common.open_atomic_read` implements the platform distinction.
`read_json` uses it and closes the descriptor even on parse errors. Saved-result
discovery also uses `read_json` instead of its separate `Path.read_text` for Run
metadata. Execution, lease, maintenance and lifecycle readers already use the
common reader. UTF-8 decoding is explicit, independent of the Windows locale.
Result queries remain read-only: no sidecar files or state recovery are added.

[CRT ownership](https://learn.microsoft.com/en-us/cpp/c-runtime-library/reference/open-osfhandle?view=msvc-170)
passes to the fd on successful `open_osfhandle`; conversion failure closes the
native handle. Pointer-width HANDLE signatures and thread-local Win32 error
capture avoid truncated handles and lost error codes. Python closes the fd.

Readers see complete old or new snapshots. This does not serialize multiple
writers or make read/modify/write transactional; existing Job locks/leases and
terminal-state rechecks still govern Run ownership. No new Windows power-loss
or network-filesystem durability guarantee is made.

There is no retry, fallback overwrite, added delay, raised timeout, ACL change
or error-to-success conversion. Missing files retain the default contract;
permission errors and malformed JSON propagate. External handles without
compatible sharing can still deny a read or replacement. Windows must support
`FileRenameInfoEx` POSIX replacement (the target baseline is Windows 10 build
19045 with a compatible local filesystem). Older OSes or unsupported
filesystems return their native error without falling back to legacy rename,
unlink or copy. Compatibility on FAT/exFAT, SMB and other filesystems is not
established. Persistent terminal save denial still prevents a terminal record;
normal orphan observation must
classify that as interrupted once worker protection is released.

`Execution.worker` imports `Lifecycle` before its first running save. If that
save fails, finalization can record the original failure and call automatic
lifecycle without an unbound-local secondary error. A real lifecycle failure
remains a separate `lifecycle_error`. Failed terminal publication still raises
and prevents automatic cleanup.

## Regression coverage

- A held reader retains the exact old JSON across replacement while a new
  reader sees the new JSON. Reader descriptors are non-inheritable.
- Three independent processes hold old readers across 40 replacements and
  validate complete Unicode payloads after each publish.
- Native Windows probe asserts that both CRT and delete-sharing readers deny
  legacy replacement. The held-reader tests assert successful native
  publication when run on Windows. A DELETE-access handle also probes the
  opposite read conflict and the new reader. Only the native probe is
  platform-gated on Mac; its native outcome is pending.
- Portable Win32 API simulations verify read-only access, sharing flags,
  Unicode, pointer-width handles, ownership transfer, rename buffer/flags,
  platform dispatch and error cleanup. Access/sharing/unsupported errors
  propagate without retry or legacy fallback. These simulations
  do not establish Windows execution success.
- Real detached Parameter Runs succeed, fail with exit 7, time out and cancel
  after readiness under two concurrent execution/result observers and a held
  reader. Assertions cover saved inputs/version, terminal state, exit code,
  finished timestamp, worker termination, lease release and stable subsequent
  observation. Existing CLI/HTTP/Dashboard contracts remain tested.
- Fault injection covers initial running save, heartbeat, final publication,
  lifecycle failure, original-byte preservation and error propagation without
  retry. Fixtures use temporary synthetic roots, never operating data.
- Existing report atomic-publication tests instrument the platform dispatch
  instead of `os.replace`, retaining their preservation/order/failure assertions
  on both backends.

## macOS validation

macOS 15.6.1 ARM64, existing venv CPython 3.9.6 and Node v20.11.1. Dependencies
were unchanged. Real scheduler opt-ins and worker trace were unset.

| Validation | Result |
| --- | --- |
| Full Python, `python -m unittest discover -v` | 363 tests: 355 passed, 8 skipped, 0 failures/errors, 48.285s, exit 0 |
| Node UI, `node --test tests/test_dashboard_ui.cjs` | 71 passed, 0 failures/skips, 123.959ms, exit 0 |

The final suite includes 16 new test methods. Desktop/mobile browser checks,
CLI/HTTP Parameter Runs, Dashboard observation, reports, maintenance and
multi-schedule regressions passed on Mac. This is not native Windows evidence.

Eight Mac skips: the new native Windows sharing probe, Windows PowerShell
parser, native Windows ACL readback, native Task Scheduler, three opt-in
launchd tests and opt-in native maintenance. The sharing probe runs normally
on Windows; it has no privilege-dependent or error-dependent skip.

The first sandboxed full attempt failed because loopback bind was denied and
Chrome could not run. It also exposed a wrong callback index in the new
heartbeat fault-injection fixture, which was corrected. Full validation then
used approved local server/browser access; the failed attempt is not counted
as a successful run. No operating Dashboard was started or changed.

## Windows validation pending

No Windows host was available for this change. Native sharing/error/handle
behavior, `FileRenameInfoEx` support on the target filesystem, simultaneous
read/replace stress, Job Object cancellation/timeout,
Parameter CLI/HTTP Runs, terminal persistence, and phase 2 maintenance,
multi-schedule and report failures require a Windows rerun. Mac/API-simulation
success does not establish Windows PASS. No previously failing Windows case is
newly skipped on Windows.

Reuse the checkout and existing venv; preserve ACLs, Developer Mode,
credentials, operating Jobs/schedules and existing Dashboard processes. With
real scheduler opt-ins unset, PowerShell commands use temporary test roots:

```powershell
$env:PYTHONUTF8 = '1'
& '.\.venv\Scripts\python.exe' -X utf8 -m unittest -v tests.test_atomic_metadata tests.test_metadata_execution
$metadataExit = $LASTEXITCODE
Write-Output ('metadata exit=' + $metadataExit)
& '.\.venv\Scripts\python.exe' -X utf8 -m unittest discover -v
$fullExit = $LASTEXITCODE
Write-Output ('full exit=' + $fullExit)
node --test tests/test_dashboard_ui.cjs
$uiExit = $LASTEXITCODE
Write-Output ('UI exit=' + $uiExit)
```

Preserve the ordinary full run first. If failures remain, follow the separate
worker trace procedure in [phase 2](windows-regression-phase2.md), adding
`tests.test_metadata_execution` when tracing its workers. Never resubmit
operating Runs or turn failed native assertions into skips.
