# Interactive Bend Notches Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add separate commands that create parameterized notches on selected same-sketch centerlines and cut all plugin-generated notch profiles in the active flat-pattern sketch.

**Architecture:** Extend pure geometry with stable left/right endpoint selection. New interactive service protocols coordinate same-sketch geometry replacement and per-sketch cut replacement, while a focused Fusion adapter owns selection validation, persistent entity attributes, constrained geometry, profile discovery, and extrusion. The existing automatic command remains isolated; the entrypoint registers all three commands in one panel.

**Tech Stack:** Python 3.13, Autodesk Fusion Python API, pytest, Ruff, ty, uv, just

**Spec:** `docs/superpowers/specs/2026-09-22-interactive-bend-notches-design.md`

## Global Constraints

- Keep **Create Bend Marks** behavior unchanged and available beside both interactive commands.
- Require an active `FlatPatternProduct`; never create or activate a flat pattern.
- Require one or more selected `SketchLine` entities from one sketch for **Create Selected Notches**.
- Convert selected centerlines to construction geometry during successful notch creation.
- Define left as lower sketch X, breaking equal-X ties with lower sketch Y; right is the opposite endpoint.
- Use shared length parameters `bend_mark_width` (`1.8 mm`), `bend_mark_inset` (`1 mm`), and `bend_mark_overhang` (`1 mm`); all values must be finite and positive.
- Add generated rectangles to the source sketch, not a separate sketch.
- Persist ownership with Fusion entity attributes; never infer ownership from names or geometry.
- Replace generated geometry only for selected source centerlines and replace cuts only for the active source sketch.
- Discover cuts automatically from closed profiles bounded entirely by tagged generated notch edges.
- Mark every command failure with `executeFailed` so Fusion aborts the command transaction.
- Keep `adsk` development-only; Fusion supplies it at runtime.

## File Structure

- `BendMarks/geometry.py`: existing rectangle calculation plus `NotchSide`, endpoint ordering, and side filtering.
- `BendMarks/service.py`: existing automatic service plus interactive notch and cut protocols, result types, and orchestration.
- `BendMarks/interactive_adapter.py`: new Fusion boundary for preselection, shared parameter expressions, same-sketch geometry ownership/replacement, tagged profile discovery, and per-sketch cut creation.
- `BendMarks/fusion_adapter.py`: expose the existing constrained rectangle helper for reuse without changing automatic behavior.
- `BendMarks/BendMarks.py`: register three commands, build interactive dialog inputs, retain handlers, report results, and clean all command definitions/controls.
- `tests/test_geometry.py`: side-ordering and filtering tests.
- `tests/test_service.py`: interactive orchestration ordering and recovery tests.
- `tests/test_interactive_adapter.py`: Fusion doubles for selection, attributes, geometry replacement, profile filtering, and cut replacement.
- `tests/test_fusion_adapter.py`: regression tests for the shared rectangle helper and automatic backend.
- `tests/test_entrypoint.py`: three-command registration, dialog, execution, lifecycle, and error reporting tests.
- `tests/test_documentation.py`: required interactive workflow wording.
- `README.md`: automatic and interactive user workflows.
- `docs/manual-verification.md`: Fusion acceptance checks for selection, side choice, reruns, persistence, cutting, DXF, and undo.

---

### Task 1: Stable Endpoint Side Geometry

**Files:**
- Modify: `BendMarks/geometry.py`
- Modify: `tests/test_geometry.py`

**Interfaces:**
- Consumes: Existing `Point2`, `Rectangle`, and `endpoint_rectangles(...)`.
- Produces: `NotchSide(StrEnum)`, `EndpointRectangle(side: NotchSide, rectangle: Rectangle)`, and `selected_endpoint_rectangles(start: Point2, end: Point2, width: float, inset: float, overhang: float, selection: NotchSide) -> tuple[EndpointRectangle, ...]`.

- [ ] **Step 1: Write failing side-ordering tests**

Add imports and tests proving physical ordering does not depend on source-line direction:

