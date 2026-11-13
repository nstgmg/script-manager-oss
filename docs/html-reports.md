# Standalone HTML reports

Reports are disabled by default. A Job may declare report.enabled, source (relative .json path within managed Run Output), filename (.html basename) and output_dir (default, project-relative, or native absolute directory). Successful local Run completion can generate a report; report failure is separate from business exit status and preserves an existing good HTML.

`python -m runner report-render JOB --source PATH` converts an existing JSON without running/recollecting a Job. --run RUN uses captured report.source. --source and --run are exclusive. Optional --filename/--output-dir override manual output. A relative --source is shell-cwd relative, not --root relative. HTML and its runtime index are written even though input collection is read-only.

Default destination is reports/{job}.html. A neutral absolute example is /example/reports or C:\Reports; use a real local directory you own. Traversal, symlink/junction paths, UNC/device paths, foreign OS absolute formats, managed code/data paths and unrelated file/Job overwrites are rejected. Existing targets must carry the matching Job marker and be single-link regular files. User-chosen external report directories must also be excluded from version control/backups as appropriate.

Input must be UTF-8 regular JSON up to 10 MiB, depth 64, 200,000 nodes. Invalid/nonfinite values fail. HTML embeds original JSON plus CSS/JS; no internet/server/build is required. It supports search, filter, sort, JSON copy, nested navigation and CSV export. Escaping, CSP, safe text rendering and CSV formula-prefix handling are retained. Full original JSON remains sensitive regardless of safe rendering; only synthetic reports belong in public artifacts.

Dashboard GET report metadata, /report/html and /report/download use the last generated report. HTML is served with sandbox CSP. Destination checking and opening the selected folder are existing mutation endpoints requiring CSRF. See [security](../SECURITY.md) and [offline sample](../examples/hello-output/README.md).
