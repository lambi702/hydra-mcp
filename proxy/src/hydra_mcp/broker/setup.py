"""Step-by-step guides for providers that refuse dynamic client registration.

Without DCR, someone must create an OAuth client for hydra-mcp in the provider's console once.
Claude and other hosted apps did that step for all their users; a self-hosted proxy is its own
app, so its owner does it. These guides make that one-time step as short as possible: direct
console links, the exact values to copy, and nothing to look up.

Guides are pure data computed from the upstream URL (no network), so the admin page can show
one before any discovery has run.
"""

from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit

from hydra_mcp.catalog import Connector, load_catalog
from hydra_mcp.models import Upstream

GOOGLE_CONSOLE = "https://console.cloud.google.com"

# `{name}mcp.googleapis.com` serves the MCP endpoint; the product API behind it must be enabled
# too, and its id does not always match the name.
GOOGLE_BASE_API = {
    "gmail": "gmail.googleapis.com",
    "drive": "drive.googleapis.com",
    "calendar": "calendar-json.googleapis.com",
    "docs": "docs.googleapis.com",
    "sheets": "sheets.googleapis.com",
    "slides": "slides.googleapis.com",
    "chat": "chat.googleapis.com",
}


def catalog_entry(upstream: Upstream) -> Connector | None:
    """The library entry for this upstream's URL, if it was installed from (or matches) one."""
    url = str(upstream.url).rstrip("/")
    return next((c for c in load_catalog().connectors if str(c.url).rstrip("/") == url), None)


def callback_for(upstream: Upstream, redirect_uri: str) -> str:
    """The callback to register at this upstream's AS.

    Usually the proxy's `<public URL>/oauth/callback`. A provider that only accepts plain-http
    callbacks on `localhost` (Slack) gets the same URL with `localhost` instead of 127.0.0.1:
    both reach this proxy, and the callback then sends the browser back to the public URL,
    where the admin page is logged in.
    """
    entry = catalog_entry(upstream)
    parts = urlsplit(redirect_uri)
    if not (entry and entry.redirect_host and parts.scheme == "http"):
        return redirect_uri
    if parts.hostname not in ("127.0.0.1", "::1"):
        return redirect_uri
    netloc = entry.redirect_host + (f":{parts.port}" if parts.port else "")
    return urlunsplit(parts._replace(netloc=netloc))


def is_google(upstream: Upstream) -> bool:
    return (urlsplit(str(upstream.url)).hostname or "").endswith(".googleapis.com")


def google_apis(upstream: Upstream) -> list[str]:
    host = urlsplit(str(upstream.url)).hostname or ""
    apis = [host]
    name = host.split(".", 1)[0].removesuffix("mcp")
    if name in GOOGLE_BASE_API:
        apis.insert(0, GOOGLE_BASE_API[name])
    return apis


def _fill(value: str, redirect_uri: str) -> str:
    base_url = redirect_uri.removesuffix("/oauth/callback")
    return value.replace("{redirect_uri}", redirect_uri).replace("{base_url}", base_url)


def _field(label: str, value: str) -> dict:
    return {"label": label, "value": value}


