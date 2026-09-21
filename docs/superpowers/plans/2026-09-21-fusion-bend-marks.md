# Fusion Bend Marks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an Autodesk Fusion add-in that creates parametric rectangular cutouts at both endpoints of every straight bend centerline in an active sheet-metal flat pattern.

**Architecture:** Pure geometry computes endpoint-local rectangles without Autodesk dependencies. A transactional service coordinates replacement through a narrow backend protocol, while a Fusion adapter owns dynamic flat-pattern API access, constrained sketch creation, attributes, and cut extrusion. A thin add-in entrypoint registers one auto-executing Sheet Metal command.

**Tech Stack:** Python 3.13, Autodesk Fusion Python API, pytest, Ruff, ty, uv, just

**Spec:** `docs/superpowers/specs/2026-09-21-fusion-bend-marks-design.md`

## Global Constraints

- Process all straight bends from the currently active `FlatPatternProduct`; never create or activate a flat pattern.
- Create two flat-pattern-only cutouts per supported bend and skip curved bend centerlines with a warning count.
- Use named length parameters `bend_mark_width` (`1.8 mm`), `bend_mark_inset` (`1 mm`), and `bend_mark_overhang` (`1 mm`); all values must remain positive.
- Tag generated sketch and cut with Fusion attributes; never establish ownership from display names.
- Reruns replace prior tagged marks and restore prior marks if replacement fails.
- Keep newer flat-pattern API dynamic access inside the Fusion adapter because current development stubs omit those classes.
- Require Fusion API October 2022 or newer, when `FlatPattern.bendLinesBody` was introduced.
- Keep `adsk` development-only; Fusion supplies it at runtime.

## File Structure

- `BendMarks/__init__.py`: package marker only.
- `BendMarks/BendMarks.py`: Fusion `run`/`stop`, command registration, handlers, and user messages.
- `BendMarks/BendMarks.manifest`: installable Fusion add-in metadata.
- `BendMarks/geometry.py`: immutable 2D geometry types and endpoint rectangle calculation.
- `BendMarks/service.py`: backend protocol, result/error types, and failure-safe replacement orchestration.
- `BendMarks/fusion_adapter.py`: all Autodesk model reads/writes, constraints, parameters, attributes, and extrusion.
- `tests/test_geometry.py`: Autodesk-independent geometry tests.
- `tests/test_service.py`: orchestration tests using an in-memory backend double.
- `tests/test_fusion_adapter.py`: narrow adapter tests for parameter validation and curve filtering using doubles.
- `tests/test_entrypoint.py`: registration constants and import smoke test.
- `README.md`: installation, operation, parameter, and limitation documentation.

---

### Task 1: Endpoint Rectangle Geometry

**Files:**
- Create: `BendMarks/__init__.py`
- Create: `BendMarks/geometry.py`
- Create: `tests/test_geometry.py`

**Interfaces:**
- Consumes: Plain `float` coordinates and dimensions in any consistent unit.
- Produces: `Point2`, `Rectangle`, `DegenerateBendError`, and `endpoint_rectangles(start: Point2, end: Point2, width: float, inset: float, overhang: float) -> tuple[Rectangle, Rectangle]`.

- [ ] **Step 1: Write failing geometry tests**

Create `BendMarks/__init__.py` empty. Create `tests/test_geometry.py` with explicit horizontal, diagonal, reversal, centering, and degenerate cases:

