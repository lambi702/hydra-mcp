"""`hydra-mcp` command line.

hydra-mcp                 same as `hydra-mcp serve`
hydra-mcp serve [--open]  run the proxy (admin page included)
hydra-mcp demo            run it with a fake provider and two accounts already connected
hydra-mcp admin-token     print the admin token
"""

from __future__ import annotations

import argparse
import errno
import logging
import socket
import sys
import tempfile
import threading
import webbrowser
from importlib import resources
from pathlib import Path

import uvicorn

from hydra_mcp import __version__
from hydra_mcp.app import Services, create_app
from hydra_mcp.settings import Settings

# A source checkout: <repo>/proxy/src/hydra_mcp/cli.py -> <repo>/admin/dist (after `make build`)
CHECKOUT_ADMIN_DIST = Path(__file__).resolve().parents[3] / "admin" / "dist"
COMMANDS = {"serve", "demo", "admin-token", "bridge"}


def packaged_admin_dist() -> Path | None:
    """The admin page shipped inside the wheel (hydra_mcp/web), if this install has one."""
    web = resources.files("hydra_mcp").joinpath("web")
    index = web.joinpath("index.html")
    return Path(str(web)) if index.is_file() else None


def find_admin_dist(settings: Settings) -> Path | None:
    """HYDRA_MCP_ADMIN_DIST, else a fresh build in a source checkout, else the packaged copy."""
    if settings.admin_dist is not None:
        return settings.admin_dist
    if (CHECKOUT_ADMIN_DIST / "index.html").is_file():
        return CHECKOUT_ADMIN_DIST
    return packaged_admin_dist()


def _browser_host(host: str) -> str:
    """The host to put in links: a wildcard bind is reached through loopback."""
    return "127.0.0.1" if host in ("0.0.0.0", "::", "") else host


def _check_port(host: str, port: int) -> None:
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    try:
        with socket.socket(family) as probe:
            if sys.platform != "win32":
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.bind((host, port))
    except OSError as error:
        if error.errno not in (errno.EADDRINUSE, getattr(errno, "WSAEADDRINUSE", errno.EADDRINUSE)):
            return  # Let Uvicorn report other bind errors as usual.
        print(
            f"hydra-mcp: port {port} is already in use. "
            "Stop the other process or choose another port with --port or HYDRA_MCP_PORT.",
            file=sys.stderr,
        )
        raise SystemExit(1) from None


def main(argv: list[str] | None = None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)
    # `hydra-mcp` and `hydra-mcp --port 9000` mean `hydra-mcp serve ...`
    if not argv or (argv[0] not in COMMANDS and argv[0] not in ("-h", "--help", "--version")):
        argv.insert(0, "serve")

    parser = argparse.ArgumentParser(
        prog="hydra-mcp", description="One MCP endpoint, every account."
    )
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    serve = sub.add_parser("serve", help="run the proxy (default command)")
    demo = sub.add_parser(
        "demo", help="try hydra-mcp with a fake provider: no account or OAuth app needed"
    )
    for p in (serve, demo):
        p.add_argument("--host", help="interface to bind (default 127.0.0.1)")
        p.add_argument("--port", type=int, help="port (default 8765)")
    serve.add_argument("--open", action="store_true", help="open the admin page in a browser")
    serve.add_argument("--reload", action="store_true", help="auto-reload on code changes (dev)")
    demo.add_argument("--no-open", action="store_true", help="do not open a browser")
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

    if args.cmd == "admin-token":
        print(settings.resolved_admin_token)
        return

    if args.host:
        settings.host = args.host
    if args.port:
        settings.port = args.port
    if "public_url" not in settings.model_fields_set:
        # Follow --host/--port unless the URL was set explicitly (a tunnel, a reverse proxy).
        settings.public_url = f"http://{_browser_host(settings.host)}:{settings.port}"
    settings.admin_dist = find_admin_dist(settings)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )

    if args.cmd == "demo":
        _run_demo(settings, open_browser=not args.no_open)
        return

    _check_port(settings.host, settings.port)
    admin_url = f"{settings.base_url}/admin/#token={settings.resolved_admin_token}"
    print(f"hydra-mcp {__version__}")
    print(f"  MCP endpoint  {settings.base_url}/mcp")
    _print_admin(settings, admin_url)
    if settings.external_base_url:
        print(
            f"  external      {settings.external_base_url}/mcp  (apps on the internet: OAuth login)"
        )
    if args.open and settings.admin_dist:
        _open_later(admin_url)
    if args.reload:
        uvicorn.run(
            "hydra_mcp.app:create_app",
            factory=True,
            host=settings.host,
            port=settings.port,
            reload=True,
        )
    else:
        uvicorn.run(create_app(settings), host=settings.host, port=settings.port)