```python
from BendMarks.geometry import (
    DegenerateBendError,
    NotchSide,
    Point2,
    endpoint_rectangles,
    selected_endpoint_rectangles,
)


@pytest.mark.parametrize(
    ("start", "end", "expected_left"),
    [
        (Point2(10, 2), Point2(0, 2), Point2(0, 2)),
        (Point2(4, 9), Point2(4, -1), Point2(4, -1)),
    ],
)
def test_left_endpoint_uses_x_then_y_order(
    start: Point2, end: Point2, expected_left: Point2
) -> None:
    selected = selected_endpoint_rectangles(start, end, 2, 1, 1, NotchSide.LEFT)

    assert len(selected) == 1
    assert selected[0].side is NotchSide.LEFT
    assert selected[0].rectangle.outer_midpoint in {
        Point2(expected_left.x - 1, expected_left.y),
        Point2(expected_left.x, expected_left.y - 1),
    }


def test_both_returns_stable_left_then_right_order() -> None:
    selected = selected_endpoint_rectangles(Point2(10, 0), Point2(0, 0), 2, 1, 1, NotchSide.BOTH)

    assert [item.side for item in selected] == [NotchSide.LEFT, NotchSide.RIGHT]
    assert [item.rectangle.outer_midpoint.x for item in selected] == [-1, 11]


def test_right_returns_only_right_rectangle() -> None:
    selected = selected_endpoint_rectangles(Point2(0, 0), Point2(10, 0), 2, 1, 1, NotchSide.RIGHT)

    assert len(selected) == 1
    assert selected[0].side is NotchSide.RIGHT
    assert selected[0].rectangle.outer_midpoint == Point2(11, 0)
```

- [ ] **Step 2: Run focused tests and verify failure**

Run: `uv run pytest tests/test_geometry.py -v`

Expected: collection fails because `NotchSide` and `selected_endpoint_rectangles` do not exist.

- [ ] **Step 3: Implement endpoint ordering and filtering**

Add these public types and function. Keep `endpoint_rectangles` unchanged for the automatic backend:

```python
from enum import StrEnum


class NotchSide(StrEnum):
    BOTH = "both"
    LEFT = "left"
    RIGHT = "right"


@dataclass(frozen=True)
class EndpointRectangle:
    side: NotchSide
    rectangle: Rectangle


def selected_endpoint_rectangles(
    start: Point2,
    end: Point2,
    width: float,
    inset: float,
    overhang: float,
    selection: NotchSide,
) -> tuple[EndpointRectangle, ...]:
    start_rectangle, end_rectangle = endpoint_rectangles(start, end, width, inset, overhang)
    if (start.x, start.y) <= (end.x, end.y):
        left, right = start_rectangle, end_rectangle
    else:
        left, right = end_rectangle, start_rectangle
    rectangles = (
        EndpointRectangle(NotchSide.LEFT, left),
        EndpointRectangle(NotchSide.RIGHT, right),
    )
    if selection is NotchSide.BOTH:
        return rectangles
    return tuple(item for item in rectangles if item.side is selection)
```

- [ ] **Step 4: Run focused checks**

Run: `uv run pytest tests/test_geometry.py -v`

Expected: all geometry tests pass.

Run: `uv run ruff check BendMarks/geometry.py tests/test_geometry.py && uv run ty check BendMarks/geometry.py tests/test_geometry.py`

Expected: both checks pass.

- [ ] **Step 5: Commit geometry**

```bash
git add BendMarks/geometry.py tests/test_geometry.py
git commit -m "feat: select notch endpoint sides"
```

---

### Task 2: Interactive Transaction Services

**Files:**
- Modify: `BendMarks/service.py`
- Modify: `tests/test_service.py`

**Interfaces:**
- Consumes: `NotchSide`, three parameter expressions, and backend implementations supplied later by `InteractiveNotchBackend` and `InteractiveCutBackend`.
- Produces: `ParameterExpressions`, `CreateNotchesResult`, `CutNotchesResult`, `InteractiveNotchBackend`, `InteractiveCutBackend`, `create_selected_notches(...)`, and `cut_selected_notches(...)`.

- [ ] **Step 1: Write failing notch replacement service tests**

Add a recording double with methods matching the protocol and assert destructive ordering occurs inside Fusion's transaction:

