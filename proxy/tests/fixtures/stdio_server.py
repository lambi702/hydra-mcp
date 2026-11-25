"""A tiny MCP server over stdio, for tests. Behaviour is driven by environment variables:

FAKE_TOKEN       required secret; without it the server exits like a real one would
FAKE_BANNER      printed on stdout before anything (a protocol violation some servers make)
FAKE_CRASH_ON    a tool name that makes the process exit mid-call
"""

import json
import os
import sys

if os.environ.get("FAKE_BANNER"):
    print(os.environ["FAKE_BANNER"], flush=True)
token = os.environ.get("FAKE_TOKEN")
if not token:
    print("error: FAKE_TOKEN is not set", file=sys.stderr, flush=True)
    sys.exit(3)

TOOLS = [
    {
        "name": "whoami",
        "description": "Who this process is",
        "inputSchema": {"type": "object", "properties": {}},
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "write_note",
        "description": "Write a note",
        "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}},
    },
]


def send(msg):
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()


for line in sys.stdin:
    msg = json.loads(line)
    method, msg_id = msg.get("method"), msg.get("id")
    if msg_id is None or method is None:  # notifications, and replies to our ping
        continue
    if method == "initialize":
        # A server may ping the client while it is initializing; the client must answer.
        send({"jsonrpc": "2.0", "id": "srv-1", "method": "ping"})
        result = {
            "protocolVersion": msg["params"]["protocolVersion"],
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "fake-stdio", "version": "1.0"},
        }
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        name = msg["params"]["name"]
        if name == os.environ.get("FAKE_CRASH_ON"):
            print("boom: simulated crash", file=sys.stderr, flush=True)
            os._exit(7)
        send({"jsonrpc": "2.0", "method": "notifications/message", "params": {"data": "hi"}})
        text = {
            "whoami": f"token={token} pid={os.getpid()} home={os.environ.get('HOME')} "
            f"shared={os.environ.get('SHARED', '')} leak={os.environ.get('HYDRA_MCP_SECRET', '')}",
            "write_note": f"wrote {msg['params'].get('arguments', {}).get('text')}",
        }[name]
        result = {"content": [{"type": "text", "text": text}]}
    else:
        send({"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32601, "message": method}})
        continue
    send({"jsonrpc": "2.0", "id": msg_id, "result": result})