def _print_admin(settings: Settings, admin_url: str) -> None:
    if settings.admin_dist:
        # The token rides in the fragment: browsers never send it to a server or log it.
        print(f"  admin page    {admin_url}")
        print("                (this link logs you in: keep it private)")
    else:
        print("  admin page    not available: this install has no built admin page.")
        print(
            "                Install from PyPI (uvx hydra-mcp) or run `make build` in a checkout."
        )


def _open_later(url: str) -> None:
    """Open the browser once uvicorn has had a moment to bind (harmless when headless)."""
    threading.Timer(1.0, lambda: webbrowser.open(url)).start()


def _run_demo(settings: Settings, *, open_browser: bool) -> None:
    from hydra_mcp.demo import DemoProvider, seed

    # Keep the terminal for the banner: per-request logs would bury it.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("hydra_mcp").setLevel(logging.WARNING)
    with tempfile.TemporaryDirectory(prefix="hydra-mcp-demo-") as tmp:
        # A throwaway data dir: the demo never touches ~/.hydra-mcp or your real accounts.
        settings.data_dir = Path(tmp)
        settings.admin_token = ""
        admin_url = f"{settings.base_url}/admin/#token={settings.resolved_admin_token}"
        provider = DemoProvider(settings.base_url)

        async def on_startup(services: Services) -> None:
            result = await seed(services, provider)
            _print_demo_banner(settings, admin_url, result.client_key, result.accounts)
            if open_browser and settings.admin_dist:
                _open_later(admin_url)

        app = create_app(settings, demo=provider, on_startup=on_startup)
        uvicorn.run(app, host=settings.host, port=settings.port, log_level="warning")


def _print_demo_banner(settings: Settings, admin_url: str, key: str, accounts: list[str]) -> None:
    mcp = f"{settings.base_url}/mcp"
    print(
        f"""
hydra-mcp {__version__}: demo mode
  A fake provider, "Demo Tracker", runs inside the proxy. Two of its workspaces are already
  connected as accounts ({" and ".join(accounts)}), through the same OAuth flow a real service
  uses. Data is in memory and in a temporary folder, deleted when you stop the demo.

  1. Admin page
     {admin_url if settings.admin_dist else "(not built in this install)"}
     Connections: "+ Add another account" on Demo Tracker shows its sign-in page
     (pick Initech). Clients: drag accounts into "Claude Code (demo)".

  2. Use it from Claude Code (the client sees acme read + write, globex read only)
     claude mcp add --scope user --transport http hydra-demo {mcp} \\
       --header "Authorization: Bearer {key}"
     Then ask: "List the open issues in acme and in globex."
     Remove it afterwards: claude mcp remove hydra-demo

  3. Or with curl
     curl -s {mcp} -H "Authorization: Bearer {key}" \\
       -H "Content-Type: application/json" \\
       -d '{{"jsonrpc":"2.0","id":1,"method":"tools/list"}}'

  Ctrl+C stops the demo.
""",
        flush=True,
    )