```python
from math import sqrt

import pytest

from BendMarks.geometry import DegenerateBendError, Point2, endpoint_rectangles


def test_horizontal_bend_creates_outward_and_inward_extents() -> None:
    start, end = endpoint_rectangles(Point2(0, 0), Point2(10, 0), 2, 3, 1)

    assert start.corners == (Point2(-1, -1), Point2(-1, 1), Point2(3, 1), Point2(3, -1))
    assert end.corners == (Point2(11, 1), Point2(11, -1), Point2(7, -1), Point2(7, 1))


def test_diagonal_bend_centers_width_on_centerline() -> None:
    start, _ = endpoint_rectangles(Point2(0, 0), Point2(2, 2), 2, 1, 1)
    root_two = sqrt(2)

    outer_midpoint = start.outer_midpoint
    inner_midpoint = start.inner_midpoint
    assert outer_midpoint.x == pytest.approx(-1 / root_two)
    assert outer_midpoint.y == pytest.approx(-1 / root_two)
    assert inner_midpoint.x == pytest.approx(1 / root_two)
    assert inner_midpoint.y == pytest.approx(1 / root_two)
    assert start.width == pytest.approx(2)


def test_reversing_bend_preserves_physical_rectangles() -> None:
    forward = endpoint_rectangles(Point2(1, 2), Point2(9, 5), 1.8, 1, 1)
    reverse = endpoint_rectangles(Point2(9, 5), Point2(1, 2), 1.8, 1, 1)

    assert set(forward[0].corners) == set(reverse[1].corners)
    assert set(forward[1].corners) == set(reverse[0].corners)


def test_zero_length_bend_is_rejected() -> None:
    with pytest.raises(DegenerateBendError, match="zero length"):
        endpoint_rectangles(Point2(4, 4), Point2(4, 4), 2, 1, 1)
```

- [ ] **Step 2: Run tests and verify failure**

Run: `uv run pytest tests/test_geometry.py -v`

Expected: FAIL during collection because `BendMarks.geometry` does not exist.

- [ ] **Step 3: Implement immutable geometry**

Create `BendMarks/geometry.py` with these public types and calculation. Corner order is outer-left, outer-right, inner-right, inner-left relative to each endpoint's inward vector:

```python
from __future__ import annotations

from dataclasses import dataclass
from math import hypot


class DegenerateBendError(ValueError):
    pass


@dataclass(frozen=True)
class Point2:
    x: float
    y: float

    def __add__(self, other: Point2) -> Point2:
        return Point2(self.x + other.x, self.y + other.y)

    def __sub__(self, other: Point2) -> Point2:
        return Point2(self.x - other.x, self.y - other.y)

    def scaled(self, factor: float) -> Point2:
        return Point2(self.x * factor, self.y * factor)


@dataclass(frozen=True)
class Rectangle:
    corners: tuple[Point2, Point2, Point2, Point2]

    @property
    def outer_midpoint(self) -> Point2:
        first, second, _, _ = self.corners
        return Point2((first.x + second.x) / 2, (first.y + second.y) / 2)

    @property
    def inner_midpoint(self) -> Point2:
        _, _, third, fourth = self.corners
        return Point2((third.x + fourth.x) / 2, (third.y + fourth.y) / 2)

    @property
    def width(self) -> float:
        first, second, _, _ = self.corners
        return hypot(second.x - first.x, second.y - first.y)


def _rectangle_at(
    endpoint: Point2,
    inward: Point2,
    width: float,
    inset: float,
    overhang: float,
) -> Rectangle:
    perpendicular = Point2(-inward.y, inward.x)
    half_width = perpendicular.scaled(width / 2)
    outer = endpoint - inward.scaled(overhang)
    inner = endpoint + inward.scaled(inset)
    return Rectangle(
        (
            outer - half_width,
            outer + half_width,
            inner + half_width,
            inner - half_width,
        )
    )


def endpoint_rectangles(
    start: Point2,
    end: Point2,
    width: float,
    inset: float,
    overhang: float,
) -> tuple[Rectangle, Rectangle]:
    delta = end - start
    length = hypot(delta.x, delta.y)
    if length <= 1e-9:
        raise DegenerateBendError("bend centerline has zero length")
    inward = delta.scaled(1 / length)
    return (
        _rectangle_at(start, inward, width, inset, overhang),
        _rectangle_at(end, inward.scaled(-1), width, inset, overhang),
    )
```

- [ ] **Step 4: Run focused and static checks**

Run: `uv run pytest tests/test_geometry.py -v`

