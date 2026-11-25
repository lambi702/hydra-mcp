# Troubleshooting

Start with the proxy's terminal output: every upstream call that fails is logged with the
account and the server's answer. Per-service pitfalls are in [connector guides](connectors.md).

## Installing and opening the admin page

**The admin page says "Not found" or is blank.** The page was not built. Run `make build` (or
`cd admin && npm install && npm run build`) and restart the proxy.

**"That admin token was not accepted".** The token changed (a new data directory, or
`HYDRA_MCP_ADMIN_TOKEN` was set). Run `cd proxy && uv run hydra-mcp admin-token` and paste it, or
use the link printed at start.

**Address already in use.** Something else uses port 8765. Pick another port and update the
public URL with it (see [configuration](configuration.md#changing-the-port)).

## Connecting an account

**"does not allow automatic registration" / the setup wizard opens.** Expected for Google,
GitHub and Asana: create the one-time OAuth app with the wizard's steps. For a server added by
URL, check its docs for "OAuth app" or "client ID".

**The provider says `redirect_uri` mismatch.** The callback registered in the provider's OAuth
app must be exactly `<public URL>/oauth/callback`, for example
`http://127.0.0.1:8765/oauth/callback`: same host (`127.0.0.1` is not `localhost`), same port,
same path, no trailing slash. GitHub's form calls it *Redirect URI*, Google's *Authorized
redirect URI*.

**"This connection link is invalid or expired".** The login took more than 10 minutes, or the
page was reloaded after it finished. Start again from the admin page.

**I logged in as the wrong identity.** The provider used the session your browser already had.
Remove the account, sign out at the provider (or use a private window), and connect again.

**Google: `access_denied` or "app has not completed the Google verification process".** Your
address is not a test user of the consent screen. Add it under *Audience, Test users*.

**Google: tools fail with 403 after a successful login.** Check, in this order: your account is
enrolled in the Workspace Developer Preview Program; both APIs of the product are enabled (for
example `gmail.googleapis.com` and `gmailmcp.googleapis.com`); the OAuth client was created with
*Use this client for an AI-powered agent* ticked.

**Atlassian: the account reaches the wrong site.** The consent page has a site dropdown; the site
selected when you clicked *Accept* is the one this account reaches. Reconnect and pick the other
site.

**"refused this token" when pasting a token.** The token is incomplete, expired, or lacks the
permissions the guide lists. For GitHub fine-grained tokens, check the selected repositories and
the organization's approval of fine-grained tokens.

## Using it from an app

**The app shows no tools.** Check, in the admin page: the client has at least one account in a
zone; the account shows *connected*; the app uses this client's current key (after **New key**,
the old one stops working). Then restart or reload the MCP server in the app.

**401 "missing or unknown client key".** The `Authorization` header is missing or the key was
replaced. Copy the setup again from **Clients, Get setup** (this creates a new key).

**403 "origin not allowed".** A browser-based client sent a non-loopback `Origin`. hydra-mcp only
accepts requests from `127.0.0.1`, `localhost` or `::1` origins.

**A tool is missing in read only.** Read only exposes only tools the server annotates
`readOnlyHint: true`. Tools without that annotation count as writes. Move the account to *read +
write* with a tool pattern if you need that one tool.

**"account '…' is not connected" / "refresh failed, reconnect it".** The token expired without a
refresh token, or the provider revoked it. Click **Reconnect** on the account (or **New token**).
Some providers cap session length (Stripe: 14 days; Google apps in Testing: refresh tokens may
expire after 7 days).

**The AI picks the wrong account.** Give accounts distinct, meaningful names (`client-acme`
rather than `account2`), and name the account in your request. The tool's `account` argument
lists each name with its identity.

**Claude Desktop or claude.ai cannot connect.** They connect from Anthropic's servers and cannot
reach `127.0.0.1`. Not supported yet.

## Slack

**`bad_redirect_uri` on Slack's page.** The Redirect URL of the Slack app must be exactly the one
the wizard shows (`http://localhost:8765/oauth/callback` by default, `localhost` and not
127.0.0.1), and the app must have PKCE turned on: Slack accepts plain-http callbacks only on
`localhost` and only from PKCE apps. Behind an https public URL, register that one instead.

**`invalid_team_for_non_distributed_app`.** The Slack app was created in another workspace. Each
workspace needs its own app: use **+ Another workspace** on the Slack card.

**The consent page says the app needs approval, or tools fail with `not_allowed`.** A workspace
admin must approve the app and allow MCP clients. Then click **Reconnect**.

## Still stuck?

[Open an issue](https://github.com/lambi702/hydra-mcp/issues/new?template=bug_report.yml) with
the hydra-mcp version, your OS, the connector, what you did and the relevant log lines. Remove
tokens, keys and email addresses from logs before posting.
