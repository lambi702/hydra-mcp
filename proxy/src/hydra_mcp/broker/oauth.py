"""The proxy as an OAuth 2.1 client of each upstream authorization server (broker mode).

Authority stays upstream: the user logs in and consents on the upstream's own pages. The proxy
only holds the resulting tokens, encrypted by the vault.

Flow for "Connect account":

    admin page --POST /admin/api/accounts/{id}/link--> proxy
        proxy: discover PRM + AS metadata, register itself (DCR) if needed,
               create state + PKCE verifier, return the authorize URL
    browser  --> upstream AS /authorize (login + consent) --> proxy /oauth/callback?code&state
        proxy: exchange code (+ PKCE verifier, + RFC 8707 resource), seal tokens in the vault
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import re
import secrets
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx

from hydra_mcp import __version__
from hydra_mcp.broker.setup import callback_for, catalog_entry
from hydra_mcp.models import Account, Upstream
from hydra_mcp.router.discovery import DiscoveryError, PrmCache, fetch_as_metadata
from hydra_mcp.store import Store
from hydra_mcp.vault import Vault, VaultError

log = logging.getLogger(__name__)

REFRESH_MARGIN_S = 60

# Per-issuer quirks, kept as data (one place to look when a provider misbehaves).
ISSUER_QUIRKS: dict[str, dict[str, str]] = {
    # Google issues a refresh token only with access_type=offline, and re-issues it only with
    # prompt=consent.
    "https://accounts.google.com": {"access_type": "offline", "prompt": "consent"},
}
# Extra scopes per issuer. Google returns an id_token (hence who logged in) only with openid.
ISSUER_EXTRA_SCOPES: dict[str, list[str]] = {
    "https://accounts.google.com": ["openid", "email"],
}


class OAuthError(RuntimeError):
    """A user-facing problem with the OAuth setup of an upstream or account."""


class NeedsManualClient(OAuthError):
    """The upstream AS has no dynamic registration: an OAuth client must be created by hand."""


class NotLinked(OAuthError):
    """The account has no token yet, or its refresh failed: it must be (re)connected."""


@dataclass
class Discovered:
    resource: str
    issuer: str
    meta: dict
    scopes: list[str]


def pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
    return verifier, challenge.rstrip(b"=").decode()


def _jwt_claims(token: str) -> dict:
    """Unverified decode, only to show who logged in (never used for an auth decision)."""
    try:
        payload = token.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except Exception:  # noqa: BLE001
        return {}


# Public mailbox domains: for these the local part tells accounts apart, not the domain.
PUBLIC_MAIL_DOMAINS = {
    "gmail.com",
    "googlemail.com",
    "outlook.com",
    "hotmail.com",
    "live.com",
    "icloud.com",
    "me.com",
    "yahoo.com",
    "proton.me",
    "protonmail.com",
    "gmx.com",
    "skynet.be",
    "orange.fr",
}


def _identity(tokens: dict) -> str:
    """Who logged in: the id_token's email or subject, else an email claim in a JWT access token.

    Unverified decodes, used only to label and de-duplicate accounts, never to authorize.
    """
    if tokens.get("id_token"):
        claims = _jwt_claims(tokens["id_token"])
        if claims.get("email") or claims.get("sub"):
            return str(claims.get("email") or claims.get("sub"))
    claims = _jwt_claims(tokens.get("access_token", ""))
    if claims.get("email"):
        return str(claims["email"])
    # Slack: the token response names the workspace the user token was granted on.
    team = tokens.get("team")
    if isinstance(team, dict) and team.get("name"):
        return str(team["name"])
    return ""


def normalize_token_response(data: dict) -> dict:
    """Bring provider-specific token responses to the RFC 6749 shape.

    Slack answers HTTP 200 with {"ok": false, "error": "..."} on failure, and its classic
    oauth.v2.access puts the user token under "authed_user". Both are mapped here so the rest
    of the broker only sees `access_token`, `refresh_token`, `expires_in`.
    """
    if data.get("ok") is False:
        raise OAuthError(f"token endpoint refused: {data.get('error') or 'unknown error'}")
    if "access_token" not in data and isinstance(data.get("authed_user"), dict):
        user = data["authed_user"]
        lifted = {
            k: user[k]
            for k in ("access_token", "refresh_token", "expires_in", "scope")
            if k in user
        }
        data = {**data, **lifted}
    return data


def suggest_alias(identity: str, n: int) -> str:
    """A first friendly name: 'acme' for bob@acme.com, 'jane' for jane@gmail.com."""
    first = identity.lower().split(",")[0].strip()
    local, at, domain = first.partition("@")
    if not at:  # a site or host name, e.g. acme.atlassian.net -> acme
        base = first.split(".")[0]
    else:
        base = local if domain in PUBLIC_MAIL_DOMAINS else domain.split(".")[0]
    slug = re.sub(r"[^a-z0-9]+", "-", base).strip("-")[:20].strip("-")
    return slug or f"account{n}"


def _unique(value: str, taken: set[str]) -> str:
    if value not in taken:
        return value
    i = 2
    while f"{value}-{i}" in taken:
        i += 1
    return f"{value}-{i}"


@dataclass
class LinkResult:
    account: Account
    created: bool  # a new account (to name), versus a reconnect of an existing one


class OAuthBroker:
    def __init__(
        self,
        store: Store,
        vault: Vault,
        http: httpx.AsyncClient,
        prm: PrmCache,
        base_url: str,
        identity_probe: Callable[[Upstream, str], Awaitable[str]] | None = None,
    ):
        self.identity_probe = identity_probe
        self.store = store
        self.vault = vault
        self.http = http
        self.prm = prm
        self.base_url = base_url
        self._locks: dict[str, asyncio.Lock] = {}

    @property
    def redirect_uri(self) -> str:
        return f"{self.base_url}/oauth/callback"

    def redirect_uri_for(self, upstream: Upstream) -> str:
        return callback_for(upstream, self.redirect_uri)

    # -- discovery and registration ------------------------------------------------------------
    async def discover(self, upstream: Upstream) -> Discovered:
        try:
            prm = await self.prm.upstream_prm(str(upstream.url))
        except DiscoveryError as exc:
            raise OAuthError(f"{upstream.name}: {exc}") from exc
        issuer = prm["authorization_servers"][0]
        found = await fetch_as_metadata(self.http, issuer)
        if found is None:
            raise OAuthError(f"{upstream.name}: no authorization server metadata at {issuer}")
        _, meta = found
        if "S256" not in (meta.get("code_challenge_methods_supported") or []):
            # MCP spec: refuse to proceed without advertised PKCE S256 support.
            raise OAuthError(f"{upstream.name}: authorization server does not advertise PKCE S256")
        issuer_id = meta.get("issuer", issuer).rstrip("/")
        # Scopes: the library's curated list when there is one, else everything the server
        # advertises. Gmail advertises ~20 scopes including full mailbox access; asking for all
        # of them makes the consent screen scarier than the tools need.
        entry = catalog_entry(upstream)
        scopes = list(entry.scopes) if entry and entry.scopes else []
        scopes = scopes or list(prm.get("scopes_supported") or [])
        scopes += [s for s in ISSUER_EXTRA_SCOPES.get(issuer_id, []) if s not in scopes]
        if (
            "offline_access" in (meta.get("scopes_supported") or [])
            and "offline_access" not in scopes
        ):
            scopes.append("offline_access")
        resource = prm.get("resource") or str(upstream.url)
        return Discovered(
            resource=resource, issuer=meta.get("issuer", issuer), meta=meta, scopes=scopes
        )

    async def ensure_client(self, upstream: Upstream, d: Discovered) -> dict:
        row = await self.store.get_upstream_oauth(upstream.id)
        if row and (row["registration"] == "manual" or row["issuer"] == d.issuer):
            return row
        reg = d.meta.get("registration_endpoint")
        if not reg:
            raise NeedsManualClient(
                f"{upstream.name}: the authorization server ({d.issuer}) does not allow "
                "automatic registration. Create an OAuth client at the provider with redirect URI "
                f"{self.redirect_uri_for(upstream)}, then enter its client ID and secret on the "
                "upstream."
            )
        body = {
            "client_name": f"hydra-mcp ({upstream.name})",
            "redirect_uris": [self.redirect_uri_for(upstream)],
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
            "software_id": "hydra-mcp",
            "software_version": __version__,
        }
        if d.scopes:
            body["scope"] = " ".join(d.scopes)
        resp = await self.http.post(reg, json=body)
        if resp.status_code not in (200, 201):
            raise OAuthError(
                f"{upstream.name}: registration failed ({resp.status_code}): {resp.text[:300]}"
            )
        data = resp.json()
        secret = data.get("client_secret")
        method = data.get("token_endpoint_auth_method") or (
            "client_secret_basic" if secret else "none"
        )
        await self.store.put_upstream_oauth(
            upstream.id,
            issuer=d.issuer,
            client_id=data["client_id"],
            secret_enc=self.vault.seal({"s": secret}, aad=f"client:{upstream.id}")
            if secret
            else None,
            auth_method=method,
            registration="dcr",
        )
        return await self.store.get_upstream_oauth(upstream.id)  # type: ignore[return-value]

    async def set_manual_client(
        self, upstream: Upstream, client_id: str, client_secret: str | None
    ) -> None:
        d = await self.discover(upstream)
        await self.store.put_upstream_oauth(
            upstream.id,
            issuer=d.issuer,
            client_id=client_id,
            secret_enc=(
                self.vault.seal({"s": client_secret}, aad=f"client:{upstream.id}")
                if client_secret
                else None
            ),
            auth_method="client_secret_post" if client_secret else "none",
            registration="manual",
        )

    # -- connect flow ----------------------------------------------------------------------------
    async def start_link(self, account: Account | None, upstream: Upstream) -> str:
        """Authorize URL for (re)connecting `account`, or for a new account when None."""
        d = await self.discover(upstream)
        client = await self.ensure_client(upstream, d)
        state = secrets.token_urlsafe(32)
        verifier, challenge = pkce_pair()
        await self.store.put_link_flow(
            state, upstream.id, account.id if account else None, verifier, time.time()
        )
        params = {
            "response_type": "code",
            "client_id": client["client_id"],
            "redirect_uri": self.redirect_uri_for(upstream),
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "resource": d.resource,
            **ISSUER_QUIRKS.get(d.issuer.rstrip("/"), {}),
        }
        if d.scopes:
            entry = catalog_entry(upstream)
            params["scope"] = (entry.scope_separator if entry else " ").join(d.scopes)
        return f"{d.meta['authorization_endpoint']}?{urlencode(params)}"

    async def finish_link(self, state: str, code: str) -> LinkResult:
        row = await self.store.pop_link_flow(state, time.time())
        if row is None:
            raise OAuthError(
                "This connection link is invalid or expired. Start again from the admin page."
            )
        upstream = await self.store.get_upstream(row["upstream_id"])
        d = await self.discover(upstream)
        tokens = await self._token_request(
            upstream,
            d,
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.redirect_uri_for(upstream),
                "code_verifier": row["verifier"],
                "resource": d.resource,
            },
        )
        identity = _identity(tokens)
        if not identity and self.identity_probe is not None:
            # e.g. Atlassian: no id_token; the site the login was granted on tells accounts apart
            identity = await self.identity_probe(upstream, tokens["access_token"])
        created = False
        if row["account_id"]:
            account, _ = await self.store.get_account(row["account_id"])
        else:
            account, created = await self._account_for(upstream, identity)
        await self._save(account.id, tokens, previous=None)
        if identity and identity != account.identity:
            # Who actually logged in beats a hand-typed hint: the model reads this label to
            # pick an account, so it must describe the token, not the intent.
            account = account.model_copy(update={"identity": identity})
            await self.store.put_account(account)
        return LinkResult(account=account, created=created)

    async def link_token(
        self, upstream: Upstream, token: str, identity: str, account_id: str | None = None
    ) -> LinkResult:
        """Store a pasted token (PAT, API key) for an account: no OAuth, no refresh.

        The caller has already checked the token against the upstream. It is used as is until
        the upstream rejects it; then the account shows as not connected.
        """
        created = False
        if account_id:
            account, _ = await self.store.get_account(account_id)
        else:
            account, created = await self._account_for(upstream, identity)
        await self._save(account.id, {"access_token": token, "kind": "token"}, previous=None)
        if identity and identity != account.identity:
            account = account.model_copy(update={"identity": identity})
            await self.store.put_account(account)
        return LinkResult(account=account, created=created)

    async def _account_for(self, upstream: Upstream, identity: str) -> tuple[Account, bool]:
        """The account a new login belongs to: the same identity again, or a new account."""
        existing = [a for a in await self.store.list_accounts() if a.upstream_id == upstream.id]
        if identity:
            same = next((a for a in existing if a.identity == identity), None)
            if same is not None:
                return same, False
        aliases = {a.alias for a in existing}
        ids = {a.id for a in await self.store.list_accounts()}
        alias = _unique(suggest_alias(identity, len(existing) + 1), aliases)
        account_id = _unique(f"{upstream.id}-{alias}"[:28].rstrip("-"), ids)
        account = Account(id=account_id, upstream_id=upstream.id, alias=alias, identity=identity)
        await self.store.put_account(account)
        return account, True

    async def unlink(self, account_id: str) -> None:
        await self.store.delete_token_row(account_id)

    # -- tokens ----------------------------------------------------------------------------------
    async def access_token(self, account: Account, upstream: Upstream) -> str:
        lock = self._locks.setdefault(account.id, asyncio.Lock())
        async with lock:
            row = await self.store.get_token_row(account.id)
            if row is None:
                raise NotLinked(f"account '{account.id}' is not connected")
            try:
                bundle = self.vault.open(row["blob"], aad=f"token:{account.id}")
            except VaultError as exc:
                raise NotLinked(f"account '{account.id}': stored token unreadable") from exc
            exp = bundle.get("expires_at")
            if exp is None or exp - REFRESH_MARGIN_S > time.time():
                return bundle["access_token"]
            if not bundle.get("refresh_token"):
                raise NotLinked(f"account '{account.id}': token expired, reconnect it")
            d = await self.discover(upstream)
            try:
                tokens = await self._token_request(
                    upstream,
                    d,
                    {
                        "grant_type": "refresh_token",
                        "refresh_token": bundle["refresh_token"],
                        "resource": d.resource,
                    },
                )
            except OAuthError as exc:
                raise NotLinked(f"account '{account.id}': refresh failed, reconnect it") from exc
            saved = await self._save(account.id, tokens, previous=bundle)
            return saved["access_token"]

    async def _token_request(self, upstream: Upstream, d: Discovered, form: dict) -> dict:
        client = await self.store.get_upstream_oauth(upstream.id)
        if client is None:
            raise OAuthError(f"{upstream.name}: no OAuth client registered")
        secret = None
        if client["secret_enc"]:
            secret = self.vault.open(client["secret_enc"], aad=f"client:{upstream.id}")["s"]
        auth = None
        form = {**form, "client_id": client["client_id"]}
        if secret and client["auth_method"] == "client_secret_basic":
            auth = httpx.BasicAuth(client["client_id"], secret)
        elif secret:
            form["client_secret"] = secret
        resp = await self.http.post(
            d.meta["token_endpoint"], data=form, auth=auth, headers={"Accept": "application/json"}
        )
        if resp.status_code != 200:
            raise OAuthError(
                f"{upstream.name}: token endpoint answered {resp.status_code}: {resp.text[:300]}"
            )
        try:
            data = normalize_token_response(resp.json())
        except OAuthError as exc:
            raise OAuthError(f"{upstream.name}: {exc}") from exc
        if "access_token" not in data:
            raise OAuthError(f"{upstream.name}: token response without access_token")
        return data

    async def _save(self, account_id: str, tokens: dict, previous: dict | None) -> dict:
        now = time.time()
        bundle = {
            "access_token": tokens["access_token"],
            # Some AS do not rotate refresh tokens: keep the previous one.
            "refresh_token": tokens.get("refresh_token") or (previous or {}).get("refresh_token"),
            "expires_at": now + float(tokens["expires_in"]) if tokens.get("expires_in") else None,
            "scope": tokens.get("scope"),
            "identity": (previous or {}).get("identity", ""),
            "kind": tokens.get("kind", "oauth"),
        }
        bundle["identity"] = _identity(tokens) or bundle["identity"]
        await self.store.put_token_row(
            account_id,
            self.vault.seal(bundle, aad=f"token:{account_id}"),
            bundle["expires_at"],
            bundle["identity"] or "",
            now,
        )
        return bundle
