# Contributing to mcp-chassis (SOLVE-IT MCP Server)

Thank you for your interest in contributing. Please read this guide before
opening a pull request.

## Development Setup

```bash
# 1. Clone the repo
git clone https://github.com/3soos3/mcp-solve-it.git
cd mcp-solve-it

# 2. Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# 3. Install the package and dev dependencies
pip install -e ".[dev]"

# 4. Install pre-commit hooks
pip install pre-commit
pre-commit install
```

## Running Tests

```bash
# Unit tests only
pytest tests/unit/ -v

# Integration tests (requires SOLVE-IT data)
pytest tests/integration/ -v

# Full suite
pytest -v
```

## Code Style

This project uses **ruff** for linting and formatting, and **mypy** in strict
mode for type checking.

```bash
# Format
ruff format src/ tests/

# Lint (auto-fix where possible)
ruff check --fix src/ tests/

# Verify clean
ruff format --check src/ tests/
ruff check src/ tests/

# Type check
mypy src/
```

Pre-commit hooks run all of the above automatically on `git commit`. You can
also run them manually at any time:

```bash
pre-commit run --all-files
```

All checks must pass before a PR can be merged.

## Submitting PRs

1. Fork the repository and create a feature branch from `main`.
2. Make your changes, add tests where appropriate.
3. Ensure all checks pass (`pre-commit run --all-files` and `pytest`).
4. Open a pull request against `main` with a clear description of the change
   and the motivation behind it.
5. Reference any related issues in the PR description.

## Deprecating a Tool or Feature

See TODO.txt L3-07 for the formal deprecation procedure — to be filled in when
L3-07 is implemented.
