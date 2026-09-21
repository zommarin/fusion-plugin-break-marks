# Python Development Tooling Design

## Goal

Provide reproducible Python development for the Fusion break-marks add-in and a reusable public GitHub template for generic Python projects.

## Fusion Repository

Mirror the established `fusion-plugin-voronoi` workflow, adapting project metadata. Nix supplies Python 3.13, uv, just, and direnv. uv manages development dependencies and the committed lockfile. The development group contains Autodesk Fusion API stubs (`adsk`), pytest, Ruff, and ty. A smoke test verifies the Fusion API imports available to editors, checks, and tests.

The justfile exposes dependency sync, formatting, linting, type checking, testing, and an aggregate check. direnv loads the flake. The README explains setup and warns that Fusion supplies `adsk` at runtime.

## Generic Template Repository

Create public `zommarin/python-template` and mark it as a GitHub template. Keep the same Python 3.13, uv, Nix, direnv, just, pytest, Ruff, and ty workflow, but omit `adsk` and all Fusion-specific content. Include a small Python-version smoke test so `just check` succeeds immediately after repository creation.

The template README explains environment setup and which project metadata to rename. Generated `flake.lock` and `uv.lock` files are committed for reproducibility.

## Verification

For each repository, run dependency synchronization and the aggregate just recipe. Validate each Nix flake. For the GitHub repository, verify public visibility and template status through GitHub CLI/API.
