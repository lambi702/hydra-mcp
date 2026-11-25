# Connector guides

<!-- Generated from proxy/src/hydra_mcp/catalog/connectors.json by `python -m hydra_mcp.catalog.docs`. Edit the JSON, not this file. -->

Checked against each vendor's documentation on 2026-11-25. The admin page shows the same guide when you pick a connector.

| Connector | Sign-in | Token option |
| --- | --- | --- |
| [Gmail](#gmail) | one-time OAuth client |  |
| [Google Drive](#google-drive) | one-time OAuth client |  |
| [Google Calendar](#google-calendar) | one-time OAuth client |  |
| [Google Docs](#google-docs) | one-time OAuth client |  |
| [Google Sheets](#google-sheets) | one-time OAuth client |  |
| [Google Slides](#google-slides) | one-time OAuth client |  |
| [Google Chat](#google-chat) | one-time OAuth client |  |
| [Google Workspace search](#google-workspace-search) | one-time OAuth client |  |
| [Atlassian (Jira, Confluence)](#atlassian-jira-confluence) | one click |  |
| [Linear](#linear) | one click | Linear API key |
| [Notion](#notion) | one click | Notion MCP token (Business and Enterprise) |
| [GitHub](#github) | one-time OAuth client | GitHub personal access token |
| [Slack](#slack) | one-time OAuth client |  |
| [Sentry](#sentry) | one click |  |
| [Stripe](#stripe) | one click | Stripe agent API key |
| [Asana](#asana) | one-time OAuth client |  |
| [Cloudflare API](#cloudflare-api) | one click | Cloudflare API token |
| [Supabase](#supabase) | one click | Supabase personal access token |

## Gmail

Google's official Gmail MCP server. Each Google account (personal Gmail or Workspace) becomes one hydra-mcp account.

- **URL:** `https://gmailmcp.googleapis.com/mcp/v1`
- **Sign-in:** One-time setup: create an OAuth client at the provider, then each account is one click.
- **Status:** Developer Preview

**Before you start**

- A Google Cloud project (free). One project and one OAuth client serve every Google connector and every Google account.
- About 10 minutes the first time, to create that OAuth client. The next Gmail or Google accounts connect in one click.
- Enrollment of your Google Cloud project in the Google Workspace Developer Preview Program (link below). Google reviews requests by hand, so ask a few days ahead. Without it, login and the tool list work but every tool call fails with 'Access to this tool requires that your Google Cloud project (…) is enrolled in the Google Workspace Developer Preview Program'. A project inside a company organization may need a Workspace admin to enroll it.

**Several accounts**

Add as many Google accounts as you like. In Testing mode, each address must first be added as a test user on the consent screen.

**One-time setup: Web application, for an AI agent at Google**

1. **Join the Google Workspace Developer Preview Program.** The Workspace MCP servers are in Developer Preview: Google only serves them to enrolled accounts. Skip this if you are already in. [Open](https://developers.google.com/workspace/preview)
2. **Pick or create a Google Cloud project.** Any project works. One project serves all your Google accounts and all the Google connectors: reuse it for the next ones. [Open](https://console.cloud.google.com/projectcreate)
3. **Enable the APIs.** Enable gmail.googleapis.com and gmailmcp.googleapis.com. The page asks you to confirm the project. [Open](https://console.cloud.google.com/flows/enableapi?apiid=gmail.googleapis.com,gmailmcp.googleapis.com)
4. **Set up the consent screen.** Click Get started. App name: hydra-mcp. Support email: yours. Audience: External (Internal if every account is in your own Workspace). Leave the app in Testing: no Google review is needed for personal use. [Open](https://console.cloud.google.com/auth/branding)
5. **Add your Google addresses as test users.** Audience, Test users, Add users: every Gmail or Workspace address you will connect (work, perso…). In Testing, Google only lets these log in. [Open](https://console.cloud.google.com/auth/audience)
6. **Declare the scopes.** Add these scopes: gmail.readonly, gmail.compose, gmail.modify. Data Access, Add or remove scopes, paste them in 'Manually add scopes', then Save. [Open](https://console.cloud.google.com/auth/scopes)
7. **Create the OAuth client.** Application type: Web application. Name: hydra-mcp. Tick 'Use this client for an AI-powered agent': Google rejects MCP calls from clients without it. Under Authorized redirect URIs, add this one. Create, then copy the client ID and secret Google shows. [Open](https://console.cloud.google.com/auth/clients/create)
   - Authorized redirect URI: `http://127.0.0.1:8765/oauth/callback`
8. **Paste the client ID and secret below.** The secret is stored encrypted on this machine. Then hydra-mcp opens Google's sign-in page, like Claude does.

`http://127.0.0.1:8765/oauth/callback` is the default; the admin page shows your real callback URL (`<public URL>/oauth/callback`).

**Good to know**

- Client type: Web application. Google rejects calls from an OAuth client unless 'Use this client for an AI-powered agent' is ticked on it (Google Auth Platform, Clients). The default Apps Script client cannot have this setting.
- APIs to enable: gmail.googleapis.com and gmailmcp.googleapis.com.
- Scopes asked: gmail.readonly, gmail.compose, gmail.modify (the server advertises about 20, including full mailbox access; hydra-mcp asks only for these three).
- Tools: search and read threads and messages, drafts, labels, trash, spam. No send tool: the AI writes a draft, you send it from Gmail.
- hydra-mcp asks Google for offline access, so it gets a refresh token and you do not log in again every hour.
- Testing-mode apps: Google may expire refresh tokens after 7 days. If an account turns 'not connected', click Reconnect, or publish the consent screen to 'In production' (no review needed for personal use under 100 users, but Google shows an 'unverified app' warning).
- Google recommends screening tool results for prompt injection (Model Armor or similar): mail content is untrusted input for the AI.

**Official docs**

- [Gmail MCP server setup (Google)](https://developers.google.com/workspace/gmail/api/guides/configure-mcp-server)
- [Configure the Workspace MCP servers (Google)](https://developers.google.com/workspace/guides/configure-mcp-servers)
- [Workspace Developer Preview Program](https://developers.google.com/workspace/preview)
- [Securing Workspace MCP servers (prompt injection)](https://developers.google.com/workspace/guides/configure-mcp-security)

## Google Drive

Google's official Drive MCP server. Each Google account (personal Gmail or Workspace) becomes one hydra-mcp account.

- **URL:** `https://drivemcp.googleapis.com/mcp/v1`
- **Sign-in:** One-time setup: create an OAuth client at the provider, then each account is one click.
- **Status:** Developer Preview

**Before you start**

- Your Google Cloud project must be enrolled in the Google Workspace Developer Preview Program (link below; Google reviews requests by hand, so ask a few days ahead): the Workspace MCP servers are not public yet. Without it, login works but every tool call is refused.
- A Google Cloud project (free). One project and one OAuth client serve every Google connector and every Google account.
- About 10 minutes the first time, to create that OAuth client. The next Drive or Google accounts connect in one click.

**Several accounts**

Add as many Google accounts as you like. In Testing mode, each address must first be added as a test user on the consent screen.

**One-time setup: Web application, for an AI agent at Google**

1. **Join the Google Workspace Developer Preview Program.** The Workspace MCP servers are in Developer Preview: Google only serves them to enrolled accounts. Skip this if you are already in. [Open](https://developers.google.com/workspace/preview)
2. **Pick or create a Google Cloud project.** Any project works. One project serves all your Google accounts and all the Google connectors: reuse it for the next ones. [Open](https://console.cloud.google.com/projectcreate)
3. **Enable the APIs.** Enable drive.googleapis.com and drivemcp.googleapis.com. The page asks you to confirm the project. [Open](https://console.cloud.google.com/flows/enableapi?apiid=drive.googleapis.com,drivemcp.googleapis.com)
4. **Set up the consent screen.** Click Get started. App name: hydra-mcp. Support email: yours. Audience: External (Internal if every account is in your own Workspace). Leave the app in Testing: no Google review is needed for personal use. [Open](https://console.cloud.google.com/auth/branding)
5. **Add your Google addresses as test users.** Audience, Test users, Add users: every Gmail or Workspace address you will connect (work, perso…). In Testing, Google only lets these log in. [Open](https://console.cloud.google.com/auth/audience)
6. **Declare the scopes.** Add these scopes: drive.readonly, drive.file. Data Access, Add or remove scopes, paste them in 'Manually add scopes', then Save. [Open](https://console.cloud.google.com/auth/scopes)
7. **Create the OAuth client.** Application type: Web application. Name: hydra-mcp. Tick 'Use this client for an AI-powered agent': Google rejects MCP calls from clients without it. Under Authorized redirect URIs, add this one. Create, then copy the client ID and secret Google shows. [Open](https://console.cloud.google.com/auth/clients/create)
   - Authorized redirect URI: `http://127.0.0.1:8765/oauth/callback`
8. **Paste the client ID and secret below.** The secret is stored encrypted on this machine. Then hydra-mcp opens Google's sign-in page, like Claude does.

`http://127.0.0.1:8765/oauth/callback` is the default; the admin page shows your real callback URL (`<public URL>/oauth/callback`).

**Good to know**

- Google rejects calls from an OAuth client unless 'Use this client for an AI-powered agent' is ticked when the client is created.
- APIs to enable: drive.googleapis.com and drivemcp.googleapis.com.
- Scopes: drive.readonly and drive.file (drive.file only reaches files the app created or you opened with it).
- hydra-mcp asks Google for offline access, so it gets a refresh token and you do not log in again every hour.
- Testing-mode apps: Google may expire refresh tokens after 7 days. If an account turns 'not connected', click Reconnect, or publish the consent screen to 'In production' (no review needed for personal use under 100 users, but Google shows an 'unverified app' warning).

**Official docs**

- [Configure the Workspace MCP servers (Google)](https://developers.google.com/workspace/guides/configure-mcp-servers)
- [Workspace Developer Preview Program](https://developers.google.com/workspace/preview)
- [Securing Workspace MCP servers (prompt injection)](https://developers.google.com/workspace/guides/configure-mcp-security)

## Google Calendar

Google's official Calendar MCP server. Each Google account (personal Gmail or Workspace) becomes one hydra-mcp account.

- **URL:** `https://calendarmcp.googleapis.com/mcp/v1`
- **Sign-in:** One-time setup: create an OAuth client at the provider, then each account is one click.
- **Status:** Developer Preview

**Before you start**

- Your Google Cloud project must be enrolled in the Google Workspace Developer Preview Program (link below; Google reviews requests by hand, so ask a few days ahead): the Workspace MCP servers are not public yet. Without it, login works but every tool call is refused.
- A Google Cloud project (free). One project and one OAuth client serve every Google connector and every Google account.
- About 10 minutes the first time, to create that OAuth client. The next Calendar or Google accounts connect in one click.

**Several accounts**

Add as many Google accounts as you like. In Testing mode, each address must first be added as a test user on the consent screen.

**One-time setup: Web application, for an AI agent at Google**

1. **Join the Google Workspace Developer Preview Program.** The Workspace MCP servers are in Developer Preview: Google only serves them to enrolled accounts. Skip this if you are already in. [Open](https://developers.google.com/workspace/preview)
2. **Pick or create a Google Cloud project.** Any project works. One project serves all your Google accounts and all the Google connectors: reuse it for the next ones. [Open](https://console.cloud.google.com/projectcreate)
3. **Enable the APIs.** Enable calendar-json.googleapis.com and calendarmcp.googleapis.com. The page asks you to confirm the project. [Open](https://console.cloud.google.com/flows/enableapi?apiid=calendar-json.googleapis.com,calendarmcp.googleapis.com)
4. **Set up the consent screen.** Click Get started. App name: hydra-mcp. Support email: yours. Audience: External (Internal if every account is in your own Workspace). Leave the app in Testing: no Google review is needed for personal use. [Open](https://console.cloud.google.com/auth/branding)
5. **Add your Google addresses as test users.** Audience, Test users, Add users: every Gmail or Workspace address you will connect (work, perso…). In Testing, Google only lets these log in. [Open](https://console.cloud.google.com/auth/audience)
6. **Declare the scopes.** Add these scopes: calendar.calendarlist.readonly, calendar.events.freebusy, calendar.events.readonly, calendar.events. Data Access, Add or remove scopes, paste them in 'Manually add scopes', then Save. [Open](https://console.cloud.google.com/auth/scopes)
7. **Create the OAuth client.** Application type: Web application. Name: hydra-mcp. Tick 'Use this client for an AI-powered agent': Google rejects MCP calls from clients without it. Under Authorized redirect URIs, add this one. Create, then copy the client ID and secret Google shows. [Open](https://console.cloud.google.com/auth/clients/create)
   - Authorized redirect URI: `http://127.0.0.1:8765/oauth/callback`
8. **Paste the client ID and secret below.** The secret is stored encrypted on this machine. Then hydra-mcp opens Google's sign-in page, like Claude does.

`http://127.0.0.1:8765/oauth/callback` is the default; the admin page shows your real callback URL (`<public URL>/oauth/callback`).

**Good to know**

- Google rejects calls from an OAuth client unless 'Use this client for an AI-powered agent' is ticked when the client is created.
- APIs to enable: calendar-json.googleapis.com and calendarmcp.googleapis.com.
- Scopes: calendarlist.readonly, events.freebusy, events.readonly, events.
- hydra-mcp asks Google for offline access, so it gets a refresh token and you do not log in again every hour.
- Testing-mode apps: Google may expire refresh tokens after 7 days. If an account turns 'not connected', click Reconnect, or publish the consent screen to 'In production' (no review needed for personal use under 100 users, but Google shows an 'unverified app' warning).

**Official docs**

- [Configure the Workspace MCP servers (Google)](https://developers.google.com/workspace/guides/configure-mcp-servers)
- [Workspace Developer Preview Program](https://developers.google.com/workspace/preview)
- [Securing Workspace MCP servers (prompt injection)](https://developers.google.com/workspace/guides/configure-mcp-security)

## Google Docs

Google's official Docs MCP server. Each Google account (personal Gmail or Workspace) becomes one hydra-mcp account.

- **URL:** `https://docsmcp.googleapis.com/mcp/v1`
- **Sign-in:** One-time setup: create an OAuth client at the provider, then each account is one click.
- **Status:** Developer Preview

**Before you start**

- Your Google Cloud project must be enrolled in the Google Workspace Developer Preview Program (link below; Google reviews requests by hand, so ask a few days ahead): the Workspace MCP servers are not public yet. Without it, login works but every tool call is refused.
- A Google Cloud project (free). One project and one OAuth client serve every Google connector and every Google account.
- About 10 minutes the first time, to create that OAuth client. The next Docs or Google accounts connect in one click.

**Several accounts**

Add as many Google accounts as you like. In Testing mode, each address must first be added as a test user on the consent screen.

**One-time setup: Web application, for an AI agent at Google**

1. **Join the Google Workspace Developer Preview Program.** The Workspace MCP servers are in Developer Preview: Google only serves them to enrolled accounts. Skip this if you are already in. [Open](https://developers.google.com/workspace/preview)
2. **Pick or create a Google Cloud project.** Any project works. One project serves all your Google accounts and all the Google connectors: reuse it for the next ones. [Open](https://console.cloud.google.com/projectcreate)
3. **Enable the APIs.** Enable docs.googleapis.com and docsmcp.googleapis.com. The page asks you to confirm the project. [Open](https://console.cloud.google.com/flows/enableapi?apiid=docs.googleapis.com,docsmcp.googleapis.com)
4. **Set up the consent screen.** Click Get started. App name: hydra-mcp. Support email: yours. Audience: External (Internal if every account is in your own Workspace). Leave the app in Testing: no Google review is needed for personal use. [Open](https://console.cloud.google.com/auth/branding)
5. **Add your Google addresses as test users.** Audience, Test users, Add users: every Gmail or Workspace address you will connect (work, perso…). In Testing, Google only lets these log in. [Open](https://console.cloud.google.com/auth/audience)
6. **Declare the scopes.** Add these scopes: drive.readonly, drive.file, documents.readonly, documents. Data Access, Add or remove scopes, paste them in 'Manually add scopes', then Save. [Open](https://console.cloud.google.com/auth/scopes)
7. **Create the OAuth client.** Application type: Web application. Name: hydra-mcp. Tick 'Use this client for an AI-powered agent': Google rejects MCP calls from clients without it. Under Authorized redirect URIs, add this one. Create, then copy the client ID and secret Google shows. [Open](https://console.cloud.google.com/auth/clients/create)
   - Authorized redirect URI: `http://127.0.0.1:8765/oauth/callback`
8. **Paste the client ID and secret below.** The secret is stored encrypted on this machine. Then hydra-mcp opens Google's sign-in page, like Claude does.

`http://127.0.0.1:8765/oauth/callback` is the default; the admin page shows your real callback URL (`<public URL>/oauth/callback`).

**Good to know**

- Google rejects calls from an OAuth client unless 'Use this client for an AI-powered agent' is ticked when the client is created.
- APIs to enable: docs.googleapis.com and docsmcp.googleapis.com.
- Scopes: drive.readonly, drive.file, documents.readonly, documents.
- hydra-mcp asks Google for offline access, so it gets a refresh token and you do not log in again every hour.
- Testing-mode apps: Google may expire refresh tokens after 7 days. If an account turns 'not connected', click Reconnect, or publish the consent screen to 'In production' (no review needed for personal use under 100 users, but Google shows an 'unverified app' warning).

**Official docs**

- [Configure the Workspace MCP servers (Google)](https://developers.google.com/workspace/guides/configure-mcp-servers)
- [Workspace Developer Preview Program](https://developers.google.com/workspace/preview)
- [Securing Workspace MCP servers (prompt injection)](https://developers.google.com/workspace/guides/configure-mcp-security)

## Google Sheets

Google's official Sheets MCP server. Each Google account (personal Gmail or Workspace) becomes one hydra-mcp account.

- **URL:** `https://sheetsmcp.googleapis.com/mcp/v1`
- **Sign-in:** One-time setup: create an OAuth client at the provider, then each account is one click.
- **Status:** Developer Preview

**Before you start**

- Your Google Cloud project must be enrolled in the Google Workspace Developer Preview Program (link below; Google reviews requests by hand, so ask a few days ahead): the Workspace MCP servers are not public yet. Without it, login works but every tool call is refused.
- A Google Cloud project (free). One project and one OAuth client serve every Google connector and every Google account.
- About 10 minutes the first time, to create that OAuth client. The next Sheets or Google accounts connect in one click.

**Several accounts**

Add as many Google accounts as you like. In Testing mode, each address must first be added as a test user on the consent screen.

**One-time setup: Web application, for an AI agent at Google**

1. **Join the Google Workspace Developer Preview Program.** The Workspace MCP servers are in Developer Preview: Google only serves them to enrolled accounts. Skip this if you are already in. [Open](https://developers.google.com/workspace/preview)
2. **Pick or create a Google Cloud project.** Any project works. One project serves all your Google accounts and all the Google connectors: reuse it for the next ones. [Open](https://console.cloud.google.com/projectcreate)
3. **Enable the APIs.** Enable sheets.googleapis.com and sheetsmcp.googleapis.com. The page asks you to confirm the project. [Open](https://console.cloud.google.com/flows/enableapi?apiid=sheets.googleapis.com,sheetsmcp.googleapis.com)
4. **Set up the consent screen.** Click Get started. App name: hydra-mcp. Support email: yours. Audience: External (Internal if every account is in your own Workspace). Leave the app in Testing: no Google review is needed for personal use. [Open](https://console.cloud.google.com/auth/branding)
5. **Add your Google addresses as test users.** Audience, Test users, Add users: every Gmail or Workspace address you will connect (work, perso…). In Testing, Google only lets these log in. [Open](https://console.cloud.google.com/auth/audience)
6. **Declare the scopes.** Add these scopes: drive.readonly, drive.file, spreadsheets.readonly, spreadsheets. Data Access, Add or remove scopes, paste them in 'Manually add scopes', then Save. [Open](https://console.cloud.google.com/auth/scopes)
7. **Create the OAuth client.** Application type: Web application. Name: hydra-mcp. Tick 'Use this client for an AI-powered agent': Google rejects MCP calls from clients without it. Under Authorized redirect URIs, add this one. Create, then copy the client ID and secret Google shows. [Open](https://console.cloud.google.com/auth/clients/create)
   - Authorized redirect URI: `http://127.0.0.1:8765/oauth/callback`
8. **Paste the client ID and secret below.** The secret is stored encrypted on this machine. Then hydra-mcp opens Google's sign-in page, like Claude does.

`http://127.0.0.1:8765/oauth/callback` is the default; the admin page shows your real callback URL (`<public URL>/oauth/callback`).

**Good to know**

- Google rejects calls from an OAuth client unless 'Use this client for an AI-powered agent' is ticked when the client is created.
- APIs to enable: sheets.googleapis.com and sheetsmcp.googleapis.com.
- Scopes: drive.readonly, drive.file, spreadsheets.readonly, spreadsheets.
- hydra-mcp asks Google for offline access, so it gets a refresh token and you do not log in again every hour.
- Testing-mode apps: Google may expire refresh tokens after 7 days. If an account turns 'not connected', click Reconnect, or publish the consent screen to 'In production' (no review needed for personal use under 100 users, but Google shows an 'unverified app' warning).

**Official docs**

- [Configure the Workspace MCP servers (Google)](https://developers.google.com/workspace/guides/configure-mcp-servers)
- [Workspace Developer Preview Program](https://developers.google.com/workspace/preview)
- [Securing Workspace MCP servers (prompt injection)](https://developers.google.com/workspace/guides/configure-mcp-security)

## Google Slides

Google's official Slides MCP server. Each Google account (personal Gmail or Workspace) becomes one hydra-mcp account.

- **URL:** `https://slidesmcp.googleapis.com/mcp/v1`
- **Sign-in:** One-time setup: create an OAuth client at the provider, then each account is one click.
- **Status:** Developer Preview

**Before you start**

- Your Google Cloud project must be enrolled in the Google Workspace Developer Preview Program (link below; Google reviews requests by hand, so ask a few days ahead): the Workspace MCP servers are not public yet. Without it, login works but every tool call is refused.
- A Google Cloud project (free). One project and one OAuth client serve every Google connector and every Google account.
- About 10 minutes the first time, to create that OAuth client. The next Slides or Google accounts connect in one click.

**Several accounts**

Add as many Google accounts as you like. In Testing mode, each address must first be added as a test user on the consent screen.

**One-time setup: Web application, for an AI agent at Google**

1. **Join the Google Workspace Developer Preview Program.** The Workspace MCP servers are in Developer Preview: Google only serves them to enrolled accounts. Skip this if you are already in. [Open](https://developers.google.com/workspace/preview)
2. **Pick or create a Google Cloud project.** Any project works. One project serves all your Google accounts and all the Google connectors: reuse it for the next ones. [Open](https://console.cloud.google.com/projectcreate)
3. **Enable the APIs.** Enable slides.googleapis.com and slidesmcp.googleapis.com. The page asks you to confirm the project. [Open](https://console.cloud.google.com/flows/enableapi?apiid=slides.googleapis.com,slidesmcp.googleapis.com)
4. **Set up the consent screen.** Click Get started. App name: hydra-mcp. Support email: yours. Audience: External (Internal if every account is in your own Workspace). Leave the app in Testing: no Google review is needed for personal use. [Open](https://console.cloud.google.com/auth/branding)
5. **Add your Google addresses as test users.** Audience, Test users, Add users: every Gmail or Workspace address you will connect (work, perso…). In Testing, Google only lets these log in. [Open](https://console.cloud.google.com/auth/audience)
6. **Declare the scopes.** Add these scopes: drive.readonly, drive.file, presentations.readonly, presentations. Data Access, Add or remove scopes, paste them in 'Manually add scopes', then Save. [Open](https://console.cloud.google.com/auth/scopes)
7. **Create the OAuth client.** Application type: Web application. Name: hydra-mcp. Tick 'Use this client for an AI-powered agent': Google rejects MCP calls from clients without it. Under Authorized redirect URIs, add this one. Create, then copy the client ID and secret Google shows. [Open](https://console.cloud.google.com/auth/clients/create)
   - Authorized redirect URI: `http://127.0.0.1:8765/oauth/callback`
8. **Paste the client ID and secret below.** The secret is stored encrypted on this machine. Then hydra-mcp opens Google's sign-in page, like Claude does.

`http://127.0.0.1:8765/oauth/callback` is the default; the admin page shows your real callback URL (`<public URL>/oauth/callback`).

**Good to know**

- Google rejects calls from an OAuth client unless 'Use this client for an AI-powered agent' is ticked when the client is created.
- APIs to enable: slides.googleapis.com and slidesmcp.googleapis.com.
- Scopes: drive.readonly, drive.file, presentations.readonly, presentations.
- hydra-mcp asks Google for offline access, so it gets a refresh token and you do not log in again every hour.
- Testing-mode apps: Google may expire refresh tokens after 7 days. If an account turns 'not connected', click Reconnect, or publish the consent screen to 'In production' (no review needed for personal use under 100 users, but Google shows an 'unverified app' warning).

**Official docs**

- [Configure the Workspace MCP servers (Google)](https://developers.google.com/workspace/guides/configure-mcp-servers)
- [Workspace Developer Preview Program](https://developers.google.com/workspace/preview)
- [Securing Workspace MCP servers (prompt injection)](https://developers.google.com/workspace/guides/configure-mcp-security)

## Google Chat

Google's official Chat MCP server. Each Google account (personal Gmail or Workspace) becomes one hydra-mcp account.

- **URL:** `https://chatmcp.googleapis.com/mcp/v1`
- **Sign-in:** One-time setup: create an OAuth client at the provider, then each account is one click.
- **Status:** Developer Preview

**Before you start**

- Your Google Cloud project must be enrolled in the Google Workspace Developer Preview Program (link below; Google reviews requests by hand, so ask a few days ahead): the Workspace MCP servers are not public yet. Without it, login works but every tool call is refused.
- A Google Cloud project (free). One project and one OAuth client serve every Google connector and every Google account.
- About 10 minutes the first time, to create that OAuth client. The next Chat or Google accounts connect in one click.

**Several accounts**

Add as many Google accounts as you like. In Testing mode, each address must first be added as a test user on the consent screen.

**One-time setup: Web application, for an AI agent at Google**

1. **Join the Google Workspace Developer Preview Program.** The Workspace MCP servers are in Developer Preview: Google only serves them to enrolled accounts. Skip this if you are already in. [Open](https://developers.google.com/workspace/preview)
2. **Pick or create a Google Cloud project.** Any project works. One project serves all your Google accounts and all the Google connectors: reuse it for the next ones. [Open](https://console.cloud.google.com/projectcreate)
3. **Enable the APIs.** Enable chat.googleapis.com and chatmcp.googleapis.com. The page asks you to confirm the project. [Open](https://console.cloud.google.com/flows/enableapi?apiid=chat.googleapis.com,chatmcp.googleapis.com)
4. **Set up the consent screen.** Click Get started. App name: hydra-mcp. Support email: yours. Audience: External (Internal if every account is in your own Workspace). Leave the app in Testing: no Google review is needed for personal use. [Open](https://console.cloud.google.com/auth/branding)
5. **Add your Google addresses as test users.** Audience, Test users, Add users: every Gmail or Workspace address you will connect (work, perso…). In Testing, Google only lets these log in. [Open](https://console.cloud.google.com/auth/audience)
6. **Declare the scopes.** Add these scopes: chat.spaces.readonly, chat.memberships.readonly, chat.messages.readonly, chat.messages.create, chat.users.readstate, chat.users.spacesettings. Data Access, Add or remove scopes, paste them in 'Manually add scopes', then Save. [Open](https://console.cloud.google.com/auth/scopes)
7. **Create the OAuth client.** Application type: Web application. Name: hydra-mcp. Tick 'Use this client for an AI-powered agent': Google rejects MCP calls from clients without it. Under Authorized redirect URIs, add this one. Create, then copy the client ID and secret Google shows. [Open](https://console.cloud.google.com/auth/clients/create)
   - Authorized redirect URI: `http://127.0.0.1:8765/oauth/callback`
8. **Paste the client ID and secret below.** The secret is stored encrypted on this machine. Then hydra-mcp opens Google's sign-in page, like Claude does.

`http://127.0.0.1:8765/oauth/callback` is the default; the admin page shows your real callback URL (`<public URL>/oauth/callback`).

**Good to know**

- Google rejects calls from an OAuth client unless 'Use this client for an AI-powered agent' is ticked when the client is created.
- APIs to enable: chat.googleapis.com and chatmcp.googleapis.com.
- Scopes: chat.spaces.readonly, chat.memberships.readonly, chat.messages.readonly, chat.messages.create, and two chat.users scopes.
- hydra-mcp asks Google for offline access, so it gets a refresh token and you do not log in again every hour.
- Testing-mode apps: Google may expire refresh tokens after 7 days. If an account turns 'not connected', click Reconnect, or publish the consent screen to 'In production' (no review needed for personal use under 100 users, but Google shows an 'unverified app' warning).
- Reading works out of the box. Sending messages also needs a Chat app configured on the Google Chat API Configuration page of your project.

**Official docs**

- [Configure the Workspace MCP servers (Google)](https://developers.google.com/workspace/guides/configure-mcp-servers)
- [Workspace Developer Preview Program](https://developers.google.com/workspace/preview)
- [Securing Workspace MCP servers (prompt injection)](https://developers.google.com/workspace/guides/configure-mcp-security)

## Google Workspace search

Google's official Workspace search MCP server. Each Google account (personal Gmail or Workspace) becomes one hydra-mcp account.

- **URL:** `https://workspacemcp.googleapis.com/mcp/v1`
- **Sign-in:** One-time setup: create an OAuth client at the provider, then each account is one click.
- **Status:** Developer Preview

**Before you start**

- Your Google Cloud project must be enrolled in the Google Workspace Developer Preview Program (link below; Google reviews requests by hand, so ask a few days ahead): the Workspace MCP servers are not public yet. Without it, login works but every tool call is refused.
- A Google Cloud project (free). One project and one OAuth client serve every Google connector and every Google account.
- About 10 minutes the first time, to create that OAuth client. The next Workspace search or Google accounts connect in one click.

**Several accounts**

Add as many Google accounts as you like. In Testing mode, each address must first be added as a test user on the consent screen.

**One-time setup: Web application, for an AI agent at Google**

1. **Join the Google Workspace Developer Preview Program.** The Workspace MCP servers are in Developer Preview: Google only serves them to enrolled accounts. Skip this if you are already in. [Open](https://developers.google.com/workspace/preview)
2. **Pick or create a Google Cloud project.** Any project works. One project serves all your Google accounts and all the Google connectors: reuse it for the next ones. [Open](https://console.cloud.google.com/projectcreate)
3. **Enable the APIs.** Enable workspacemcp.googleapis.com. The page asks you to confirm the project. [Open](https://console.cloud.google.com/flows/enableapi?apiid=workspacemcp.googleapis.com)
4. **Set up the consent screen.** Click Get started. App name: hydra-mcp. Support email: yours. Audience: External (Internal if every account is in your own Workspace). Leave the app in Testing: no Google review is needed for personal use. [Open](https://console.cloud.google.com/auth/branding)
5. **Add your Google addresses as test users.** Audience, Test users, Add users: every Gmail or Workspace address you will connect (work, perso…). In Testing, Google only lets these log in. [Open](https://console.cloud.google.com/auth/audience)
6. **Declare the scopes.** Add these scopes: gmail.readonly, drive.readonly, calendar.readonly, chat.messages.readonly, chat.spaces.readonly, chat.memberships.readonly. Data Access, Add or remove scopes, paste them in 'Manually add scopes', then Save. [Open](https://console.cloud.google.com/auth/scopes)
7. **Create the OAuth client.** Application type: Web application. Name: hydra-mcp. Tick 'Use this client for an AI-powered agent': Google rejects MCP calls from clients without it. Under Authorized redirect URIs, add this one. Create, then copy the client ID and secret Google shows. [Open](https://console.cloud.google.com/auth/clients/create)
   - Authorized redirect URI: `http://127.0.0.1:8765/oauth/callback`
8. **Paste the client ID and secret below.** The secret is stored encrypted on this machine. Then hydra-mcp opens Google's sign-in page, like Claude does.

`http://127.0.0.1:8765/oauth/callback` is the default; the admin page shows your real callback URL (`<public URL>/oauth/callback`).

**Good to know**

- Google rejects calls from an OAuth client unless 'Use this client for an AI-powered agent' is ticked when the client is created.
- APIs to enable: workspacemcp.googleapis.com.
- Read-only: one search tool across Gmail, Drive, Calendar and Chat. Scopes: gmail.readonly, drive.readonly, calendar.readonly and three Chat read scopes.
- hydra-mcp asks Google for offline access, so it gets a refresh token and you do not log in again every hour.
- Testing-mode apps: Google may expire refresh tokens after 7 days. If an account turns 'not connected', click Reconnect, or publish the consent screen to 'In production' (no review needed for personal use under 100 users, but Google shows an 'unverified app' warning).

**Official docs**

- [Workspace search MCP server setup (Google)](https://developers.google.com/workspace/guides/universal-search-mcp)
- [Configure the Workspace MCP servers (Google)](https://developers.google.com/workspace/guides/configure-mcp-servers)
- [Workspace Developer Preview Program](https://developers.google.com/workspace/preview)
- [Securing Workspace MCP servers (prompt injection)](https://developers.google.com/workspace/guides/configure-mcp-security)

## Atlassian (Jira, Confluence)

Atlassian's official Rovo MCP server: Jira, Confluence, Compass, plus Teamwork Graph search. One click: hydra-mcp registers itself, you log in at Atlassian.

- **URL:** `https://mcp.atlassian.com/v2/mcp`
- **Sign-in:** One click. hydra-mcp registers itself at the provider, you log in.
- **Status:** Generally available

**Before you start**

- An Atlassian Cloud site (xxx.atlassian.net). Server and Data Center are not supported.
- Your site admin may restrict which apps can connect. If the consent page says access is denied, ask them to allow the Atlassian Rovo MCP server for your site.

**Several accounts**

One hydra-mcp account per Atlassian site: the login is granted on the site you pick on the consent page. To add another site, click '+ Add another account' and choose the other site there. hydra-mcp reads the site name to label the account.

**Good to know**

- On the consent page, check which site is selected in the dropdown before you click Accept: it decides which site this account reaches.
- Some tools (enriched Teamwork Graph calls) consume Rovo credits of your site.
- Atlassian moves remaining v1 clients to the v2 tools on 1 March 2027. hydra-mcp already uses v2.
- API tokens (email + token, Basic auth) also exist, but only if your org admin enables them. OAuth is Atlassian's recommended way and is what hydra-mcp uses.

**Official docs**

- [Get started with the Atlassian Rovo MCP server](https://support.atlassian.com/atlassian-ai-gateway/docs/get-started-with-the-atlassian-remote-mcp-server/)
- [Authentication and authorization](https://support.atlassian.com/atlassian-ai-gateway/docs/authentication-and-authorization/)
- [Supported tools](https://support.atlassian.com/atlassian-ai-gateway/docs/supported-tools/)
- [Troubleshoot your setup](https://support.atlassian.com/atlassian-ai-gateway/docs/troubleshoot-and-verify-your-setup/)
- [Admin: control the MCP server settings](https://support.atlassian.com/security-and-access-policies/docs/control-atlassian-rovo-mcp-server-settings/)

## Linear

Linear's official MCP server: issues, projects, cycles, comments. One click: hydra-mcp registers itself, you log in at Linear.

- **URL:** `https://mcp.linear.app/mcp`
- **Sign-in:** One click. hydra-mcp registers itself at the provider, you log in. Or paste a Linear API key.
- **Status:** Generally available

**Before you start**

- A Linear account. No plan or admin approval is needed for the standard login.

**Several accounts**

One hydra-mcp account per Linear workspace. To add another workspace, click '+ Add another account' and pick the other workspace on Linear's consent page.

**With a token instead: Linear API key**

Linear, Settings, Security & access, Personal API keys, New key. Pick the workspace and the permissions (Read only is enough to search). Copy the key (lin_api_...). [Create one](https://linear.app/settings/account/security), then in the admin page pick the connector and choose *Use a token instead*.

**Good to know**

- Linear's OAuth sessions start with a 25-day refresh window. If an account turns 'not connected', click Reconnect.
- Read-only: add https://mcp.linear.app/mcp/readonly by URL (it only ever exposes read tools), or use a Linear API key with only the Read permission ('Use a token instead'). A read-only grant in hydra-mcp also hides write tools.
- Linear's own docs mention mcp-remote config folders for several workspaces: not needed here, each hydra-mcp account keeps its own token.

**Official docs**

- [Linear MCP server](https://linear.app/docs/mcp)
- [FAQ and troubleshooting](https://linear.app/docs/mcp#faq)

## Notion

Notion's official hosted MCP server: search, read and edit pages and databases. One click: hydra-mcp registers itself, you log in at Notion.

- **URL:** `https://mcp.notion.com/mcp`
- **Sign-in:** One click. hydra-mcp registers itself at the provider, you log in. Or paste a Notion MCP token (Business and Enterprise).
- **Status:** Generally available

**Before you start**

- You must be a member of the workspace. Guests cannot connect.
- The AI sees exactly what your Notion user can see in the workspace you pick.

**Several accounts**

One hydra-mcp account per Notion workspace: pick the workspace on Notion's consent page.

**With a token instead: Notion MCP token (Business and Enterprise)**

A workspace owner creates it in Notion's Developer portal with 'New MCP token'. Paste it here; no browser login is needed. [Create one](https://developers.notion.com/guides/mcp/get-started-with-mcp), then in the admin page pick the connector and choose *Use a token instead*.

**Good to know**

- Search across connected sources (Slack, Google Drive...) and some search filters need a Business or Enterprise plan with Notion AI.
- Business and Enterprise plans get higher rate limits.
- File uploads through the tools are limited to 20 MiB.
- MCP tokens (no browser login) exist on Business and Enterprise only, and only workspace owners can create them.
- An Enterprise workspace policy can block MCP connections: ask your workspace owner if the consent page refuses.
- The older open-source notion-mcp-server (integration token) is no longer maintained: use this hosted one.

**Official docs**

- [Get started with Notion MCP](https://developers.notion.com/guides/mcp/get-started-with-mcp)
- [Supported tools and rate limits](https://developers.notion.com/guides/mcp/mcp-supported-tools)

## GitHub

GitHub's official remote MCP server: repositories, issues, pull requests, Actions, code search. GitHub does not let apps register themselves, so choose one of two ways.

- **URL:** `https://api.githubcopilot.com/mcp/`
- **Sign-in:** One-time setup: create an OAuth client at the provider, then each account is one click. Or paste a GitHub personal access token.
- **Status:** Generally available

**Before you start**

- Fastest: a personal access token (2 minutes, nothing to register). Click 'Use a token instead'.
- Or a GitHub OAuth App (5 minutes, once): then every GitHub account signs in with one click, like in Claude.
- Organization repositories: the org may require owner approval for OAuth Apps, or for fine-grained tokens. Check Organization settings, Third-party access.

**Several accounts**

One hydra-mcp account per GitHub user (or per token). hydra-mcp labels it with the GitHub login.

**One-time setup: OAuth App at GitHub**

1. **Open 'Register a new OAuth app' on GitHub.** For an app owned by an organization instead of you: Organization settings, Developer settings, OAuth Apps, New OAuth App. [Open](https://github.com/settings/applications/new)
2. **Fill in the form.** Redirect URI is the callback below, not the homepage. Leave 'Allow wildcard matching' and 'Enable Device Flow' unticked. Tick 'Expire user access tokens': GitHub then issues 8-hour tokens with a refresh token, which hydra-mcp renews on its own (unticked works too: tokens never expire). Then click Register application.
   - Application name: `hydra-mcp`
   - Homepage URL: `http://127.0.0.1:8765`
   - Redirect URI: `http://127.0.0.1:8765/oauth/callback`
3. **Generate a client secret.** On the app's page, copy the Client ID, then click 'Generate a new client secret' and copy it now: GitHub shows it only once.
4. **Paste the client ID and secret below.** The secret is stored encrypted on this machine. Then GitHub asks you to authorize hydra-mcp. For organization repositories, use 'Request' or 'Grant' next to the org on that page.

`http://127.0.0.1:8765/oauth/callback` is the default; the admin page shows your real callback URL (`<public URL>/oauth/callback`).

**With a token instead: GitHub personal access token**

Fine-grained token: name it hydra-mcp, pick an expiration, choose the resource owner and the repositories, then under Repository permissions give Contents, Issues and Pull requests: Read (or Read and write). Metadata: Read is added automatically. Generate, then copy the token (github_pat_...). A classic token (ghp_..., scope repo) also works. [Create one](https://github.com/settings/personal-access-tokens/new), then in the admin page pick the connector and choose *Use a token instead*.

**Good to know**

- The OAuth consent screen lists broad classic scopes (repo, read:org, gist, notifications...). For narrow access, use a fine-grained token restricted to some repositories.
- Fine-grained tokens expire (you choose the date, up to a year). When one expires, the account shows 'not connected': create a new token and click 'New token' on that account.
- Fewer tools: GitHub serves one URL per toolset, for example https://api.githubcopilot.com/mcp/x/issues or /mcp/x/pull_requests, and /readonly after any of them (/mcp/readonly, /mcp/x/issues/readonly). Add such a URL as 'Another MCP server (by URL)'. Your AI then gets fewer, more relevant tools.
- GitHub Enterprise Server is not supported by the remote server. GitHub Enterprise Cloud with data residency uses another host (copilot-api.<your-subdomain>.ghe.com/mcp): add it by URL, with a token.

**Official docs**

- [GitHub MCP server (README)](https://github.com/github/github-mcp-server)
- [Remote server: URLs, toolsets, read-only](https://github.com/github/github-mcp-server/blob/main/docs/remote-server.md)
- [Creating an OAuth App](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/creating-an-oauth-app)
- [Managing personal access tokens](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens)
- [Policies and governance](https://github.com/github/github-mcp-server/blob/main/docs/policies-and-governance.md)

## Slack

Slack's official MCP server: search messages and files, read channels and threads, send and schedule messages, canvases, lists, reactions. It acts as you (user token): the AI sees what you see.

- **URL:** `https://mcp.slack.com/mcp`
- **Sign-in:** One-time setup: create an OAuth client at the provider, then each account is one click.
- **Status:** Generally available

**Before you start**

- A workspace admin must allow MCP integrations, and approve your app if your workspace requires app approval. On a workspace you own, you approve it yourself.
- About 5 minutes per workspace, to create a small Slack app. Slack does not let apps register themselves, and only lets an app you created be used in its own workspace.
- IP allowlists of your workspace apply to MCP calls too: the machine running hydra-mcp must be allowed.

**Several accounts**

One Slack app per workspace. For a second workspace, click '+ Another workspace' on the Slack card: hydra-mcp adds a second Slack server with its own app, and its tools appear as slack-2__… . A second person in the same workspace is '+ Add another account' (same app).

**One-time setup: Slack app (internal) at Slack**

1. **Create the Slack app from a manifest.** Click 'Create New App', choose 'From a manifest', pick the workspace this account is in, select the JSON tab and replace its content with the manifest below. It sets the name, the callback and the user scopes. Review, then Create. [Open](https://api.slack.com/apps)
   - App manifest (JSON):

     ```json
     {
       "display_information": {
         "name": "hydra-mcp"
       },
       "oauth_config": {
         "redirect_urls": [
           "http://localhost:8765/oauth/callback"
         ],
         "scopes": {
           "user": [
             "search:read.public",
             "search:read.private",
             "search:read.mpim",
             "search:read.im",
             "search:read.files",
             "search:read.users",
             "channels:history",
             "groups:history",
             "mpim:history",
             "im:history",
             "channels:read",
             "groups:read",
             "mpim:read",
             "im:read",
             "users:read",
             "users:read.email",
             "files:read",
             "canvases:read",
             "lists:read",
             "emoji:read",
             "reactions:read",
             "chat:write",
             "reactions:write",
             "canvases:write",
             "files:write",
             "lists:write",
             "channels:write",
             "groups:write",
             "im:write",
             "mpim:write"
           ]
         }
       },
       "settings": {
         "org_deploy_enabled": false,
         "socket_mode_enabled": false,
         "token_rotation_enabled": false
       }
     }
     ```

2. **Turn on MCP for the app.** In the app's sidebar, open 'Agents' and switch on 'Slack Model Context Protocol (MCP) Server'.
3. **Opt in to PKCE.** OAuth & Permissions: opt in to PKCE. Slack accepts the plain-http localhost callback only from PKCE apps. This makes the app a public client and cannot be undone, which is fine for an app used only by hydra-mcp. Skip this step if hydra-mcp runs behind an https public URL.
4. **Copy the Client ID.** Basic Information, App Credentials: copy the Client ID. With PKCE on, leave the secret empty below. Without PKCE, also copy the Client Secret.
5. **Paste it below, then allow access.** Slack shows its consent page for your workspace. If it says the app needs approval, your admin approves it in the workspace's app management; then click Reconnect.

`http://localhost:8765/oauth/callback` is the default; the admin page shows your real callback URL (`<public URL>/oauth/callback`).

**Good to know**

- Turn on PKCE in the app (OAuth & Permissions): Slack only accepts a plain-http callback on localhost from apps with PKCE, which is why the callback below says localhost and not 127.0.0.1. PKCE makes the app a public client, cannot be undone, and its refresh tokens last 30 days. Leave the client secret empty in hydra-mcp then.
- Behind an HTTPS public URL (a tunnel, see the Claude guides) you can skip PKCE: register that https callback and paste the client secret instead.
- Scopes: hydra-mcp asks for every user scope the Slack tools document (search, history, write...). Remove the ones you do not want from the app's User Token Scopes before installing; tools that need them will then fail. Read-only use: also give your AI app a 'read only' grant in hydra-mcp.
- The consent page shows the workspace in its top right corner: check it before you click Allow. hydra-mcp labels the account with the workspace name.
- Slack rejects apps that are distributed but not published in the Slack Marketplace: keep 'Manage Distribution' off.

**Official docs**

- [Slack MCP server overview](https://docs.slack.dev/ai/slack-mcp-server/)
- [Developing with the Slack MCP server](https://docs.slack.dev/ai/slack-mcp-server/developing)
- [PKCE and desktop redirects](https://docs.slack.dev/authentication/using-pkce)
- [Guide to MCP in Slack (Help Center)](https://slack.com/help/articles/48855576908307-Guide-to-MCP-in-Slack)

## Sentry

Sentry's official MCP server: issues, events, traces, releases, and Seer analysis. One click: hydra-mcp registers itself, you log in at Sentry.

- **URL:** `https://mcp.sentry.dev/mcp`
- **Sign-in:** One click. hydra-mcp registers itself at the provider, you log in.
- **Status:** Generally available

**Before you start**

- A sentry.io account. Self-hosted Sentry is not served by this remote server (Sentry's CLI offers a local one).

**Several accounts**

One hydra-mcp account per Sentry login. To keep two organizations apart, add each by URL scoped to it: https://mcp.sentry.dev/mcp/<org-slug> (or /<org-slug>/<project-slug>, which Sentry recommends).

**Good to know**

- Sentry offers no token login for the remote server: OAuth only.
- Add ?experimental=1 to the URL to get Sentry's experimental tools.

**Official docs**

- [Sentry MCP server](https://mcp.sentry.dev/)
- [Sentry CLI (local MCP, self-hosted)](https://cli.sentry.dev/getting-started/)

## Stripe

Stripe's official MCP server: customers, payments, invoices, subscriptions, docs search. One click: hydra-mcp registers itself, you approve access in Stripe.

- **URL:** `https://mcp.stripe.com/`
- **Sign-in:** One click. hydra-mcp registers itself at the provider, you log in. Or paste a Stripe agent API key.
- **Status:** Generally available

**Before you start**

- A Stripe account. Team admins can switch MCP access off, separately for live mode and sandboxes: Dashboard, Settings, MCP and CLI access.
- Start with a sandbox: on the consent page you choose live or sandbox and the permissions per environment.

**Several accounts**

One hydra-mcp account per Stripe account and environment you approve.

**With a token instead: Stripe agent API key**

In the Stripe Dashboard, create an agent API key with only the permissions you want the AI to have (it shows an 'Agent' badge). Paste it here. [Create one](https://docs.stripe.com/keys#agent-keys), then in the admin page pick the connector and choose *Use a token instead*.

**Good to know**

- Stripe's OAuth sessions last 14 days at most, refresh included: after that the account shows 'not connected' and you click Reconnect. An agent API key avoids this.
- Sensitive actions such as refunds ask for a confirmation in the Stripe Dashboard, through a link the AI gives you. It expires after 24 hours.
- From 11 January 2027, Stripe MCP only accepts OAuth or agent API keys: full secret keys (sk_...) and plain restricted keys stop working.
- Connect platforms: OAuth cannot act on connected accounts; use an agent API key.

**Official docs**

- [Stripe MCP](https://docs.stripe.com/mcp)
- [Agent API keys](https://docs.stripe.com/keys#agent-keys)
- [Dashboard: MCP and CLI access](https://dashboard.stripe.com/settings/mcp-and-cli-access)

## Asana

Asana's official MCP server (v2): tasks, projects, goals, portfolios. Asana does not let apps register themselves: you create an Asana app once.

- **URL:** `https://mcp.asana.com/v2/mcp`
- **Sign-in:** One-time setup: create an OAuth client at the provider, then each account is one click.
- **Status:** Generally available

**Before you start**

- About 5 minutes once, in Asana's developer console, to create the app hydra-mcp signs in with.
- Your workspace admin may block MCP clients in App management (Enterprise). If the login says the app is blocked, ask them to allow it.

**Several accounts**

One hydra-mcp account per Asana login; it reaches the workspaces that user belongs to.

**One-time setup: Asana app (OAuth) at Asana**

1. **Read Asana's MCP integration guide.** It shows which app type to pick for an MCP client. Keep it open next to the console. [Open](https://developers.asana.com/docs/integrating-with-asanas-mcp-server)
2. **Create the app in the developer console.** My apps, Create new app, name it hydra-mcp. In its OAuth settings, add this redirect URL. [Open](https://app.asana.com/0/my-apps)
   - Redirect URL: `http://127.0.0.1:8765/oauth/callback`
3. **Paste the client ID and secret below.** Both are on the app's OAuth page. The secret is stored encrypted on this machine.

`http://127.0.0.1:8765/oauth/callback` is the default; the admin page shows your real callback URL (`<public URL>/oauth/callback`).

**Good to know**

- 'Client not found' at login: the client ID is wrong or the app was deleted. Use 'Reset' on the server (Advanced) and paste a new one.
- The old v1 endpoint (mcp.asana.com/sse) is shut down; hydra-mcp uses v2.
- Asana has no token login for the v2 MCP server.

**Official docs**

- [Using Asana's MCP server](https://developers.asana.com/docs/using-asanas-mcp-server)
- [Integrating with Asana's MCP server](https://developers.asana.com/docs/integrating-with-asanas-mcp-server)
- [MCP tools reference](https://developers.asana.com/docs/mcp-tools-reference)

## Cloudflare API

Cloudflare's API MCP server: the whole Cloudflare API (2,500+ endpoints) through search and execute tools. One click: hydra-mcp registers itself, you pick the permissions at Cloudflare.

- **URL:** `https://mcp.cloudflare.com/mcp`
- **Sign-in:** One click. hydra-mcp registers itself at the provider, you log in. Or paste a Cloudflare API token.
- **Status:** Generally available

**Before you start**

- A Cloudflare account. On the consent page you choose which permissions the AI gets: grant the least you need.

**Several accounts**

One hydra-mcp account per Cloudflare login, or per API token.

**With a token instead: Cloudflare API token**

My Profile, API Tokens, Create Token. Start from a template or pick permissions and accounts. User tokens and account tokens both work. [Create one](https://dash.cloudflare.com/profile/api-tokens), then in the admin page pick the connector and choose *Use a token instead*.

**Good to know**

- The execute tool runs JavaScript the AI writes against the Cloudflare API, in an isolated sandbox. With write permissions it can change DNS, Workers, etc. Give a read-only grant to clients that only need to look.
- Product servers (docs, browser, containers...) have their own URLs, e.g. https://docs.mcp.cloudflare.com/mcp: add them by URL.

**Official docs**

- [MCP servers for Cloudflare](https://developers.cloudflare.com/agents/model-context-protocol/cloudflare/servers-for-cloudflare/)
- [Cloudflare API](https://developers.cloudflare.com/api/)

## Supabase

Supabase's official MCP server: projects, SQL, migrations, Edge Functions, logs, docs. One click: hydra-mcp registers itself, you pick the organization at Supabase.

- **URL:** `https://mcp.supabase.com/mcp`
- **Sign-in:** One click. hydra-mcp registers itself at the provider, you log in. Or paste a Supabase personal access token.
- **Status:** Generally available

**Before you start**

- A Supabase account. On the consent page, choose the organization that holds your project.
- Supabase strongly advises against connecting production data. Use a dev project, or scope and lock it down (see below).

**Several accounts**

One hydra-mcp account per Supabase organization you approve, or per access token.

**With a token instead: Supabase personal access token**

Account, Access Tokens, Generate new token. Supabase recommends also scoping the server URL with ?project_ref=<id>. [Create one](https://supabase.com/dashboard/account/tokens), then in the admin page pick the connector and choose *Use a token instead*.

**Good to know**

- Safer URL: add it by URL with ?project_ref=<id>&read_only=true to reach one project, read-only. features=<groups> limits the tool groups.
- Branching tools need a paid plan. Storage tools are off by default.
- Confirmation forms before risky tools are a guardrail, not a guarantee.

**Official docs**

- [Supabase MCP server](https://supabase.com/docs/guides/ai-tools/mcp)
- [Personal access tokens](https://supabase.com/docs/guides/platform/personal-access-tokens)
- [Source and security notes](https://github.com/supabase/mcp)
