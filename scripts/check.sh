#!/bin/sh
# Lint, format check and tests; run by the pre-commit hook and CI.
set -e
uv run --all-extras ruff check .
uv run --all-extras ruff format --check .
uv run --all-extras pytest -q
