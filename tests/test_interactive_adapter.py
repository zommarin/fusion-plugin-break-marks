from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, cast

import adsk.fusion
import pytest

from BendMarks.geometry import NotchSide, Point2
from BendMarks.interactive_adapter import (
    ATTRIBUTE_GROUP,
    GEOMETRY_SIDE_ATTRIBUTE,
    GEOMETRY_SOURCE_ATTRIBUTE,
    INTERACTIVE_CUT_ATTRIBUTE,
    NOTCH_EDGE_ATTRIBUTE,
    SKETCH_ID_ATTRIBUTE,
    SOURCE_ID_ATTRIBUTE,
    InteractiveCutBackend,
    InteractiveNotchBackend,
    parameter_expressions,
)
from BendMarks.service import (
    BendMarksError,
    CreateNotchesResult,
    CutNotchesResult,
    ParameterExpressions,
)

DEFAULT_START = Point2(0, 0)
DEFAULT_END = Point2(10, 0)


class FakeAttributes:
    def __init__(
        self,
        values: dict[str, str] | None = None,
        add_result: bool | Exception = True,
    ) -> None:
        self.values = values or {}
        self.add_result = add_result

    def itemByName(self, group: str, name: str) -> object | None:
        if group != ATTRIBUTE_GROUP or name not in self.values:
            return None
        return SimpleNamespace(value=self.values[name])

    def add(self, group: str, name: str, value: str) -> object:
        assert group == ATTRIBUTE_GROUP
        if isinstance(self.add_result, Exception):
            raise self.add_result
        if not self.add_result:
            return False
        self.values[name] = value
        return object()


class FakeCollection:
    def __init__(self, items: list[object] | None = None) -> None:
        self.items = items or []

    @property
    def count(self) -> int:
        return len(self.items)

    def item(self, index: int) -> object:
        return self.items[index]


@dataclass
class FakeParameter:
    _expression: str
    value: float
    unit: str = "mm"

    @property
    def expression(self) -> str:
        return self._expression

    @expression.setter
    def expression(self, expression: str) -> None:
        self._expression = expression
        self.value = float(expression.split()[0]) / 10


@dataclass
class FakeUserParameters:
    parameters: dict[str, FakeParameter] = field(default_factory=dict)
    added: list[tuple[str, object, str, str]] = field(default_factory=list)

    def itemByName(self, name: str) -> FakeParameter | None:
        return self.parameters.get(name)

    def add(self, name: str, value: object, unit: str, comment: str) -> FakeParameter:
        self.added.append((name, value, unit, comment))
        parameter = FakeParameter(str(value), float(str(value).split()[0]) / 10, unit)
        self.parameters[name] = parameter
        return parameter


class FakeSketch:
    objectType = "adsk::fusion::Sketch"

    def __init__(
        self,
        parent_component: object | None = None,
        profiles: list[object] | None = None,
    ) -> None:
        self.parentComponent = parent_component
        self.attributes = FakeAttributes()
        self.sketchCurves = SimpleNamespace(sketchLines=FakeCollection())
        self.profiles = FakeCollection(profiles)


class FakeLine:
    objectType = "adsk::fusion::SketchLine"

    def __init__(
        self,
        start: Point2 = DEFAULT_START,
        end: Point2 = DEFAULT_END,
        *,
        parent_sketch: FakeSketch | None = None,
        source_id: str | None = None,
        generated_source: str | None = None,
        generated_side: str | None = None,
        delete_result: bool | Exception = True,
    ) -> None:
        self.parentSketch = parent_sketch or FakeSketch()
        self.startSketchPoint = SimpleNamespace(geometry=SimpleNamespace(x=start.x, y=start.y))
        self.endSketchPoint = SimpleNamespace(geometry=SimpleNamespace(x=end.x, y=end.y))
        self.isConstruction = False
        values = {}
        if source_id is not None:
            values[SOURCE_ID_ATTRIBUTE] = source_id
        if generated_source is not None:
            values[GEOMETRY_SOURCE_ATTRIBUTE] = generated_source
        if generated_side is not None:
            values[GEOMETRY_SIDE_ATTRIBUTE] = generated_side
        self.attributes = FakeAttributes(values)
        self.delete_result = delete_result
        self.deleted = False

    def deleteMe(self) -> bool:
        if isinstance(self.delete_result, Exception):
            raise self.delete_result
        self.deleted = True
        return self.delete_result


