from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, cast

import pytest

from BendMarks.geometry import NotchSide, Point2
from BendMarks.interactive_adapter import (
    ATTRIBUTE_GROUP,
    GEOMETRY_SIDE_ATTRIBUTE,
    GEOMETRY_SOURCE_ATTRIBUTE,
    NOTCH_EDGE_ATTRIBUTE,
    SKETCH_ID_ATTRIBUTE,
    SOURCE_ID_ATTRIBUTE,
    InteractiveNotchBackend,
    parameter_expressions,
)
from BendMarks.service import BendMarksError, CreateNotchesResult, ParameterExpressions

DEFAULT_START = Point2(0, 0)
DEFAULT_END = Point2(10, 0)


class FakeAttributes:
    def __init__(self, values: dict[str, str] | None = None) -> None:
        self.values = values or {}

    def itemByName(self, group: str, name: str) -> object | None:
        if group != ATTRIBUTE_GROUP or name not in self.values:
            return None
        return SimpleNamespace(value=self.values[name])

    def add(self, group: str, name: str, value: str) -> object:
        assert group == ATTRIBUTE_GROUP
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
    def __init__(self, parent_component: object | None = None) -> None:
        self.parentComponent = parent_component
        self.attributes = FakeAttributes()
        self.sketchCurves = SimpleNamespace(sketchLines=FakeCollection())


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
) -> object:
    product = SimpleNamespace(
        objectType="adsk::fusion::FlatPatternProduct",
        rootComponent=root_component or object(),
        userParameters=FakeUserParameters(parameters or {}),
    )
    return SimpleNamespace(activeProduct=product)


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