Expected: 4 tests PASS.

Run: `uv run ruff check BendMarks/geometry.py tests/test_geometry.py && uv run ty check BendMarks/geometry.py tests/test_geometry.py`

Expected: both commands PASS.

- [ ] **Step 5: Commit geometry**

```bash
git add BendMarks/__init__.py BendMarks/geometry.py tests/test_geometry.py docs/superpowers/plans/2026-09-21-fusion-bend-marks.md
git commit -m "feat: calculate endpoint bend marks"
```

---

### Task 2: Failure-Safe Replacement Service

**Files:**
- Create: `BendMarks/service.py`
- Create: `tests/test_service.py`

**Interfaces:**
- Consumes: A `BendMarksBackend` implementation with `prepare`, parameter, ownership, suppression, build, and deletion operations.
- Produces: `BuildResult(processed_bends: int, created_marks: int, skipped_bends: int)`, `BuildArtifacts`, `ExistingMarks`, `BendMarksError`, and `rebuild_bend_marks(backend: BendMarksBackend) -> BuildResult`.

- [ ] **Step 1: Write failing orchestration tests**

Create `tests/test_service.py`. Use a `FakeBackend` that records calls and can fail `build`. Cover first creation, replacement ordering, and restoration:

```python
from dataclasses import dataclass, field

import pytest

from BendMarks.service import (
    BuildArtifacts,
    BuildResult,
    ExistingMarks,
    rebuild_bend_marks,
)


@dataclass
class FakeBackend:
    existing: ExistingMarks = ExistingMarks()
    fail_build: bool = False
    calls: list[str] = field(default_factory=list)
    created_parameters: tuple[object, ...] = ()

    def prepare(self) -> None:
        self.calls.append("prepare")

    def ensure_parameters(self) -> tuple[object, ...]:
        self.calls.append("ensure_parameters")
        return self.created_parameters

    def find_existing_marks(self) -> ExistingMarks:
        self.calls.append("find_existing_marks")
        return self.existing

    def set_cut_suppressed(self, cut: object, suppressed: bool) -> None:
        self.calls.append(f"suppress:{suppressed}")

    def build(self) -> BuildArtifacts:
        self.calls.append("build")
        if self.fail_build:
            raise RuntimeError("profile creation failed")
        return BuildArtifacts("new-sketch", "new-cut", BuildResult(2, 4, 1))

    def delete_existing_marks(self, marks: ExistingMarks) -> None:
        self.calls.append("delete_existing")

    def delete_parameters(self, parameters: tuple[object, ...]) -> None:
        self.calls.append("delete_parameters")


def test_first_build_returns_counts_without_suppression() -> None:
    backend = FakeBackend()
    assert rebuild_bend_marks(backend) == BuildResult(2, 4, 1)
    assert backend.calls == [
        "prepare",
        "ensure_parameters",
        "find_existing_marks",
        "build",
        "delete_existing",
    ]


def test_rebuild_suppresses_old_cut_before_build_and_deletes_after() -> None:
    backend = FakeBackend(existing=ExistingMarks("old-sketch", "old-cut"))
    rebuild_bend_marks(backend)
    assert backend.calls.index("suppress:True") < backend.calls.index("build")
    assert backend.calls.index("build") < backend.calls.index("delete_existing")


def test_failed_rebuild_restores_old_cut_and_new_parameters() -> None:
    parameter = object()
    backend = FakeBackend(
        existing=ExistingMarks("old-sketch", "old-cut"),
        fail_build=True,
        created_parameters=(parameter,),
    )
    with pytest.raises(RuntimeError, match="profile creation failed"):
        rebuild_bend_marks(backend)
    assert backend.calls[-2:] == ["suppress:False", "delete_parameters"]
    assert "delete_existing" not in backend.calls
```

- [ ] **Step 2: Run tests and verify failure**

Run: `uv run pytest tests/test_service.py -v`

Expected: FAIL during collection because `BendMarks.service` does not exist.

