# hydra-mcp

<!-- mcp-name: io.github.lambi702/hydra-mcp -->

**One MCP endpoint, every account.** A self-hosted proxy that lets Claude Code, Cursor, VS Code
and any MCP client use *several accounts of the same service*: two Gmail inboxes, three Atlassian
sites, work and personal GitHub. You decide which app sees which account, read only or
read + write.

Each tool appears once (`atlassian__searchJiraIssuesUsingJql`) with an extra `account` argument
(`"acme"`, `"globex"`). Your AI picks the account by its friendly name; hydra-mcp sends the call
with that account's token. Login stays with each provider (OAuth 2.1 + PKCE), tokens are encrypted
at rest, and everything runs on your machine.

## Try it in one minute

No account, no OAuth app: the demo runs a fake provider with two workspaces already connected.

```bash
uvx hydra-mcp demo
```

## Install

```bash
uvx hydra-mcp            # run without installing (needs uv)
pipx install hydra-mcp   # or install the `hydra-mcp` command
hydra-mcp                # starts on http://127.0.0.1:8765 and prints the admin page link
```

Or with Docker:

```bash
docker run -d --name hydra-mcp -p 127.0.0.1:8765:8765 -v hydra-mcp:/data \
  ghcr.io/lambi702/hydra-mcp
docker logs hydra-mcp    # prints the admin page link
```

Requires Python 3.11+. The admin page is included in the package: no Node needed.

## Links

- Source, screenshots and full README: <https://github.com/lambi702/hydra-mcp>
- Getting started: <https://github.com/lambi702/hydra-mcp/blob/main/docs/getting-started.md>
- Connector guides: <https://github.com/lambi702/hydra-mcp/blob/main/docs/connectors.md>
- Security model: <https://github.com/lambi702/hydra-mcp/blob/main/docs/security.md>

Apache-2.0. Not affiliated with Anthropic, Atlassian, Google, GitHub or any provider it connects
to.
