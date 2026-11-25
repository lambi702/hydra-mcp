# Claude Desktop

Two ways to use hydra-mcp from Claude Desktop. Pick the first unless you also want hydra-mcp in
claude.ai on the web or on your phone.

| | Local bridge (recommended) | Custom connector |
| --- | --- | --- |
| Where Claude connects from | your Mac or PC | Anthropic's servers |
| Needs a public HTTPS URL (tunnel) | no | yes |
| Also available in claude.ai and mobile | no | yes, the connector follows your Claude account |
| Sign-in | a client key in a config file | hydra-mcp's own login page (OAuth) |

## Local bridge

Claude Desktop starts local MCP servers as commands. It cannot send an HTTP header to a local
URL, so hydra-mcp ships a tiny command that does it: `hydra-mcp bridge` reads MCP messages from
Claude Desktop on stdin, forwards each one to `http://127.0.0.1:8765/mcp` with the client key,
and writes the answers back.

```
Claude Desktop --stdin/stdout--> hydra-mcp bridge --HTTP + key--> hydra-mcp serve --> Gmail, Jira…
```

1. In the admin page, **Clients**, **+ New client**, preset *Claude Desktop*. Drag in the
   accounts it may use.
2. **Get setup**, tab **Claude Desktop**. Copy the JSON. It already holds the full path of your
   `hydra-mcp` command and the new key.
3. In Claude Desktop: **Settings**, **Developer**, **Edit Config**. This opens
   `claude_desktop_config.json`:
   - macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
   - Windows: `%APPDATA%\Claude\claude_desktop_config.json`

   Merge the copied `hydra` entry into its `mcpServers` object (keep the servers already there),
   and save.
4. Quit Claude Desktop completely and open it again. `hydra` appears in the tools menu of a
   new chat.

```json
{
  "mcpServers": {
    "hydra": {
      "command": "/Users/you/hydra-mcp/proxy/.venv/bin/hydra-mcp",
      "args": ["bridge"],
      "env": {
        "HYDRA_MCP_KEY": "hmcp_…",
        "HYDRA_MCP_URL": "http://127.0.0.1:8765/mcp"
      }
    }
  }
}
```

If you run hydra-mcp with `uvx`, the snippet instead says `"command": "/path/to/uvx"` and
`"args": ["hydra-mcp", "bridge"]`: uvx keeps its environments in a cache it may clean, so the
config must not point inside it.

`hydra-mcp serve` must be running (see [running it in the background](../configuration.md#running-it-in-the-background)).
The bridge itself keeps nothing: grants change in the admin page apply to the next call.

**If the tools do not show up:** Claude Desktop writes each server's output to
`~/Library/Logs/Claude/mcp-server-hydra.log` (macOS) or `%APPDATA%\Claude\logs` (Windows).

- `hydra-mcp is not reachable at http://127.0.0.1:8765/mcp`: start `hydra-mcp serve`.
- `hydra-mcp refused the client key`: the key was replaced (**New key**) or the client deleted.
  Get a new setup and update the config.
- `No such file or directory`: the `command` path moved (a new checkout or virtualenv). Copy the
  snippet again.

## Custom connector

Custom connectors in Claude Desktop are the same as in claude.ai: they are stored in your Claude
account and Anthropic's servers connect to hydra-mcp. Follow the [claude.ai guide](claude-ai.md);
the connector then appears in Claude Desktop too (**Settings**, **Connectors**).
