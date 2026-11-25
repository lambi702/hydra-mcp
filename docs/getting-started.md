# Getting started

This walks through a first setup: install, connect two accounts of the same service, give an AI
app access, and use it. Count about ten minutes, more if a service needs a one-time OAuth app
(Google, GitHub, Slack, Asana).

## 0. Try the demo (optional, one minute)

```bash
uvx hydra-mcp demo        # or: docker run --rm -p 127.0.0.1:8765:8765 ghcr.io/lambi702/hydra-mcp demo
```

The demo starts the proxy with a fake provider, *Demo Tracker*, served by the proxy itself. It
behaves like a real remote MCP server (discovery, dynamic client registration, a sign-in page,
PKCE, tokens), and two of its workspaces, `acme` and `globex`, are already connected through that
flow. The terminal prints the admin page link and a ready `claude mcp add` command for a client
that sees `acme` read + write and `globex` read only. In the admin page, **+ Add another
account** on Demo Tracker opens its sign-in page, where you pick a third workspace.

Everything lives in memory and in a temporary folder that is deleted when you stop it (Ctrl+C):
the demo never touches `~/.hydra-mcp`.

## 1. Install and start

Pick one. All three serve the admin page; none needs Node.

```bash
uvx hydra-mcp                  # uv runs the latest release in a cached environment
pipx install hydra-mcp && hydra-mcp     # or a permanent `hydra-mcp` command
```

```bash
docker run -d --name hydra-mcp -p 127.0.0.1:8765:8765 -v hydra-mcp:/data ghcr.io/lambi702/hydra-mcp
docker logs hydra-mcp          # the admin page link
```

With Docker, publish the port on `127.0.0.1` as above: the proxy holds your tokens, and the
container listens on all its interfaces. Your data is in the `hydra-mcp` volume. If you map
another host port, set `-e HYDRA_MCP_PUBLIC_URL=http://127.0.0.1:<port>` too. A
[`compose.yaml`](../compose.yaml) is in the repository.

**From source** (to contribute; needs uv and Node 20+):

```bash
git clone https://github.com/lambi702/hydra-mcp && cd hydra-mcp
make install build     # Python and Node dependencies, then the admin page
make proxy             # cd proxy && uv run hydra-mcp serve
```

The terminal prints:

```
hydra-mcp 0.2.0
  MCP endpoint  http://127.0.0.1:8765/mcp
  admin page    http://127.0.0.1:8765/admin/#token=…
                (this link logs you in: keep it private)
```

Open the admin page link. The token after `#` is never sent to a server; the page stores it in
your browser and removes it from the address bar. Lost it? `hydra-mcp admin-token` prints it again
(`docker exec hydra-mcp hydra-mcp admin-token` with Docker, `cd proxy && uv run hydra-mcp
admin-token` from source). Add `--open` to `hydra-mcp serve` to open it in your browser.

Everything hydra-mcp keeps lives in `~/.hydra-mcp` (see [Configuration](configuration.md)).

## 2. Connect your accounts

Open **Connections** and pick a connector. Its guide opens first: read *Before you start*, it
lists what the service needs (a plan, an admin approval, a preview program).

Then click **Sign in**. Depending on the service:

- **One click** (Atlassian, Linear, Notion, Sentry, Stripe, Cloudflare, Supabase): hydra-mcp
  registers itself at the service and sends you to its login page.
- **One-time OAuth app** (Google, GitHub, Slack, Asana): these services do not let apps register
  themselves. A wizard lists the steps with direct links and the exact values to paste,
  including the callback URL `http://127.0.0.1:8765/oauth/callback`. You do this once per
  service; every later account is one click. Slack is the exception: one small Slack app per
  workspace (**+ Another workspace** on its card), and its callback uses `localhost`.
- **Token** (GitHub, Linear, Stripe, Cloudflare, Supabase, Notion Business): click *Use a token
  instead*, create a personal token with the link given, paste it. hydra-mcp tries it against
  the service before saving it.

After the login, hydra-mcp suggests a friendly name from who you logged in as (the Atlassian
site, the Google domain, the GitHub login). Keep it or type your own: `work`, `perso`,
`client-acme`. Your AI chooses accounts by this name, so short and distinct works best.

To add a second account of the same service, click **+ Add another account** on its card and log
in as the other identity. For Atlassian, pick the other site in the site dropdown of the
consent page. Logging in as the same identity again only refreshes that account.

> **Tip:** to be sure you log in as the right identity, use a private window or sign out of the
> service first. The provider's page uses whatever session your browser already has.

## 3. Give an AI app access

Open **Clients** and click **+ New client**. Pick a preset (Claude Code, Cursor, VS Code) or type
a name. One client per app keeps their access separate.

Drag accounts from *Your accounts* into the client:

- **Read only** (left): the app only sees tools the service marks as read-only (`readOnlyHint`).
  Searching Jira works, creating issues does not.
- **Read + write** (right): every tool.

The **⋯** on an account in a client limits it to a tool pattern, for example `search*`.

## 4. Install it in your app

Click **Get setup**. hydra-mcp creates the client's key and shows the config for each app. The
key is shown once: hydra-mcp only keeps its SHA-256 hash. Lost it? **New key** replaces it.

**Claude Code**

```bash
claude mcp add --scope user --transport http hydra http://127.0.0.1:8765/mcp \
  --header "Authorization: Bearer hmcp_…"
```

`--scope user` makes hydra available in every folder. Without it, Claude Code only sees it in the
folder where you ran the command.

**Cursor** (`~/.cursor/mcp.json`, or `.cursor/mcp.json` in a project)

```json
{
  "mcpServers": {
    "hydra": {
      "url": "http://127.0.0.1:8765/mcp",
      "headers": { "Authorization": "Bearer hmcp_…" }
    }
  }
}
```

**VS Code** (`.vscode/mcp.json`, or *MCP: Open User Configuration*)

```json
{
  "servers": {
    "hydra": {
      "type": "http",
      "url": "http://127.0.0.1:8765/mcp",
      "headers": { "Authorization": "Bearer hmcp_…" }
    }
  }
}
```

**Any other app**: Streamable HTTP at `http://127.0.0.1:8765/mcp` with the header
`Authorization: Bearer hmcp_…`.

**Claude Desktop**: the *Claude Desktop* tab gives a block for `claude_desktop_config.json`
that starts `hydra-mcp bridge`, a small local relay. No tunnel. See
[Claude Desktop](clients/claude-desktop.md).

**claude.ai** (and Claude mobile) connects from Anthropic's servers, so it needs hydra-mcp on a
public HTTPS address (a tunnel), and signs in with OAuth instead of a key. See
[claude.ai](clients/claude-ai.md).

## 5. Use it

Ask your AI something that names an account:

- "List my open Jira issues on acme."
- "Search the globex Confluence for the onboarding page."
- "Compare my open PRs on work and perso GitHub."

Every tool has an `account` argument listing the accounts this client may use, so the AI picks
one, or asks you when it is unclear. hydra-mcp also tells the AI never to guess the account for
an action that sends, modifies or deletes.

## Day to day

- **Home** shows where your setup stands and which accounts need a reconnect.
- An account shows *not connected* when its token expired and could not be refreshed, or was
  revoked at the service. Click **Reconnect** (or **New token** for a pasted token).
- Removing an account deletes its token; clients that had it simply lose that account.

Next: [how it works](architecture.md), [security model](security.md),
[troubleshooting](troubleshooting.md).
