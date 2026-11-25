# Changelog

All notable changes to hydra-mcp are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[semantic versioning](https://semver.org/) (before 1.0, minor versions may break things).

## [Unreleased]

### Fixed

- Google connectors: the guides now list enrollment of the Google Cloud project in the Workspace
  Developer Preview as a required step (found testing Gmail with a real account: login works,
  every tool call is refused until the project is enrolled).
- The Claude Code setup command now uses `--scope user`: without it, Claude Code only saw hydra
  in the folder where the command was run.

## [0.2.0] - 2026-11-25

### Added

- Local (stdio) servers: hydra-mcp starts a program (`npx …`, `uvx …`) once per account, each
  copy with its own encrypted secret settings and optionally its own home folder. Started on
  first use, stopped when idle, restarted after a crash with the program's last output in the
  error. `HYDRA_MCP_STDIO_ENABLED`, `HYDRA_MCP_STDIO_IDLE_S`.
- Slack connector (official server at `mcp.slack.com`): app manifest with the callback and user
  scopes, PKCE so a local `http://localhost` callback works, one Slack app per workspace with
  **+ Another workspace**, accounts named after the workspace.
- Provider quirks as connector data: `redirect_host`, `scope_separator`,
  `one_client_per_workspace`. Token responses in Slack's shape (`ok`, `authed_user`) are
  normalized.
- claude.ai and Claude Desktop custom connectors: hydra-mcp is now also an OAuth server for apps
  (protected resource and server metadata, dynamic registration, consent page bound to a
  hydra-mcp client, PKCE, rotating refresh tokens with reuse detection, revocation). Apps
  signed in this way show on their client card and can be signed out.
- `HYDRA_MCP_EXTERNAL_URL` for a tunnel: only `/mcp` and the app login are served under it; the
  admin page and API stay local-only.
- `hydra-mcp bridge`: a stdio relay for Claude Desktop's config file, no tunnel needed. The
  admin page's setup now has *Claude Desktop* and *claude.ai* tabs.
- Guides: `docs/clients/claude-desktop.md`, `docs/clients/claude-ai.md`.
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

- Gmail, GitHub, Notion and Linear guides re-checked against vendor docs (2026-11-25): Gmail
  client type and tools, GitHub toolset URLs, Notion SSE retirement and limits, Linear
  read-only URL.
- After a provider login, the browser returns to the absolute public URL of the admin page.
- The public URL follows `--port`/`HYDRA_MCP_PORT` unless `HYDRA_MCP_PUBLIC_URL` is set, so
  changing the port no longer breaks OAuth callbacks.
- The Claude Desktop snippet runs `uvx hydra-mcp bridge` when hydra-mcp itself runs from `uvx`,
  whose environment lives in a cache uv may clean.

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

[Unreleased]: https://github.com/lambi702/hydra-mcp/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/lambi702/hydra-mcp/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/lambi702/hydra-mcp/releases/tag/v0.1.0
