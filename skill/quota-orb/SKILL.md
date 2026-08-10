---
name: quota-orb
description: Install and verify the Hermes Desktop quota orb.
version: 0.1.0
author: weipch-1980, Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [Hermes, Desktop, Tokens, Quota, Usage]
    related_skills: [hermes-agent]
---

# Quota Orb Skill

Install a Hermes Desktop floating quota orb, status-bar chip, provider quota panel, and end-of-day report. The plugin reads local Hermes token accounting and uses Hermes's own account-usage adapters; it never reads credentials in renderer JavaScript.

## When to Use

- The user wants live token totals inside Hermes Desktop.
- The user wants Codex, Anthropic OAuth, or OpenRouter quota/reset data when the provider exposes it.
- The user wants a once-per-day local usage report.

Don't use for an operating-system-wide overlay outside Hermes; this package creates a draggable floating pane inside Hermes Desktop.

## Prerequisites

- Hermes Agent v0.20.0 or newer.
- Hermes Desktop with runtime desktop plugins enabled.
- Approval before copying files, enabling the Python backend, or restarting Hermes Desktop.
- A supported provider login for exact account quota data. Local token totals work without a quota API.

## How to Run

Resolve this skill's directory from `skill_view`, then dry-run the installer:

```text
terminal(command="python <skill-dir>/scripts/install.py", timeout=30)
```

After the user approves the displayed destinations, apply the copy:

```text
terminal(command="python <skill-dir>/scripts/install.py --apply", timeout=30)
```

Enable the backend only after a separate configuration approval:

```text
terminal(command="hermes plugins enable quota-orb --no-allow-tool-override", timeout=60)
```

Restart Hermes Desktop once, then use the Desktop command palette action **Reload desktop plugins** if the orb is not already visible. The Python API routes are mounted during Desktop backend startup; restarting only the gateway is insufficient.

## Quick Reference

- Desktop renderer: `desktop-plugins/quota-orb/plugin.js`
- Read-only backend: `plugins/quota-orb/dashboard/plugin_api.py`
- Backend manifest: `plugins/quota-orb/dashboard/manifest.json`
- Backend route: `GET /api/plugins/quota-orb/snapshot`
- Local live session data: gateway RPC `session.usage`
- Default daily report time: 18:00 local time
- Stored renderer keys: `hermes.plugin.quota-orb.reportHour` and `hermes.plugin.quota-orb.lastReportDay`

## Procedure

1. Load this skill and inspect `assets/desktop-plugin/plugin.js` plus `assets/hermes-plugin/dashboard/plugin_api.py`; confirm neither contains credential-reading renderer code or write routes.
2. Run the installer without `--apply`; confirm exactly four destinations under the active `$HERMES_HOME` are listed.
3. Obtain approval and run with `--apply`; confirm all four destination files exist.
4. Obtain separate approval and run `hermes plugins enable quota-orb --no-allow-tool-override`; confirm `hermes plugins list` reports `quota-orb` enabled.
5. Restart Hermes Desktop and reload desktop plugins if needed; confirm the floating orb and status-bar chip both appear.
6. Open the orb; confirm current model/session tokens, today's totals, provider windows, remaining percentages, and reset times render without an error toast.
7. Leave the plugin running at or after the configured report hour; confirm only one in-app/native report is emitted for that local date.

## Data Semantics

- **Current session Token:** exact values returned by the live `session.usage` RPC after completed provider calls.
- **Today's Token:** sums persisted local session input/output totals whose session start time is within the current local day. Cache-read and reasoning Token are shown separately.
- **Provider quota:** returned by Hermes `agent.account_usage.fetch_account_usage`; Codex exposes session and weekly windows, Anthropic OAuth exposes supported account windows, and OpenRouter exposes credit/key limits when available.
- Provider failures fail open: the UI keeps local totals and labels quota unavailable rather than inventing a value.

## Pitfalls

- Desktop enable state and Python backend enable state are separate security gates. A visible orb with “quota unavailable” usually means the backend is not enabled or Hermes Desktop has not been restarted since installation.
- Runtime desktop plugins are unsandboxed renderer code. Inspect locally before enabling code from an untrusted fork.
- A provider subscription quota is not the same as context-window usage or local Token totals.
- The daily report uses a fixed local hour, not an operating-system shutdown event. Change `hermes.plugin.quota-orb.reportHour` in plugin storage only through a trusted UI/update.
- The current day's aggregate assigns a whole session to the day it started; a session spanning midnight is not split by individual turn.
- Exact quota/reset values are unavailable for providers without an account-usage API.

## Verification

Run the repository tests before installation or publication:

```text
terminal(command="python tests/test_plugin_api.py -v && python tests/test_plugin_contract.py -v && python tests/test_installer.py -v && python tests/test_skill_package.py -v && node --check desktop-plugin/plugin.js", timeout=180, workdir="<repository-root>")
```

Acceptance criteria:

- Every test passes with no warnings or secret output.
- `plugin.js` imports only `@hermes/plugin-sdk`, `react`, or `react/jsx-runtime`.
- The backend exports only the read-only `/snapshot` route.
- Skill assets match the tested development sources byte-for-byte.
- Hermes Desktop shows both contribution surfaces without a plugin load-error toast.
