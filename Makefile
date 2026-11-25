.PHONY: install dev proxy demo admin build package docker test lint fmt

install:          ## install Python and Node dependencies
	cd proxy && uv sync
	cd admin && npm install

build:            ## build the admin page and copy it into the Python package (served at /admin/)
	cd admin && npm run build
	rm -rf proxy/src/hydra_mcp/web && cp -R admin/dist proxy/src/hydra_mcp/web

package: build    ## build the sdist and wheel (admin page included) into proxy/dist
	cd proxy && rm -rf dist && uv build

docker:           ## build the Docker image hydra-mcp:dev
	docker build -t hydra-mcp:dev .

proxy:            ## run the proxy (serves admin/dist if built)
	cd proxy && uv run hydra-mcp serve

demo:             ## run the demo: a fake provider with two accounts already connected
	cd proxy && uv run hydra-mcp demo

dev:              ## proxy with auto-reload + admin page with hot reload on :5173
	(cd proxy && uv run hydra-mcp serve --reload) & (cd admin && npm run dev); wait

test:             ## Python tests + TypeScript type check
	cd proxy && uv run pytest -q
	cd admin && npm run typecheck

lint:
	cd proxy && uv run ruff check . && uv run ruff format --check .

fmt:
	cd proxy && uv run ruff format . && uv run ruff check --fix .