- [ ] **Step 3: Implement service protocol and transaction**

Create `BendMarks/service.py`. `build` is atomic: it must clean its own partial Fusion entities if it raises, and successful return of `BuildArtifacts` is the commit point. Old-mark deletion is post-commit cleanup; if it fails, preserve the new artifacts and leave the old cut suppressed:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class BendMarksError(RuntimeError):
    pass


@dataclass(frozen=True)
class BuildResult:
    processed_bends: int
    created_marks: int
    skipped_bends: int


@dataclass(frozen=True)
class ExistingMarks:
    sketch: object | None = None
    cut: object | None = None


@dataclass(frozen=True)
class BuildArtifacts:
    sketch: object
    cut: object
    result: BuildResult


class BendMarksBackend(Protocol):
    def prepare(self) -> None: ...
    def ensure_parameters(self) -> tuple[object, ...]: ...
    def find_existing_marks(self) -> ExistingMarks: ...
    def set_cut_suppressed(self, cut: object, suppressed: bool) -> None: ...
    def build(self) -> BuildArtifacts: ...
    def delete_existing_marks(self, marks: ExistingMarks) -> None: ...
    def delete_parameters(self, parameters: tuple[object, ...]) -> None: ...


def rebuild_bend_marks(backend: BendMarksBackend) -> BuildResult:
    backend.prepare()
    created_parameters = backend.ensure_parameters()
    existing = ExistingMarks()
    cut_to_restore: object | None = None
    try:
        existing = backend.find_existing_marks()
        if existing.cut is not None:
            cut_to_restore = existing.cut
            backend.set_cut_suppressed(existing.cut, True)
        artifacts = backend.build()
    except Exception as error:
        if cut_to_restore is not None:
            try:
                backend.set_cut_suppressed(cut_to_restore, False)
            except Exception as cleanup_error:
                error.add_note(f"Cut restoration failed: {cleanup_error}")
        try:
            backend.delete_parameters(created_parameters)
        except Exception as cleanup_error:
            error.add_note(f"Parameter cleanup failed: {cleanup_error}")
        raise

    backend.delete_existing_marks(existing)
    return artifacts.result
```

Add tests where ownership lookup, suppression, or build fails after parameter creation. Assert every applicable recovery action is attempted independently, the primary failure remains raised, and cleanup failures are attached as exception notes. Add one test where `delete_existing_marks` raises after successful `build`; assert new artifacts remain committed, the old cut remains suppressed, and created parameters are retained.

- [ ] **Step 4: Run focused and static checks**

Run: `uv run pytest tests/test_service.py -v`

Expected: all service tests PASS.

Run: `uv run ruff check BendMarks/service.py tests/test_service.py && uv run ty check BendMarks/service.py tests/test_service.py`

Expected: both commands PASS.

- [ ] **Step 5: Commit service**

```bash
git add BendMarks/service.py tests/test_service.py
git commit -m "feat: rebuild bend marks safely"
```

---

### Task 3: Fusion Flat-Pattern Adapter

**Files:**
- Create: `BendMarks/fusion_adapter.py`
- Create: `tests/test_fusion_adapter.py`

**Interfaces:**
- Consumes: `adsk.core.Application`, active `FlatPatternProduct`, `FlatPattern.bendLinesBody`, Task 1 geometry, and Task 2 service types.
- Produces: `FusionBackend(application: adsk.core.Application)` implementing every `BendMarksBackend` method; `classify_bend_geometry(geometry: object) -> bool`; `validate_parameter(name: str, parameter: object) -> float`.

- [ ] **Step 1: Write failing adapter boundary tests**

Create `tests/test_fusion_adapter.py` with doubles that do not instantiate Fusion objects:

```python
from dataclasses import dataclass

import pytest

from BendMarks.fusion_adapter import classify_bend_geometry, validate_parameter
from BendMarks.service import BendMarksError


class FakeLine3D:
    objectType = "adsk::core::Line3D"