def fake_line(
    start: Point2 = DEFAULT_START,
    end: Point2 = DEFAULT_END,
    **kwargs: Any,
) -> FakeLine:
    line = FakeLine(start, end, **kwargs)
    if line not in line.parentSketch.sketchCurves.sketchLines.items:
        line.parentSketch.sketchCurves.sketchLines.items.append(line)
    return line


def flat_pattern_application(
    *,
    parameters: dict[str, FakeParameter] | None = None,
    root_component: object | None = None,
    active_edit_object: object | None = None,
) -> object:
    product = SimpleNamespace(
        objectType="adsk::fusion::FlatPatternProduct",
        rootComponent=root_component or object(),
        userParameters=FakeUserParameters(parameters or {}),
    )
    return SimpleNamespace(activeProduct=product, activeEditObject=active_edit_object)


def generated_edge(
    *,
    notch: str | None = "1",
    source_id: str | None = "source-a",
    side: str | None = "left",
) -> object:
    values = {}
    if notch is not None:
        values[NOTCH_EDGE_ATTRIBUTE] = notch
    if source_id is not None:
        values[GEOMETRY_SOURCE_ATTRIBUTE] = source_id
    if side is not None:
        values[GEOMETRY_SIDE_ATTRIBUTE] = side
    return SimpleNamespace(attributes=FakeAttributes(values))


def untagged_edge() -> object:
    return SimpleNamespace(attributes=FakeAttributes())


def fake_profile(edges: list[object], *, extra_loop: bool = False) -> object:
    loops: list[object] = [
        SimpleNamespace(
            profileCurves=FakeCollection([SimpleNamespace(sketchEntity=edge) for edge in edges])
        )
    ]
    if extra_loop:
        loops.append(SimpleNamespace(profileCurves=FakeCollection()))
    return SimpleNamespace(profileLoops=FakeCollection(loops))


def prepared_cut_backend(
    *,
    profiles: list[object] | None = None,
    sketch_id: str = "sketch-a",
    cuts: list[object] | None = None,
    root_component: object | None = None,
) -> InteractiveCutBackend:
    root_component = root_component or object()
    sketch = FakeSketch(root_component, profiles)
    sketch.attributes.values[SKETCH_ID_ATTRIBUTE] = sketch_id
    application = flat_pattern_application(root_component=root_component, active_edit_object=sketch)
    cut_attributes: list[object] = [
        SimpleNamespace(
            parent=cut,
            value=attribute_value(cut, INTERACTIVE_CUT_ATTRIBUTE),
        )
        for cut in cuts or []
    ]
    cast(Any, application).activeProduct.findAttributes = lambda group, name: (
        FakeCollection(cut_attributes)
        if group == ATTRIBUTE_GROUP and name == INTERACTIVE_CUT_ATTRIBUTE
        else FakeCollection()
    )
    backend = InteractiveCutBackend(application)
    backend.prepare()
    return backend


class FakeCut:
    objectType = "adsk::fusion::ExtrudeFeature"

    def __init__(
        self,
        *,
        attribute_value: str | None = None,
        valid: bool = True,
        attribute_result: bool | Exception = True,
        delete_result: bool | Exception = True,
    ) -> None:
        values = (
            {INTERACTIVE_CUT_ATTRIBUTE: attribute_value} if attribute_value is not None else None
        )
        self.attributes = FakeAttributes(values, attribute_result)
        self.isValid = valid
        self.isSuppressed = False
        self.name = ""
        self.delete_result = delete_result
        self.deleted = False

    def deleteMe(self) -> bool:
        if isinstance(self.delete_result, Exception):
            raise self.delete_result
        self.deleted = True
        return self.delete_result


