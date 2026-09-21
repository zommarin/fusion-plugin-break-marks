default:
    @just --list

dev:
    uv sync --all-groups

format:
    uv run ruff format .
    uv run ruff check --fix .

lint:
    uv run ruff format --check .
    uv run ruff check .

typecheck:
    uv run ty check tests

test:
    uv run pytest

check: lint typecheck test
