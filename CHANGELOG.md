# Changelog

## 0.5.1

- Added the explicit `--autostart-widget` MCP option for Windows clients. It launches the bundled widget fail-closed before MCP serving and never starts a GUI by default.
- Added a Windows local named mutex so repeated MCP starts keep one desktop orb instance.

## 0.5.0

- Added an official, read-only Codex rate-limit source through the experimental local app-server `account/rateLimits/read` method. The source exposes no independent REST API, sends no credentials, reads no credential files, and fails closed to `Unavailable`.
- Refined the independent Windows crystal orb with percentage-correct visible liquid area, two natural asymmetric waves, and a color-key-safe circular boundary without an external shadow or fringe.
- Added a professional read-only details panel with English and Simplified Chinese fixed labels while preserving raw provider and quota-window labels.
- Moved snapshot collection to one background worker so slow refreshes do not block the widget; failed refreshes retain the latest verified snapshot and report the failure.
- Kept truth-only level selection explicit: the lowest valid subscription window wins, and a Token allowance can drive the orb only when no valid subscription window exists.
- Fixed release CI so every native install, test, syntax-check, build, and GitHub Release command stops the workflow immediately on a nonzero exit.

## 0.4.0

- Added a provider-neutral, read-only quota schema that keeps subscription quota, API quota, local Token usage, and Token billing separate and preserves real 0% versus Unavailable semantics.
- Added explicit provider-reported `actual` versus official-price-table `estimated` cost classification; local Token totals are never described as an invoice.
- Added strict liquid state colors across Hermes, MCP Apps, and the Windows widget: green at 50% or above, yellow below 50%, red below 30%, and neutral for Unknown.
- Increased panel text contrast and metadata font weight/size for readability.
- Added OpenClaw support through its official managed `--global` Skill CLI and WorkBuddy/CodeBuddy Code user Skill, MCP, and documented status-line cost boundary.
- Added an official Python MCP SDK server with three read-only tools, stdio and Streamable HTTP transports, and a portable MCP Apps emerald-orb resource.
- Added truthful ChatGPT, Codex, Claude/Claude Code, Gemini Spark, Antigravity, Gemini CLI, Cursor, GitHub Copilot, Qwen Code, Kimi CLI, and Hermes adapters without claiming unsupported personal-subscription APIs or a universal native plugin format.
- Added a dated Chinese frontier compatibility set for Kimi, Qwen, DeepSeek, GLM, and MiniMax, with native-client versus compatible-host boundaries stated explicitly.
- Added a target-required, preview-first user-global Agent Skill installer that cannot fall back to Hermes and refuses conflicts or link/reparse destinations.
- Hardened portable installation and both release builders against Windows junction/reparse check-to-commit parent swaps; guarded ZIP and checksum publication now remains bound to the validated output directory.
- Added an independent Windows always-on-top emerald orb with left-button drag threshold, multi-monitor/negative-coordinate recovery, DPI awareness, atomic position persistence, real 0%, and Unknown semantics.
- Added a reproducible Universal ZIP builder while preserving the existing Hermes Skill package and native renderer/backend behavior.
- Added CI-native tests, deterministic dual-package builds, SHA-256 integrity gates, separate attestations for both ZIPs, and four-asset GitHub Release publication for v0.4.0 tags.

## 0.3.1

- Changed only supply-chain release automation: pushed tags now run CI-native tests, build the release ZIP and SHA-256 sidecar, verify integrity, attest the CI-built ZIP, and create the Release with those same assets.
- Preserved the `0.3.0` Release history unchanged; it is not retroactively attested.

## 0.3.0

- Added the third-generation emerald crystal quota orb with double-layer thick glass, dual-track refraction, and provider-derived liquid levels.
- Documented the three-state Auto / 中文 / English language selector and profile-scoped language and daily-report storage semantics.
- Added fail-fast installer conflict detection, safe dry runs, and explicit `--force` overwrites.
- Rejected symlink, junction/reparse-point, resolved-path escapes, and commit-time destination-parent swaps during installation, including under `--force`.
- Hardened installation and release packaging against no-follow source-file races, including same-size, preserved-mtime content mutation.
- Added a reproducible standard-library-only Skill ZIP builder with a SHA-256 sidecar.
- Versioned the Skill and Hermes backend manifests together at 0.3.0.

## 0.2.0

- Added the borderless crystal orb, provider/model daily usage grouping, and read-only account quota panel.
