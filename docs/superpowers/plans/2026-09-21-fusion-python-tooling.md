# Fusion Python Tooling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add reproducible Python development tooling for the Fusion break-marks add-in.

**Architecture:** Nix and direnv provide system tools. uv owns Python development dependencies and locking; just exposes stable developer actions. A pytest smoke test proves Fusion API stubs are installed.

**Tech Stack:** Python 3.13, uv, Nix flakes, direnv, just, pytest, Ruff, ty, adsk

**Spec:** `docs/superpowers/specs/2026-09-21-python-development-tooling-design.md`

## Global Constraints

- Match `../fusion-plugin-voronoi` development workflow.
- Keep `adsk` development-only because Fusion supplies it at runtime.
- Commit `flake.lock` and `uv.lock`.
- `just check` must run formatting checks, lint, type checking, and tests.

---

### Task 1: Fusion Development Environment

**Files:**
- Create: `.envrc`
- Create: `.python-version`
- Create: `flake.nix`
- Create: `flake.lock`
- Create: `justfile`
- Create: `pyproject.toml`
- Create: `uv.lock`
- Create: `tests/test_adsk.py`
- Modify: `.gitignore`
- Modify: `README.md`

**Interfaces:**
- Consumes: Nix flakes and Python package index.
- Produces: `just dev`, `just format`, `just lint`, `just typecheck`, `just test`, and `just check` developer commands.

- [ ] **Step 1: Add Fusion API smoke test**

```python
import adsk.core
import adsk.fusion


def test_fusion_api_is_available() -> None:
    assert adsk.core.Application
    assert adsk.fusion.Design
```

- [ ] **Step 2: Run test to verify missing development environment**

Run: `python3 -m pytest tests/test_adsk.py`
Expected: failure because pytest or `adsk` is unavailable from the unmanaged environment.

- [ ] **Step 3: Add project and tool configuration**

Create project metadata for `fusion-plugin-break-marks`, Python `>=3.13`, Ruff line length 100 with `E`, `F`, `I`, `UP`, `B`, and `SIM` rules, ty Python 3.13, and development dependencies `adsk`, `pytest`, `ruff`, and `ty`. Add Nix packages `direnv`, `just`, `python313`, and `uv`; set `UV_PYTHON` to Nix Python. Add just recipes matching the produced interface. Track `.envrc`, ignore `.direnv/`, and document setup plus runtime ownership of `adsk`.

- [ ] **Step 4: Generate reproducibility locks**

Run: `nix flake lock`
Expected: `flake.lock` created.

Run: `nix develop --command uv lock`
Expected: `uv.lock` created with all four development dependencies.

- [ ] **Step 5: Run checks**

Run: `nix develop --command just dev`
Expected: dependencies synchronized into `.venv`.

Run: `nix develop --command just check`
Expected: Ruff, ty, and pytest pass.

Run: `nix flake check`
Expected: flake evaluates successfully.

- [ ] **Step 6: Commit**

```bash
git add .envrc .gitignore .python-version README.md flake.lock flake.nix justfile pyproject.toml tests/test_adsk.py uv.lock docs/superpowers/plans/2026-09-21-fusion-python-tooling.md
git commit -m "build: add Fusion Python development tooling"
```