class FakeObjectCollection:
    def __init__(self, *, add_result: bool = True) -> None:
        self.items: list[object] = []
        self.add_result = add_result

    def add(self, item: object) -> bool:
        if not self.add_result:
            return False
        self.items.append(item)
        return True


class FakeExtrudeInput:
    def __init__(self, *, extent_result: bool = True) -> None:
        self.extent_result = extent_result
        self.one_side_extents: list[tuple[object, object]] = []

    def setOneSideExtent(self, extent: object, direction: object) -> bool:
        self.one_side_extents.append((extent, direction))
        return self.extent_result


class FakeExtrudes:
    def __init__(
        self,
        *,
        input_result: object = True,
        extent_result: bool = True,
        cut: FakeCut | None = None,
    ) -> None:
        self.input = FakeExtrudeInput(extent_result=extent_result)
        self.input_result = input_result
        self.cut: FakeCut | None = cut or FakeCut()
        self.create_arguments: tuple[object, object] | None = None

    def createInput(self, profiles: object, operation: object) -> object | None:
        self.create_arguments = (profiles, operation)
        return self.input if self.input_result else None

    def add(self, _extrude_input: object) -> FakeCut | None:
        return self.cut


def prepared_cut_backend_with_extrudes(
    monkeypatch: pytest.MonkeyPatch,
    *,
    profile_count: int = 2,
    collection_add_result: bool = True,
    input_result: object = True,
    extent_result: bool = True,
    cut: FakeCut | None = None,
) -> tuple[InteractiveCutBackend, FakeExtrudes]:
    monkeypatch.setattr(
        "BendMarks.interactive_adapter.adsk.core.ObjectCollection.create",
        lambda: FakeObjectCollection(add_result=collection_add_result),
    )
    monkeypatch.setattr(
        "BendMarks.interactive_adapter.adsk.fusion.ThroughAllExtentDefinition.create",
        lambda: "through-all",
    )
    extrudes = FakeExtrudes(
        input_result=input_result,
        extent_result=extent_result,
        cut=cut,
    )
    root_component = SimpleNamespace(features=SimpleNamespace(extrudeFeatures=extrudes))
    profiles = [fake_profile([generated_edge() for _ in range(4)]) for _ in range(profile_count)]
    return prepared_cut_backend(profiles=profiles, root_component=root_component), extrudes


def test_cut_prepare_requires_active_flat_pattern_sketch() -> None:
    application = flat_pattern_application(active_edit_object=None)

    with pytest.raises(BendMarksError, match="Activate the sketch containing generated notches"):
        InteractiveCutBackend(application).prepare()


def test_cut_prepare_requires_active_flat_pattern_product() -> None:
    application = flat_pattern_application(active_edit_object=FakeSketch())
    cast(Any, application).activeProduct.objectType = "adsk::fusion::Design"

    with pytest.raises(BendMarksError, match="Open a sheet-metal flat pattern"):
        InteractiveCutBackend(application).prepare()


def test_cut_prepare_rejects_wrong_active_edit_object_type() -> None:
    active_object = SimpleNamespace(objectType="adsk::fusion::ExtrudeFeature")

    with pytest.raises(BendMarksError, match="Activate the sketch containing generated notches"):
        InteractiveCutBackend(flat_pattern_application(active_edit_object=active_object)).prepare()


def test_cut_prepare_rejects_sketch_outside_active_flat_pattern_root() -> None:
    sketch = FakeSketch(parent_component=object())

    with pytest.raises(BendMarksError, match="active flat pattern"):
        InteractiveCutBackend(flat_pattern_application(active_edit_object=sketch)).prepare()


@pytest.mark.parametrize("sketch_id", [None, ""], ids=["missing", "empty"])
def test_cut_prepare_requires_valid_sketch_id(sketch_id: str | None) -> None:
    root_component = object()
    sketch = FakeSketch(root_component)
    if sketch_id is not None:
        sketch.attributes.values[SKETCH_ID_ATTRIBUTE] = sketch_id

    with pytest.raises(BendMarksError, match="generated notch sketch ID"):
        InteractiveCutBackend(
            flat_pattern_application(root_component=root_component, active_edit_object=sketch)
        ).prepare()