class FakeArc3D:
    objectType = "adsk::core::Arc3D"


@dataclass
class FakeParameter:
    value: float
    unit: str = "mm"


def test_only_line3d_geometry_is_supported() -> None:
    assert classify_bend_geometry(FakeLine3D())
    assert not classify_bend_geometry(FakeArc3D())


@pytest.mark.parametrize("value", [0, -0.1])
def test_parameter_must_be_positive(value: float) -> None:
    with pytest.raises(BendMarksError, match="bend_mark_width must be a positive length"):
        validate_parameter("bend_mark_width", FakeParameter(value))


def test_parameter_returns_internal_centimeter_value() -> None:
    assert validate_parameter("bend_mark_width", FakeParameter(0.18)) == 0.18
```

- [ ] **Step 2: Run tests and verify failure**

Run: `uv run pytest tests/test_fusion_adapter.py -v`

Expected: FAIL during collection because `BendMarks.fusion_adapter` does not exist.

- [ ] **Step 3: Implement context, bend, parameter, and ownership boundaries**

Create `BendMarks/fusion_adapter.py` with constants:

```python
ATTRIBUTE_GROUP = "fusion-plugin-bend-marks"
SKETCH_ATTRIBUTE = "generated-sketch"
CUT_ATTRIBUTE = "generated-cut"
PARAMETERS = (
    ("bend_mark_width", "1.8 mm", "Bend mark width"),
    ("bend_mark_inset", "1 mm", "Bend mark depth toward bend"),
    ("bend_mark_overhang", "1 mm", "Bend mark extension beyond bend endpoint"),
)
```

Implement `classify_bend_geometry` by comparing `geometry.objectType` with `adsk.core.Line3D.classType()` when available and the stable runtime string `"adsk::core::Line3D"` otherwise. Implement `validate_parameter` using `parameter.value` in Fusion internal centimeters and reject values `<= 0`; use `parameter.unit`/`unitType` when available to reject non-length parameters with the same message.

In `FusionBackend.prepare`:

1. Read `application.activeProduct` dynamically.
2. Require `objectType == "adsk::fusion::FlatPatternProduct"`.
3. Store `product`, `product.flatPattern`, and `product.rootComponent`.
4. Enumerate `flatPattern.bendLinesBody.edges` by `count`/`item(index)`.
5. Partition straight and curved edges with `classify_bend_geometry`.
6. Raise `BendMarksError("Open a sheet-metal flat pattern before creating bend marks")` for wrong context, `BendMarksError("The active flat pattern has no bend lines")` for zero edges, and `BendMarksError("The active flat pattern has no supported straight bend lines")` when all edges are curved.

In `ensure_parameters`, use `product.userParameters.itemByName`; validate existing values and create missing values with `adsk.core.ValueInput.createByString(default_expression)`, unit `"mm"`, and the listed comment. Return only newly created parameter objects. If creation or validation fails after one or more parameters were added, delete those newly added parameters in reverse order before raising; the service cannot clean objects from a call that never returned.

In `find_existing_marks`, call `product.findAttributes(ATTRIBUTE_GROUP, SKETCH_ATTRIBUTE)` and the equivalent cut query. Resolve each attribute's `parent` and return at most one valid owned sketch and cut; raise `BendMarksError` if duplicate owned sketches or cuts exist rather than deleting ambiguous data.

- [ ] **Step 4: Implement projected constrained rectangles**

Implement a private `_create_sketch()` that adds a sketch to `rootComponent.sketches` on `flatPattern.topFace`, names it `Bend Marks`, and immediately tags it with `sketch.attributes.add(ATTRIBUTE_GROUP, SKETCH_ATTRIBUTE, "1")`.

For each supported edge:

1. Call `sketch.project(edge)` and require exactly one projected `SketchLine`.
2. Set projected line `isConstruction = True`.
3. Read projected endpoint coordinates from `startSketchPoint.geometry` and `endSketchPoint.geometry`.
4. Call `endpoint_rectangles` using current parameter values in internal centimeters.
5. Build each rectangle's four lines with `sketch.sketchCurves.sketchLines.addByTwoPoints`.
6. Add parallel/perpendicular constraints so long sides stay parallel to the projected line and end edges stay perpendicular.
7. Add two construction lines: outer midpoint to projected endpoint and projected endpoint to inner midpoint. Use projected endpoint `SketchPoint` objects directly so coincidence is structural; set both lines construction.
8. Add `addMidPoint` constraints between each construction-line free endpoint and its corresponding rectangle end edge, and `addCollinear` constraints between each construction line and projected bend line.
9. Add aligned driving distance dimensions for outer construction length, inner construction length, and rectangle width. Assign their model-parameter expressions to `bend_mark_overhang`, `bend_mark_inset`, and `bend_mark_width` respectively.

Use `adsk.fusion.DimensionOrientations.AlignedDimensionOrientation`. Position dimension text from the initial rectangle coordinates; text position does not affect geometry. If projection, a constraint, or a dimension returns null/false, raise `BendMarksError` with bend index and operation, for example `"Bend 3: could not project centerline"`.

Wrap `_create_sketch` internals in `try/except`; if any entity creation fails, call `sketch.deleteMe()` before re-raising. This satisfies the service contract that `build` does not leak partial entities before returning artifacts.

- [ ] **Step 5: Implement profile cut and transactional methods**

After all rectangles exist, collect every `sketch.profiles.item(index)` into `adsk.core.ObjectCollection`. Require at least one profile. Create one extrusion from `rootComponent.features.extrudeFeatures` using:

```python
extrude_input = extrudes.createInput(profiles, adsk.fusion.FeatureOperations.CutFeatureOperation)
if not extrude_input.setAllExtent(adsk.fusion.ExtentDirections.SymmetricExtentDirection):
    raise BendMarksError("Could not set bend mark cut to through-all")
