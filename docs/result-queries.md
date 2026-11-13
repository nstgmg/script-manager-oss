# Saved-result queries

Queries never start Jobs, recollect data, visit original URLs or search the web. Discover purposes/artifacts with `result-jobs --keyword TEXT`, then use `results JOB`. Relative dates are interpreted by the calling agent in the user timezone. New data collection requires an explicit request.

| Option | Meaning |
| --- | --- |
| --keyword TEXT | repeatable AND, case-insensitive substring |
| --status VALUE / --source VALUE | existing vocabulary, use returned available values |
| --from DATE / --to DATE | inclusive collection-date bounds by default |
| --date-field FIELD | existing dot path; default collected_at |
| --timezone NAME | default Asia/Seoul; platform timezone DB limits apply |
| --stale-hours N | default 24; disclosure threshold, not a refresh schedule |
| --run RUN / --all-runs | particular snapshot / separate historical snapshots, exclusive |
| --file PATH | selected result filename or permitted project-relative artifact |
| --limit N / --offset N | default 20/0; max limit 200 |

Example: `results hello-output --keyword Alpha --status ready --source synthetic`. The bundled example writes result.json with records. Adapters support JSON arrays/single objects and records/results/items envelopes, grouped announcements for compatibility, JSONL/CSV and text. These are format adapters, not dependencies on real business Jobs. The generic distribution has no personal legacy-file mappings; compatibility-map tests inject synthetic paths only.

Read total/has_more/offset; do not present one page as all rows. Default selection uses the latest completed saved snapshot, including failed/partial evidence. Do not silently substitute older results when the current snapshot is empty or has no matches. If the latest execution has no Output and older saved results are selected, disclose the returned warning.

Report collection time distinct from query time, Job/Run/result path and original URL if stored. Handle stale_data, unknown_collection_time, partial_result, no_saved_results and no_matches explicitly. Stored status reflects collection time, not current eligibility/status. Reconcile matches minus exclusions minus explicitly merged duplicate rows against displayed rows, accounting for pagination; record IDs/reasons. Literal keyword matches are not semantic relevance or proof of eligibility.

Queries preserve Output/State/Workspace and use common deterministic filtering. Do not manually filter full files or import Job source for a simple lookup. Run inputs are discovered through config.parameters; query filters are not script input. See [CLI](cli.md).
