# syntax=docker/dockerfile:1
# hydra-mcp: the proxy with its admin page, in one image.
#
#   docker run -d --name hydra-mcp -p 127.0.0.1:8765:8765 -v hydra-mcp:/data ghcr.io/lambi702/hydra-mcp
#   docker logs hydra-mcp                 # prints the admin page link
#   docker run --rm -p 127.0.0.1:8765:8765 ghcr.io/lambi702/hydra-mcp demo   # try it, no account needed

# Base images, overridable (e.g. --build-arg PYTHON_IMAGE=mirror.gcr.io/library/python:3.13-slim)
ARG NODE_IMAGE=node:22-alpine
ARG PYTHON_IMAGE=python:3.13-slim

# 1. The admin page (TypeScript -> static files)
FROM ${NODE_IMAGE} AS admin
WORKDIR /src/admin
COPY admin/package.json admin/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY admin/ ./
RUN npm run build

# 2. The Python wheel, with the admin page inside it (same artifact as on PyPI)
FROM ${PYTHON_IMAGE} AS wheel
RUN pip install --no-cache-dir --root-user-action=ignore "uv>=0.11,<0.12"
WORKDIR /src/proxy
COPY proxy/ ./
COPY --from=admin /src/admin/dist ./src/hydra_mcp/web
RUN uv build --wheel --out-dir /dist \
 && uv export --frozen --no-dev --no-emit-project --format requirements-txt -o /dist/requirements.txt

# 3. Runtime: locked dependencies + the wheel, as an unprivileged user
FROM ${PYTHON_IMAGE}
LABEL org.opencontainers.image.title="hydra-mcp" \
      org.opencontainers.image.description="One MCP endpoint, every account: a multi-account proxy for MCP servers" \
      org.opencontainers.image.source="https://github.com/lambi702/hydra-mcp" \
      org.opencontainers.image.licenses="Apache-2.0" \
      io.modelcontextprotocol.server.name="io.github.lambi702/hydra-mcp"
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    # Inside the container the proxy must listen on all interfaces; publish the port on the
    # host's loopback only (-p 127.0.0.1:8765:8765) to keep it private to your machine.
    HYDRA_MCP_HOST=0.0.0.0 \
    HYDRA_MCP_PORT=8765 \
    HYDRA_MCP_DATA_DIR=/data
COPY --from=wheel /dist /tmp/dist
RUN pip install --no-cache-dir -r /tmp/dist/requirements.txt \
 && pip install --no-cache-dir --no-deps /tmp/dist/*.whl \
 && rm -rf /tmp/dist \
 && useradd --uid 10001 --create-home hydra \
 && mkdir /data && chown hydra:hydra /data
USER hydra
VOLUME /data
EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/healthz', timeout=2)"
ENTRYPOINT ["hydra-mcp"]
CMD ["serve"]
