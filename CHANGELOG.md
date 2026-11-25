# Changelog

All notable changes to hydra-mcp are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[semantic versioning](https://semver.org/) (before 1.0, minor versions may break things).

## [Unreleased]

### Added

- Local (stdio) servers: hydra-mcp starts a program (`npx …`, `uvx …`) once per account, each
  copy with its own encrypted secret settings and optionally its own home folder. Started on
  first use, stopped when idle, restarted after a crash with the program's last output in the
  error. `HYDRA_MCP_STDIO_ENABLED`, `HYDRA_MCP_STDIO_IDLE_S`.

## [0.1.0] - 2026-11-24

### Added

- Broker mode: one `/mcp` endpoint for every account, a key per AI app, read only or read + write
  grants per account with optional tool patterns, re-checked on every call.
- OAuth client toward upstream servers: discovery (RFC 9728, RFC 8414), Dynamic Client
  Registration or a manual OAuth app, PKCE S256, `resource` indicators, refresh.
- Accounts named from who logged in (OpenID email, Atlassian site, GitHub login).
- Token login for servers that accept personal tokens (GitHub, Linear, Stripe, Cloudflare,
  Supabase, Notion).
- Encrypted token vault (AES-256-GCM, key outside the database).
- Connector library of 17 servers with in-app guides, generated `docs/connectors.md`.
- One-time OAuth app wizards for Google, GitHub and Asana.
- Admin page: Home checklist, Connections, Clients (drag-and-drop grants, ready-made setup for
  Claude Code, Cursor and VS Code), Advanced.
- Router mode: one URL per account, no token storage.

[Unreleased]: https://github.com/lambi702/hydra-mcp/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/lambi702/hydra-mcp/releases/tag/v0.1.0
