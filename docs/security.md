# Security model

hydra-mcp holds OAuth tokens that can read and change your mail, tickets and code. This page says
what it stores, how it protects it, what it defends against and what it does not. To report a
vulnerability, see [SECURITY.md](../SECURITY.md).

## Design principles

- **Authority stays with the provider.** Login, consent, scopes and token issuance happen at each
  service's own authorization server. hydra-mcp never asks for or sees a password, and cannot
  grant itself more than you approved on the consent page.
- **Least privilege per app.** Each AI app has its own key and sees only the accounts and tools
  granted to it. Grants are enforced again on every call, not only when tools are listed.
- **Local by default.** The proxy binds to `127.0.0.1`. Nothing leaves your machine except calls
  to the services you connected. No telemetry.

## What is stored, and how

Everything lives in the data directory (`~/.hydra-mcp`, created with mode `0700`).

| Item | Where | Protection |
| --- | --- | --- |
| Upstream access and refresh tokens | `hydra-mcp.sqlite3`, table `account_tokens` | AES-256-GCM, key in `vault.key` |
| OAuth client secrets you pasted, or DCR secrets | `hydra-mcp.sqlite3`, table `upstream_oauth` | AES-256-GCM, key in `vault.key` |
| Pasted personal tokens (PAT, API keys) | same as upstream tokens | AES-256-GCM |
| Secret settings of local (stdio) accounts | same as upstream tokens | AES-256-GCM |
| Client keys (`hmcp_…`) | `hydra-mcp.sqlite3`, table `clients` | SHA-256 hash only; the key is shown once |
| Vault key | `vault.key` | 32 random bytes, file mode `0600` |
| Admin token | `admin_token` (unless set by environment) | file mode `0600` |
| Account names, identities, URLs, grants | `hydra-mcp.sqlite3` | plain text |

Each encrypted blob is bound to its row with AES-GCM associated data (`token:<account>`,
`client:<upstream>`): a blob copied onto another account's row fails to decrypt instead of
silently granting that account's access.

**Consequences:**

- A copy of the database alone (a backup, a sync folder) reveals which services and identities
  you use, not the tokens.
- Anyone who can read both the database *and* `vault.key` as your user can use your tokens. This
  is the same trust boundary as your browser's cookies or `~/.config` credentials: protect your
  user account and disk (FileVault, BitLocker, LUKS).
- Losing `vault.key` means reconnecting every account; nothing else is lost.

## Authentication surfaces

| Endpoint | Who calls it | Authentication |
| --- | --- | --- |
| `/admin/` and `/admin/api/*` | you, in the browser | admin token as `Authorization: Bearer`, compared in constant time |
| `/mcp` | your AI apps | client key `hmcp_…`, looked up by SHA-256 |
| `/oauth/callback` | the provider, through your browser | single-use `state` (10 minutes) bound to a PKCE verifier |
| `/a/{account}/mcp` (router mode) | your AI apps | none at the proxy; the upstream checks the app's own token |

The admin page keeps the admin token in the browser's `localStorage`. The `#token=` login link
puts it in the URL fragment, which browsers never send to servers; the page removes it from the
address bar right away. The link is printed in the terminal (and in the log if you redirect
output to a file): treat it like a password.

## OAuth details

- PKCE `S256` on every login; hydra-mcp refuses authorization servers that do not advertise it.
- `state` is 32 random bytes, stored server side, deleted on first use, valid 10 minutes.
- `resource` (RFC 8707) is sent on authorization, token and refresh requests, so tokens are bound
  to the upstream they are for.
- Requested scopes come from the connector library when it has a curated list (Google), else
  from what the server advertises. `offline_access` is added when supported, for refresh tokens.
- The callback URL is fixed: `<public URL>/oauth/callback`. Register exactly that URL at
  providers that need a manual OAuth app, with no wildcard.

## Threat model

**In scope, mitigated:**

- *An AI app tries to use an account or tool it was not granted*, for example because a prompt
  injection asks it to: the account enum only lists granted accounts, and every call is checked
  against the grants before any token is fetched.
- *A web page in your browser tries to call the proxy* (DNS rebinding, cross-site requests):
  `/mcp` rejects any non-loopback `Origin`; the admin API needs the bearer token, which a
  cross-site request cannot read or send.
- *A stolen database backup*: tokens are encrypted with a key that is not in the database.
- *A replayed or forged OAuth callback*: `state` is single-use and tied to a PKCE verifier only
  hydra-mcp knows.
- *A tampered token row copied between accounts*: AEAD associated data makes it fail.
- *A local (stdio) server reading secrets it was not given*: started programs get a short list
  of variables (`PATH`, `HOME`, locale…), the server's shared settings and their own account's
  secrets, never the rest of the proxy's environment.

**Out of scope (not defended against):**

- Malware running as your user: it can read `vault.key` and the database, like any local secret.
- What a granted app does with a granted account. *Read + write* means the AI can send, change
  or delete through that account. Prefer *read only* unless the app needs to write, and keep
  write grants narrow with a tool pattern.
- Prompt injection inside the content the AI reads (an email, a ticket). hydra-mcp limits which
  accounts and tools are reachable; it does not inspect content.
- The upstream servers themselves and their tool annotations: a server that marks a write tool
  `readOnlyHint: true` defeats the *read only* mode for that tool.
- The admin token can start programs. Local (stdio) servers are commands you type in the admin
  page, run as your user, like the `command` entries of any app's MCP config. Whoever has the
  admin token can run any program. Set `HYDRA_MCP_STDIO_ENABLED=false` where that is not wanted.
- Exposing the proxy to a network. It is designed for `127.0.0.1`. If you bind it elsewhere, put
  it behind TLS and a firewall, and know that anyone who reaches `/a/{account}/mcp` can use
  router mode.

## Hardening checklist

- Keep the default `HYDRA_MCP_HOST=127.0.0.1`.
- Use full-disk encryption; keep `~/.hydra-mcp` out of cloud-synced folders.
- One client per app; *read only* by default; tool patterns for write grants.
- Prefer fine-grained, expiring personal tokens over classic ones when you paste a token.
- Rotate a client key (**New key**) if a config file containing it was shared or committed.
- Review connected accounts on the Home page; remove the ones you no longer use. Removing an
  account deletes its token from hydra-mcp; revoke it at the provider too (for example GitHub,
  Settings, Applications) if you want it gone everywhere.
