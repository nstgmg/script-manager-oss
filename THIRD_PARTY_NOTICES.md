# Third-party notices

The manager's own code/docs use [MIT](LICENSE), following the rights holder's confirmation of publication authority and absence of additional external rights restrictions. No original screenshot, user Job, collected data, dependency binary or browser/OS tool is bundled. Runtime dependencies are installed separately; preserve their upstream notices when redistributing them or derivative bundles.

| Dependency | Reviewed version | License | Source |
| --- | --- | --- | --- |
| ruamel.yaml | 0.18.17 (direct pin) | MIT | [PyPI 0.18.17](https://pypi.org/project/ruamel.yaml/0.18.17/) |
| ruamel.yaml.clib | 0.2.15 baseline; resolved install recorded in validation | MIT | [PyPI 0.2.15](https://pypi.org/project/ruamel.yaml.clib/0.2.15/) |

ruamel.yaml declares ruamel.yaml.clib >=0.2.15 on CPython with Python <3.15. A future fresh install may resolve another clib version; review the actual installed license/notice before redistributing it. Optional upstream docs/jinja2 extras are not required by this manager. See [validation](docs/validation.md) for actual resolved versions.

The reviewed ruamel.yaml notice identifies Copyright (c) 2014–2025 Anthon van der Neut, Ruamel bvba. The reviewed ruamel.yaml.clib notice identifies Copyright (c) 2019–2025 Anthon van der Neut, Ruamel bvba. Their MIT grants require retaining their copyright/permission notices in copies or substantial portions. The full installed LICENSE files accompany the upstream distributions; standalone/vendor/binary redistributions must include the applicable texts and any included component notices. Local verification does not certify every future dependency resolution or bundle.

Python stdlib, Node, Chrome/Chromium, OpenSSH and host scheduling/systemd tools are external runtimes/tools, not copied code here. Their own licenses apply to any separate binary redistribution. There are no npm package dependencies or CDN assets. This notice does not grant rights to external API data, scraped material or arbitrary user Job contents.

License reference: [OSI MIT text](https://opensource.org/license/mit). Maintainers must keep these records accurate for changes and new dependencies.
