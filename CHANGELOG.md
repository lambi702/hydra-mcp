# Changelog

All notable changes to hydra-mcp are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[semantic versioning](https://semver.org/) (before 1.0, minor versions may break things).

## [Unreleased]

### Added

- One-line install: `uvx hydra-mcp` or `pipx install hydra-mcp`. The wheel ships the admin page,
  so Node is no longer needed to run hydra-mcp.
- `hydra-mcp demo`: a fake provider (Demo Tracker) served by the proxy, with two accounts already
  connected through the real OAuth flow and a ready client, in a throwaway data directory.
- Docker image `ghcr.io/lambi702/hydra-mcp` (amd64 and arm64, non-root, healthcheck) and a
  `compose.yaml`.
- Release workflow publishing to PyPI (trusted publishing) and ghcr.io; CI now builds and
  smoke-tests the wheel and the image on every PR.
- `hydra-mcp serve --open` opens the admin page; `hydra-mcp` alone means `hydra-mcp serve`.

### Changed

- The public URL follows `--port`/`HYDRA_MCP_PORT` unless `HYDRA_MCP_PUBLIC_URL` is set, so
  changing the port no longer breaks OAuth callbacks.

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
