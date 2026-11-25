#!/usr/bin/env bash
# Check a built dist/ the way a user meets it: the wheel ships the admin page, and
# `hydra-mcp demo` from a clean virtualenv serves the admin page and a working /mcp.
#
#   scripts/check-dist.sh proxy/dist
set -euo pipefail
dist=${1:?usage: check-dist.sh DIST_DIR}
wheel=$(ls "$dist"/hydra_mcp-*.whl)
sdist=$(ls "$dist"/hydra_mcp-*.tar.gz)

# (listings captured first: `grep -q` closing a pipe early would trip pipefail)
wheel_files=$(unzip -l "$wheel")
sdist_files=$(tar tzf "$sdist")
grep -q 'hydra_mcp/web/index.html' <<<"$wheel_files" || { echo "wheel has no admin page"; exit 1; }
grep -q 'src/hydra_mcp/web/index.html' <<<"$sdist_files" || { echo "sdist has no admin page"; exit 1; }

venv=$(mktemp -d)
log=$(mktemp)
port=${PORT:-18765}
uv venv -q "$venv"
uv pip install -q --python "$venv/bin/python" "$wheel"
"$venv/bin/hydra-mcp" --version
"$venv/bin/hydra-mcp" demo --no-open --port "$port" >"$log" 2>&1 &
pid=$!
trap 'kill $pid 2>/dev/null || true; rm -rf "$venv" "$log"' EXIT

for _ in $(seq 1 30); do curl -fs "http://127.0.0.1:$port/healthz" >/dev/null && break; sleep 1; done
curl -fs -o /dev/null "http://127.0.0.1:$port/admin/" || { cat "$log"; echo "no admin page"; exit 1; }
key=$(grep -o 'hmcp_[A-Za-z0-9_-]*' "$log" | head -1)
tools=$(curl -fs "http://127.0.0.1:$port/mcp" -H "Authorization: Bearer $key" \
  -H 'Content-Type: application/json' -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}')
echo "$tools" | grep -q '"demo__search_issues"' || { echo "$tools"; exit 1; }
echo "dist OK: $(basename "$wheel")"
