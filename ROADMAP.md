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

## Done (v0.2.0)

- **One-line install**: `uvx hydra-mcp` and `pipx install hydra-mcp`, with the admin page
  bundled in the package, plus a Docker image.
- **Demo mode**: `hydra-mcp demo` starts a fake service with two accounts already connected, so
  the whole flow works offline. Its recording is the GIF at the top of the README.
- **stdio servers**: local MCP servers (`npx …`, `uvx …`), one process per account, each with
  its own encrypted settings.
- **Claude Desktop and claude.ai**: hydra-mcp is an OAuth server toward your apps (one click to
  approve a new app), `HYDRA_MCP_EXTERNAL_URL` for a tunnel, and `hydra-mcp bridge` for Claude
  Desktop's config file.
- **Slack** connector (one Slack app per workspace).

## Now: more connectors tested end to end

- **Real accounts, two of each**: Gmail, GitHub, Slack, Notion and Linear first, because those
  are the services people most often have twice.

Where to help: test a connector you use with two real accounts and report what happened
(the [connector template](https://github.com/lambi702/hydra-mcp/issues/new?template=connector_request.yml)
has the checklist), or pick a `connector` issue.

## Next

- **MCP 2026-07-28**: the stateless protocol version, alongside 2025-11-25.
- **Identity for every connector**: every service should name its accounts by who logged in, so
  logging in again updates the account instead of creating a second one.
- **Built-in HTTPS**, so claude.ai can reach hydra-mcp without a separate tunnel.

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
