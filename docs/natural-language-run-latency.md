# Resident execution observation

The calling agent translates natural language into a selected Job and declared public parameters. The optional `run-dashboard` client verifies an existing server's session root, identifies the Job, submits once, observes the same Run and returns bounded stdout/stderr plus filtered saved results. It does not start/restart a service or bypass agent network restrictions.

Use a verified loopback HTTP URL with explicit port. Proxy/redirect forwarding is not used. Keep CSRF in memory; never print session headers/tokens. queued/HTTP 202 is accepted, not success. Events reflect observed states/timestamps, not invented progress counts.

Default wait is 60 seconds, polling 3 seconds; a client wait limit is not Job timeout/cancellation. Keep run_id and use `run-dashboard JOB --run RUN_ID` with the same filters after observation loss. --run cannot accept --parameters. If POST response was ambiguous, inspect existing Run evidence before choosing an ID; never blindly submit twice. GET failure may be retried for the same Run.

Keyword/source/status filter saved results after execution. They do not set script inputs. `--parameters` uses declared config.parameters. Success requires succeeded/exit 0/logs/result evidence. The CLI returns exit 0 for verified success, 1 for failure/observation error, 2 for wait limit. HTML/result errors do not justify rerunning completed work.

No personal timing/production Run evidence is shipped. Local validation uses isolated synthetic Jobs and records actual results in [validation](validation.md). When approved resident access is unavailable for a network Job, report that limit rather than starting a restricted worker or using browser automation as a workaround.
