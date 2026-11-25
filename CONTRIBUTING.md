# Contributing to hydra-mcp

Thanks for helping. hydra-mcp is small on purpose: a proxy you can read in an afternoon. Changes
that keep it that way are the easiest to merge.

## Ways to help

- **Report a bug** with the [bug template](https://github.com/lambi702/hydra-mcp/issues/new?template=bug_report.yml).
- **Request or fix a connector**: a service missing from the library, or a guide that is out of
  date with the vendor's docs. The [connector template](https://github.com/lambi702/hydra-mcp/issues/new?template=connector_request.yml)
  asks for what we need.
- **Improve the docs**: if a step confused you, it will confuse the next person.
- **Pick an issue** labelled [`good first issue`](https://github.com/lambi702/hydra-mcp/labels/good%20first%20issue)
  or [`help wanted`](https://github.com/lambi702/hydra-mcp/labels/help%20wanted).
- **Help with the roadmap**: [ROADMAP.md](ROADMAP.md) says what comes next and where a hand helps
  most.

For anything larger than a bug fix, open an issue first so we can agree on the approach before
you spend time on it. Security issues never go in a public issue: see [SECURITY.md](SECURITY.md).

## Development setup

Requirements: Python 3.11+, [uv](https://docs.astral.sh/uv/), Node 20+.

```bash
git clone https://github.com/<you>/hydra-mcp && cd hydra-mcp
make install      # uv sync + npm install
make dev          # proxy with auto-reload on :8765, admin page with hot reload on :5173/admin/
```

Use a separate data directory while developing, so you never touch your real accounts:

```bash
export HYDRA_MCP_DATA_DIR=/tmp/hydra-dev HYDRA_MCP_ADMIN_TOKEN=dev
```

## Checks

Run before every pull request; CI runs the same:

```bash
make lint         # ruff check + ruff format --check
make test         # pytest + TypeScript type check
make build        # the admin page must build
```

`make fmt` fixes formatting and import order.

The Python tests (`proxy/tests`) run against an in-process fake provider (`FakeProvider` in
`test_broker.py`): an MCP server plus an OAuth authorization server with DCR, PKCE, refresh,
sessions and SSE. New behaviour toward upstreams should come with a test against it. No test
may reach the network.

## Project layout

- `proxy/src/hydra_mcp/`: the Python proxy. [docs/architecture.md](docs/architecture.md) has a
  code map.
- `admin/src/`: the admin page (React, no UI library, one stylesheet with tokens for light and
  dark).
- `docs/`: user documentation. `docs/connectors.md` is generated.

## Adding or updating a connector

The library is `proxy/src/hydra_mcp/catalog/connectors.json`. Each entry has the server URL,
how sign-in works (`auth`), optional curated `scopes`, and a `guide` shown in the admin page.

1. Check the facts against the vendor's current documentation and the server's live discovery:

   ```bash
   curl -si -X POST <url> -H 'Content-Type: application/json' -d '{}' | grep -i www-authenticate
   curl -s <protected resource metadata URL from that header>
   curl -s <authorization server>/.well-known/oauth-authorization-server
   ```

   `auth` is `oauth_dcr` when the authorization server metadata has a `registration_endpoint`,
   `oauth_preregistered` when it does not (then add `guide.client` steps).
2. Write the guide for someone who has never used the service: what to prepare, how two accounts
   are told apart, pitfalls with dates when they expire, and links to the official docs only.
3. If the server returns no identity in its tokens, consider an identity probe in
   `broker/identity.py` so accounts get a meaningful name.
4. Regenerate the docs and run the tests (a test fails if they differ):

   ```bash
   cd proxy && uv run python -m hydra_mcp.catalog.docs ../docs/connectors.md && uv run pytest -q
   ```

5. Update `checked_at` in `connectors.json` when you re-verified the whole library.

## Pull requests

- One topic per pull request, with a description of what changes for a user and how you tested
  it (the template asks).
- Keep commits focused; we squash on merge, so the PR title becomes the commit message. Write it
  in the imperative: "Add Jira Data Center connector".
- Add a line to `CHANGELOG.md` under *Unreleased* for anything a user would notice.
- UI changes: include a screenshot, light and dark if colours changed.
- Never commit tokens, keys, real email addresses or `.env` files. Push protection blocks known
  secret formats, but not everything.

## Style

- Python: ruff (line length 100), type hints, `from __future__ import annotations`. Prefer the
  standard library; every new dependency needs a reason in the PR.
- TypeScript: strict mode, function components, no UI framework.
- Comments explain *why*, not what. Docstrings on modules and public functions.
- User-facing text: short sentences, active voice, say what to do next.

## Code of conduct

Everyone taking part follows the [Code of Conduct](CODE_OF_CONDUCT.md).

## License

By contributing, you agree that your contributions are licensed under the
[Apache License 2.0](LICENSE), as stated in its section 5.