```python
@dataclass
class FakeInteractiveNotchBackend:
    existing: tuple[object, ...] = ()
    calls: list[str] = field(default_factory=list)

    def prepare(self) -> None:
        self.calls.append("prepare")

    def update_parameters(self, expressions: ParameterExpressions) -> None:
        self.calls.append(f"parameters:{expressions.width}")

    def find_existing_geometry(self) -> tuple[object, ...]:
        self.calls.append("find")
        return self.existing

    def delete_geometry(self, geometry: tuple[object, ...]) -> None:
        self.calls.append(f"delete:{len(geometry)}")

    def build(self, side: NotchSide) -> CreateNotchesResult:
        self.calls.append(f"build:{side.value}")
        return CreateNotchesResult(2, 4)


def test_create_selected_notches_replaces_only_discovered_geometry() -> None:
    backend = FakeInteractiveNotchBackend(existing=(object(), object()))
    result = create_selected_notches(
        backend,
        ParameterExpressions("2 mm", "1 mm", "0.5 mm"),
        NotchSide.BOTH,
    )

    assert result == CreateNotchesResult(2, 4)
    assert backend.calls == [
        "prepare",
        "parameters:2 mm",
        "find",
        "delete:2",
        "build:both",
    ]
```

- [ ] **Step 2: Write failing cut replacement and restoration tests**

Use a cut double with `prepare`, `find_existing_cut`, `set_cut_suppressed`, `build`, and `delete_cut`. Verify first cut, successful replacement, build failure restoration, and delete failure propagation:

```python
def test_cut_selected_notches_replaces_prior_cut() -> None:
    backend = FakeInteractiveCutBackend(existing_cut="old-cut")

    assert cut_selected_notches(backend) == CutNotchesResult(3)
    assert backend.calls == [
        "prepare",
        "find",
        "suppress:True",
        "build",
        "delete",
    ]


def test_failed_interactive_cut_restores_prior_cut() -> None:
    backend = FakeInteractiveCutBackend(existing_cut="old-cut", fail_build=True)

    with pytest.raises(RuntimeError, match="cut failed"):
        cut_selected_notches(backend)

    assert backend.calls[-2:] == ["build", "suppress:False"]
```

- [ ] **Step 3: Run service tests and verify failure**

Run: `uv run pytest tests/test_service.py -v`

Expected: collection fails because interactive service types do not exist.

- [ ] **Step 4: Implement protocols and orchestration**

Add immutable values and narrow protocols:

```python
@dataclass(frozen=True)
class ParameterExpressions:
    width: str
    inset: str
    overhang: str


@dataclass(frozen=True)
class CreateNotchesResult:
    processed_lines: int
    created_notches: int


@dataclass(frozen=True)
class CutNotchesResult:
    cut_profiles: int


class InteractiveNotchBackend(Protocol):
    def prepare(self) -> None: ...
    def update_parameters(self, expressions: ParameterExpressions) -> None: ...
    def find_existing_geometry(self) -> tuple[object, ...]: ...
    def delete_geometry(self, geometry: tuple[object, ...]) -> None: ...
    def build(self, side: NotchSide) -> CreateNotchesResult: ...


class InteractiveCutBackend(Protocol):
    def prepare(self) -> None: ...
    def find_existing_cut(self) -> object | None: ...
    def set_cut_suppressed(self, cut: object, suppressed: bool) -> None: ...
    def build(self) -> CutNotchesResult: ...
    def delete_cut(self, cut: object) -> None: ...
```

Implement `create_selected_notches` with exact call order from the test. Implement `cut_selected_notches` using the existing `rebuild_bend_marks` suppression pattern: restore only when `build()` raises; after successful build, propagate deletion failures and rely on `executeFailed` transaction rollback.

- [ ] **Step 5: Run service regression checks**

Run: `uv run pytest tests/test_service.py -v`

Expected: all automatic and interactive service tests pass.

Run: `uv run ruff check BendMarks/service.py tests/test_service.py && uv run ty check BendMarks/service.py tests/test_service.py`

Expected: both checks pass.

- [ ] **Step 6: Commit service contracts**

```bash
git add BendMarks/service.py tests/test_service.py
git commit -m "feat: orchestrate interactive notches"
```

---

