# How hydra-mcp works

This page explains what happens between your AI app, hydra-mcp and the MCP servers it talks to.
It assumes you know what MCP is; the OAuth parts are explained as they come.

## The problem

A remote MCP server protects itself with OAuth, following the
[MCP authorization spec](https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization):

1. The client calls the server without a token and gets `401` with a `WWW-Authenticate` header.
2. That header points to the server's *protected resource metadata* (RFC 9728), which names its
   *authorization server* (AS).
3. The client reads the AS metadata (RFC 8414), registers itself if the AS allows it (Dynamic
   Client Registration, RFC 7591), and runs an authorization code flow with PKCE, sending the
   server's URL as `resource` (RFC 8707) so the token is bound to that server.
4. The client calls the server with `Authorization: Bearer <token>`.

MCP clients store that token **per server URL**. One URL, one token, one account. A second
Atlassian site or a second Google address has no place to live.

## Two ways around it

hydra-mcp has two modes. They can run side by side; broker mode is the one the admin page is
built around.

### Broker mode (recommended): one URL for every account

hydra-mcp is itself an OAuth client of each upstream server, and a single MCP server
(`/mcp`) toward your apps.

```
AI app ──key hmcp_…──▶ /mcp ─┬─ tools/list: merge the tools of every granted account
                             └─ tools/call {account: "acme"} ─▶ token of atlassian-acme ─▶ Atlassian
```

**Connecting an account** (Connections page, `POST /admin/api/connect`):

1. hydra-mcp discovers the upstream's AS through its protected resource metadata, and refuses
   an AS that does not advertise PKCE `S256`.
2. It registers itself once per upstream: by DCR when the AS has a `registration_endpoint`,
   otherwise with the client ID and secret you created by hand (the setup wizard).
3. It sends your browser to the AS with PKCE, a single-use `state` (10 minute lifetime) and
   `resource` set to the upstream's URL.
4. The AS redirects to `/oauth/callback`. hydra-mcp exchanges the code, then works out *who*
   logged in: the email in an OpenID Connect `id_token`, or, for servers that return no
   identity (Atlassian, GitHub), a call to one of the server's own tools
   (`getAccessibleAtlassianResources` gives the site, `get_me` the login).
5. Same identity as an existing account: that account's token is replaced (a reconnect).
   New identity: a new account is created, named from the identity. No account exists before
   a login succeeded.

Tokens are refreshed shortly before they expire, with the refresh token when the AS gave one.

**Pasted tokens** (`POST /admin/api/connect-token`) skip OAuth: the token is tried with an
`initialize` and `tools/list` call, then stored the same way, without expiry or refresh.

**Serving an app** (`/mcp`):

- The app authenticates with its client key (`Authorization: Bearer hmcp_…`). hydra-mcp stores
  only the key's SHA-256.
- `tools/list`: for each account the client is granted, hydra-mcp lists the upstream's tools
  (cached for a few minutes), drops the tools the grant does not allow, and merges them. A tool
  is exposed once as `{upstream}__{tool}`, with an `account` argument whose `enum` lists the
  accounts that may run it, and a description that maps names to identities
  (`acme = acme.atlassian.net`).
- `tools/call`: hydra-mcp reads and removes the `account` argument, **checks the grant again**,
  gets a fresh token for that account and forwards the call.
- Each upstream session belongs to one account; sessions are never shared between accounts.

**Grants**: a grant is (client, account, tool pattern, mode). Mode `read` allows only tools
annotated `readOnlyHint: true` by the upstream; tools without annotations count as writes. The
tool pattern is a shell-style pattern on the upstream tool name (`search*`, `get*`).

### Router mode: one URL per account, no token storage

Each account gets its own URL, `/a/{account}/mcp`. Your app logs in *directly* at the upstream
AS and keeps the token; hydra-mcp only forwards requests and rewrites the discovery documents so
that the login goes to the right place:

```
app ──token──▶ /a/gmail-work/mcp ──same token──▶ upstream MCP
 │                  │
 │  401, WWW-Authenticate rewritten to point at the proxy's metadata for this account
 └─▶ /.well-known/oauth-protected-resource/a/gmail-work/mcp
        { resource: <proxy URL>, authorization_servers: [<upstream AS>] }
     then OAuth + PKCE directly with the upstream AS
```

hydra-mcp never reads, stores or changes the `Authorization` header in this mode. The catch: an
AS that strictly binds tokens to `resource` mints a token for the proxy's URL, which the upstream
then rejects. Router mode also cannot enforce per-app grants, because the app never
authenticates to hydra-mcp. Use broker mode unless you need zero custody.

## Storage

One SQLite file and one key file in the data directory (`~/.hydra-mcp` by default):

| Table | Holds |
| --- | --- |
| `upstreams` | MCP servers: id, name, URL |
| `accounts` | one row per identity: upstream, friendly name, identity label |
| `clients`, `grants` | apps and what each may use |
| `upstream_oauth` | hydra-mcp's OAuth registration per upstream (client secret encrypted) |
| `account_tokens` | access and refresh tokens, **encrypted** (one sealed blob per account) |
| `link_flows` | pending logins: state and PKCE verifier, single use, 10 minutes |

Encryption details are in the [security model](security.md).

## Code map

```
proxy/src/hydra_mcp/
├── app.py              wires everything into one Starlette app
├── cli.py              hydra-mcp serve | admin-token
├── settings.py         HYDRA_MCP_* settings
├── models.py           Upstream, Account, Client, Grant (Client.allows)
├── store.py            SQLite
├── vault/              AES-256-GCM sealing
├── catalog/            connector library (connectors.json) and docs generator
├── broker/
│   ├── oauth.py        discovery, registration, login, refresh, account identity
│   ├── identity.py     "who is this token?" probes for servers without id_token
│   ├── setup.py        one-time OAuth app guides (Google, GitHub, Asana, generic)
│   ├── upstream.py     MCP client toward upstreams (Streamable HTTP, sessions, SSE)
│   ├── stdio.py        MCP client toward local servers: one process per account
│   ├── aggregator.py   merges tools, applies grants, routes calls
│   └── endpoint.py     the /mcp endpoint apps connect to
├── router/             router mode: passthrough and discovery rewriting
└── admin/api.py        JSON API behind the admin page
admin/src/              the admin page (React + Vite)
```

## Protocol support

- Transport: Streamable HTTP toward apps. Toward upstreams: Streamable HTTP (responses may be
  JSON or SSE) and stdio for [local servers](local-servers.md), one process per account. Legacy
  HTTP+SSE servers are not supported yet.
- MCP versions negotiated with apps: 2025-11-25, 2025-06-18, 2025-03-26.
- `/mcp` keeps no session state of its own: each request is served on its own.
