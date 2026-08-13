---
name: quota-orb
description: Inspect read-only quota and usage snapshots truthfully.
---

# Quota Orb

Use this Skill in Codex, Claude Code, Antigravity or Gemini CLI, Cursor, GitHub Copilot CLI, Qwen Code, Kimi CLI, OpenClaw, and WorkBuddy/CodeBuddy Code when the user asks about provider quota, reset windows, API limits, local model usage, Token allowance, or usage-based billing. Live data comes only from the connected `quota-orb` MCP server; the Skill itself does not read another AI client's files or credentials.

## Procedure

1. Call `get_supported_sources` when platform or provider capability is unclear.
2. Call `get_quota_snapshot` for the combined provider-neutral snapshot.
3. Call `get_daily_usage` only when the user specifically asks for local daily Token totals.
4. Keep **subscription quota**, **API quota**, **local usage**, and **Token billing** as separate sections.
5. Preserve provider, profile, account, model, source, reset-window names, currency, and cost classification exactly as returned.
6. If `available` is false, report **Unavailable** with `unavailable_reason`; never convert it to 0%.
7. Treat `remaining_percent: 0` as a real empty allowance, not missing data.
8. Describe `classification: actual` as provider-reported billed cost and `classification: estimated` only as an estimate. Never describe an estimate as an invoice charge.
9. If Token usage exists but allowance or cost is absent, show usage and report the missing value as **Unavailable**; never invent a remaining percentage or price.

## Desktop Widget

On Windows, the optional `quota-orb-widget` command opens the independent draggable desktop orb. When a local MCP command explicitly includes `--autostart-widget`, loading that MCP starts the widget automatically; it is opt-in and the Windows local named mutex keeps one orb instance. Explicit snapshot, Hermes, or Codex configuration wins; otherwise the widget checks only the fixed user Codex app-server path and never searches `PATH` or reads credentials. Fixed labels follow the Windows system language (`zh` uses Simplified Chinese; other locales use English), and the color-key-safe boundary suppresses external shadow or fringe. Its liquid level uses the lowest available subscription or Token-allowance percentage: green at 50% or above, yellow below 50%, and red below 30%. Unknown remains neutral.

## Safety

- All three MCP tools are read-only.
- Do not infer subscription allowance from local Token totals, API limits, or Token billing.
- Do not infer Token allowance or billing amount from subscription quota.
- Do not request or expose passwords, access tokens, API keys, or authentication material.
- Do not claim a personal subscription allowance or billed amount is available unless the snapshot names an official source.
- Do not install or configure another AI client when the user selected the current host.

## Verification

A valid installation appears in the selected host's personal or officially managed global Skill location, not another client's directory. A valid response separates all four data classes, preserves Unknown/0% semantics, distinguishes actual and estimated cost, and names the source for every available value.
