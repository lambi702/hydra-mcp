# Configuration

hydra-mcp works without configuration. Settings come from environment variables prefixed with
`HYDRA_MCP_`, or from a `.env` file in the directory you start it from (`proxy/` with `make
proxy`). With Docker, pass them with `-e` (the image sets `HYDRA_MCP_HOST=0.0.0.0` and
`HYDRA_MCP_DATA_DIR=/data`). A template is in [`.env.example`](../.env.example).

| Variable | Default | Meaning |
| --- | --- | --- |
| `HYDRA_MCP_HOST` | `127.0.0.1` | Interface to listen on. Keep the loopback default unless you know why not (see [security](security.md)). |
| `HYDRA_MCP_PORT` | `8765` | Port. |
| `HYDRA_MCP_PUBLIC_URL` | `http://127.0.0.1:<port>` | The URL your apps and browser use to reach the proxy. When unset it follows the port (and the host, unless that is `0.0.0.0`). Set it behind a tunnel, a reverse proxy, or a Docker port mapped to another host port. It builds the OAuth callback (`<public URL>/oauth/callback`) and the router-mode resources, so it must match exactly what you register at providers and paste into apps. Change it together with the port. |
| `HYDRA_MCP_EXTERNAL_URL` | empty | Public HTTPS address of this proxy (a tunnel), for apps that connect from their own servers: claude.ai, Claude Desktop custom connectors. Only `/mcp` and the app login (`/oauth/*`, `/.well-known/*`) answer there. See [claude.ai](clients/claude-ai.md). |
| `HYDRA_MCP_DATA_DIR` | `~/.hydra-mcp` | Database, vault key and admin token. |
| `HYDRA_MCP_ADMIN_TOKEN` | generated | Fixed admin token. When empty, one is generated on first start and kept in `<data dir>/admin_token`. |
| `HYDRA_MCP_ADMIN_DIST` | the packaged page | Built admin page to serve at `/admin/`. By default: `admin/dist` in a source checkout after `make build`, else the copy shipped inside the package. |
| `HYDRA_MCP_UPSTREAM_TIMEOUT_S` | `300` | Timeout for calls to upstream servers, in seconds. |
| `HYDRA_MCP_STDIO_ENABLED` | `true` | Allow [local (stdio) servers](local-servers.md). Turn off where the admin page must not start programs. |
| `HYDRA_MCP_STDIO_IDLE_S` | `900` | A local server process unused this long is stopped; the next call starts it again. |

Commands:

| Command | What it does |
| --- | --- |
| `hydra-mcp` or `hydra-mcp serve [--host H] [--port P] [--open] [--reload]` | Run the proxy. `--open` opens the admin page in your browser; `--reload` is for development. |
| `hydra-mcp demo [--port P] [--no-open]` | Run the demo: a fake provider and two connected accounts, in a temporary data directory deleted on exit. Ignores `HYDRA_MCP_DATA_DIR` and `HYDRA_MCP_ADMIN_TOKEN`. |
| `hydra-mcp admin-token` | Print the admin token. |
| `hydra-mcp bridge [--url URL]` | A stdio MCP server relaying to a running hydra-mcp, for [Claude Desktop](clients/claude-desktop.md). Reads `HYDRA_MCP_KEY` and `HYDRA_MCP_URL`. |
| `hydra-mcp --version` | Print the version. |

## Changing the port

```bash
hydra-mcp --port 9000          # the public URL follows: http://127.0.0.1:9000
```

Then update the callback URL in the OAuth apps you created by hand (Google, GitHub, Slack, Asana) and the
URL in your apps' MCP config.

## The data directory

| File | Content | Back it up? |
| --- | --- | --- |
| `hydra-mcp.sqlite3` | servers, accounts, clients, grants, encrypted tokens | yes |
| `vault.key` | the encryption key for tokens and secrets | yes, separately and safely: without it the tokens are unreadable |
| `admin_token` | the admin page token | optional |
| `stdio/<account>/` | home folders of local servers with *separate home folder* | if those servers keep a login there |

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
  <key>ProgramArguments</key>
  <array><string>/opt/homebrew/bin/uvx</string><string>hydra-mcp</string><string>serve</string></array>
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
ExecStart=%h/.local/bin/uvx hydra-mcp serve
Restart=on-failure

[Install]
WantedBy=default.target
```

**Docker**: `--restart unless-stopped` on `docker run`, or `docker compose up -d` with the
repository's [`compose.yaml`](../compose.yaml), keeps it running across reboots.

The log contains the admin login link: keep it in the data directory or another private place.

## Development mode

`make dev` runs the proxy with auto-reload and the admin page with hot reload on
`http://localhost:5173/admin/` (API calls are proxied to `:8765`). See
[CONTRIBUTING.md](../CONTRIBUTING.md).