def test_profile_discovery_accepts_only_fully_tagged_boundaries() -> None:
    valid = fake_profile([generated_edge() for _ in range(4)])
    unrelated = fake_profile([untagged_edge() for _ in range(4)])
    incomplete = fake_profile([generated_edge() for _ in range(3)] + [untagged_edge()])
    mixed_sources = fake_profile(
        [
            generated_edge(source_id="a"),
            generated_edge(source_id="b"),
            generated_edge(),
            generated_edge(),
        ]
    )
    mixed_sides = fake_profile(
        [generated_edge(side="left"), generated_edge(side="right")] + [generated_edge()] * 2
    )
    wrong_edge_count = fake_profile([generated_edge() for _ in range(3)])
    unrelated_multiple_loops = fake_profile([untagged_edge() for _ in range(4)], extra_loop=True)
    backend = prepared_cut_backend(
        profiles=[
            valid,
            unrelated,
            incomplete,
            mixed_sources,
            mixed_sides,
            wrong_edge_count,
            unrelated_multiple_loops,
        ]
    )

    assert backend.discover_profiles() == (valid,)


def test_profile_discovery_rejects_tagged_profile_with_multiple_loops() -> None:
    tagged_multiple_loops = fake_profile([generated_edge() for _ in range(4)], extra_loop=True)
    backend = prepared_cut_backend(profiles=[tagged_multiple_loops])

    with pytest.raises(BendMarksError, match="exactly one loop"):
        backend.discover_profiles()


@pytest.mark.parametrize(
    "edges",
    [
        [generated_edge(source_id=None) for _ in range(4)],
        [generated_edge(source_id="") for _ in range(4)],
        [generated_edge(side=None) for _ in range(4)],
        [generated_edge(side="center") for _ in range(4)],
        [generated_edge(notch="0") for _ in range(4)],
        [generated_edge(notch=None) for _ in range(4)],
    ],
    ids=[
        "missing-source",
        "empty-source",
        "missing-side",
        "invalid-side",
        "invalid-notch",
        "missing-notch",
    ],
)
def test_profile_discovery_rejects_malformed_generated_metadata(edges: list[object]) -> None:
    backend = prepared_cut_backend(profiles=[fake_profile(edges)])

    with pytest.raises(BendMarksError, match="invalid generated notch metadata"):
        backend.discover_profiles()


def test_profile_discovery_rejects_no_generated_profiles() -> None:
    backend = prepared_cut_backend(profiles=[fake_profile([untagged_edge() for _ in range(4)])])

    with pytest.raises(BendMarksError, match="The active sketch has no generated notch profiles"):
        backend.discover_profiles()


def test_find_existing_cut_filters_by_active_sketch_id() -> None:
    matching = FakeCut(attribute_value="sketch-a")
    other = FakeCut(attribute_value="sketch-b")
    invalid = FakeCut(attribute_value="sketch-a", valid=False)
    wrong_type = FakeCut(attribute_value="sketch-a")
    wrong_type.objectType = "adsk::fusion::Sketch"
    backend = prepared_cut_backend(cuts=[matching, other, invalid, wrong_type])

    assert backend.find_existing_cut() is matching


def test_find_existing_cut_rejects_duplicate_matching_cuts() -> None:
    backend = prepared_cut_backend(
        cuts=[FakeCut(attribute_value="sketch-a"), FakeCut(attribute_value="sketch-a")]
    )

    with pytest.raises(BendMarksError, match="multiple interactive cuts"):
        backend.find_existing_cut()