### Task 3: Same-Sketch Notch Adapter

**Files:**
- Create: `BendMarks/interactive_adapter.py`
- Create: `tests/test_interactive_adapter.py`
- Modify: `BendMarks/fusion_adapter.py`
- Modify: `tests/test_fusion_adapter.py`
- Modify: `justfile`
- Modify: `tests/test_deploy.py`

**Interfaces:**
- Consumes: `application`, captured selection entities, `ParameterExpressions`, `NotchSide`, and the existing rectangle constraint logic.
- Produces: `parameter_expressions(application: object) -> ParameterExpressions` and `InteractiveNotchBackend(application: object, selected_entities: tuple[object, ...])` implementing the Task 2 protocol.

- [ ] **Step 1: Extract reusable constrained rectangle creation**

Write a regression test that invokes a module-level helper with an existing sketch line and endpoint, then checks four profile edges, two construction helpers, seven geometric constraints, and three named dimensions. Move `FusionBackend._add_rectangle` to:

```python
def add_constrained_rectangle(
    sketch: object,
    centerline: object,
    endpoint: object,
    rectangle: Rectangle,
    context: str,
) -> tuple[object, object, object, object, object, object]: ...
```

Use `context` in every `BendMarksError`, such as `"Bend 1: could not create rectangle edge"`. Update `FusionBackend._create_sketch` to call the helper. Do not change automatic geometry, dimensions, ownership tags, or error text.

- [ ] **Step 2: Run automatic adapter regression tests**

Run: `uv run pytest tests/test_fusion_adapter.py -v`

Expected: all existing tests and the helper regression pass.

- [ ] **Step 3: Write failing selection and parameter tests**

Create adapter doubles and tests for these exact cases:

```python
def test_prepare_requires_at_least_one_selected_line() -> None:
    backend = InteractiveNotchBackend(flat_pattern_application(), ())

    with pytest.raises(BendMarksError, match="Select one or more sketch centerlines"):
        backend.prepare()


def test_prepare_rejects_mixed_sketches() -> None:
    first = fake_line(parent_sketch=FakeSketch())
    second = fake_line(parent_sketch=FakeSketch())

    with pytest.raises(BendMarksError, match="same sketch"):
        InteractiveNotchBackend(flat_pattern_application(), (first, second)).prepare()


def test_parameter_expressions_reuse_existing_expressions() -> None:
    application = flat_pattern_application(
        parameters={
            "bend_mark_width": FakeParameter("2 mm", 0.2),
            "bend_mark_inset": FakeParameter("0.8 mm", 0.08),
            "bend_mark_overhang": FakeParameter("1.2 mm", 0.12),
        }
    )

    assert parameter_expressions(application) == ParameterExpressions("2 mm", "0.8 mm", "1.2 mm")
```

Also test non-line selection, sketch outside the active flat-pattern root component, invalid existing parameters, creation of missing parameters from entered expressions, and update of existing parameter `.expression` values.

- [ ] **Step 4: Implement preparation and shared parameter updates**

In `interactive_adapter.py`, reuse `ATTRIBUTE_GROUP`, `PARAMETERS`, `_collection_items`, and `validate_parameter`. Define distinct ownership names:

```python
SOURCE_ID_ATTRIBUTE = "interactive-source-id"
SKETCH_ID_ATTRIBUTE = "interactive-sketch-id"
GEOMETRY_SOURCE_ATTRIBUTE = "interactive-geometry-source"
GEOMETRY_SIDE_ATTRIBUTE = "interactive-geometry-side"
NOTCH_EDGE_ATTRIBUTE = "interactive-notch-edge"
INTERACTIVE_CUT_ATTRIBUTE = "interactive-cut-sketch"
```

`prepare()` must validate `activeProduct.objectType == "adsk::fusion::FlatPatternProduct"`, every selected entity's type against `adsk.fusion.SketchLine.classType()`, one shared `parentSketch`, and `sketch.parentComponent is product.rootComponent`. Store validated product, sketch, and lines only after all checks pass.

`parameter_expressions` returns each existing parameter's `.expression`; use defaults from `PARAMETERS` when missing. `update_parameters` creates missing parameters with `ValueInput.createByString(expression)` and assigns entered expressions to existing parameters. Validate each result with `validate_parameter` after assignment; any failure propagates so Fusion rolls back all changes.

