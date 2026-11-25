# claude.ai (and Claude mobile)

claude.ai connects to MCP servers **from Anthropic's servers**, not from your browser. So it
cannot reach `http://127.0.0.1:8765`: hydra-mcp needs a public HTTPS address, which a tunnel
gives you without opening your router. And claude.ai custom connectors cannot send a static
key: they sign in with OAuth. hydra-mcp includes the OAuth server they need.

```
claude.ai servers --HTTPS--> tunnel --> hydra-mcp on your machine --> Gmail, Jira, Slack…
        ↑ login once                     /oauth/* consent page: you pick the client
     your browser ----------------------^
```

What you need: a Claude plan that allows custom connectors, hydra-mcp running, and a tunnel.

## 1. Pick a tunnel with a stable address

The connector URL is saved in claude.ai, so it should not change. Port 443 only: claude.ai does
not connect to other ports.

| Tunnel | Command | Address | Notes |
| --- | --- | --- | --- |
| **Tailscale Funnel** (recommended) | `tailscale funnel --bg 8765` | `https://<machine>.<tailnet>.ts.net` | Free, stable, nothing to buy. Funnel must be enabled for your tailnet (the command tells you how the first time). |
| Cloudflare Tunnel (named) | `cloudflared tunnel run hydra` after `cloudflared tunnel create hydra` and a DNS route | a hostname on your own domain | Needs a domain on Cloudflare. Quick tunnels (`cloudflared tunnel --url …`) get a new random address at each start: fine to try, not to keep. |
| ngrok | `ngrok http 8765 --url=<your-domain>.ngrok-free.app` | your free static domain | Free plans show an interstitial page in the browser before the login page: click through. |

These commands are the tunnels' own; check their docs if a flag changed.

## 2. Tell hydra-mcp its public address

Restart hydra-mcp with the tunnel address:

```bash
HYDRA_MCP_EXTERNAL_URL=https://mymac.tail1234.ts.net uv run hydra-mcp serve
```

(or put `HYDRA_MCP_EXTERNAL_URL=…` in `proxy/.env`). The terminal now prints an `external`
line ending in `/mcp`. Keep `HYDRA_MCP_PUBLIC_URL` as it is: the admin page and the logins at
Google, GitHub, Slack… keep using the local address, so nothing you set up earlier changes.

Through the tunnel, hydra-mcp only answers the MCP endpoint and the app login pages. The admin
page, the admin API, provider callbacks and router mode answer 404 there, even with the admin
token. See [security](../security.md#the-external-url).

## 3. Add the connector in claude.ai

1. In hydra-mcp's admin page, **Clients**: create a client for claude.ai (for example
   *Claude*) and drag in the accounts it may use. **Get setup**, tab **claude.ai**, shows the
   URL to use. You do not need the key.
2. claude.ai: **Settings**, **Connectors**, **Add custom connector**. Name: `hydra`. URL: your
   external URL followed by `/mcp`, for example `https://mymac.tail1234.ts.net/mcp`. Leave the
   OAuth client ID and secret empty: claude.ai registers itself.
3. Click **Connect**. A hydra-mcp page opens: **Allow Claude to use hydra-mcp?**
   - *Use the access of*: pick the client from step 1. A client with the same name as the app
     is preselected. *New client* creates an empty one, which you then fill in the admin page.
   - *Admin token*: `hydra-mcp admin-token` prints it. It proves that you, the owner of this
     hydra-mcp, approve the login.
4. **Allow**. You are back in claude.ai, connected. In a chat, enable `hydra` in the tools menu
   and ask: "list my open Jira issues on acme".

The connector also appears in Claude Desktop and the mobile apps, since it belongs to your Claude
account.

## Managing access

- **What claude.ai may do** is the client's grants: change them in **Clients**, they apply at
  the next call, no reconnect needed.
- **Sign out claude.ai**: the client card shows *Claude signed in*; its **×** revokes the login.
  claude.ai then asks to connect again.
- Sessions: an access token lasts one hour and is renewed by claude.ai on its own; the renewal
  token lasts 30 days from its last use and changes at every renewal. A renewal token used twice
  (a stolen copy) revokes the login.

## Troubleshooting

- **claude.ai says it cannot reach the server.** Open `https://<your address>/healthz` from
  your phone on mobile data: it must answer `{"ok": true…}`. If not, the tunnel is down or
  hydra-mcp is not running.
- **The connector connects but shows no tools.** The client picked on the consent page has no
  accounts, or its accounts are *not connected*. Check **Clients** and **Home**.
- **"Unknown application" on the login page.** hydra-mcp forgot an unfinished registration
  (unused for a day). Remove the connector in claude.ai and add it again.
- **"Wrong admin token".** Copy it again with `hydra-mcp admin-token`. After 10 wrong tries in
  10 minutes the page refuses for a while.
- **The address changed** (a quick tunnel restarted): update `HYDRA_MCP_EXTERNAL_URL`, then
  remove and re-add the connector in claude.ai, since its URL cannot be edited.

## Restricting the tunnel further (optional)

claude.ai's servers connect from `160.79.104.0/21` (Anthropic's published range). If your tunnel
can filter by IP, you may restrict `/mcp`, `/oauth/token`, `/oauth/register` and
`/.well-known/*` to that range. Leave `/oauth/authorize` open: it is opened by **your browser**,
not by Anthropic's servers.