def setup_guide(upstream: Upstream, redirect_uri: str) -> dict:
    """The one-time OAuth client setup for `upstream`, as steps with links and values to copy.

    Sources, most specific first: Google's console (computed from the URL), the library entry's
    own `guide.client` steps (GitHub, Asana), else a generic guide.
    """
    entry = catalog_entry(upstream)
    docs = str(entry.docs) if entry else None
    guide_data = entry.guide if entry else None
    token = guide_data.token.model_dump(mode="json") if guide_data and guide_data.token else None
    if is_google(upstream):
        guide = _google_guide(upstream, redirect_uri, docs)
    elif entry and entry.guide and entry.guide.client:
        c = entry.guide.client
        guide = {
            "provider": c.provider,
            "client_type": c.client_type,
            "redirect_uri": redirect_uri,
            "docs": docs,
            "steps": [
                {
                    "title": step.title,
                    "text": step.text,
                    "link": str(step.link) if step.link else None,
                    "fields": [_field(f.label, _fill(f.value, redirect_uri)) for f in step.fields],
                }
                for step in c.steps
            ],
        }
    else:
        guide = {
            "provider": upstream.name,
            "client_type": None,
            "redirect_uri": redirect_uri,
            "docs": docs,
            "steps": [
                {
                    "title": "Create an OAuth client for hydra-mcp at the provider",
                    "text": "In the provider's developer settings, create an OAuth application "
                    "(authorization code flow, also called 'web application') with this redirect "
                    "URI. Its docs usually call this 'registering an app'.",
                    "link": docs,
                    "fields": [_field("Redirect URI", redirect_uri)],
                },
                {
                    "title": "Paste its client ID (and secret, if it has one) below",
                    "text": "The secret is stored encrypted on this machine.",
                },
            ],
        }
    guide["token"] = token
    return guide


def _google_guide(upstream: Upstream, redirect_uri: str, docs: str | None) -> dict:
    apis = google_apis(upstream)
    entry = catalog_entry(upstream)
    scopes = [s.rsplit("/", 1)[-1] for s in (entry.scopes if entry else [])]
    scope_text = (
        f"Add these scopes: {', '.join(scopes)}. "
        if scopes
        else "Add the scopes listed in Google's guide for this product. "
    )
    return {
        "provider": "Google",
        "client_type": "Web application, for an AI agent",
        "redirect_uri": redirect_uri,
        "docs": docs,
        "steps": [
            {
                "title": "Join the Google Workspace Developer Preview Program",
                "text": "The Workspace MCP servers are in Developer Preview: Google only serves "
                "them to enrolled accounts. Skip this if you are already in.",
                "link": "https://developers.google.com/workspace/preview",
            },
            {
                "title": "Pick or create a Google Cloud project",
                "text": "Any project works. One project serves all your Google accounts and all "
                "the Google connectors: reuse it for the next ones.",
                "link": f"{GOOGLE_CONSOLE}/projectcreate",
            },
            {
                "title": "Enable the APIs",
                "text": f"Enable {' and '.join(apis)}. The page asks you to confirm the project.",
                "link": f"{GOOGLE_CONSOLE}/flows/enableapi?apiid={','.join(apis)}",
            },
            {
                "title": "Set up the consent screen",
                "text": "Click Get started. App name: hydra-mcp. Support email: yours. Audience: "
                "External (Internal if every account is in your own Workspace). Leave the app "
                "in Testing: no Google review is needed for personal use.",
                "link": f"{GOOGLE_CONSOLE}/auth/branding",
            },
            {
                "title": "Add your Google addresses as test users",
                "text": "Audience, Test users, Add users: every Gmail or Workspace address you "
                "will connect (work, perso…). In Testing, Google only lets these log in.",
                "link": f"{GOOGLE_CONSOLE}/auth/audience",
            },
            {
                "title": "Declare the scopes",
                "text": scope_text + "Data Access, Add or remove scopes, paste them in "
                "'Manually add scopes', then Save.",
                "link": f"{GOOGLE_CONSOLE}/auth/scopes",
            },
            {
                "title": "Create the OAuth client",
                "text": "Application type: Web application. Name: hydra-mcp. Tick 'Use this "
                "client for an AI-powered agent': Google rejects MCP calls from clients without "
                "it. Under Authorized redirect URIs, add this one. Create, then copy the client "
                "ID and secret Google shows.",
                "link": f"{GOOGLE_CONSOLE}/auth/clients/create",
                "fields": [_field("Authorized redirect URI", redirect_uri)],
            },
            {
                "title": "Paste the client ID and secret below",
                "text": "The secret is stored encrypted on this machine. Then hydra-mcp opens "
                "Google's sign-in page, like Claude does.",
            },
        ],
    }
