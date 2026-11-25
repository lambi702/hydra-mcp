# Local servers (stdio)

Many MCP servers are not hosted anywhere: you install them and an app starts them as a program
(`npx some-mcp-server`, `uvx some-mcp-server`, a binary). They talk MCP over the program's stdin
and stdout. hydra-mcp can start them too, which gives them what they lack on their own: several
accounts, and per-app access.

## Why one process per account

A local server reads its credentials once, when it starts: from an environment variable
(`GITHUB_PERSONAL_ACCESS_TOKEN=…`) or from a file it wrote after a browser login (often under
`~/.config/…`). It has no idea which person, or which account, is calling it. So the only way to
use the same server with two identities is to run it twice, each copy with its own environment.

That is what hydra-mcp does. For a server added once, each account gets:

- its own process, started on the first call that needs it and stopped after
  `HYDRA_MCP_STDIO_IDLE_S` seconds without use (15 minutes by default);
- its own secret settings (`KEY=value` lines), stored encrypted in the vault like OAuth tokens,
  and never shown again in the admin page;
- optionally its own home folder (`~/.hydra-mcp/stdio/<account>`), for servers that save a
  browser login under `~`.

Everything else works as for remote servers: the tools of every account are merged into one
`{server}__{tool}` tool with an `account` argument, grants are checked on every call, and
*read only* grants only show tools the server marks `readOnlyHint`.

```
AI app ──/mcp──> hydra-mcp ──stdin/stdout──> github-mcp-server  (GITHUB_TOKEN=work token)
                           └─stdin/stdout──> github-mcp-server  (GITHUB_TOKEN=perso token)
```

## Adding one

**Connections**, **+ Add a connector**, then *A local server you run with a command (stdio)*.

| Field | Example | Notes |
| --- | --- | --- |
| Name | `GitHub (local)` | Becomes the tool prefix (`github-local__…`). |
| Command | `npx` | Run directly, **not through a shell**: no quotes, `~`, `$VAR` or pipes. If the program is not on the `PATH` of the hydra-mcp process, give its full path (`/opt/homebrew/bin/npx`). |
| Arguments | `-y` and `@scope/server` | One per line, passed as is. |
| Shared settings | `LOG_LEVEL=info` | Not secret, the same for every account. Visible in the admin page. |
| Separate home folder | off | Turn on when the server keeps a login in `~/.config`, `~/.cache`… |
| Account name | `work` | What your AI picks. |
| Secrets | `GITHUB_PERSONAL_ACCESS_TOKEN=github_pat_…` | This account's credentials. Encrypted. |

**Check and save** starts the program once with these settings and asks for its tool list. If
the program does not start, exits, or does not answer, nothing is saved and you see the reason,
usually the last lines the program printed ("token invalid", "command not found").

The next account of the same server only needs a name and its secrets: **+ Add another account**
on the server's card. **New secrets** replaces an account's secrets and restarts its process.

## What the program inherits

A started program gets only:

- from the hydra-mcp process: `PATH`, `HOME`, `USER`, `LOGNAME`, `SHELL`, `TERM`, `LANG`,
  `LC_ALL`, `TMPDIR` (and on Windows `SYSTEMROOT`, `APPDATA`, `LOCALAPPDATA`, `PROGRAMFILES`);
- the server's shared settings;
- the account's secrets;
- with *separate home folder*: `HOME`, `USERPROFILE` and the `XDG_*` folders pointing to the
  account's own folder.

Nothing else: the admin token, cloud credentials or other secrets in the environment of
hydra-mcp never reach a started program. Its working directory is the account's folder (with
*separate home folder*) or the data directory.

## Servers that log in with a browser

Some local servers open a browser on first start and save the result under `~`. With *separate
home folder* on, each account keeps its own login. The first call of each account then triggers
that server's own login flow, on the machine where hydra-mcp runs. The probe on **Check and
save** may time out while that login is pending: finish the login, then save again.

When the server is also available as a remote (HTTP) server, prefer that: hydra-mcp then does
the login itself, in the admin page, and refreshes the tokens.

## Limits

- Server-to-app requests are not relayed: sampling, elicitation, roots. hydra-mcp answers
  `ping` and refuses the rest, as it does for remote servers.
- Notifications from the server (logs, progress, list changes) are not relayed. The tool list
  is cached for 5 minutes.
- Router mode (`/a/{account}/mcp`) only forwards to remote servers.
- Running commands is powerful: anyone with the admin token can make hydra-mcp start any
  program as your user. On a shared host, set `HYDRA_MCP_STDIO_ENABLED=false`.

## Troubleshooting

- **cannot start 'npx': No such file or directory.** hydra-mcp does not see the same `PATH` as
  your terminal, typically when it runs from launchd or systemd. Use the full path
  (`which npx` in your terminal).
- **the local server exited with code 1; its last output: …** The server refused its settings.
  The output usually names the missing or wrong variable.
- **no answer to initialize within 300s.** The program started but does not speak MCP on
  stdio, or waits for a login. Check that its arguments select the stdio transport (some
  servers need `stdio` or `--transport stdio`).
- A server that prints text on stdout before speaking MCP breaks the protocol for most clients;
  hydra-mcp skips lines that are not JSON and shows them in the error if the start fails.