- [ ] **Step 5: Write failing ownership and replacement tests**

Test first creation and a selective rerun:

```python
def test_build_converts_lines_and_tags_generated_geometry(monkeypatch: pytest.MonkeyPatch) -> None:
    line = fake_line(Point2(0, 0), Point2(10, 0))
    backend = prepared_backend(monkeypatch, (line,))

    result = backend.build(NotchSide.BOTH)

    assert result == CreateNotchesResult(1, 2)
    assert line.isConstruction
    assert attribute_value(line, SOURCE_ID_ATTRIBUTE)
    assert attribute_value(line.parentSketch, SKETCH_ID_ATTRIBUTE)
    assert generated_profile_sides(line.parentSketch) == ["left", "right"]
    assert all(attribute_value(edge, NOTCH_EDGE_ATTRIBUTE) == "1" for edge in profile_edges)


def test_find_existing_geometry_returns_only_selected_sources() -> None:
    selected = fake_line(source_id="selected")
    other = fake_line(source_id="other", parent_sketch=selected.parentSketch)
    selected_geometry = fake_generated_line("selected")
    other_geometry = fake_generated_line("other")
    selected.parentSketch.sketchCurves.sketchLines = FakeCollection(
        [selected, other, selected_geometry, other_geometry]
    )
    backend = prepared_backend(lines=(selected,))

    assert backend.find_existing_geometry() == (selected_geometry,)
```

Also test left-only/right-only counts, duplicate source IDs, malformed side values, deletion false/exception propagation, and preservation of other source geometry.

- [ ] **Step 6: Implement persistent ownership and same-sketch build**

Use `uuid.uuid4().hex` only when a selected line or source sketch lacks its ID. Before assigning new IDs, reject duplicate non-empty source IDs among sketch lines. `find_existing_geometry()` scans sketch lines for `GEOMETRY_SOURCE_ATTRIBUTE` values matching selected source IDs and validates associated `GEOMETRY_SIDE_ATTRIBUTE` as `left` or `right`.

`build(side)` must, for each selected line:

1. Set `line.isConstruction = True` and verify the assignment.
2. Convert start/end sketch-point geometry into `Point2`.
3. Call `selected_endpoint_rectangles` using current parameter values.
4. Call `add_constrained_rectangle` with context `"Centerline {index}"`.
5. Tag all six returned lines with source ID and side.
6. Tag only the first four rectangle boundary lines with `NOTCH_EDGE_ATTRIBUTE = "1"`.

Return `CreateNotchesResult(len(lines), created_rectangle_count)`. `delete_geometry` calls `deleteMe()` for every discovered generated line and raises `BendMarksError` on false or exception; transaction rollback restores prior entities if any deletion or build operation fails.

- [ ] **Step 7: Run notch adapter checks**

Run: `uv run pytest tests/test_interactive_adapter.py -k 'not cut' -v`

Expected: all selection, parameter, ownership, and geometry tests pass.

Run: `uv run pytest tests/test_fusion_adapter.py -v`

Expected: automatic adapter regression suite passes.

- [ ] **Step 8: Include the interactive adapter in deployment**

Add `--include '/interactive_adapter.py'` beside the existing runtime modules in the `just deploy` rsync allowlist. Add `"interactive_adapter.py"` to the exact deployed-file set in `tests/test_deploy.py`.

Run: `uv run pytest tests/test_deploy.py -v`

Expected: both deployment and isolated Fusion-style import tests pass with the new runtime module included.

- [ ] **Step 9: Commit notch adapter**

```bash
git add BendMarks/fusion_adapter.py BendMarks/interactive_adapter.py tests/test_fusion_adapter.py tests/test_interactive_adapter.py justfile tests/test_deploy.py
git commit -m "feat: create selected sketch notches"
```

---

### Task 4: Tagged Profile Cut Adapter

**Files:**
- Modify: `BendMarks/interactive_adapter.py`
- Modify: `tests/test_interactive_adapter.py`