def test_build_cuts_discovered_profiles_through_all(monkeypatch: pytest.MonkeyPatch) -> None:
    backend, extrudes = prepared_cut_backend_with_extrudes(monkeypatch, profile_count=2)

    assert backend.build() == CutNotchesResult(2)
    assert extrudes.create_arguments is not None
    collection, operation = extrudes.create_arguments
    assert cast(FakeObjectCollection, collection).items == list(backend.discover_profiles())
    assert operation == adsk.fusion.FeatureOperations.CutFeatureOperation
    assert extrudes.input.one_side_extents == [
        ("through-all", adsk.fusion.ExtentDirections.NegativeExtentDirection)
    ]
    assert extrudes.cut is not None
    assert extrudes.cut.name == "Selected Notches Cut"
    assert attribute_value(extrudes.cut, INTERACTIVE_CUT_ATTRIBUTE) == backend.sketch_id


def test_build_rejects_profile_collection_add_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    backend, _ = prepared_cut_backend_with_extrudes(monkeypatch, collection_add_result=False)

    with pytest.raises(BendMarksError, match="Could not collect generated notch profile"):
        backend.build()


def test_build_rejects_null_extrude_input(monkeypatch: pytest.MonkeyPatch) -> None:
    backend, _ = prepared_cut_backend_with_extrudes(monkeypatch, input_result=None)

    with pytest.raises(BendMarksError, match="Could not create interactive cut input"):
        backend.build()


def test_build_rejects_through_all_extent_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    backend, _ = prepared_cut_backend_with_extrudes(monkeypatch, extent_result=False)

    with pytest.raises(BendMarksError, match="Could not set interactive cut to through-all"):
        backend.build()


def test_build_rejects_null_cut(monkeypatch: pytest.MonkeyPatch) -> None:
    backend, extrudes = prepared_cut_backend_with_extrudes(monkeypatch)
    extrudes.cut = None

    with pytest.raises(BendMarksError, match="Could not create interactive cut"):
        backend.build()


def test_build_tag_failure_deletes_partial_cut(monkeypatch: pytest.MonkeyPatch) -> None:
    cut = FakeCut(attribute_result=False)
    backend, _ = prepared_cut_backend_with_extrudes(monkeypatch, cut=cut)

    with pytest.raises(BendMarksError, match=f"Could not set {INTERACTIVE_CUT_ATTRIBUTE}"):
        backend.build()

    assert cut.deleted


def test_interactive_cut_suppression_assignment_is_verified() -> None:
    backend = prepared_cut_backend()
    cut = FakeCut()
    backend.set_cut_suppressed(cut, True)
    assert cut.isSuppressed

    class IgnoredSuppression:
        @property
        def isSuppressed(self) -> bool:
            return False

        @isSuppressed.setter
        def isSuppressed(self, _value: bool) -> None:
            pass

    with pytest.raises(BendMarksError, match="Could not suppress interactive cut"):
        backend.set_cut_suppressed(IgnoredSuppression(), True)


@pytest.mark.parametrize(
    "failure",
    [False, RuntimeError("delete exploded")],
    ids=["false", "exception"],
)
def test_delete_interactive_cut_propagates_failures(failure: bool | Exception) -> None:
    backend = prepared_cut_backend()

    with pytest.raises(BendMarksError, match="Could not delete existing interactive cut"):
        backend.delete_cut(FakeCut(delete_result=failure))


def attribute_value(entity: object, name: str) -> str | None:
    attribute = cast(Any, entity).attributes.itemByName(ATTRIBUTE_GROUP, name)
    return None if attribute is None else attribute.value


def prepared_backend(
    monkeypatch: pytest.MonkeyPatch,
    lines: tuple[FakeLine, ...],
) -> tuple[InteractiveNotchBackend, list[FakeLine]]:
    sketch = lines[0].parentSketch
    root_component = object()
    sketch.parentComponent = root_component
    application = flat_pattern_application(
        parameters={
            "bend_mark_width": FakeParameter("2 mm", 0.2),
            "bend_mark_inset": FakeParameter("0.8 mm", 0.08),
            "bend_mark_overhang": FakeParameter("1.2 mm", 0.12),
        },
        root_component=root_component,
    )
    generated: list[FakeLine] = []

    def add_rectangle(*_arguments: object, **_keywords: object) -> tuple[FakeLine, ...]:
        created = tuple(FakeLine(parent_sketch=sketch) for _ in range(6))
        sketch.sketchCurves.sketchLines.items.extend(created)
        generated.extend(created)
        return created

    monkeypatch.setattr("BendMarks.interactive_adapter.add_constrained_rectangle", add_rectangle)
    backend = InteractiveNotchBackend(application, lines)
    backend.prepare()
    return backend, generated


