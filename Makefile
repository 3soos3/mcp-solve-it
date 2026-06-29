.PHONY: install test test-unit test-integration \
        test-images test-images-fast test-images-crypto test-images-auth test-images-network \
        build-live build-monthly build-version build-all \
        ci ci-images \
        lint typecheck format

SOLVE_IT_VERSION ?= v0.2026-06

# ── Dev install ────────────────────────────────────────────────────────────────
install:
	pip install -e ".[dev]"

# ── Unit / integration tests ───────────────────────────────────────────────────
test: test-unit test-integration

test-unit:
	pytest tests/unit/ -v

test-integration:
	pytest tests/integration/ -v

# ── Image build targets ────────────────────────────────────────────────────────
build-live:
	podman build \
	  --build-arg SOLVE_IT_MODE=live \
	  --build-arg FORENSIC_METADATA=false \
	  -t solve-it-mcp:live .

build-monthly:
	podman build \
	  --build-arg SOLVE_IT_MODE=monthly \
	  --build-arg FORENSIC_METADATA=false \
	  --build-arg SOLVE_IT_VERSION=main-$(shell date -u +%Y%m) \
	  -t solve-it-mcp:monthly .

build-version:
	podman build \
	  --build-arg SOLVE_IT_MODE=release \
	  --build-arg FORENSIC_METADATA=true \
	  --build-arg SOLVE_IT_VERSION=$(SOLVE_IT_VERSION) \
	  -t solve-it-mcp:version .

build-all: build-live build-monthly build-version

# ── Image test targets ─────────────────────────────────────────────────────────
test-images:
	pytest tests/images/ -v -m "not network"

test-images-fast:
	pytest tests/images/ -v -m "not slow and not network"

test-images-crypto:
	pytest tests/images/ -v -m crypto

test-images-auth:
	pytest tests/images/ -v -m auth

test-images-network:
	pytest tests/images/ -v -m network

# Pass custom image tags from CI (e.g. content-addressed digests):
#   make test-images-ci PYTEST_ARGS="--version-image solve-it-mcp@sha256:abc"
test-images-ci:
	pytest tests/images/ -v -m "not network" $(PYTEST_ARGS)

# ── CI pipeline ────────────────────────────────────────────────────────────────
ci: test build-all test-images

ci-images: build-all test-images

# ── Code quality ───────────────────────────────────────────────────────────────
lint:
	ruff check src/ tests/

typecheck:
	mypy src/mcp_chassis/

format:
	ruff format src/ tests/
	ruff check --fix src/ tests/
