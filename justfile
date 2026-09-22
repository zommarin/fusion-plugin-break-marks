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
    uv run ty check .

test:
    uv run pytest

check: lint typecheck test

deploy:
    #!/usr/bin/env bash
    set -euo pipefail
    dest="${FUSION_ADDINS_DIR:-$HOME/Library/Application Support/Autodesk/Autodesk Fusion 360/API/AddIns}/BendMarks"
    mkdir -p "$dest"
    rsync -av --delete --delete-excluded \
        --include '/__init__.py' \
        --include '/geometry.py' \
        --include '/service.py' \
        --include '/fusion_adapter.py' \
        --include '/interactive_adapter.py' \
        --include '/BendMarks.py' \
        --include '/BendMarks.manifest' \
        --exclude '*' \
        BendMarks/ "$dest/"
