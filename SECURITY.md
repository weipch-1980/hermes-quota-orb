# Security

## Runtime boundary

- The Hermes Desktop renderer plugin executes with renderer permissions. It is runtime desktop code, not a sandbox, so inspect the exact source and assets before enabling a fork or downloaded copy.
- The Python backend is read-only: it opens Hermes state data read-only and exposes only the namespaced snapshot route for local usage and provider-reported quota. It does not provide write, shell, credential-export, or tool-override routes.
- Renderer code must not read OAuth tokens, API keys, `auth.json`, environment credentials, or other secret stores. Authentication and quota retrieval stay inside Hermes's existing provider adapters.

## Reporting a vulnerability

When GitHub **Private Vulnerability Reporting** is enabled for this repository, use **Security → Report a vulnerability** and include a reproducible description, affected version, and a safe proof of impact. Until that private channel is enabled, open a minimal public issue requesting private contact without disclosing the vulnerability, exploit details, or sensitive diagnostics. Do not publicly disclose an unpatched issue.

Never include passwords, OAuth tokens, API keys, cookies, private configuration, or other credentials in an issue, report, log, screenshot, or pull request. Redact secrets before sharing any diagnostic material.
