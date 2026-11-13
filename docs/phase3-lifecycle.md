# Data and lifecycle

Local runs receive absolute SCRIPT_MANAGER_* paths: JOB_DATA_DIR=runtime/job-data/{job}, JOB_DATA_ROOT=runtime/job-data, OUTPUT_ROOT={job-data}/output, OUTPUT_DIR={output}/{run}, STATE_DIR={job-data}/state, WORKSPACE_DIR=workspace, RUN_ID={run}. Scripts must actually use the variables for data to enter these contracts.

Lifecycle policies live in runtime/lifecycle/{job}.json, not Job YAML. Defaults: package_keep=5, package_auto=false, output_days=null, output_runs=null, output_auto=false, empty pins/rollback_packages. Automatic processing is opt-in and there is no resident cleanup daemon. State/Workspace, arbitrary legacy files, execution logs/source snapshots and detached unrecorded files are not Output retention targets.

Use the Dashboard/Data & Lifecycle or existing `/api/jobs/{job}/lifecycle` GET/PUT, `/cleanup` POST and `/restore` POST. There is no dedicated runner CLI. Preview candidates and match expected selections before approved cleanup. Running Jobs and protected releases prevent unsafe operations.

Package cleanup permanently removes eligible ZIPs only, retains metadata/manifests/receipts and protects pins, rollback selections, current/previous verified target releases and unconfirmed operations. A Package without ZIP cannot be downloaded/deployed. Never manually overwrite immutable Packages or erase history.

Output cleanup moves only registered completed-run Output to runtime/job-data/{job}/trash/{run}. It does not free disk space. Restore preserves original age and the data may qualify again. No permanent-delete/trash purge endpoint or automatic trash emptying is provided. Output selection uses age OR count limits when configured; defaults are unlimited.

Job deletion moves its source/config to runtime/trash but retains Job data and Workspace. Restoring conflicts never overwrite existing Jobs and do not automatically reapply OS schedules. Respect data ownership and explicit approval for deletion/cleanup; keep generated data out of Git and source exports.
