---
name: quota-orb
description: Install and verify the Hermes Desktop quota orb.
version: 0.3.1
author: weipch-1980, Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [Hermes, Desktop, Tokens, Quota, Usage]
    related_skills: [hermes-agent]
---

# Quota Orb Skill

Install the third-generation emerald crystal quota orb for Hermes Desktop. The v3 orb is an independent, borderless surface with a double-layer thick-glass shell, dual-track refraction, Fresnel and specular highlights, caustics, rising micro-bubbles, and two asymmetric ocean-like waves. Its liquid level is real provider data: the lowest available provider-reported remaining window, clamped to 0–100; unsupported providers stay neutral glass rather than receiving an estimate. The package also provides a status-bar chip, provider/model usage details, and a once-per-day local report.

The language selector has three states—**Auto**, **中文**, and **English**—and is scoped to the active Hermes profile. The plugin reads local Hermes token accounting and calls Hermes's existing account-usage adapters; renderer JavaScript never reads credentials.

## When to Use

- The user wants live token totals inside Hermes Desktop.
- The user wants Codex, Anthropic OAuth, or OpenRouter quota/reset data when the provider exposes it.
- The user wants a once-per-day local usage report.

Don't use this for an operating-system-wide overlay outside Hermes; this package creates an independent borderless floating surface inside Hermes Desktop.

## Prerequisites

- Hermes Agent v0.20.0 or newer.
- Hermes Desktop with runtime desktop plugins enabled.
- Approval before copying files, enabling the Python backend, or restarting Hermes Desktop.
- A supported provider login for exact account quota data. Local token totals work without a quota API.

## How to Run

Resolve this Skill's directory from `skill_view`, then run the installer as a dry run. The default is always read-only and prints the status of every destination as `new`, `identical`, or `conflict`:

```text
terminal(command="python <skill-dir>/scripts/install.py", timeout=30)
```

A dry run never creates the Hermes home or writes any destination. Review all four destinations before applying:

```text
terminal(command="python <skill-dir>/scripts/install.py --apply", timeout=30)
```

Apply performs a complete preflight. If any destination already exists with different bytes, it reports `conflict` and raises `FileExistsError` before writing anything; this prevents partial installation. Resolve the local file or explicitly approve an overwrite with:

```text
terminal(command="python <skill-dir>/scripts/install.py --apply --force", timeout=30)
```

`--force` is the explicit overwrite switch for conflicts. It is not needed for `identical` files, and it never makes a dry run write.

`--force` does not bypass path safety. The installer rejects symlinks, Windows junctions/reparse points, and any source or destination that resolves outside the Skill or `HERMES_HOME` root.

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

## Storage Semantics

The renderer storage keys are intentionally split by scope:

- `hermes.plugin.quota-orb.reportHour` (`reportHour`) is the local hour at or after which the daily report may be emitted.
- `hermes.plugin.quota-orb.language:<profile>` (`language:<profile>`) stores exactly one of the three language states—`auto`, `zh`, or `en`—for that Hermes profile. Changing it repaints only Quota Orb and does not change another profile or Hermes globally.
- `hermes.plugin.quota-orb.lastReportDay:<profile>` (`lastReportDay:<profile>`) stores the local ISO date of the last report for that profile. A profile gets at most one report per local day; switching profiles uses the other profile's independent value.

Do not collapse these to an unscoped `language` or `lastReportDay`: the language and report guard are profile-scoped by design.

## Procedure

1. Load this Skill and inspect `assets/desktop-plugin/plugin.js` plus `assets/hermes-plugin/dashboard/plugin_api.py`; confirm neither contains credential-reading renderer code or write routes.
2. Run the installer without `--apply`; confirm exactly four destinations under the active `$HERMES_HOME` are listed with their `new` / `identical` / `conflict` status.
3. Obtain approval and run with `--apply`. If a conflict is reported, stop with no partial copy and ask for resolution or explicit `--force` approval.
4. Obtain separate approval and run `hermes plugins enable quota-orb --no-allow-tool-override`; confirm `hermes plugins list` reports `quota-orb` enabled.
5. Restart Hermes Desktop and reload desktop plugins if needed; confirm the orb appears without a card, title bar, or rectangular background and the status-bar chip also appears.
6. Open the orb; switch Auto / 中文 / English and confirm each selection immediately repaints only Quota Orb and persists for the current profile.
7. Confirm the emerald crystal shell, double-layer thick glass, dual-track refraction, Fresnel/specular highlights, two moving asymmetric water waves, rising micro-bubbles, real quota-to-liquid-level mapping, current profile/model/session tokens, today's provider/model groups, provider windows, remaining percentages, and reset times render without an error toast.
8. Leave the plugin running at or after the configured report hour; confirm only one in-app/native report is emitted for that profile and local date.

## Data Semantics

- **Current session Token:** exact values returned by the live `session.usage` RPC after completed provider calls.
- **Today's Token:** sums persisted local session input/output totals whose session start time is within the current local day. Cache-read and reasoning Token are shown separately and grouped by provider and model for the active Hermes profile.
- **Provider quota:** returned by Hermes `agent.account_usage.fetch_account_usage`; Codex exposes session and weekly windows, Anthropic OAuth exposes supported account windows, and OpenRouter exposes credit/key limits when available.
- **Real liquid level:** the lowest available provider window's remaining percentage, clamped to 0–100. Providers without an official account-usage source show neutral glass rather than an estimate.
- **Failure behavior:** provider failures fail open; the UI keeps local totals and labels quota unavailable rather than inventing a value.

## Pitfalls

- Desktop enable state and Python backend enable state are separate security gates. A visible orb with “quota unavailable” usually means the backend is not enabled or Hermes Desktop has not been restarted since installation.
- Runtime desktop plugins are unsandboxed renderer code. Inspect locally before enabling code from an untrusted fork.
- Hermes namespaces the floating contribution as `quota-orb:orb`; the renderer's scoped CSS removes chrome only from that exact pane id.
- A provider subscription quota is not the same as context-window usage or local Token totals.
- The daily report uses the fixed local `reportHour`, not an operating-system shutdown event. The `language:<profile>` and `lastReportDay:<profile>` values must remain profile-scoped.
- The current day's aggregate assigns a whole session to the day it started; a session spanning midnight is not split by individual turn.
- Exact quota/reset values are unavailable for providers without an account-usage API; their local provider/model Token groups still appear.

## Verification

Run the repository tests before installation or publication:

```text
terminal(command="python tests/test_plugin_api.py -v && python tests/test_plugin_contract.py -v && python tests/test_installer.py -v && python tests/test_skill_package.py -v && python tests/test_release_package.py -v && node --check desktop-plugin/plugin.js", timeout=180, workdir="<repository-root>")
```

Acceptance criteria:

- Every test passes with no warnings or secret output.
- `plugin.js` imports only `@hermes/plugin-sdk`, `react`, or `react/jsx-runtime`.
- The backend exports only the read-only `/snapshot` route.
- Skill assets match the tested development sources byte-for-byte.
- Hermes Desktop shows both contribution surfaces, animated water respects reduced-motion preferences, and the details panel groups local data by provider/model without a plugin load-error toast.
