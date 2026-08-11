# Hermes adapter

Hermes keeps the existing native implementation unchanged:

- `desktop-plugin/plugin.js` provides the floating crystal orb and status chip.
- `hermes-plugin/dashboard/plugin_api.py` provides the read-only local snapshot endpoint.
- `skill/quota-orb/` remains the installable Hermes Skill.

The shared MCP core does not replace Hermes account adapters or access Hermes credentials. It provides a portable representation for other clients while the native Hermes UI preserves the approved liquid-level, 0%, Unknown, language, profile, and reduced-motion behavior.