**Interfaces:**
- Consumes: `application.activeEditObject`, generated notch-edge attributes, source sketch ID, and root-component extrude features.
- Produces: `InteractiveCutBackend(application: object)` implementing the Task 2 cut protocol.

- [ ] **Step 1: Write failing active-sketch and profile-discovery tests**

Add profile-loop doubles matching Fusion's `Profile.profileLoops -> ProfileLoop.profileCurves -> ProfileCurve.sketchEntity` shape. Cover:

```python
def test_cut_prepare_requires_active_flat_pattern_sketch() -> None:
    application = flat_pattern_application(active_edit_object=None)

    with pytest.raises(BendMarksError, match="Activate the sketch containing generated notches"):
        InteractiveCutBackend(application).prepare()


def test_profile_discovery_accepts_only_fully_tagged_boundaries() -> None:
    valid = fake_profile([tagged_edge() for _ in range(4)])
    unrelated = fake_profile([untagged_edge() for _ in range(4)])
    incomplete = fake_profile([tagged_edge(), tagged_edge(), tagged_edge(), untagged_edge()])
    mixed_sources = fake_profile(
        [tagged_edge(source_id="a"), tagged_edge(source_id="b"), tagged_edge(), tagged_edge()]
    )
    backend = prepared_cut_backend(profiles=[valid, unrelated, incomplete, mixed_sources])

    assert backend.discover_profiles() == (valid,)
```

Also reject an active object of the wrong type, a sketch outside the active root component, missing/malformed sketch ID, profiles with multiple loops, invalid source/side metadata, and no valid generated profiles.

- [ ] **Step 2: Implement active sketch and strict profile discovery**

`prepare()` validates active flat-pattern product, `application.activeEditObject` type against `adsk.fusion.Sketch.classType()`, and `parentComponent is product.rootComponent`. Require exactly one non-empty `SKETCH_ID_ATTRIBUTE` value on the sketch.

`discover_profiles()` includes a profile only when it has one closed loop containing exactly four curves, every curve shares one source ID and side, and every curve's `sketchEntity` has all of:

- `NOTCH_EDGE_ATTRIBUTE == "1"`
- non-empty `GEOMETRY_SOURCE_ATTRIBUTE`
- `GEOMETRY_SIDE_ATTRIBUTE` equal to `left` or `right`

Reject malformed generated metadata with `BendMarksError`; ignore fully untagged profiles and mixed tagged/untagged profiles. Raise `BendMarksError("The active sketch has no generated notch profiles")` when none qualify.

- [ ] **Step 3: Write failing cut ownership and extrusion tests**

Cover exact sketch-scoped ownership and through-all behavior:

```python
def test_find_existing_cut_filters_by_active_sketch_id() -> None:
    matching = fake_cut(attribute_value="sketch-a")
    other = fake_cut(attribute_value="sketch-b")
    backend = prepared_cut_backend(sketch_id="sketch-a", cuts=[matching, other])

    assert backend.find_existing_cut() is matching


def test_build_cuts_discovered_profiles_through_all() -> None:
    backend, extrudes = prepared_cut_backend_with_extrudes(profile_count=2)

    assert backend.build() == CutNotchesResult(2)
    assert extrudes.input.one_side_extents == [
        ("through-all", adsk.fusion.ExtentDirections.NegativeExtentDirection)
    ]
    assert extrudes.cut.name == "Selected Notches Cut"
    assert attribute_value(extrudes.cut, INTERACTIVE_CUT_ATTRIBUTE) == backend.sketch_id
```

Also test duplicate matching cuts, profile collection add failure, null extrude input, extent failure, null cut, tag failure cleanup, suppression verification, and delete false/exception propagation.

- [ ] **Step 4: Implement sketch-scoped cut replacement operations**

`find_existing_cut()` calls `product.findAttributes(ATTRIBUTE_GROUP, INTERACTIVE_CUT_ATTRIBUTE)`, filters valid `ExtrudeFeature` parents by attribute value equal to active sketch ID, and rejects more than one match.

