# Hermes Quota Orb

A local-first Hermes Desktop plugin that shows:

- a draggable floating quota orb inside Hermes;
- a compact status-bar chip;
- current-session and current-day Token usage;
- provider-reported remaining quota and reset times;
- a once-per-day usage report (18:00 local time by default).

![Hermes](https://img.shields.io/badge/Hermes-v0.20.0%2B-gold)
![License](https://img.shields.io/badge/license-MIT-blue)

## Data sources

| Display | Source | Semantics |
|---|---|---|
| Current session | Hermes `session.usage` RPC | Live session input/output totals |
| Today | Local Hermes `state.db` | Persisted sessions that started during the local day |
| Account quota | Hermes `agent.account_usage` | Exact only when the provider exposes an account-usage API |
| Daily report | Local plugin timer/storage | Once per local day at/after the configured hour |

Supported exact account sources in Hermes v0.20.0 include OpenAI Codex OAuth, Anthropic OAuth, and OpenRouter. Unsupported or unreachable providers degrade to “quota unavailable”; local Token statistics continue working.

## Security boundary

The renderer JavaScript never reads OAuth tokens, API keys, `auth.json`, or environment credentials. It calls a namespaced, read-only local backend route:

```text
GET /api/plugins/quota-orb/snapshot
```

That backend delegates authentication and quota retrieval to Hermes's existing provider adapters. Runtime desktop plugins have renderer authority, so inspect third-party forks before installing them.

## Install with the included Skill

The distributable Hermes Skill is under [`skill/quota-orb`](skill/quota-orb).

1. Install/copy the Skill into your Hermes skill directory or load it from this repository.
2. Read `SKILL.md` and dry-run:

   ```bash
   python skill/quota-orb/scripts/install.py
   ```

3. After reviewing the three destinations, copy the files:

   ```bash
   python skill/quota-orb/scripts/install.py --apply
   ```

4. Enable the read-only Python backend:

   ```bash
   hermes plugins enable quota-orb --no-allow-tool-override
   ```

5. Restart Hermes Desktop once (the Python API is mounted when the Desktop backend starts), then run **Reload desktop plugins** if the orb is not already visible.

> Enabling a Python backend and restarting Hermes are separate system changes. Review the files first and obtain the appropriate approval in managed environments.

## Repository layout

```text
desktop-plugin/plugin.js                    Tested renderer source
hermes-plugin/dashboard/plugin_api.py       Read-only quota/daily-usage API
hermes-plugin/dashboard/manifest.json       Backend manifest
skill/quota-orb/                            Distributable Hermes Skill
skill/quota-orb/assets/                     Installable copies of the sources
tests/                                      Standard-library test suite
```

## Test

No test-only packages are required beyond Hermes's normal Python environment:

```bash
python tests/test_plugin_api.py -v
python tests/test_plugin_contract.py -v
python tests/test_installer.py -v
python tests/test_skill_package.py -v
node --check desktop-plugin/plugin.js
```

## Known limits

- The orb floats inside Hermes Desktop, not above every Windows application.
- The default report is time-based (18:00 local), not tied to OS shutdown.
- Today's aggregate assigns a whole session to the day it started; it does not split a session across midnight.
- Provider subscription quota, local Token totals, API rate-limit headers, and model context-window usage are different metrics.
- Providers without an account-usage API cannot expose an exact remaining subscription quota.

## License

MIT — see [LICENSE](LICENSE).