cut = extrudes.add(extrude_input)
cut.name = "Bend Marks Cut"
cut.attributes.add(ATTRIBUTE_GROUP, CUT_ATTRIBUTE, "1")
```

Wrap extrusion creation, naming, and attribute tagging together. If any operation fails after the cut exists, delete the cut and then the new sketch; if failure occurs before a cut exists, delete the new sketch. Return `BuildArtifacts(sketch, cut, BuildResult(len(straight_edges), len(straight_edges) * 2, len(curved_edges)))` only after both ownership attributes exist.

Implement remaining backend methods exactly:

- `set_cut_suppressed`: assign `cut.isSuppressed` and verify resulting value.
- `delete_existing_marks`: delete old cut first, then old sketch; no-op for missing members.
- `delete_parameters`: call `deleteMe()` in reverse creation order.

Raise `BendMarksError` when a required delete or suppression operation reports failure.

- [ ] **Step 6: Extend adapter tests for shape and validation branches**

Add tests with collection doubles for these pure boundaries:

- Existing positive parameters are not recreated.
- Missing parameters use exact default expressions and `mm` units.
- Duplicate ownership attributes raise instead of choosing one.
- Mixed line/arc edges retain lines and increment skipped count.
- Empty bend body and all-curved body produce their exact errors.

Keep Fusion object traversal behind small private functions accepting structural objects, so these tests need no Fusion runtime.

- [ ] **Step 7: Run focused and complete checks**

Run: `uv run pytest tests/test_fusion_adapter.py tests/test_geometry.py tests/test_service.py -v`

Expected: all tests PASS.

Run: `just check`

Expected: Ruff formatting/lint, ty, and all tests PASS. If ty flags missing newer flat-pattern members, use adapter-local `cast(Any, value)` only at each dynamic API boundary; do not add global ignores.

- [ ] **Step 8: Commit adapter**

```bash
git add BendMarks/fusion_adapter.py tests/test_fusion_adapter.py
git commit -m "feat: build flat-pattern bend cuts"
```

---

### Task 4: Fusion Add-In Lifecycle And Command

**Files:**
- Create: `BendMarks/BendMarks.py`
- Create: `BendMarks/BendMarks.manifest`
- Create: `tests/test_entrypoint.py`

**Interfaces:**
- Consumes: `FusionBackend` and `rebuild_bend_marks`.
- Produces: Fusion-required `run(context: object) -> None` and `stop(context: object) -> None`; command ID `zommarin_fusion_break_marks_create`; Sheet Metal tab ID `SheetMetalTab`.

- [ ] **Step 1: Write failing entrypoint tests**

Create `tests/test_entrypoint.py`:

```python
import json
from pathlib import Path

