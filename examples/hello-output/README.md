# Hello Output

Purpose: verify an empty Script Manager installation without internet, credentials, native scheduling or SSH. This is original synthetic example code, not a renamed business Job.

From the code root after [installation](../../INSTALL.md), ensure hello-output is absent. Run `python -m runner create hello-output --file examples/hello-output/job.yaml`; then copy this main.py and README.md into the newly created jobs/hello-output directory. create --file generates default source, so the copy is required. Never overwrite an existing Job to install the example.

Run `python -m runner get hello-output`, then `python -m runner run hello-output --wait` once. Keep the returned Run ID. Expected: succeeded, exit code 0 and stdout `Hello Output: wrote 2 synthetic records to result.json`. `logs hello-output RUN_ID --stream stderr` should be empty. Parameters/required_env are not declared. Schedules are empty and report/auto cleanup are disabled by default.

Output is UTF-8 JSON in SCRIPT_MANAGER_OUTPUT_DIR/result.json. generated_at/collected_at are UTC ISO timestamps, complete is true and records contains alpha/beta in fixed order with id/title/source/status/value. Source is synthetic; status ready means generated successfully, not a real recruitment state. Two records are mandatory; invalid output or missing runtime environment fails nonzero. No durable State, remote fetch or side effect exists. Re-execution writes into a new Run's Output; original results remain.

`python -m runner results hello-output --keyword Alpha --source synthetic --status ready` should return total 1. For HTML, use `python -m runner report-render hello-output --source runtime/job-data/hello-output/output/RUN_ID/result.json` with the actual Run ID, then open the returned reports/hello-output.html directly. No Dashboard is required. It embeds only synthetic JSON, with search/sort/copy/CSV controls.

If --root points elsewhere, the data path starts at that root, while example/code paths still refer to the code checkout. Do not assume relative --source is --root-relative. A missing required runtime path fails explicitly rather than writing into source cwd. See [authoring](../../docs/script-authoring.md) and [results](../../docs/result-queries.md).
