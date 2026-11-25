# Roadmap

What hydra-mcp is working toward, in the order we expect to get there. Dates are not promised:
this is a small project, and the order changes when users tell us something matters more.

Want to influence it? Comment on the linked issue, or start a thread in
[Discussions, Ideas](https://github.com/lambi702/hydra-mcp/discussions). Want to help? Every
section lists where to start, and [`good first issue`](https://github.com/lambi702/hydra-mcp/labels/good%20first%20issue)
is the easiest way in.

## Done (v0.1.0)

- **Broker mode**: one `/mcp` endpoint for every account, a key per AI app, read only or
  read + write grants per account, re-checked on every call.
- **OAuth toward upstream servers**: discovery, Dynamic Client Registration or a manual OAuth app,
  PKCE, `resource` indicators, refresh. Encrypted token vault.
- **Router mode**: one URL per account, no token stored by hydra-mcp.
- **Connector library**: 17 servers with in-app guides; token login where a server accepts
  personal tokens.
- **Admin page**: Home checklist, Connections, Clients with drag-and-drop grants, ready-made
  setup for Claude Code, Cursor and VS Code.

## Now: try it in one minute (v0.2.0)

The goal of v0.2.0 is that someone who has never heard of hydra-mcp can see it work without
cloning the repository or creating an OAuth app.

- **One-line install**: `uvx hydra-mcp` and `pipx install hydra-mcp` from PyPI, with the admin
  page bundled in the package, plus a Docker image.
- **Demo mode**: a fake MCP server with two fake accounts, started by hydra-mcp itself, so the
  whole flow (connect, grant, call a tool with `account`) works offline.
- **A 30-second demo** at the top of the README: two accounts of the same service, one AI app,
  the tool asking which account to use.
- **More connectors tested end to end** with real accounts: Gmail, GitHub, Slack, Notion and
  Linear first, because those are the services people most often have twice.

Where to help: test a connector you use with two real accounts and report what happened
(the [connector template](https://github.com/lambi702/hydra-mcp/issues/new?template=connector_request.yml)
has the checklist), or pick a `connector` issue.

## Next

- **stdio servers**: run local MCP servers (the ones started with `npx …` or `uvx …`), one
  process per account, with that account's environment variables.
- **Claude Desktop and claude.ai**: they only reach HTTPS URLs. Guides for a tunnel
  (Cloudflare Tunnel, Tailscale Funnel, ngrok), then built-in HTTPS.
- **Apps log in with OAuth** instead of a pasted `hmcp_…` key: hydra-mcp becomes an
  authorization server toward your apps, so a new app is one click to approve.
- **MCP 2026-07-28**: the stateless protocol version, alongside 2025-11-25.
- **Identity for every connector**: every service should name its accounts by who logged in, so
  logging in again updates the account instead of creating a second one.

## Later

- **Legacy HTTP+SSE upstreams**, for servers that have not moved to Streamable HTTP.
- **Several people on one hydra-mcp** (a team or a family on a small server), each with their own
  accounts and apps.
- **Hosted deployment guide**: a VPS behind a reverse proxy, backups, key rotation.
- **Audit log** in the admin page: which app called which tool on which account, and when.

## Not planned

- **Handling sign-in for upstream servers ourselves.** hydra-mcp never asks for your provider
  password and never replaces the provider's own login: authority stays with the upstream
  server. See [docs/security.md](docs/security.md).
- **A hosted service run by the project.** hydra-mcp is self-hosted software.

## How this file is kept up to date

Maintainers update it with each release, and when a direction changes. A pull request that
finishes a roadmap item moves it to *Done* in the same change.
