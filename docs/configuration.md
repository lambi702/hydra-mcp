# Configuration

hydra-mcp works without configuration. Settings come from environment variables prefixed with
`HYDRA_MCP_`, or from a `.env` file in the directory you start it from (`proxy/` with `make
proxy`). A template is in [`.env.example`](../.env.example).

| Variable | Default | Meaning |
| --- | --- | --- |
| `HYDRA_MCP_HOST` | `127.0.0.1` | Interface to listen on. Keep the loopback default unless you know why not (see [security](security.md)). |
| `HYDRA_MCP_PORT` | `8765` | Port. |
| `HYDRA_MCP_PUBLIC_URL` | `http://127.0.0.1:8765` | The URL your apps and browser use to reach the proxy. It builds the OAuth callback (`<public URL>/oauth/callback`) and the router-mode resources, so it must match exactly what you register at providers and paste into apps. Change it together with the port. |
| `HYDRA_MCP_EXTERNAL_URL` | empty | Public HTTPS address of this proxy (a tunnel), for apps that connect from their own servers: claude.ai, Claude Desktop custom connectors. Only `/mcp` and the app login (`/oauth/*`, `/.well-known/*`) answer there. See [claude.ai](clients/claude-ai.md). |
| `HYDRA_MCP_DATA_DIR` | `~/.hydra-mcp` | Database, vault key and admin token. |
| `HYDRA_MCP_ADMIN_TOKEN` | generated | Fixed admin token. When empty, one is generated on first start and kept in `<data dir>/admin_token`. |
| `HYDRA_MCP_ADMIN_DIST` | `admin/dist` of the checkout | Built admin page to serve at `/admin/`. |
| `HYDRA_MCP_UPSTREAM_TIMEOUT_S` | `300` | Timeout for calls to upstream servers, in seconds. |

Command-line flags: `hydra-mcp serve [--host H] [--port P] [--reload]`, `hydra-mcp
admin-token` (prints the admin token) and `hydra-mcp bridge [--url URL]` (a stdio MCP server
relaying to a running hydra-mcp, for [Claude Desktop](clients/claude-desktop.md); reads
`HYDRA_MCP_KEY` and `HYDRA_MCP_URL`).

## Changing the port

```bash
HYDRA_MCP_PORT=9000 HYDRA_MCP_PUBLIC_URL=http://127.0.0.1:9000 uv run hydra-mcp serve
```

Then update the callback URL in the OAuth apps you created by hand (Google, GitHub, Asana) and the
URL in your apps' MCP config.

## The data directory

| File | Content | Back it up? |
| --- | --- | --- |
| `hydra-mcp.sqlite3` | servers, accounts, clients, grants, encrypted tokens | yes |
| `vault.key` | the encryption key for tokens and secrets | yes, separately and safely: without it the tokens are unreadable |
| `admin_token` | the admin page token | optional |

To move hydra-mcp to another machine, copy the whole directory with its permissions. To start
from scratch, stop the proxy and delete it.

## Running it in the background

**macOS (launchd)**: save as `~/Library/LaunchAgents/dev.hydra-mcp.plist`, adjusting the paths,
then `launchctl load ~/Library/LaunchAgents/dev.hydra-mcp.plist`.

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>dev.hydra-mcp</string>
  <key>WorkingDirectory</key><string>/Users/YOU/hydra-mcp/proxy</string>
  <key>ProgramArguments</key>
  <array><string>/opt/homebrew/bin/uv</string><string>run</string><string>hydra-mcp</string><string>serve</string></array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>/Users/YOU/.hydra-mcp/proxy.log</string>
  <key>StandardErrorPath</key><string>/Users/YOU/.hydra-mcp/proxy.log</string>
</dict>
</plist>
```

**Linux (systemd user service)**: save as `~/.config/systemd/user/hydra-mcp.service`, then
`systemctl --user enable --now hydra-mcp`.

```ini
[Unit]
Description=hydra-mcp

[Service]
WorkingDirectory=%h/hydra-mcp/proxy
ExecStart=%h/.local/bin/uv run hydra-mcp serve
Restart=on-failure

[Install]
WantedBy=default.target
```

The log contains the admin login link: keep it in the data directory or another private place.

## Development mode

`make dev` runs the proxy with auto-reload and the admin page with hot reload on
`http://localhost:5173/admin/` (API calls are proxied to `:8765`). See
[CONTRIBUTING.md](../CONTRIBUTING.md).
