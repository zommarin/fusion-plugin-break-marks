# Generic Python Template Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish a generic public GitHub repository template with the same Python workflow and no Fusion dependency.

**Architecture:** A standalone repository contains Nix/direnv system tooling, uv dependency management, just actions, and baseline quality checks. Generic smoke coverage keeps the untouched template green. GitHub marks the public repository as a template.

**Tech Stack:** Python 3.13, uv, Nix flakes, direnv, just, pytest, Ruff, ty, GitHub CLI

**Spec:** `docs/superpowers/specs/2026-09-21-python-development-tooling-design.md`

## Global Constraints

- Create public `zommarin/python-template`.
- Do not include `adsk` or Fusion-specific content.
- Commit `flake.lock` and `uv.lock`.
- `just check` must pass before publication.
- Mark repository as a GitHub template.

---

### Task 1: Generic Template Scaffold

**Files:**
- Create: `.envrc`
- Create: `.gitignore`
- Create: `.python-version`
- Create: `LICENSE`
- Create: `README.md`
- Create: `flake.nix`
- Create: `flake.lock`
- Create: `justfile`
- Create: `pyproject.toml`
- Create: `tests/test_python.py`
- Create: `uv.lock`

**Interfaces:**
- Consumes: Nix flakes and Python package index.
- Produces: green baseline repository with `just dev`, `just format`, `just lint`, `just typecheck`, `just test`, and `just check`.

- [ ] **Step 1: Initialize local Git repository**

Create `/Users/az/src/zommarin/python-template`, initialize branch `main`, and copy the existing MIT license plus Python ignore rules. Track `.envrc`; ignore `.direnv/` and `.venv`.

- [ ] **Step 2: Add baseline smoke test**

```python
import sys


def test_supported_python_version() -> None:
    assert sys.version_info >= (3, 13)
```

- [ ] **Step 3: Run test to verify missing development environment**

Run: `python3 -m pytest tests/test_python.py`
Expected: failure when host Python is older than 3.13 or pytest is unavailable.

- [ ] **Step 4: Add generic project and tool configuration**

Create metadata named `python-template`, Python `>=3.13`, no runtime dependencies, and development dependencies `pytest`, `ruff`, and `ty`. Configure Ruff line length 100 with `E`, `F`, `I`, `UP`, `B`, and `SIM`; configure ty for Python 3.13. Add the same Nix shell and just recipes as the Fusion repository, excluding `adsk`. Document `direnv allow`, `just dev`, `just check`, and metadata renaming after template creation.

- [ ] **Step 5: Generate locks and verify**

Run: `nix flake lock`
Expected: `flake.lock` created.

Run: `nix develop --command uv lock`
Expected: `uv.lock` created without `adsk`.

Run: `nix develop --command just dev`
Expected: dependencies synchronized.

Run: `nix develop --command just check`
Expected: Ruff, ty, and pytest pass.

Run: `nix flake check`
Expected: flake evaluates successfully.

- [ ] **Step 6: Commit scaffold**

```bash
git add .
git commit -m "build: add Python project template"
```

### Task 2: GitHub Publication

**Files:**
- No local file changes.

**Interfaces:**
- Consumes: committed local `main` branch.
- Produces: public template repository at `https://github.com/zommarin/python-template`.

- [ ] **Step 1: Create and push public repository**

Run: `gh repo create zommarin/python-template --public --source=. --remote=origin --push`
Expected: repository created and `main` pushed.

- [ ] **Step 2: Enable template status**

Run: `gh api --method PATCH repos/zommarin/python-template -f is_template=true`
Expected: response contains `"is_template": true`.

- [ ] **Step 3: Verify publication**

Run: `gh repo view zommarin/python-template --json url,visibility,isTemplate`
Expected: URL `https://github.com/zommarin/python-template`, visibility `PUBLIC`, template status `true`.
