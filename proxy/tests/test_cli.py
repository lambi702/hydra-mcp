from __future__ import annotations

import socket

import pytest

from hydra_mcp.cli import main


@pytest.mark.parametrize("extra_args", [[], ["--reload"]])
def test_serve_reports_busy_port_before_printing_links(
    capsys, monkeypatch, tmp_path, extra_args
) -> None:
    monkeypatch.setenv("HYDRA_MCP_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(
        "hydra_mcp.cli.uvicorn.run",
        lambda *args, **kwargs: pytest.fail("uvicorn should not run on a known busy port"),
    )
    with socket.socket() as occupied:
        occupied.bind(("127.0.0.1", 0))
        occupied.listen()
        port = occupied.getsockname()[1]
        with pytest.raises(SystemExit) as exc:
            main(["serve", "--host", "127.0.0.1", "--port", str(port), *extra_args])
    assert exc.value.code == 1
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == (
        f"hydra-mcp: port {port} is already in use. "
        "Stop the other process or choose another port with --port or HYDRA_MCP_PORT.\n"
    )