def test_prepare_requires_at_least_one_selected_line() -> None:
    backend = InteractiveNotchBackend(flat_pattern_application(), ())

    with pytest.raises(BendMarksError, match="Select one or more sketch centerlines"):
        backend.prepare()


def test_prepare_rejects_non_line_selection() -> None:
    entity = SimpleNamespace(objectType="adsk::fusion::SketchCircle")

    with pytest.raises(BendMarksError, match="Select one or more sketch centerlines"):
        InteractiveNotchBackend(flat_pattern_application(), (entity,)).prepare()


def test_prepare_rejects_mixed_sketches() -> None:
    first = fake_line(parent_sketch=FakeSketch())
    second = fake_line(parent_sketch=FakeSketch())

    with pytest.raises(BendMarksError, match="same sketch"):
        InteractiveNotchBackend(flat_pattern_application(), (first, second)).prepare()


def test_prepare_rejects_sketch_outside_active_flat_pattern_root() -> None:
    line = fake_line(parent_sketch=FakeSketch(object()))

    with pytest.raises(BendMarksError, match="active flat pattern"):
        InteractiveNotchBackend(flat_pattern_application(), (line,)).prepare()


def test_parameter_expressions_reuse_existing_expressions() -> None:
    application = flat_pattern_application(
        parameters={
            "bend_mark_width": FakeParameter("2 mm", 0.2),
            "bend_mark_inset": FakeParameter("0.8 mm", 0.08),
            "bend_mark_overhang": FakeParameter("1.2 mm", 0.12),
        }
    )

    assert parameter_expressions(application) == ParameterExpressions("2 mm", "0.8 mm", "1.2 mm")


def test_parameter_expressions_use_defaults_for_missing_parameters() -> None:
    assert parameter_expressions(flat_pattern_application()) == ParameterExpressions(
        "1.8 mm", "1 mm", "1 mm"
    )


def test_parameter_expressions_reject_invalid_existing_parameter() -> None:
    application = flat_pattern_application(parameters={"bend_mark_width": FakeParameter("0 mm", 0)})

    with pytest.raises(BendMarksError, match="bend_mark_width must be a positive length"):
        parameter_expressions(application)


def test_update_parameters_creates_missing_from_entered_expressions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "BendMarks.interactive_adapter.adsk.core.ValueInput.createByString", lambda value: value
    )
    line = fake_line()
    root = object()
    line.parentSketch.parentComponent = root
    application = flat_pattern_application(root_component=root)
    backend = InteractiveNotchBackend(application, (line,))
    backend.prepare()

    backend.update_parameters(ParameterExpressions("2 mm", "0.8 mm", "1.2 mm"))

    assert cast(Any, application).activeProduct.userParameters.added == [
        ("bend_mark_width", "2 mm", "mm", "Bend mark width"),
        ("bend_mark_inset", "0.8 mm", "mm", "Bend mark depth toward bend"),
        ("bend_mark_overhang", "1.2 mm", "mm", "Bend mark extension beyond bend endpoint"),
    ]


def test_update_parameters_assigns_existing_expressions() -> None:
    parameters = {
        "bend_mark_width": FakeParameter("1 mm", 0.1),
        "bend_mark_inset": FakeParameter("1 mm", 0.1),
        "bend_mark_overhang": FakeParameter("1 mm", 0.1),
    }
    line = fake_line()
    root = object()
    line.parentSketch.parentComponent = root
    backend = InteractiveNotchBackend(
        flat_pattern_application(parameters=parameters, root_component=root), (line,)
    )
    backend.prepare()

    backend.update_parameters(ParameterExpressions("2 mm", "0.8 mm", "1.2 mm"))

    assert [parameter.expression for parameter in parameters.values()] == [
        "2 mm",
        "0.8 mm",
        "1.2 mm",
    ]


