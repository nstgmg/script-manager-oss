# Contributing and validation

Read [README](README.md), [AGENTS](AGENTS.md), [architecture](docs/architecture.md) and [authoring](docs/script-authoring.md). Install dependencies in a fresh venv. Node is optional for runtime, required for UI tests. The validated tool versions are in [validation](docs/validation.md). Do not copy an existing venv, user Job, secret, generated HTML, operating logs or real targets into the tree.

```sh
python -m unittest discover -v
node --test tests/test_dashboard_ui.cjs
```

Use the intended venv's Python. Tests create isolated temporary data roots and loopback servers; SSH/systemd/scheduler changes use fakes. Chrome tests use temporary profiles and offline pages. Native launchd/Windows tests are opt-in: leave `SCRIPT_MANAGER_TEST_LAUNCHD` and `SCRIPT_MANAGER_TEST_WINDOWS` unset for normal validation. Do not enable them or use real SSH/OS schedules without explicit authorization. Missing tools and platform skips must be disclosed. Repeat the full suite only after relevant changes/failures justify it.

New examples must be original synthetic code, work offline without API keys, use managed Output and empty schedules, document the result contract and avoid external writes. Tests must verify behavior/failure boundaries rather than mirror implementation. Check YAML through supported interfaces, not direct mutation of existing Jobs. Keep the `runner/`, `dashboard/`, `deployments/` module and Package helper contracts stable unless a separately reviewed change updates them together.

## Manual upstream-to-candidate changes

The initial maintenance direction is manual upstream → candidate. The repositories and histories remain independent. Never mirror, merge histories, auto-sync or recursively copy a working installation. Select only generic source, relevant synthetic tests and public docs. Review each path against an explicit export allowlist and exclude user Jobs, env, targets, runtime, reports, workspace, Packages/history and private development records.

Maintain the mapping of upstream identifiers/hashes, candidate hashes/commits, reason and verification in a private upstream-side ledger. Public documentation must not include private source paths or operational identifiers. Compare against the last accepted hashes before applying changes, resolve conflicts manually, then re-scan and run relevant tests. Record actual results/skips.

Candidate → upstream changes are exceptional, separately reviewed selections. Confirm license authority, compare behavior and user Job contracts, apply only approved core changes, and verify without changing live schedules/data/services. Do not bring candidate test data or Git history back. If the candidate later becomes the common core's source of truth, agree a new policy first; no automatic bidirectional synchronization.

## Contact and security reports

For general questions, contributions, collaboration or licensing inquiries, contact [oss@def-v.com](mailto:oss@def-v.com). Public issues and pull requests may be used for non-sensitive contribution discussions.

Report security vulnerabilities privately to [security@def-v.com](mailto:security@def-v.com), following [SECURITY.md](SECURITY.md#reporting). Do not post vulnerability details in public GitHub issues, pull requests or commits, or send them to the general inquiry address. GitHub Private Vulnerability Reporting is a planned additional channel after the separately approved Public transition and verification; it is not currently active.

## Before hosting

Confirm source/license authority, preserve [LICENSE](LICENSE) and [notices](THIRD_PARTY_NOTICES.md), resolve security findings, check exact candidate manifest, document supported platforms and establish a private vulnerability reporting channel. Local validation does not authorize Git initialization, hosting, upload, release or Public visibility changes. Those are separate owner actions.