from BendMarks import BendMarks


def test_command_uses_stable_ids() -> None:
    assert BendMarks.COMMAND_ID == "zommarin_fusion_break_marks_create"
    assert BendMarks.TAB_ID == "SheetMetalTab"
    assert BendMarks.PANEL_ID == "zommarin_fusion_break_marks_panel"


def test_manifest_defines_cross_platform_addin() -> None:
    manifest = json.loads(Path("BendMarks/BendMarks.manifest").read_text())
    assert manifest["autodeskProduct"] == "Fusion360"
    assert manifest["type"] == "addin"
    assert manifest["supportedOS"] == "windows|mac"
```

- [ ] **Step 2: Run tests and verify failure**

Run: `uv run pytest tests/test_entrypoint.py -v`

Expected: FAIL because entrypoint and manifest do not exist.

- [ ] **Step 3: Add manifest**

Create `BendMarks/BendMarks.manifest`:

```json
{
  "autodeskProduct": "Fusion360",
  "type": "addin",
  "author": "zommarin",
  "description": {
    "": "Create alignment cutouts at sheet-metal bend endpoints"
  },
  "version": "0.1.0",
  "runOnStartup": false,
  "supportedOS": "windows|mac"
}
```

- [ ] **Step 4: Implement command registration and handlers**

Create `BendMarks/BendMarks.py` with module constants from the test plus `COMMAND_NAME = "Create Bend Marks"`. Keep handler objects in module-level `_handlers: list[object]` so Fusion does not garbage-collect them.

`run` must:

1. Get `adsk.core.Application.get()` and `userInterface`.
2. Delete stale command/control/panel objects with this add-in's IDs left by an interrupted reload.
3. Add a button definition with `ui.commandDefinitions.addButtonDefinition(COMMAND_ID, COMMAND_NAME, "Create rectangular alignment cuts at every flat-pattern bend endpoint", "")`.
4. Attach a `CommandCreatedEventHandler` whose `notify` sets `args.command.isAutoExecute = True` and attaches an execute handler.
5. Locate `ui.allToolbarTabs.itemById(TAB_ID)`, create panel `PANEL_ID` named `Bend Marks`, and add the command control.
6. Raise a visible message if the Sheet Metal tab is unavailable, then remove any command definition created before failure.

The execute handler must call `rebuild_bend_marks(FusionBackend(application))`. On success, show:

```text
Created {created_marks} bend marks across {processed_bends} bends.
Skipped {skipped_bends} unsupported curved bends.
```

Omit the second line when skipped count is zero. Catch `BendMarksError` and show its message. Catch unexpected exceptions and show `traceback.format_exc()` prefixed with `Create Bend Marks failed:` so API failures remain diagnosable.

`stop` must delete the command control, panel, and command definition if present, then clear `_handlers`. Make every removal idempotent so reload and partial startup both work.

- [ ] **Step 5: Test lifecycle helpers with UI doubles**

Move lookup/deletion into private helpers receiving `ui`. Add doubles proving:

- Repeated cleanup tolerates all objects missing.
- Cleanup deletes control before panel and command definition.
- Success message includes skipped line only when nonzero.
- `run` retains both command-created and execute handlers.

- [ ] **Step 6: Run complete checks**

Run: `just check`

Expected: Ruff formatting/lint, ty, and all tests PASS.

- [ ] **Step 7: Commit add-in lifecycle**

```bash
git add BendMarks/BendMarks.py BendMarks/BendMarks.manifest tests/test_entrypoint.py
git commit -m "feat: register bend marks add-in"
```

---

### Task 5: Installation Documentation And End-To-End Verification

**Files:**
- Modify: `README.md`
- Create: `docs/manual-verification.md`

**Interfaces:**
- Consumes: Completed `BendMarks` add-in folder.
- Produces: macOS/Windows installation instructions and repeatable Fusion acceptance checklist.

- [ ] **Step 1: Write documentation acceptance test**

Add `tests/test_documentation.py`:

```python
from pathlib import Path


