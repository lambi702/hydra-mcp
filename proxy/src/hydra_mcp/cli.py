"""`hydra-mcp` command line."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import uvicorn

from hydra_mcp import __version__
from hydra_mcp.app import create_app
from hydra_mcp.settings import Settings

DEFAULT_ADMIN_DIST = Path(__file__).resolve().parents[3] / "admin" / "dist"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="hydra-mcp")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    serve = sub.add_parser("serve", help="run the proxy")
    serve.add_argument("--host")
    serve.add_argument("--port", type=int)
    serve.add_argument("--reload", action="store_true", help="auto-reload on code changes (dev)")

    sub.add_parser("admin-token", help="print the admin token for the admin page")

    bridge = sub.add_parser(
        "bridge",
        help="stdio MCP server relaying to a running hydra-mcp (for Claude Desktop)",
        description="Reads the client key from HYDRA_MCP_KEY. Logs go to stderr; stdout is "
        "the MCP channel.",
    )
    bridge.add_argument("--url", help="hydra-mcp /mcp URL (default http://127.0.0.1:8765/mcp)")

    args = parser.parse_args(argv)
    if args.cmd == "bridge":
        # Before Settings(): the bridge must not read the proxy's .env or touch its data dir.
        from hydra_mcp.bridge import main as bridge_main

        raise SystemExit(bridge_main(args.url, None))
    settings = Settings()
    if settings.admin_dist is None and DEFAULT_ADMIN_DIST.is_dir():
        settings.admin_dist = DEFAULT_ADMIN_DIST

    if args.cmd == "admin-token":
        print(settings.resolved_admin_token)
        return

    host = args.host or settings.host
    port = args.port or settings.port
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    print(f"hydra-mcp {__version__}")
    print(f"  proxy      http://{host}:{port}")
    if settings.admin_dist:
        # The token rides in the fragment: browsers never send it to a server or log it.
        print(f"  admin page http://{host}:{port}/admin/#token={settings.resolved_admin_token}")
        print("             (open this link: it logs you in; keep it private)")
    if settings.external_base_url:
        print(f"  external   {settings.external_base_url}/mcp  (apps on the internet: OAuth login)")
    else:
        print(f"  admin token: run `hydra-mcp admin-token` (stored in {settings.data_dir})")
    if args.reload:
        uvicorn.run("hydra_mcp.app:create_app", factory=True, host=host, port=port, reload=True)
    else:
        uvicorn.run(create_app(settings), host=host, port=port)
