# Script authoring

Read [AGENTS](../AGENTS.md), [CLI](cli.md) and [operations](operations.md). Translate a user's purpose, inputs, required result, success/failure criteria and side effects into deterministic code. Ask only about consequential ambiguity; preserve existing contracts.

Keep code, dependency declarations, README and job.yaml inside the Job directory. Use supported create/etag update for YAML; edit scripts directly. Defaults: manual schedules [], argv command, cwd ., 300-second total timeout, JSON structured Output, stdout progress/stderr errors. Override defaults for demonstrated needs and record why. The manager does not infer or automatically install script dependencies.

Record id/name/purpose, command/cwd/env/timeout in existing YAML; public per-run inputs in parameters; credential names in required_env; requested schedules in schedules. Record schema, sorting, dates, empty/partial results, idempotence, retries, dependency/environment setup and recovery in README. Do not invent YAML fields for business contracts or create separate management JSON.

New scripts must require SCRIPT_MANAGER_OUTPUT_DIR for results and SCRIPT_MANAGER_STATE_DIR for durable checkpoints where needed. Use WORKSPACE_DIR only for shared working files; read other Job results through JOB_DATA_ROOT without modifying them. Do not persist state inside captured source or fall back silently to cwd. The [hello-output example](../examples/hello-output/README.md) is original offline code with synthetic data.

Validate inputs and bounded response/file sizes before work. Write temporary output in the same filesystem, verify schema/counts/completeness, atomically replace final output, then commit checkpoints. Missing/corrupt State must not be silently treated as empty. Idempotent business IDs or destination idempotency keys prevent repeated side effects; a new Run ID is not business deduplication.

For new network read scripts, bound each request (default proposal 30 seconds), input/page counts and total budget. Retry only transient read failures (429/5xx/temporary networking) at most twice after the first attempt, suggested waits 1/2 seconds respecting bounded Retry-After. Authentication/input/schema errors fail immediately. External writes must not be retried without an idempotency/observation contract. These are authoring proposals, not runner config fields. Network access must be explicitly available in the execution environment.

Exit 0 only when all required work and result checks succeed; fail nonzero on required partial failure. A verified empty result may succeed. Record complete=false and safe failure scope for partial Output. Runner has no separate partial-success state, automatic whole-Job retry or distributed transaction. Design interruption recovery around durable state, not termination hooks alone.

Log phase/time/safe identifiers, counts, retries, final status and relative result filenames. Never log secrets or entire raw private responses. stdout/stderr retention is 5 MiB each, no automatic masking or age-based log/snapshot retention. Output lifecycle does not clean logs/State/Workspace. There is no CPU/memory/Output quota.

Before registration/activation validate code and configuration; then verify the authorized Run's state, exit code, both logs and actual result. Check empty/error/retry/duplicate/partial/interrupted cases when meaningful. Do not execute external writes merely as a test. Keep secrets-dependent schedules disabled until an authorized successful real run verifies credentials. Native scheduling/SSH need separate authorization.

Remote helper lacks local required_env root and standard Output/State/Workspace path injection. Do not claim local-only scripts are remotely compatible without a separate implementation and approved validation. See [remote limits](packages.md).
