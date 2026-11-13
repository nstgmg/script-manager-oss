# Operational contracts

`jobs/{id}/job.yaml` is the single definition. Use `get` to read config/YAML/etag and `create`/`update --file --etag` to validate/write. No database or separate Job management JSON is used. Never overwrite an existing Job. Code and README are agent-editable; Dashboard edits configuration, not code.

```yaml
version: 1
id: sample
name: Sample
description: Synthetic task
command: [python3, main.py]
cwd: .
env: {}
timeout_seconds: 300
schedules: []
```

IDs are lowercase alphanumeric/hyphen, 1–63 characters, matching folder names. Command is 1–100 argv strings; cwd is Job-relative without traversal. Timeout is integer 1–86400. Name is nonblank up to 200 characters. Unknown fields are rejected. Optional fields include required_env or legacy env_file (not both), [parameters](run-parameters.md), [report](html-reports.md), and schedules. YAML is max 128 KiB; aliases/anchors/tags and duplicate keys are rejected.

Schedules each have id/name/enabled/type, calendar times/weekdays or interval_seconds, max 100 per Job. Legacy singular schedule remains readable, cannot coexist with schedules, and supported save handles migration. OS Schedule times use host local time. macOS/Windows user sessions have login/sleep limitations; no exactly-once/catch-up promise. Linux local application is unsupported. Schedule saving checks ownership, etag and real OS status with rollback/degraded reporting. Do not apply/change active schedules without approval.

Execution snapshots normal files with hashes/modes/config; symlinks are rejected. Common dependency/cache/env/key/log files are excluded. Snapshot limits are 100 MiB/10,000 files. Name-based exclusion cannot discover arbitrary embedded secrets. Per-Job run locks prevent simultaneous local manual/scheduled execution; there is no queue or cross-host business deduplication. Captured scripts execute with argv, not an implicit shell; they still have user permissions.

Workers are detached from Dashboard, monitor timeout/cancel and bound logs to 5 MiB per stream. State is queued/running then succeeded/failed/timed_out/cancelled/interrupted. `runs` can repair interrupted metadata. Success requires exit 0 plus actual expected Output checks. Dependencies/interpreters are installed separately; Job venv directories are not included in source snapshots.

Root .env values are read by runner only and required_env passes only declared names. Base OS variables and non-secret env are retained; arbitrary shell secrets are not inherited. The user registers values directly, POSIX permission 600. Legacy env_file is a relative Job file, not new recommended storage. Values are never put in parameters/inline env/command/logs. Logs are not automatically masked.

Standard paths are injected on local execution: SCRIPT_MANAGER_OUTPUT_DIR, STATE_DIR, WORKSPACE_DIR, JOB_DATA_ROOT, JOB_DATA_DIR, OUTPUT_ROOT and RUN_ID. State and Workspace are not managed Output. [Lifecycle](phase3-lifecycle.md) handles registered Output/Package retention only. Job deletion moves source/config to trash but preserves managed data; restore conflicts never overwrite an existing ID and do not automatically re-register schedules.

Remote Linux uses independent releases, shared logs, immutable Package helpers, user systemd units, checked activation and receipts. It does not have the same local credential/data contract. [Package and remote details](packages.md) and [security](../SECURITY.md) are authoritative for these limits. Do not equate file/systemd verification with business execution success.