def test_readme_documents_required_workflow() -> None:
    readme = Path("README.md").read_text()
    for phrase in (
        "Create Bend Marks",
        "bend_mark_width",
        "bend_mark_inset",
        "bend_mark_overhang",
        "active flat pattern",
        "October 2022",
    ):
        assert phrase in readme


def test_manual_verification_covers_model_safety() -> None:
    checklist = Path("docs/manual-verification.md").read_text()
    for phrase in ("irregular", "Rerun", "Undo", "DXF", "folded"):
        assert phrase in checklist
```

- [ ] **Step 2: Run documentation tests and verify failure**

Run: `uv run pytest tests/test_documentation.py -v`

Expected: FAIL because required usage documentation is absent.

- [ ] **Step 3: Document installation and use**

Expand `README.md` with:

- Fusion October 2022 or newer requirement.
- Copy/symlink the repository's `BendMarks` directory into Fusion's `API/AddIns` directory, or add it through **Utilities > Add-Ins > Scripts and Add-Ins**.
- macOS default root: `~/Library/Application Support/Autodesk/Autodesk Fusion 360/API/AddIns/`.
- Windows default root: `%APPDATA%\Autodesk\Autodesk Fusion 360\API\AddIns\`.
- Start/reload `BendMarks`, open an existing sheet-metal flat pattern, and run **Create Bend Marks** from the Sheet Metal tab.
- Parameter names, defaults, positivity requirement, and parameter-edit behavior.
- Rerun replacement behavior.
- Straight-bend-only, active-flat-required, and flat-pattern-only limitations.

- [ ] **Step 4: Add manual verification checklist**

Create `docs/manual-verification.md` with exact acceptance steps:

1. Use a sheet-metal fixture containing one horizontal bend, one diagonal bend, one irregular/angled outside edge, and at least one curved bend if Fusion permits it.
2. Confirm folded model has no generated marks.
3. Open flat pattern and run command; expect two marks per straight bend and curved skip count.
4. Measure defaults: width `1.8 mm`, inset `1 mm`, overhang `1 mm`.
5. Change all three named parameters and compute all; verify existing marks update without rerun.
6. Rerun; verify one tagged sketch and one tagged cut remain.
7. Undo once; verify complete rerun reverses as one user action.
8. Force failure by temporarily setting a parameter to zero; verify prior marks remain and error identifies parameter.
9. Export flat pattern DXF; verify physical cutout outlines exist.
10. Return to folded model; verify cutouts remain absent.

- [ ] **Step 5: Run all automated verification**

Run: `just check`

Expected: Ruff formatting/lint, ty, and all pytest tests PASS.

Run: `nix flake check`

Expected: flake evaluates successfully.

Run: `git diff --check`

Expected: no output.

- [ ] **Step 6: Perform Fusion verification**

Install/reload the add-in and complete every item in `docs/manual-verification.md`. Record Fusion version, operating system, fixture name, and pass/fail result at the bottom of the checklist. Any failed item blocks completion and must become a focused failing automated test where the behavior can be reproduced outside Fusion.

- [ ] **Step 7: Commit documentation and verification**

```bash
git add README.md docs/manual-verification.md tests/test_documentation.py
git commit -m "docs: add bend marks usage guide"
```
