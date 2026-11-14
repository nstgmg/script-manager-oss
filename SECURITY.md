# Security model

Script Manager is for a trusted local user running reviewed Jobs. Jobs execute arbitrary programs with that user's OS permissions; there is no isolation sandbox, multi-tenant authorization, CPU/memory quota or disk quota. Do not run untrusted Jobs or expose the Dashboard through public bindings, proxies or port forwarding.

The Dashboard binds only 127.0.0.1. Host validation, same-origin mutation checks and a random session CSRF token protect browser interactions. They are not user authentication: another local process able to reach loopback can fetch a session. GET responses may expose paths, configs and logs. Do not weaken these checks.

Job/Schedule IDs and file paths are validated. Relative paths reject traversal/symlinks, YAML rejects anchors/aliases/tags, writes use locks/etag/atomic replacement, and reports have additional junction/hardlink/ownership checks. Advisory locks and check-then-use validation do not defend against a hostile account controlling the same filesystem. Use private, user-owned directories and suitable Windows ACLs.

Local data-directory creation keeps POSIX `0700` (subject to umask) and existing directory permissions. On Windows it uses normal parent ACL inheritance instead of Python 3.13's protected `0700` DACL, so the intended user's sandbox and ordinary processes can share access allowed by that parent. This does not grant Everyone access or change existing ACLs. The installation/data root must already have a private ACL limited to the intended user, required sandbox identities and necessary system/administrative principals; a broadly shared parent is not made private by this policy. Permission denial stops the operation without an ACL-reset/elevation fallback. See [Windows ACL diagnosis and recovery](INSTALL.md#windows-런타임-acl-복구). POSIX atomic file modes, secret preflight, Package read-only files and the Linux-only remote helper's permissions are unchanged.

Keep secrets only in root .env and allowlist their names with required_env. Never submit credentials as parameters, inline env, command arguments or source. Run metadata retains public inputs; stdout/stderr are not automatically masked. Snapshot/Package filename exclusions cannot discover arbitrary hardcoded values. Generated HTML embeds full JSON and is sensitive whenever its input is sensitive.

SSH uses BatchMode, strict host checking, safe aliases/paths, selected immutable Packages, hashes and reviewed plan hashes. Host keys, dedicated accounts, dependencies and Linux user linger are prepared by the operator. Hashes detect differences; they are not publisher signatures. Deployment verification is not a successful business run. Never deploy without explicit approval. See [remote limits](docs/packages.md).

Local logs are bounded to 5 MiB per stream; YAML to 128 KiB, HTTP mutation bodies to 256 KiB, source snapshots to 100 MiB/10,000 files and report JSON to 10 MiB. HTTP worker concurrency and disk/CPU/memory consumption are not globally capped. Avoid public-server use.

## Reporting

The official confidential vulnerability reporting channel is [security@def-v.com](mailto:security@def-v.com). The maintainer has verified external sending and receiving for this address. Use [oss@def-v.com](mailto:oss@def-v.com) for general, contribution, collaboration and licensing inquiries; keep vulnerability reports on the security channel. **Do not post vulnerability details in public GitHub issues**, pull requests or commits. Never include real credentials or user data in a report.

The repository is **Public**. GitHub **Private Vulnerability Reporting** for `nstgmg/script-manager-oss` is **enabled**, as observed in GitHub Security Overview on 2026-11-13. It is an additional confidential channel; [security@def-v.com](mailto:security@def-v.com) remains available as the email channel and fallback. Public source availability does not make the Dashboard a public or multi-user service.

For either channel, include the affected commit/version and file/line, impact, prerequisites, and a minimal isolated reproduction using synthetic data. Submit no real secrets or attacks against real deployments.

To report through GitHub, open this repository's **Security and quality → Advisories → Report a vulnerability** and use the private reporting form. A GitHub account is required. The Enabled setting has been checked; this follow-up did not submit a test report or verify a non-admin account's complete reporting workflow.

If the button is missing or the GitHub form is unavailable, email [security@def-v.com](mailto:security@def-v.com) directly. Do not use a public issue as a vulnerability reporting fallback.

## Maintainer reporting checks

GitHub allows owners/admins to enable private vulnerability reporting on **Public** repositories; SECURITY.md does not enable it. Follow the official [repository configuration instructions](https://docs.github.com/en/code-security/how-tos/report-and-fix-vulnerabilities/configure-vulnerability-reporting/configure-for-a-repository) and [reporter instructions](https://docs.github.com/en/code-security/how-tos/report-and-fix-vulnerabilities/report-privately).

- Keep the verified security email monitored and identify the repository owner/admin responsible for confidential triage. Review [current status and historical checks](docs/public-readiness.md).
- Keep Private Vulnerability Reporting enabled. Verify the **Report a vulnerability** button and form from a non-admin collaborator/researcher view without submitting a fabricated vulnerability. This workflow check remains distinct from observing Enabled.
- Confirm the responsible maintainer's **Watch → Custom → Security alerts** (or All Activity), notification delivery and access to incoming private reports. No notification settings were changed by this follow-up.
- Verify Dependency graph, Dependabot security updates, secret scanning/push protection and code scanning settings against the [current checklist](docs/public-readiness.md#현재-운영-확인). Do not infer protection from Public visibility or a related Enabled feature alone.
- If GitHub reporting becomes unavailable, keep the email fallback accessible, correct the instructions and resolve the channel before making an operational-ready claim.

## Disclosure and support

The repository owner is responsible for monitoring the security mailbox and incoming GitHub private reports, acknowledging receipt, assessing impact/reproducibility, coordinating fixes and agreeing disclosure with the reporter. Confirmed credential exposures require the credential owner to revoke/rotate the credential directly. Keep exploit details private during triage; publish an advisory with affected/fixed commits and mitigation when ready, crediting the reporter only with consent. Do not promise a fixed disclosure date before triage.

Triage targets the latest `main` source commit. There are no releases or guaranteed backports to older commits. No fixed response, remediation or disclosure deadlines, or contractual response SLA, are promised. Maintained CPython is recommended for new installations; Python 3.9 compatibility records are historical and are not a security endorsement. [Validation](docs/validation.md) and [public readiness](docs/public-readiness.md) distinguish tested features from unverified platforms. Native schedules and real SSH/systemd require separately authorized environment verification.
