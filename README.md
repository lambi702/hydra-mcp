<p align="center">
  <img src="docs/assets/logo.svg" width="72" alt="" />
</p>

<h1 align="center">hydra-mcp</h1>

<p align="center">
  <strong>One MCP endpoint, every account.</strong><br />
  A self-hosted proxy that lets Claude Code, Cursor, VS Code and any MCP client use
  <em>several accounts of the same service</em>: two Gmail inboxes, three Atlassian sites, work and
  personal GitHub. You decide which app sees which account, read only or read + write.
</p>

<p align="center">
  <a href="https://github.com/lambi702/hydra-mcp/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/lambi702/hydra-mcp/actions/workflows/ci.yml/badge.svg" /></a>
  <a href="LICENSE"><img alt="License: Apache-2.0" src="https://img.shields.io/badge/license-Apache--2.0-blue.svg" /></a>
  <img alt="Status: alpha" src="https://img.shields.io/badge/status-alpha-orange.svg" />
</p>

<p align="center">
  <img src="docs/assets/connections.png" width="820" alt="The Connections page: three Atlassian accounts and two GitHub accounts, each showing which AI app may use it" />
</p>

## Why

Remote MCP servers (Atlassian, Gmail, GitHub, Linear, Notion…) are built around **one login per
server**. Most MCP clients key connections by server URL, so connecting a second Atlassian site
or a second Gmail inbox either replaces the first or is impossible. If you work for several
clients, or keep work and personal apart, your AI only ever sees one of them.

hydra-mcp sits between your AI apps and those servers:

```
 Claude Code ─┐                       ┌─▶ Atlassian (acme.atlassian.net)
 Cursor ──────┼─▶  hydra-mcp  /mcp  ──┼─▶ Atlassian (globex.atlassian.net)
 VS Code ─────┘   one URL, one key    ├─▶ Gmail (work)   ├─▶ Gmail (perso)
                  per app             └─▶ GitHub (work)  └─▶ GitHub (perso)
```

Each tool appears once (`atlassian__searchJiraIssuesUsingJql`) with an extra `account` argument
(`"acme"`, `"globex"`). Your AI picks the account by its friendly name; hydra-mcp sends the call
with that account's token.

## Features

- **Many accounts per service.** Connect as many accounts of the same MCP server as you need.
  Accounts are named after the identity they logged in as (the Atlassian site, the Google
  address, the GitHub login), and you can rename them.
- **Per-app access.** One client per AI app, each with its own key. Drag accounts into a client
  as *read only* (only tools the server marks `readOnlyHint`) or *read + write*, optionally
  limited to a tool pattern. Grants are re-checked on every call, not just when tools are listed.
- **Login stays with the provider.** You sign in on Atlassian's, Google's or GitHub's own page,
  with OAuth 2.1 + PKCE. hydra-mcp never sees a password.
- **Encrypted at rest.** Tokens and OAuth client secrets are sealed with AES-256-GCM. The key
  lives outside the database, so a copy of the database alone decrypts nothing.
- **A connector library with real guides.** 17 well-known servers, each with what to prepare,
  how accounts are told apart, known pitfalls and the vendor's official docs, checked against
  live discovery. Servers that allow it register in one click (Dynamic Client Registration);
  for the others (Google, GitHub, Asana) a wizard walks you through the one-time OAuth app with
  the exact values to paste. Some servers also accept a personal token instead.
- **Any MCP server.** Paste the URL of any Streamable HTTP MCP server that follows the MCP
  authorization spec.
- **Local first.** Runs on your machine, binds to `127.0.0.1`, no account, no telemetry.

## Quick start

Requirements: Python 3.11+, [uv](https://docs.astral.sh/uv/), Node 20+.

```bash
git clone https://github.com/lambi702/hydra-mcp && cd hydra-mcp
make install build     # Python and Node dependencies, then the admin page
make proxy             # starts on http://127.0.0.1:8765
```

The terminal prints an **admin page** link that logs you in. Then:

1. **Connections**: pick a connector, sign in on the provider's page, name the account. Repeat
   for each account.
2. **Clients**: create a client for your AI app and drag accounts into it.
3. **Get setup**: copy the ready-made config for Claude Code, Cursor or VS Code.

```bash
claude mcp add --transport http hydra http://127.0.0.1:8765/mcp \
  --header "Authorization: Bearer hmcp_…"
```

The full walkthrough is in [docs/getting-started.md](docs/getting-started.md).

<p align="center">
  <img src="docs/assets/clients.png" width="820" alt="The Clients page: accounts dragged into a client's read only and read + write zones" />
</p>

## Supported connectors

| Sign-in | Connectors |
| --- | --- |
| One click (the proxy registers itself) | Atlassian (Jira, Confluence), Linear, Notion, Sentry, Stripe, Cloudflare, Supabase |
| One-time OAuth app, then one click | Gmail, Google Drive, Calendar, Docs, Sheets, Slides, Chat, Workspace search (Developer Preview), GitHub, Asana |
| Personal token also accepted | GitHub, Linear, Notion (Business), Stripe, Cloudflare, Supabase |

Per-connector guides: [docs/connectors.md](docs/connectors.md). Missing one?
[Request a connector](https://github.com/lambi702/hydra-mcp/issues/new?template=connector_request.yml).

## Documentation

| | |
| --- | --- |
| [Getting started](docs/getting-started.md) | Install, connect accounts, set up Claude Code, Cursor, VS Code |
| [Connector guides](docs/connectors.md) | What each service needs, multi-account notes, pitfalls, official docs |
| [How it works](docs/architecture.md) | Broker and router modes, the OAuth flows, tool aggregation, storage |
| [Security model](docs/security.md) | What is stored, what is encrypted, threat model, hardening |
| [Configuration](docs/configuration.md) | Environment variables, data directory, ports, running as a service |
| [Troubleshooting](docs/troubleshooting.md) | Common errors and how to fix them |
| [Contributing](CONTRIBUTING.md) | Dev setup, tests, adding a connector, pull requests |

## Status

hydra-mcp is **alpha**: it is tested end to end against real Atlassian accounts and against a
fake provider in CI, but expect rough edges and breaking changes before 1.0. It is built for one person on one machine;
multi-user and hosted deployments are on the roadmap, not supported yet.

| | |
| --- | --- |
| Done | Broker mode (one `/mcp`, per-app keys and grants, encrypted vault), router mode, connector library and guides, token login, admin page |
| Now | One-line install (`uvx`, `pipx`, Docker), offline demo mode, more connectors tested end to end |
| Next | stdio servers (one process per account), HTTPS for Claude Desktop and claude.ai, apps log in with OAuth instead of a static key, MCP 2026-07-28 (stateless) |

The full plan, and where to help, is in [ROADMAP.md](ROADMAP.md).

## Contributing

Bug reports, connector requests and pull requests are welcome. Start with
[CONTRIBUTING.md](CONTRIBUTING.md); security issues go through
[SECURITY.md](SECURITY.md), never a public issue.

## License

[Apache-2.0](LICENSE). hydra-mcp is not affiliated with Anthropic, Atlassian, Google, GitHub or
any other provider it connects to; their names are used only to say what it works with.
