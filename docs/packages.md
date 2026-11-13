# Packages and SSH

Package creation is `POST /api/jobs/{job}/packages` or the Dashboard, not a dedicated runner CLI. Lists/details/download use the same base route and `/{package}`, `/{package}/difference`, `/{package}/download`. Mutations preserve Host/Origin/CSRF checks. ZIP export does not install dependencies, execute a Job or register schedules.

Immutable files live at deployments/packages/{package-id}/: ZIP, metadata and manifest with source/runtime file hashes, modes, config, dependency-file names and archive hash. Files are verified before download/deployment. Snapshots include Job source and selected common/parameters/execution/remote helper code. manager/LICENSE preserves the bundled manager code notice; it does not automatically license arbitrary user Job source. Do not manually replace a Package. Read RUNME.md and package.json before using an export; package.json is manager metadata, not npm configuration.

Env files, keys/credential-like names, logs/data/output/cache/runtime/workspace/state and build/dependency artifacts are excluded. Inline env values cause Package creation to fail. Arbitrary hardcoded secrets inside normal files are not detected by these exclusions. Install runtime/dependencies and provide secrets on the destination; they are not bundled or automatically installed. Retention is separate and opt-in: see [lifecycle](phase3-lifecycle.md).

Copy only fictional targets.example.yaml to prepare a real Git-ignored targets.yaml/local file. Fields are version:1, targets → ID → ssh_host/root. Use a prepared ~/.ssh/config safe Host alias and dedicated absolute Linux root. Keys/known_hosts stay outside this distribution. Actual SSH operations require explicit authorization.

`deploy-plan JOB TARGET --package-id PACKAGE` is offline and returns plan_hash. `deploy` requires the same Package and `--plan-hash HASH`; hashes, target and ZIP integrity are rechecked before SSH. No automatic latest-Package selection. SSH uses BatchMode, StrictHostKeyChecking and bounded connection/operation timeouts. Remote paths/ownership/symlinks, file hashes and user systemd unit syntax/state are validated. Receipts are pending/verified/unconfirmed; ambiguous responses require inspection rather than blind resubmission. `verify` and `rollback --release` really connect to SSH.

## Current remote limitations

- Only Linux Python 3.9+ with SSH, systemd user bus/systemctl/systemd-analyze/loginctl and pre-enabled linger is a target. Operators prepare dependencies, accounts, host keys and secrets. No sudo/system setup or dependency installation is automated.
- Remote environment(config, shared) does not pass project_root: Jobs declaring required_env fail remote environment construction. Legacy env_file paths must be provided under the prepared shared directory; do not change local secret policy merely to hide this limitation.
- Remote execution does not inject the local standard SCRIPT_MANAGER_OUTPUT_DIR/STATE_DIR/WORKSPACE_DIR/JOB_DATA_ROOT/RUN_ID set, generate local reports or sync Output/logs. Parameters use declared defaults, not arbitrary remote overrides.
- verified checks files/systemd application, not an actual successful business run. No real SSH/systemd server has been validated for this candidate. Local mocks do not change that status.
- Rollback restores retained code/config/unit files and timer state, not external dependencies, secret values or business data. There is no centralized monitoring/log sync or missed-run replay guarantee.

Keep [security boundaries](../SECURITY.md) intact; do not advertise remote feature parity with local execution.