`build()` collects discovered profiles in `adsk.core.ObjectCollection`, creates a cut input with `CutFeatureOperation`, applies `ThroughAllExtentDefinition` in `NegativeExtentDirection`, adds the feature, names it `Selected Notches Cut`, and tags it with `INTERACTIVE_CUT_ATTRIBUTE = sketch_id`. If creation or tagging fails after a cut exists, delete that partial cut before re-raising. Return `CutNotchesResult(profile_count)`.

`set_cut_suppressed` assigns and verifies `isSuppressed`, using interactive-cut error text. `delete_cut` requires `deleteMe()` to return true.

- [ ] **Step 5: Run full adapter checks**

Run: `uv run pytest tests/test_interactive_adapter.py tests/test_fusion_adapter.py -v`

Expected: all interactive and automatic adapter tests pass.

Run: `uv run ruff check BendMarks/interactive_adapter.py tests/test_interactive_adapter.py && uv run ty check BendMarks/interactive_adapter.py tests/test_interactive_adapter.py`

Expected: both checks pass.

- [ ] **Step 6: Commit cut adapter**

```bash
git add BendMarks/interactive_adapter.py tests/test_interactive_adapter.py
git commit -m "feat: cut generated sketch notches"
```

---

### Task 5: Three-Command Fusion UI

**Files:**
- Modify: `BendMarks/BendMarks.py`
- Modify: `tests/test_entrypoint.py`

**Interfaces:**
- Consumes: `parameter_expressions`, both interactive backends, Task 2 service functions, `NotchSide`, and Fusion active selections.
- Produces: three controls under the Bend Marks panel with IDs `zommarin_fusion_break_marks_create`, `zommarin_fusion_break_marks_create_selected`, and `zommarin_fusion_break_marks_cut_selected`.

- [ ] **Step 1: Refactor lifecycle tests for multiple command IDs**

Replace one-ID fake assumptions with `COMMAND_IDS` iteration. Assert `run()` creates definitions and controls for:

```python
COMMAND_SPECS = (
    (COMMAND_ID, "Create Bend Marks"),
    (CREATE_SELECTED_COMMAND_ID, "Create Selected Notches"),
    (CUT_SELECTED_COMMAND_ID, "Cut Selected Notches"),
)
```

Update cleanup tests to expect all controls deleted before panel deletion and all definitions deleted afterward. Keep tests for missing tab, partial registration failure, repeated cleanup, handler rollback, destroy release, and `stop()`; each must verify no retained handler or UI entity leaks.

- [ ] **Step 2: Implement generic three-command registration and cleanup**

Add constants and iterate command specifications in `run()`. Create one panel, add controls in specification order, and retain one command-created handler per definition. `_cleanup_ui` must attempt deletion of all known controls and definitions even after individual failures, aggregate diagnostics, and delete the shared panel after controls but before definitions.

Keep the existing automatic command's `isAutoExecute = True`. Both interactive commands use normal dialogs with `isAutoExecute = False`.

- [ ] **Step 3: Write failing Create Selected Notches dialog tests**

Extend command doubles with `commandInputs`, `activeSelections`, and value/dropdown inputs. Assert command creation captures selection entities and adds:

```python
(
    ("width", "Width", "mm", "bend_mark_width expression"),
    ("inset", "Inset", "mm", "bend_mark_inset expression"),
    ("overhang", "Overhang", "mm", "bend_mark_overhang expression"),
)
```

Assert side list item names are `Both`, `Left`, `Right`, with `Both` selected. On execute, assert entered expressions become `ParameterExpressions`, selected item maps to `NotchSide`, and the handler calls:

```python
create_selected_notches(
    InteractiveNotchBackend(application, captured_entities),
    expressions,
    side,
)
```

Expected success message: `Created 3 notches from 2 selected centerlines.` Domain failures set `executeFailed` and show the domain message; unexpected failures include `Create Selected Notches failed:` plus traceback.

- [ ] **Step 4: Implement Create Selected Notches handlers**

At command creation, read `ui.activeSelections` into an immutable tuple of `.entity` values before building inputs. Read defaults through `parameter_expressions(application)`. Add three `ValueCommandInput` values using `ValueInput.createByString`, unit `mm`, and a `TextListDropDownStyle` side input. Retain execute and destroy handlers exactly as for the automatic command.

At execute, use each value input's `.expression`, map selected item name case-insensitively through `NotchSide(value)`, invoke the service, and report the specified result text.

