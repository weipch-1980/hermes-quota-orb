# Hermes Quota Orb v0.3.1

A local-first Hermes Desktop plugin that shows:

- a third-generation emerald crystal quota orb with a double-layer thick-glass shell, dual-track refraction, Fresnel edge light, specular reflection, caustics, rising micro-bubbles, and two asymmetric ocean-like water waves inside Hermes;
- a compact status-bar chip;
- current-session and current-day Token usage;
- provider-reported remaining quota and reset times;
- a three-state profile-scoped language selector: Auto, 中文, and English;
- local usage grouped by the active customer profile, provider, and model;
- a once-per-day usage report (18:00 local time by default).

Quota Orb is an independent community project and is not an official Nous Research or Hermes product.

![Quota Orb preview](docs/quota-orb-preview.png)

![Hermes](https://img.shields.io/badge/Hermes-v0.20.0%2B-gold)
![Quota Orb](https://img.shields.io/badge/Quota%20Orb-v0.3.1-emerald)
![License](https://img.shields.io/badge/license-MIT-blue)

## Data sources

| Display | Source | Semantics |
|---|---|---|
| Current session | Hermes `session.usage` RPC | Live session input/output totals |
| Today | Local Hermes `state.db` | Persisted sessions grouped by provider and model for the active profile |
| Account quota | Hermes `agent.account_usage` | Exact only when the provider exposes an account-usage API |
| Daily report | Local plugin timer/storage | Once per local day at/after the configured hour and once per active profile |

Supported exact account sources in Hermes v0.20.0 include OpenAI Codex OAuth, Anthropic OAuth, and OpenRouter. Unsupported or unreachable providers degrade to “quota unavailable”; local Token statistics continue working.

## Security boundary

The renderer JavaScript never reads OAuth tokens, API keys, `auth.json`, or environment credentials. It calls a namespaced, read-only local backend route:

```text
GET /api/plugins/quota-orb/snapshot
```

That backend delegates authentication and quota retrieval to Hermes's existing provider adapters. Runtime desktop plugins execute with renderer permissions, so inspect third-party forks before installing them. See [SECURITY.md](SECURITY.md) for the reporting policy.

## Install the Skill

The distributable Hermes Skill is under [`skill/quota-orb`](skill/quota-orb). From GitHub, install it directly with:

```bash
hermes skills install weipch-1980/hermes-quota-orb/skill/quota-orb
```

To install from a local checkout, first review the dry-run plan:

```bash
python skill/quota-orb/scripts/install.py
```

The installer labels each destination `new`, `identical`, or `conflict`. Dry-run mode never writes. Applying is fail-fast: if any destination exists with different bytes, it raises `FileExistsError` before writing any destination, so there is no partial copy:

```bash
python skill/quota-orb/scripts/install.py --apply
```

Resolve a conflict or explicitly approve replacement with `--force`:

```bash
python skill/quota-orb/scripts/install.py --apply --force
```

`--force` is the safety boundary for overwriting existing conflicting files; it is never implied by `--apply`, and dry-run mode remains non-writing even when `--force` is supplied.

Path safety is not forceable: the installer rejects symlinks, Windows junctions/reparse points, and any source or destination that resolves outside the Skill or `HERMES_HOME` root.

After reviewing and applying the four destinations, enable the read-only Python backend:

```bash
hermes plugins enable quota-orb --no-allow-tool-override
```

Restart Hermes Desktop once (the Python API is mounted when the Desktop backend starts), then run **Reload desktop plugins** if the orb is not already visible.

> Enabling a Python backend and restarting Hermes are separate system changes. Review the files first and obtain the appropriate approval in managed environments.

## Build the release package

The standard-library-only builder creates a reproducible package rooted at `quota-orb/`, plus its SHA-256 sidecar. The CLI defaults to `dist`:

```bash
python scripts/build_skill_package.py
```

Outputs:

```text
dist/quota-orb-skill-v0.3.1.zip
dist/quota-orb-skill-v0.3.1.sha256
```

The archive contains only `skill/quota-orb` content, in sorted order with fixed timestamps; `__pycache__` directories and `*.pyc` files are excluded.

## Artifact Attestation

For `v0.3.1` and later, pushing a release tag triggers native GitHub Actions CI: the runner tests the checked-out tag, builds the ZIP and SHA-256 sidecar once, verifies the tag against the builder version and the sidecar against the ZIP, attests that CI-built ZIP, then creates the GitHub Release with those same two assets. Any integrity-gate failure stops before attestation or publication.

The existing `v0.3.0` Release remains unchanged and has no Artifact Attestation; this workflow never rebuilds or modifies historical releases. Verify a downloaded release ZIP with:

```bash
gh attestation verify <zip> -R weipch-1980/hermes-quota-orb
```

## Repository layout

```text
desktop-plugin/plugin.js                    Tested renderer source
hermes-plugin/dashboard/plugin_api.py       Read-only quota/daily-usage API
hermes-plugin/dashboard/manifest.json       Backend manifest
skill/quota-orb/                            Distributable Hermes Skill
skill/quota-orb/assets/                     Installable copies of the sources
scripts/build_skill_package.py               Reproducible release builder
tests/                                      Standard-library test suite
docs/quota-orb-preview.png                  Release preview image
```

## Test

No test-only packages are required beyond Hermes's normal Python environment:

```bash
python tests/test_plugin_api.py -v
python tests/test_plugin_contract.py -v
python tests/test_installer.py -v
python tests/test_skill_package.py -v
python tests/test_release_package.py -v
node --check desktop-plugin/plugin.js
```

## Known limits

- The orb floats inside Hermes Desktop, not above every Windows application.
- The runtime contribution is scoped as `quota-orb:orb`; plugin CSS removes only that pane's card/header chrome and does not alter other Hermes panes.
- The default report is time-based (18:00 local), not tied to OS shutdown.
- Today's aggregate assigns a whole session to the day it started; it does not split a session across midnight.
- Provider subscription quota, local Token totals, API rate-limit headers, and model context-window usage are different metrics.
- Providers without an account-usage API cannot expose an exact remaining subscription quota.
- The real liquid level uses the lowest provider-reported remaining window. Unsupported providers display neutral glass, never an invented fill level.

## Support and commercial integration

Use GitHub Issues for reproducible bug reports, feature requests, installation support, or commercial integration enquiries. Do not include credentials, private configuration, or undisclosed vulnerability details. Private vulnerability reporting guidance is in [SECURITY.md](SECURITY.md).

## License

MIT — see [LICENSE](LICENSE).
