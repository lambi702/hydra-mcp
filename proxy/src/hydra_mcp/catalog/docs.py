"""Render the connector library as Markdown (docs/connectors.md), from the same data the admin
page shows, so the two never disagree. Regenerate with `python -m hydra_mcp.catalog.docs`."""

from __future__ import annotations

import sys
from pathlib import Path

from hydra_mcp.catalog import AuthKind, Connector, load_catalog
from hydra_mcp.models import Upstream

EXAMPLE_CALLBACK = "http://127.0.0.1:8765/oauth/callback"

SIGN_IN = {
    AuthKind.OAUTH_DCR: "One click. hydra-mcp registers itself at the provider, you log in.",
    AuthKind.OAUTH: "OAuth login at the provider.",
    AuthKind.OAUTH_PREREGISTERED: "One-time setup: create an OAuth client at the provider, "
    "then each account is one click.",
    AuthKind.BEARER: "Paste a token.",
}


def _connector(c: Connector) -> list[str]:
    g = c.guide
    out = [f"## {c.name}", ""]
    if g:
        out += [g.summary, ""]
    out += [
        f"- **URL:** `{c.url}`",
        f"- **Sign-in:** {SIGN_IN[c.auth]}"
        + (f" Or paste a {g.token.name}." if g and g.token else ""),
        f"- **Status:** {'Developer Preview' if c.status == 'preview' else 'Generally available'}",
        "",
    ]
    if not g:
        return out
    if g.before:
        out += ["**Before you start**", ""] + [f"- {b}" for b in g.before] + [""]
    if g.accounts:
        out += ["**Several accounts**", "", g.accounts, ""]
    if c.auth == AuthKind.OAUTH_PREREGISTERED:
        from hydra_mcp.broker.setup import callback_for, setup_guide  # late: imports catalog

        up = Upstream(id=c.id, name=c.name, url=c.url)
        callback = callback_for(up, EXAMPLE_CALLBACK)
        guide = setup_guide(up, callback)
        out += [f"**One-time setup: {guide['client_type']} at {guide['provider']}**", ""]
        for i, step in enumerate(guide["steps"], 1):
            line = f"{i}. **{step['title']}.** {step['text']}"
            if step.get("link"):
                line += f" [Open]({step['link']})"
            out.append(line)
            for f in step.get("fields", []):
                if "\n" in f["value"]:  # a manifest or other block: a fenced code block
                    out += [f"   - {f['label']}:", "", "     ```json"]
                    out += [f"     {line}" for line in f["value"].splitlines()]
                    out += ["     ```", ""]
                else:
                    out.append(f"   - {f['label']}: `{f['value']}`")
        out += [
            "",
            f"`{callback}` is the default; the admin page shows your real callback URL "
            "(`<public URL>/oauth/callback`).",
            "",
        ]
    if g.token:
        out += [
            f"**With a token instead: {g.token.name}**",
            "",
            f"{g.token.how} [Create one]({g.token.create_url}), then in the admin page pick "
            "the connector and choose *Use a token instead*.",
            "",
        ]
    if g.gotchas:
        out += ["**Good to know**", ""] + [f"- {x}" for x in g.gotchas] + [""]
    out += ["**Official docs**", ""] + [f"- [{lk.label}]({lk.url})" for lk in g.links] + [""]
    return out


def render() -> str:
    cat = load_catalog()
    lines = [
        "# Connector guides",
        "",
        "<!-- Generated from proxy/src/hydra_mcp/catalog/connectors.json by "
        "`python -m hydra_mcp.catalog.docs`. Edit the JSON, not this file. -->",
        "",
        f"Checked against each vendor's documentation on {cat.checked_at}. The admin page "
        "shows the same guide when you pick a connector.",
        "",
        "| Connector | Sign-in | Token option |",
        "| --- | --- | --- |",
    ]
    for c in cat.connectors:
        anchor = c.name.lower().replace(" ", "-").replace("(", "").replace(")", "")
        anchor = anchor.replace(",", "")
        token = c.guide.token.name if c.guide and c.guide.token else ""
        sign_in = {
            AuthKind.OAUTH_DCR: "one click",
            AuthKind.OAUTH: "OAuth",
            AuthKind.OAUTH_PREREGISTERED: "one-time OAuth client",
            AuthKind.BEARER: "token",
        }[c.auth]
        lines.append(f"| [{c.name}](#{anchor}) | {sign_in} | {token} |")
    lines.append("")
    for c in cat.connectors:
        lines += _connector(c)
    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("../docs/connectors.md")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render(), encoding="utf-8")
    print(f"wrote {target}")


if __name__ == "__main__":
    main()
