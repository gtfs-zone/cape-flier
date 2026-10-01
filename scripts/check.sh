#!/bin/sh
# Lint, format, dead code, dependencies and tests; run by the pre-commit hook and CI.
set -e
uv run --all-extras ruff check .
uv run --all-extras ruff format --check .
uv run --all-extras vulture
uv run --all-extras deptry src
uv run --all-extras pytest -q