- [ ] **Step 5: Write failing Cut Selected Notches command tests**

Assert cut command creation adds no inputs and retains execute/destroy handlers. On execute, patch `InteractiveCutBackend` and `cut_selected_notches`; verify success text `Cut 4 generated notch profiles.`. Test domain and unexpected errors with `executeFailed = True`, including traceback prefix `Cut Selected Notches failed:`.

- [ ] **Step 6: Implement Cut Selected Notches handlers**

Use a normal non-auto-executing command so Fusion presents command confirmation consistently. Execute `cut_selected_notches(InteractiveCutBackend(application))`; show profile count on success and preserve the common failure behavior.

- [ ] **Step 7: Run UI and regression checks**

Run: `uv run pytest tests/test_entrypoint.py -v`

Expected: all three-command registration, dialog, execution, cleanup, and handler lifetime tests pass.

Run: `uv run pytest tests/test_adsk.py tests/test_service.py tests/test_fusion_adapter.py tests/test_interactive_adapter.py -v`

Expected: all API smoke, service, and adapter regressions pass.

- [ ] **Step 8: Commit command UI**

```bash
git add BendMarks/BendMarks.py tests/test_entrypoint.py
git commit -m "feat: register interactive notch commands"
```

---

### Task 6: User Documentation And Acceptance

**Files:**
- Modify: `README.md`
- Modify: `docs/manual-verification.md`
- Modify: `tests/test_documentation.py`

**Interfaces:**
- Consumes: Final command names, side ordering, shared parameters, ownership, and rerun behavior.
- Produces: Installation-independent usage instructions and manual Fusion acceptance evidence.

- [ ] **Step 1: Write failing documentation assertions**

Extend required README phrases with:

```python
for phrase in (
    "Create Selected Notches",
    "Cut Selected Notches",
    "construction geometry",
    "same sketch",
    "lower sketch X",
    "active sketch",
):
    assert phrase in readme
```

Extend manual-checklist assertions with `Both`, `Left`, `Right`, `save and reopen`, and `selected centerlines`.

- [ ] **Step 2: Run documentation tests and verify failure**

Run: `uv run pytest tests/test_documentation.py -v`

Expected: tests fail because interactive instructions are absent.

- [ ] **Step 3: Document both workflows**

Keep the current automatic usage section. Add an interactive section with this sequence:

1. Open the flat pattern and edit one sketch.
2. Select one or more centerlines from that sketch.
3. Run **Create Selected Notches**, enter shared parameter expressions, and choose Both, Left, or Right.
4. Explain automatic conversion to construction geometry and lower-X/lower-Y side ordering.
5. Inspect or edit generated geometry, keep the sketch active, then run **Cut Selected Notches**.
6. Explain per-centerline geometry replacement, per-sketch cut replacement, and save/reopen ownership persistence.

Update limitations to require one source sketch per creation invocation and straight `SketchLine` centerlines.

- [ ] **Step 4: Expand manual Fusion verification**

Add a fixture sketch containing horizontal, reversed, vertical, and diagonal lines plus an unrelated closed profile. Add checks for multi-selection, shared dialog expressions, all three side choices, non-construction conversion, selected-only replacement, preserving another line's notches, ignoring unrelated profiles, replacing one cut, save/reopen persistence, one-step undo after each command, DXF output, and folded-model isolation.

- [ ] **Step 5: Run complete verification**

Run: `just format`

Expected: formatting completes without errors.

Run: `just check`

Expected: Ruff formatting/lint, ty type checking, and all pytest tests pass.

Run: `git diff --check`

Expected: no whitespace errors.

- [ ] **Step 6: Commit documentation and formatting**

```bash
git add README.md docs/manual-verification.md tests/test_documentation.py BendMarks tests
git commit -m "docs: explain interactive notch workflow"
```

- [ ] **Step 7: Perform Fusion manual verification when Fusion is available**

Reload the add-in and complete every item in `docs/manual-verification.md`. Record Fusion version, operating system, fixture name, overall result, and failure notes. If Fusion is unavailable, leave runtime fields explicitly pending and report that limitation without claiming manual acceptance.
