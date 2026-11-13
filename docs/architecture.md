# Architecture

Script Manager operates filesystem-backed Jobs. Agents author scripts; the runner executes and observes them. There is no database, LLM runtime dependency, task queue, resident worker agent or own timer loop.

| Component | Responsibility |
| --- | --- |
| runner CLI / Store / Common | validated YAML CRUD, etag, locks, atomic files, JSON interface |
| Execution / Parameters | captured source/config/input, detached bounded subprocess, log/state tracking |
| Scheduler / WindowsScheduler | OS-owned schedules, application and observed-state checks |
| Results | deterministic saved-file filtering, provenance, collection-time warnings; no recollection |
| Reports + report_template.html | standalone offline HTML, escaping and safe destination checks |
| Lifecycle | standard Output/State/Workspace paths, opt-in retention and protected Packages |
| Dashboard + static files | optional loopback HTTP/UI using the same services |
| Packages | immutable Job archives and helper code, manifests and hashes |
| Deployment client / remote_runtime | explicit SSH and Linux systemd user releases, verification and rollback |

CLI imports Store, Execution and Scheduler; execution also needs Lifecycle and may invoke Reports/automatic policy checks. Dashboard uses the same core services. Package generation imports snapshot helpers and includes runner/common/execution/parameters plus the remote helper. Keep their module layout and bundled helper contract consistent.

Job code lives in jobs/; run snapshots/logs and managed data in runtime/; shared project files in workspace/; default generated HTML in reports/. Data is not source. Real Jobs and mutable data are Git-ignored; only examples and synthetic tests are shipped.

Python and the YAML library run the manager; Node/Chrome are development-only. No frontend build/CDN is needed. Other Job interpreters/dependencies are operator-provided. Schedule definitions retain Python/code/data paths; moving an installation requires reviewed reapplication, not a directory copy.

Local scheduling supports macOS launchd and Windows Task Scheduler, not Linux local application. Remote Linux systemd is a separate path with different credential/data contracts. See [operational contracts](operations.md), [remote limits](packages.md) and [security](../SECURITY.md). No automatic catch-up, cross-host exactly-once guarantee, remote log sync or multi-user isolation is provided.