def test_build_converts_lines_and_tags_generated_geometry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    line = fake_line(Point2(0, 0), Point2(10, 0))
    backend, generated = prepared_backend(monkeypatch, (line,))

    result = backend.build(NotchSide.BOTH)

    assert result == CreateNotchesResult(1, 2)
    assert line.isConstruction
    assert attribute_value(line, SOURCE_ID_ATTRIBUTE)
    assert attribute_value(line.parentSketch, SKETCH_ID_ATTRIBUTE)
    assert [attribute_value(generated[index], GEOMETRY_SIDE_ATTRIBUTE) for index in (0, 6)] == [
        "left",
        "right",
    ]
    profile_edges = generated[:4] + generated[6:10]
    construction_helpers = generated[4:6] + generated[10:12]
    assert all(attribute_value(edge, NOTCH_EDGE_ATTRIBUTE) == "1" for edge in profile_edges)
    assert all(attribute_value(edge, NOTCH_EDGE_ATTRIBUTE) is None for edge in construction_helpers)
    assert all(attribute_value(edge, GEOMETRY_SOURCE_ATTRIBUTE) for edge in generated)


@pytest.mark.parametrize(
    ("side", "expected_side"),
    [(NotchSide.LEFT, "left"), (NotchSide.RIGHT, "right")],
)
def test_build_creates_only_selected_side(
    monkeypatch: pytest.MonkeyPatch, side: NotchSide, expected_side: str
) -> None:
    line = fake_line()
    backend, generated = prepared_backend(monkeypatch, (line,))

    assert backend.build(side) == CreateNotchesResult(1, 1)
    assert len(generated) == 6
    assert {attribute_value(item, GEOMETRY_SIDE_ATTRIBUTE) for item in generated} == {expected_side}


def test_build_rejects_duplicate_source_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    sketch = FakeSketch()
    first = fake_line(parent_sketch=sketch, source_id="duplicate")
    fake_line(parent_sketch=sketch, source_id="duplicate")
    backend, _ = prepared_backend(monkeypatch, (first,))

    with pytest.raises(BendMarksError, match="duplicate"):
        backend.build(NotchSide.BOTH)


def test_find_existing_geometry_returns_only_selected_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sketch = FakeSketch()
    selected = fake_line(source_id="selected", parent_sketch=sketch)
    other = fake_line(source_id="other", parent_sketch=sketch)
    selected_geometry = fake_line(
        generated_source="selected", generated_side="left", parent_sketch=sketch
    )
    other_geometry = fake_line(
        generated_source="other", generated_side="right", parent_sketch=sketch
    )
    backend, _ = prepared_backend(monkeypatch, (selected,))

    assert backend.find_existing_geometry() == (selected_geometry,)
    assert other in sketch.sketchCurves.sketchLines.items
    assert other_geometry in sketch.sketchCurves.sketchLines.items


def test_find_existing_geometry_rejects_malformed_side(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sketch = FakeSketch()
    selected = fake_line(source_id="selected", parent_sketch=sketch)
    fake_line(generated_source="selected", generated_side="center", parent_sketch=sketch)
    backend, _ = prepared_backend(monkeypatch, (selected,))

    with pytest.raises(BendMarksError, match="side"):
        backend.find_existing_geometry()


@pytest.mark.parametrize(
    "failure",
    [False, RuntimeError("delete exploded")],
    ids=["false", "exception"],
)
def test_delete_geometry_propagates_failures(
    monkeypatch: pytest.MonkeyPatch, failure: bool | Exception
) -> None:
    line = fake_line()
    backend, _ = prepared_backend(monkeypatch, (line,))
    generated = fake_line(delete_result=failure)
    remaining = fake_line()

    with pytest.raises(BendMarksError, match="Could not delete selected notch geometry"):
        backend.delete_geometry((generated, remaining))

    assert remaining.deleted
