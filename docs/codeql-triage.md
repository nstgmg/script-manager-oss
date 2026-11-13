# CodeQL follow-up and alert handling

Review date: 2026-11-13 (Asia/Seoul). Baseline: public repository `nstgmg/script-manager-oss`, commit `9040b78`. The 155 baseline alerts were 151 `py/path-injection` (High), two `py/command-line-injection` (Critical), one `js/xss-through-dom` (High) and one `py/polynomial-redos` (High).

## Classification and scope

The baseline review classified 146 alerts as false positives under the documented trusted local user/filesystem model, eight report destination alerts as intended behavior, and #1 as requiring performance verification. No exploitable vulnerability was established by that static review. This is not a claim that the project has no vulnerabilities, or authorization to dismiss alerts. The review covered each alert's default CodeQL path and source/sink; not every alternative path was individually expanded.

- Path alerts: follow Job/Run/Schedule/Package ID validation and `contained()`/`safe()` to the actual read, write, rename or unlink. Validate the caller and allowed root, not just the helper's name. Report destinations deliberately allow selected local absolute directories with link, ownership marker and collision protections.
- The 44 remote runtime default paths pass through the test-only transport in `tests/test_dashboard.py`. Real operations cross SSH and validate targets, IDs, relative paths, ownership and hashes. Test injection is not evidence of a public remote endpoint.
- Critical #153/#154: input reaches a subprocess wrapper, but identifiers are restricted, executable/options are fixed and commands use argv without a shell. Review actual platform callers as well as CodeQL's cross-platform approximations. Preserve scheduling behavior.
- #155: the sink is a fixed-origin download `href` property, not HTML parsing. Package IDs are now encoded as a URL component. Normal generated IDs, API route, download filename and ZIP contract are unchanged; malformed IDs remain server-side errors.
- #1: type and 200-byte UTF-8 length checks now precede the unchanged filename regex. All existing character, extension, hidden-name and Windows reserved-name checks remain. Oversized input is rejected before regex evaluation.

## Focused verification

The unchanged regex was measured in separate subprocesses on CPython 3.13.18 and historical 3.9.6 with synthetic repeated `!`, late suffix failure, valid suffix and Unicode failure inputs, from 200 to roughly 1,048,576 characters. Each worker had a two-second CPU limit and four-second wall timeout. For 16-fold input growth from 65,536 to 1,048,576, measured median regex time grew 14.5–16.3-fold across those cases; the largest measurements were 2.6–5.0 ms per match. No superlinear growth or timeout was observed in these families. Finite timing measurements do not prove all runtimes or inputs safe, and Python 3.9 remains EOL. The new length guard bounds regex input independently of that observation.

Before/after validation was compared on 38,344 deterministic synthetic cases (486 accepted, 37,858 rejected), including returned error results, with no differences. Focused tests cover ASCII/multibyte byte boundaries, controls, reserved names, malformed paths, early rejection, report configuration/preview and Package download UI/API behavior. Tests use isolated data roots; HTTP fixtures own temporary loopback servers. No real Job, resident service, native scheduler or remote deployment was operated. The full regression suite was not repeated. Windows native and real Linux/SSH/systemd verification and remote feature limitations remain as documented in [INSTALL](../INSTALL.md) and [packages](packages.md).

## Observed code-commit analysis

The [CodeQL run for code commit eba8dcd](https://github.com/nstgmg/script-manager-oss/actions/runs/43398782562) completed successfully for Python and JavaScript/TypeScript. GitHub showed **154 open / two closed** after the 155-open baseline: [#1](https://github.com/nstgmg/script-manager-oss/security/code-scanning/1) and [#155](https://github.com/nstgmg/script-manager-oss/security/code-scanning/155) were automatically marked Fixed via that commit, while a new [#156](https://github.com/nstgmg/script-manager-oss/security/code-scanning/156) reports the same filename regex at its new line.

The #156 path still contains the preceding UTF-8 byte limit. An imprecise length-guard model is a possible explanation, not a verified diagnosis of CodeQL internals. The unchanged pattern's measured behavior and enforced limit are evidence for review, not grounds for an automatic False Positive dismissal. #156 remains open; no regex rewrite or analysis suppression was added to reduce the count. The documentation commit's exact-SHA analysis must still be checked separately in the task result.

## Alert state policy

1. A classification in this document is separate from GitHub's current open/fixed/dismissed state. Read the completed analysis for the exact pushed SHA and both configured languages. Never infer a count change from a local edit, queued workflow or one completed language.
2. Reevaluate changed sinks and shared validators first. The filename ordering and download URL changes do not justify reclassifying unrelated engine, schedule or SSH code. No query-wide exclusion, suppression or test-directory exclusion was introduced.
3. Leave unresolved findings open until evidence exists. For #1, record the measured runtime/input bounds and the new validation guard, then inspect the actual reanalysis result; do not call finite measurements a universal proof.
4. If a future individual dismissal is approved, record the exact alert ID, rule, analyzed commit, input-to-sink path, enforced validation/authorization boundary, deployment assumptions and residual verification limits in that alert's reason/comment. Distinguish false positive from accepted intended behavior; a trusted-local assumption alone is not a sanitizer.
5. This follow-up performs no manual alert dismissals or bulk state changes. GitHub may automatically mark a finding fixed after completed analysis; report that separately from a manual dismissal. Preserve the prior classification ledger and report actual before/after counts in the task result.

Keep exploit details and real data private through [SECURITY](../SECURITY.md#reporting). Public source availability does not provide authentication, sandboxing or safe multi-user hosting.
