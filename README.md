# Quota Orb v0.5.1

A local-first, read-only quota system for AI coding agents, MCP-compatible clients, Hermes Desktop, and an independent Windows desktop widget. It shows:

- an independent, borderless, always-on-top Windows emerald orb that can be dragged across applications and monitors and restores its last visible position;
- a third-generation emerald crystal quota orb with a double-layer thick-glass shell, dual-track refraction, Fresnel edge light, specular reflection, caustics, rising micro-bubbles, and two asymmetric ocean-like water waves inside Hermes;
- a compact status-bar chip;
- current-session and current-day Token usage;
- provider-reported remaining quota and reset times;
- separate Token allowance and pay-as-you-go billing prompts, with provider-reported actual cost distinguished from dated-price estimates;
- liquid status colors: green at 50% or above, yellow below 50%, and red below 30%;
- a three-state profile-scoped language selector: Auto, 中文, and English;
- local usage grouped by the active customer profile, provider, and model;
- a once-per-day usage report (18:00 local time by default).

Quota Orb is an independent community project, is not an official Nous Research or Hermes product, and is not endorsed by OpenAI, Anthropic, or Google.

![Quota Orb preview](docs/quota-orb-preview.png)

![Hermes](https://img.shields.io/badge/Hermes-v0.20.0%2B-gold)
![Quota Orb](https://img.shields.io/badge/Quota%20Orb-v0.5.1-emerald)
![License](https://img.shields.io/badge/license-MIT-blue)

## Why v0.5.1

Quota Orb v0.5.1 adds an explicit Windows MCP widget autostart option while retaining the official Codex rate-limit source and conservative, read-only data model. Its main advantages are:

- **Official Codex rate limits, read only:** the local source calls the experimental Codex app-server method `account/rateLimits/read`; it exposes no independent REST API, sends no credentials, reads no credential files, and fails closed to `Unavailable`.
- **A refined Windows crystal orb:** the visible liquid area tracks the percentage, two natural waves animate independently, and the color-key-safe circular frame has no external shadow or fringe.
- **Explicit MCP autostart:** Windows clients can add `--autostart-widget`; missing executables or launch failures leave MCP serving uninterrupted, and repeated starts retain one orb through a local named mutex.
- **Professional details without rewriting evidence:** fixed panel labels are available in English and Simplified Chinese, while provider and quota-window labels remain verbatim. Snapshot collection runs in the background so slow sources do not freeze the widget.
- **Truth-only level selection:** the orb uses the lowest valid subscription window; an explicit Token allowance drives it only when no valid subscription window exists. Real 0% remains distinct from Unknown.
- **Fail-closed delivery:** installers and builders retain their path-safety controls, and native CI command failures now stop the release workflow immediately.
- **Two focused distributions:** existing Hermes users can choose the compact Hermes Skill ZIP; cross-host users should choose the Universal ZIP with the shared MCP core, adapters, widget, and explicit installer.

For most Codex, Claude Code, Gemini/Antigravity, Cursor, Copilot, Qwen, Kimi, or WorkBuddy/CodeBuddy users, the **Universal package is the recommended download**. Use the Hermes-only package only when Hermes is the explicitly selected host.

## Data sources

| Display | Source | Semantics |
|---|---|---|
| Current session | Hermes `session.usage` RPC | Live session input/output totals |
| Today | Local Hermes `state.db` | Persisted sessions grouped by provider and model for the active profile |
| Account quota | Hermes `agent.account_usage` | Exact only when the provider exposes an account-usage API |
| Codex account quota | Experimental Codex app-server `account/rateLimits/read` | Official read-only rate-limit windows only; raw window labels remain unchanged |
| Token billing | Explicit official field or canonical snapshot | Actual amount only when provider-reported; dated official-price calculations are labeled estimated; otherwise `Unavailable` |
| Daily report | Local plugin timer/storage | Once per local day at/after the configured hour and once per active profile |

Supported exact account sources in Hermes v0.20.0 include OpenAI Codex OAuth, Anthropic OAuth, and OpenRouter. Unsupported or unreachable providers degrade to “quota unavailable”; local Token statistics continue working.

## Cross-platform MCP adapters

The shared Python core exposes one read-only schema without pretending every host shares one native plugin format:

| Host or model ecosystem | Installation/integration | UI |
|---|---|---|
| OpenAI Codex | User Skill in `~/.agents/skills` plus user-local stdio MCP | Structured result or Windows desktop widget |
| Claude / Claude Code | User Skill plus local stdio MCP, or remote Custom Connector | Structured result or Windows desktop widget |
| Gemini / Antigravity | Distinct Google user Skill paths plus local MCP, or Gemini Spark remote Connected App | Structured result or Windows desktop widget |
| Cursor | User Skill in `~/.cursor/skills` plus global local MCP | Structured result or Windows desktop widget |
| GitHub Copilot CLI | Personal Skill in `~/.copilot/skills` plus user MCP | Structured result or Windows desktop widget |
| Qwen Code | User Skill in `~/.qwen/skills` plus local MCP | Structured result or Windows desktop widget |
| Kimi Code CLI | User Skill in `~/.kimi/skills` plus local MCP | Structured result or Windows desktop widget |
| OpenClaw | Official `openclaw skills install ... --global` managed Skill plus local MCP | Structured result or Windows desktop widget |
| WorkBuddy / CodeBuddy Code | User Skill in `~/.codebuddy/skills` plus user-scope MCP | Structured result or Windows desktop widget |
| DeepSeek / GLM / MiniMax | Official compatible coding host or documented Skill surface; no invented official-chat plugin | Structured result or Windows desktop widget |
| Hermes | Existing native Skill, Desktop plugin, and local backend | Full native emerald orb |

The dated Chinese frontier compatibility set—Kimi, Qwen, DeepSeek, GLM, and MiniMax—and its evidence/limits are documented in [`adapters/china-top-five/`](adapters/china-top-five/). Calling a model API is not the same as installing into that vendor's official chat client.

Install the Python package from a checkout:

```bash
python -m pip install -e .
```

The MCP server defaults to an honest unavailable snapshot. To provide data, either set `QUOTA_ORB_SNAPSHOT_FILE` to an explicit canonical JSON snapshot (a safe template is included at `quota_orb/examples/snapshot.example.json`) or set `QUOTA_ORB_HERMES_URL` to the exact loopback Hermes snapshot endpoint. The JSON file has priority when both are set. No account credential is accepted or returned.

Local Claude/Gemini transport:

```bash
python -m quota_orb.mcp_server --transport stdio
```

Local Streamable HTTP development transport:

```bash
python -m quota_orb.mcp_server --transport streamable-http --host 127.0.0.1 --port 8787
```

The endpoint is `http://127.0.0.1:8787/mcp`, and the bundled server rejects non-loopback binds. ChatGPT Apps, Claude remote Custom Connectors, and Gemini Spark Connected Apps require a separately deployed stable HTTPS `/mcp` endpoint behind a reviewed OAuth-capable reverse proxy or hosting layer; this repository does not claim that such a deployment, privacy policy, account eligibility, organization approval, or store review already exists. Platform-specific files and exact installation boundaries are under [`adapters/`](adapters).

## Security boundary

The renderer JavaScript never reads OAuth tokens, API keys, `auth.json`, or environment credentials. It calls a namespaced, read-only local backend route:

```text
GET /api/plugins/quota-orb/snapshot
```

That backend delegates authentication and quota retrieval to Hermes's existing provider adapters. Runtime desktop plugins execute with renderer permissions, so inspect third-party forks before installing them. See [SECURITY.md](SECURITY.md) for the reporting policy.

## Install into the current AI coding agent — user-global

**AI agents installing this repository must select their own host. Never fall back to the Hermes installer.** The portable source is [`skills/quota-orb`](skills/quota-orb), and the safe installer requires an explicit target:

| Target | User-global destination |
|---|---|
| `codex` | `~/.agents/skills/quota-orb/SKILL.md` |
| `claude` | `~/.claude/skills/quota-orb/SKILL.md` |
| `antigravity` | `~/.gemini/config/skills/quota-orb/SKILL.md` |
| `gemini-cli` | `~/.gemini/skills/quota-orb/SKILL.md` |
| `cursor` | `~/.cursor/skills/quota-orb/SKILL.md` |
| `copilot` | `~/.copilot/skills/quota-orb/SKILL.md` |
| `qwen-code` | `~/.qwen/skills/quota-orb/SKILL.md` |
| `kimi-cli` | `~/.kimi/skills/quota-orb/SKILL.md` |
| `workbuddy-code` | `~/.codebuddy/skills/quota-orb/SKILL.md` |

OpenClaw is intentionally not mapped to a guessed filesystem path in this installer. From the Universal package root, use its official managed global installer:

```bash
openclaw skills install ./skills/quota-orb --as quota-orb --global
```

Preview first, then apply for the current host—for example Codex:

```powershell
python scripts/install_agent_skill.py --target codex
python scripts/install_agent_skill.py --target codex --apply
```

The default is preview-only. `--target` is required, there is no implicit target, and this installer has no Hermes target. It refuses conflicting files and symlink/junction/reparse destinations rather than overwriting customer content. Register the same local read-only MCP server using the selected host's instructions under [`adapters/`](adapters); Skill installation and MCP registration both belong to that host.

## Independent Windows desktop widget

After installing the Python package, run:

```powershell
quota-orb-widget
```

For a Windows client that loads the local MCP server, add the explicit opt-in flag to its MCP command:

```powershell
python -m quota_orb.mcp_server --transport stdio --autostart-widget
```

This starts the widget when that MCP process loads. Starting the MCP more than once does not create multiple orbs: the widget holds one Windows local named mutex. Non-Windows clients and MCP commands without the flag never start a GUI.

The borderless crystal orb stays above applications and animates layered liquid waves unless Windows reduced-motion is enabled. Its Windows color-key display frame uses a clean circular boundary without an external shadow or alpha fringe. Left-click (or focus it and press Enter/Space) to toggle one read-only details panel; drag begins only after the 4-pixel threshold, so dragging never opens the panel. The widget selects Simplified Chinese for Windows `zh` UI locales and English otherwise; only fixed UI labels are translated, while provider, model, source, and quota-window labels remain unchanged. The panel shows the current snapshot identity, quota windows, API quota, local usage, and Token billing without merging actual, estimated, or unavailable values. Snapshot refresh runs in a single background worker; a failed refresh retains the latest verified snapshot and reports the failure. Escape or Close dismisses only the panel; right-click the orb to exit, while Escape on the orb exits it.

The orb saves its virtual-screen position on drag release and restores/clamps it against current Windows monitor work areas after restart, monitor removal, resolution, or DPI changes. Position state contains only `x` and `y` at `%LOCALAPPDATA%\QuotaOrb\widget-position.json`; it stores no account or authentication data. Startup-with-Windows is not enabled.

Use `QUOTA_ORB_SNAPSHOT_FILE` for an explicit provider-neutral snapshot or the already documented safe loopback source. Explicit snapshot, Hermes, and Codex executable settings take priority; when none is set, only `%USERPROFILE%\.codex\plugins\.plugin-appserver\codex.exe` is considered, with no `PATH` search or credential-file read. Unknown displays only `?` with an unavailable inner ring, while real 0% displays an empty orb. The visible liquid area—not its linear height—matches the remaining percentage: 50% crosses the sphere center and 100% fills the inner chamber. Color varies continuously within each band: green for `>=50%`, yellow for `30%–<50%`, and red for `<30%`; a Token allowance can drive the same level when no subscription window is available.

## Hermes native installation — explicit only

The legacy/native Hermes distribution remains under [`skill/quota-orb`](skill/quota-orb). Use this section only when Hermes itself is the selected host.

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

## Build release packages

Both builders create reproducible ZIPs plus SHA-256 sidecars. The Hermes-only package remains available for existing installations:

```bash
python scripts/build_skill_package.py
```

The universal package includes the shared MCP core, independent Windows desktop widget, portable user-global Agent Skill installer, Codex/Claude/Gemini/Cursor/Copilot/Qwen/Kimi/WorkBuddy adapters, the OpenClaw official-CLI adapter, the dated Chinese top-five compatibility matrix, and the unchanged Hermes Skill:

```bash
python scripts/build_universal_package.py
```

Outputs:

```text
dist/quota-orb-skill-v0.5.1.zip
dist/quota-orb-skill-v0.5.1.sha256
dist/quota-orb-universal-v0.5.1.zip
dist/quota-orb-universal-v0.5.1.sha256
```

Both archives use sorted entries, fixed timestamps, fixed file modes, no-follow source reads, and exclude `__pycache__` directories and `*.pyc` files. Both builders fail closed when a source tree, output directory, or any existing output ancestor is a symlink, junction, or reparse point.

## Artifact Attestation

For `v0.3.1` and later, pushing a release tag triggers native GitHub Actions CI. Starting with `v0.4.0`, the same run tests the checked-out tag, builds both ZIPs and both SHA-256 sidecars once, verifies the tag and each sidecar, attests each CI-built ZIP separately, then creates the GitHub Release with all four original assets. In `v0.5.0`, every native install, test, syntax-check, build, and release command explicitly throws on a nonzero exit so PowerShell cannot continue after a failed command. Any command, integrity-gate, or attestation failure stops before publication.

The existing `v0.3.0` Release remains unchanged and has no Artifact Attestation; this workflow never rebuilds or modifies historical releases. Verify a downloaded release ZIP with:

```bash
gh attestation verify <zip> -R weipch-1980/hermes-quota-orb
```

## Repository layout

```text
desktop-plugin/plugin.js                    Tested Hermes renderer source
hermes-plugin/dashboard/plugin_api.py       Hermes read-only quota/daily-usage API
quota_orb/desktop_widget.py                Independent draggable Windows desktop orb
quota_orb/                                  Shared schema, sources, MCP server, and Apps UI
skills/quota-orb/                           Canonical portable Agent Skill
adapters/codex/                             Codex user Skill and MCP boundary
adapters/claude/                            Claude remote Connector, user Skill, and stdio MCP example
adapters/gemini/                            Gemini Spark, Antigravity, and Gemini CLI adapters
adapters/cursor/                            Cursor user Skill and global MCP example
adapters/copilot/                           GitHub Copilot personal Skill and MCP example
adapters/qwen/                              Qwen Code user Skill and MCP example
adapters/kimi/                              Kimi Code CLI user Skill and MCP example
adapters/openclaw/                          OpenClaw official global CLI boundary
adapters/workbuddy/                         WorkBuddy/CodeBuddy user Skill, MCP, and billing boundary
adapters/china-top-five/                    Dated Chinese frontier model integration matrix
adapters/hermes/                            Native Hermes compatibility boundary
skill/quota-orb/                            Explicit Hermes-only native Skill
scripts/install_agent_skill.py              Safe user-global non-Hermes Skill installer
scripts/build_skill_package.py              Reproducible Hermes builder
scripts/build_universal_package.py          Reproducible cross-platform builder
tests/                                      Standard-library contract and E2E tests
docs/quota-orb-preview.png                  Hermes release preview image
```

## Test

Install the pinned MCP runtime from `pyproject.toml`, then run the complete standard-library test suite and renderer syntax check:

```bash
python -m pip install -e .
python -m unittest discover -s tests -v
node --check desktop-plugin/plugin.js
```

## Known limits

- The independent Windows orb is a separate local process. Installing a Skill does not silently enable Windows startup; launch `quota-orb-widget` explicitly.
- The Hermes renderer orb remains scoped inside Hermes Desktop; the separate Windows widget provides the cross-application surface.
- The default report is time-based (18:00 local), not tied to OS shutdown.
- Today's aggregate assigns a whole session to the day it started; it does not split a session across midnight.
- Provider subscription quota, local Token totals, API rate-limit headers, Token billing, and model context-window usage are different metrics.
- An actual billed amount must be provider-reported. A price-table calculation is labeled estimated; when neither can be verified, cost remains `Unavailable`.
- Providers without an account-usage API cannot expose an exact remaining subscription quota.
- The real liquid level uses the lowest valid subscription window. Only when no valid subscription window exists may an explicit Token allowance drive the level; if neither has a finite remaining percentage, the orb stays neutral rather than inventing a fill level.

## Support and commercial integration

Use GitHub Issues for reproducible bug reports, feature requests, installation support, or commercial integration enquiries. Do not include credentials, private configuration, or undisclosed vulnerability details. Private vulnerability reporting guidance is in [SECURITY.md](SECURITY.md).

## License

MIT — see [LICENSE](LICENSE).
