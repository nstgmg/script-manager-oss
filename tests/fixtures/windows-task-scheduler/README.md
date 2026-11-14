# Windows Task Scheduler handoff evidence

`handoff.json` preserves three **anonymized** Base64 entries supplied by the owner
in `WINDOWS_TASK_SCHEDULER_HANDOFF.md` on 2026-11-15 KST, for product commit
`d3b20094edfd6affbac1281626f116d17a1c2ccc`. It contains no original account/path
mapping. It is evidence from the owner's Windows run, not a Windows run performed
by this change's author. The attached document's proposed commands are not an
authorization to change schedules or execute native tests.

- `generated-task.xml` was reconstructed after validation with the original
  arguments/metadata; it is **not the exact first /Create submission**.
- `registered-task.xml` is the saved OS export, UTF-8 bytes with a UTF-16 XML
  declaration. It contains 41 CR-CR-CR-LF sequences. Neither the saved file nor
  this fixture is claimed to reproduce the original OS output bytes.
- `registration-state-extract.json` distinguishes the original registration and
  observed snapshots from the **removed** current/cleanup state. The reported
  calendar Run succeeded with exit code 0 and the temporary task was removed.

The per-entry SHA-256/byte counts verify the **anonymized saved bytes**, restored
without newline conversion. Original definition hashes, state.task_sha256,
schedule_hash and etag retained inside the evidence do not hash these anonymized
bytes. The original state.task_sha256 and doctor.definition_hash were equal
(`2d1292d7…`), despite differing pre/post task_definition_hash values
(`62556afa…` versus `6409be6a…`). This establishes that a trusted post-registration
export was already recorded when doctor rejected the pre-registration checksum.

Tests first verify these preserved bytes, parse XML by decoding UTF-8 to a Python
string, and inspect the observed differences. Doctor integration rebinds paths,
namespace and required files to an isolated temporary installation, reserializes
XML, and recomputes its synthetic pre-registration and recorded-export hashes.
Those integration results are **macOS simulation/replay**, not verification of
the original hashes, native registration, SID resolution or the fixed Windows
product. No OS-added field is discarded: later changes to SID, principal/action
context, idle settings, unified engine, defaults, triggers or execution paths
must still fail the complete recorded-export comparison.
