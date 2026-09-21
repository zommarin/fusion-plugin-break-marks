from collections.abc import Sequence
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, cast

import pytest

from BendMarks.fusion_adapter import FusionBackend, classify_bend_geometry, validate_parameter
from BendMarks.service import BendMarksError, BuildResult, ExistingMarks


class FakeLine3D:
    objectType = "adsk::core::Line3D"


class FakeArc3D:
    objectType = "adsk::core::Arc3D"


@dataclass
class FakeParameter:
    value: float
    unit: str = "mm"


class FakeCollection:
    def __init__(self, items: Sequence[object]) -> None:
        self.items = items

    @property
    def count(self) -> int:
        return len(self.items)

    def item(self, index: int) -> object:
        return self.items[index]


@dataclass
class FakeEdge:
    geometry: object


@dataclass
class FakeCreatedParameter(FakeParameter):
    name: str = ""
    deleted: bool = False

    def deleteMe(self) -> bool:
        self.deleted = True
        return True


@dataclass
class FakeUserParameters:
    existing: dict[str, FakeParameter] = field(default_factory=dict)
    added: list[tuple[str, object, str, str]] = field(default_factory=list)
    created: list[FakeCreatedParameter] = field(default_factory=list)
    fail_on_add: int | None = None
    null_on_add: int | None = None

    def itemByName(self, name: str) -> FakeParameter | None:
        return self.existing.get(name)

    def add(self, name: str, value: object, unit: str, comment: str) -> FakeCreatedParameter | None:
        if self.fail_on_add == len(self.added):
            raise RuntimeError("parameter add failed")
        self.added.append((name, value, unit, comment))
        if self.null_on_add == len(self.added) - 1:
            return None
        parameter = FakeCreatedParameter(1, unit, name)
        self.created.append(parameter)
        return parameter


@dataclass
class FakeAttribute:
    parent: object


@dataclass
class FakeProduct:
    edges: list[object]
    userParameters: FakeUserParameters = field(default_factory=FakeUserParameters)
    attributes: dict[str, list[FakeAttribute]] = field(default_factory=dict)
    objectType: str = "adsk::fusion::FlatPatternProduct"

    def __post_init__(self) -> None:
        self.flatPattern = SimpleNamespace(
            bendLinesBody=SimpleNamespace(edges=FakeCollection(self.edges)),
            topFace=object(),
        )
        self.rootComponent = object()

    def findAttributes(self, _group: str, name: str) -> FakeCollection:
        return FakeCollection(self.attributes.get(name, []))


def make_backend(product: object) -> FusionBackend:
    return FusionBackend(cast(Any, SimpleNamespace(activeProduct=product)))


def test_only_line3d_geometry_is_supported() -> None:
    assert classify_bend_geometry(FakeLine3D())
    assert not classify_bend_geometry(FakeArc3D())


@pytest.mark.parametrize("value", [0, -0.1])
def test_parameter_must_be_positive(value: float) -> None:
    with pytest.raises(BendMarksError, match="bend_mark_width must be a positive length"):
        validate_parameter("bend_mark_width", FakeParameter(value))


def test_parameter_returns_internal_centimeter_value() -> None:
    assert validate_parameter("bend_mark_width", FakeParameter(0.18)) == 0.18


def test_non_length_parameter_is_rejected() -> None:
    with pytest.raises(BendMarksError, match="bend_mark_width must be a positive length"):
        validate_parameter("bend_mark_width", FakeParameter(1, "deg"))


def test_prepare_rejects_non_flat_pattern_product() -> None:
    backend = make_backend(SimpleNamespace(objectType="adsk::fusion::Design"))

    with pytest.raises(
        BendMarksError, match="Open a sheet-metal flat pattern before creating bend marks"
    ):
        backend.prepare()


def test_empty_bend_body_is_rejected() -> None:
    backend = make_backend(FakeProduct([]))

    with pytest.raises(BendMarksError, match="The active flat pattern has no bend lines"):
        backend.prepare()


def test_all_curved_bend_body_is_rejected() -> None:
    backend = make_backend(FakeProduct([FakeEdge(FakeArc3D())]))

    with pytest.raises(
        BendMarksError, match="The active flat pattern has no supported straight bend lines"
    ):
        backend.prepare()


def test_mixed_bend_body_retains_lines_and_counts_curves() -> None:
    line = FakeEdge(FakeLine3D())
    backend = make_backend(FakeProduct([line, FakeEdge(FakeArc3D())]))

    backend.prepare()

    assert backend.straight_edges == (line,)
    assert backend.skipped_bend_count == 1


def test_existing_positive_parameters_are_not_recreated() -> None:
    parameters = FakeUserParameters(
        existing={
            "bend_mark_width": FakeParameter(0.18),
            "bend_mark_inset": FakeParameter(0.1),
            "bend_mark_overhang": FakeParameter(0.1),
        }
    )
    backend = make_backend(FakeProduct([FakeEdge(FakeLine3D())], userParameters=parameters))
    backend.prepare()

    assert backend.ensure_parameters() == ()
    assert parameters.added == []


def test_missing_parameters_use_exact_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "BendMarks.fusion_adapter.adsk.core.ValueInput.createByString",
        lambda expression: f"value:{expression}",
    )
    parameters = FakeUserParameters()
    backend = make_backend(FakeProduct([FakeEdge(FakeLine3D())], userParameters=parameters))
    backend.prepare()

    created = backend.ensure_parameters()

    assert [item[:4] for item in parameters.added] == [
        ("bend_mark_width", "value:1.8 mm", "mm", "Bend mark width"),
        ("bend_mark_inset", "value:1 mm", "mm", "Bend mark depth toward bend"),
        (
            "bend_mark_overhang",
            "value:1 mm",
            "mm",
            "Bend mark extension beyond bend endpoint",
        ),
    ]
    assert created == tuple(
        FakeCreatedParameter(1, "mm", name)
        for name in ("bend_mark_width", "bend_mark_inset", "bend_mark_overhang")
    )


def test_parameter_creation_failure_deletes_new_parameters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "BendMarks.fusion_adapter.adsk.core.ValueInput.createByString",
        lambda expression: expression,
    )
    parameters = FakeUserParameters(fail_on_add=1)
    backend = make_backend(FakeProduct([FakeEdge(FakeLine3D())], userParameters=parameters))
    backend.prepare()

    with pytest.raises(RuntimeError, match="parameter add failed"):
        backend.ensure_parameters()

    assert parameters.created[0].deleted


def test_null_parameter_creation_deletes_prior_parameters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "BendMarks.fusion_adapter.adsk.core.ValueInput.createByString",
        lambda expression: expression,
    )
    parameters = FakeUserParameters(null_on_add=1)
    backend = make_backend(FakeProduct([FakeEdge(FakeLine3D())], userParameters=parameters))
    backend.prepare()

    with pytest.raises(BendMarksError, match="Could not create bend_mark_inset"):
        backend.ensure_parameters()

    assert parameters.created[0].deleted


def test_duplicate_owned_sketches_are_rejected() -> None:
    first = SimpleNamespace(isValid=True)
    second = SimpleNamespace(isValid=True)
    product = FakeProduct(
        [FakeEdge(FakeLine3D())],
        attributes={
            "generated-sketch": [FakeAttribute(first), FakeAttribute(second)],
        },
    )
    backend = make_backend(product)
    backend.prepare()

    with pytest.raises(BendMarksError, match="multiple owned bend mark sketches"):
        backend.find_existing_marks()


@dataclass
class FakeSketchPoint:
    geometry: object


@dataclass
class FakeSketchLine:
    startSketchPoint: FakeSketchPoint
    endSketchPoint: FakeSketchPoint
    objectType: str = "adsk::fusion::SketchLine"
    isConstruction: bool = False


class FakeSketchLines:
    def __init__(self) -> None:
        self.created: list[FakeSketchLine] = []

    def addByTwoPoints(self, start: object, end: object) -> FakeSketchLine:
        start_point = start if isinstance(start, FakeSketchPoint) else FakeSketchPoint(start)
        end_point = end if isinstance(end, FakeSketchPoint) else FakeSketchPoint(end)
        line = FakeSketchLine(start_point, end_point)
        self.created.append(line)
        return line


class FakeConstraints:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object, object]] = []

    def _add(self, operation: str, first: object, second: object) -> object:
        self.calls.append((operation, first, second))
        return object()

    def addParallel(self, first: object, second: object) -> object:
        return self._add("parallel", first, second)

    def addPerpendicular(self, first: object, second: object) -> object:
        return self._add("perpendicular", first, second)

    def addMidPoint(self, first: object, second: object) -> object:
        return self._add("midpoint", first, second)

    def addCollinear(self, first: object, second: object) -> object:
        return self._add("collinear", first, second)


@dataclass
class FakeDimensionParameter:
    expression: str = ""


@dataclass
class FakeDimension:
    parameter: FakeDimensionParameter = field(default_factory=FakeDimensionParameter)


class FakeDimensions:
    def __init__(self) -> None:
        self.created: list[FakeDimension] = []

    def addDistanceDimension(self, *arguments: object) -> FakeDimension:
        assert len(arguments) == 5
        assert arguments[-1] is True
        dimension = FakeDimension()
        self.created.append(dimension)
        return dimension


class FakeAttributes:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.added: list[tuple[str, str, str]] = []

    def add(self, group: str, name: str, value: str) -> object:
        if self.fail:
            raise RuntimeError("attribute failed")
        self.added.append((group, name, value))
        return object()


class FakeSketch:
    def __init__(self, log: list[str], projected_items: Sequence[object] | None = None) -> None:
        self.log = log
        self.name = ""
        self.attributes = FakeAttributes()
        self.projected_items = (
            projected_items
            if projected_items is not None
            else [
                FakeSketchLine(
                    FakeSketchPoint(SimpleNamespace(x=0.0, y=0.0)),
                    FakeSketchPoint(SimpleNamespace(x=10.0, y=0.0)),
                )
            ]
        )
        self.sketchCurves = SimpleNamespace(sketchLines=FakeSketchLines())
        self.geometricConstraints = FakeConstraints()
        self.sketchDimensions = FakeDimensions()
        self.profiles = FakeCollection([object(), object()])
        self.deleted = False

    def project(self, _edge: object) -> FakeCollection:
        return FakeCollection(self.projected_items)

    def deleteMe(self) -> bool:
        self.deleted = True
        self.log.append("delete sketch")
        return True


class FakeSketches:
    def __init__(self, sketch: FakeSketch) -> None:
        self.sketch = sketch
        self.faces: list[object] = []

    def add(self, face: object) -> FakeSketch:
        self.faces.append(face)
        return self.sketch


class FakeObjectCollection:
    def __init__(self) -> None:
        self.items: list[object] = []

    def add(self, item: object) -> bool:
        self.items.append(item)
        return True


class FakeExtrudeInput:
    def __init__(self, all_extent_result: bool = True) -> None:
        self.all_extent_result = all_extent_result
        self.extent_directions: list[object] = []

    def setAllExtent(self, direction: object) -> bool:
        self.extent_directions.append(direction)
        return self.all_extent_result


class FakeCut:
    def __init__(self, log: list[str], fail_attribute: bool = False) -> None:
        self.log = log
        self.name = ""
        self.attributes = FakeAttributes(fail_attribute)
        self.deleted = False
        self.isSuppressed = False

    def deleteMe(self) -> bool:
        self.deleted = True
        self.log.append("delete cut")
        return True


class FakeExtrudes:
    def __init__(
        self,
        log: list[str],
        *,
        all_extent_result: bool = True,
        fail_cut_attribute: bool = False,
    ) -> None:
        self.input = FakeExtrudeInput(all_extent_result)
        self.cut = FakeCut(log, fail_cut_attribute)
        self.create_arguments: tuple[object, object] | None = None

    def createInput(self, profiles: object, operation: object) -> FakeExtrudeInput:
        self.create_arguments = (profiles, operation)
        return self.input

    def add(self, _extrude_input: object) -> FakeCut:
        return self.cut


def build_ready_backend(
    monkeypatch: pytest.MonkeyPatch,
    *,
    projected_items: Sequence[object] | None = None,
    all_extent_result: bool = True,
    fail_cut_attribute: bool = False,
) -> tuple[FusionBackend, FakeSketch, FakeExtrudes, list[str]]:
    monkeypatch.setattr(
        "BendMarks.fusion_adapter.adsk.core.Point3D.create",
        lambda x, y, z: SimpleNamespace(x=x, y=y, z=z),
    )
    monkeypatch.setattr(
        "BendMarks.fusion_adapter.adsk.core.ObjectCollection.create", FakeObjectCollection
    )
    log: list[str] = []
    sketch = FakeSketch(log, projected_items)
    extrudes = FakeExtrudes(
        log,
        all_extent_result=all_extent_result,
        fail_cut_attribute=fail_cut_attribute,
    )
    parameters = FakeUserParameters(
        existing={
            "bend_mark_width": FakeParameter(0.18),
            "bend_mark_inset": FakeParameter(0.1),
            "bend_mark_overhang": FakeParameter(0.1),
        }
    )
    product = FakeProduct([FakeEdge(FakeLine3D()), FakeEdge(FakeArc3D())], parameters)
    product.rootComponent = SimpleNamespace(
        sketches=FakeSketches(sketch),
        features=SimpleNamespace(extrudeFeatures=extrudes),
    )
    backend = make_backend(product)
    backend.prepare()
    return backend, sketch, extrudes, log


def test_build_creates_constrained_rectangles_and_committed_cut(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend, sketch, extrudes, _ = build_ready_backend(monkeypatch)

    artifacts = backend.build()

    assert artifacts.result == BuildResult(1, 2, 1)
    assert artifacts.sketch is sketch
    assert artifacts.cut is extrudes.cut
    assert sketch.name == "Bend Marks"
    assert sketch.attributes.added == [("fusion-plugin-bend-marks", "generated-sketch", "1")]
    assert isinstance(sketch.projected_items[0], FakeSketchLine)
    assert sketch.projected_items[0].isConstruction
    assert len(sketch.sketchCurves.sketchLines.created) == 12
    assert [call[0] for call in sketch.geometricConstraints.calls] == [
        "parallel",
        "parallel",
        "perpendicular",
        "perpendicular",
        "midpoint",
        "collinear",
        "midpoint",
        "collinear",
    ] * 2
    assert [dimension.parameter.expression for dimension in sketch.sketchDimensions.created] == [
        "bend_mark_overhang",
        "bend_mark_inset",
        "bend_mark_width",
    ] * 2
    assert extrudes.cut.name == "Bend Marks Cut"
    assert extrudes.cut.attributes.added == [("fusion-plugin-bend-marks", "generated-cut", "1")]
    assert extrudes.create_arguments is not None
    assert isinstance(extrudes.create_arguments[0], FakeObjectCollection)
    assert len(extrudes.create_arguments[0].items) == 2


def test_projection_failure_deletes_partial_sketch(monkeypatch: pytest.MonkeyPatch) -> None:
    backend, sketch, _, log = build_ready_backend(monkeypatch, projected_items=[])

    with pytest.raises(BendMarksError, match="Bend 1: could not project centerline"):
        backend.build()

    assert sketch.deleted
    assert log == ["delete sketch"]


def test_through_all_failure_deletes_sketch(monkeypatch: pytest.MonkeyPatch) -> None:
    backend, sketch, extrudes, log = build_ready_backend(monkeypatch, all_extent_result=False)

    with pytest.raises(BendMarksError, match="Could not set bend mark cut to through-all"):
        backend.build()

    assert not extrudes.cut.deleted
    assert sketch.deleted
    assert log == ["delete sketch"]


def test_cut_tag_failure_deletes_cut_before_sketch(monkeypatch: pytest.MonkeyPatch) -> None:
    backend, sketch, extrudes, log = build_ready_backend(monkeypatch, fail_cut_attribute=True)

    with pytest.raises(RuntimeError, match="attribute failed"):
        backend.build()

    assert extrudes.cut.deleted
    assert sketch.deleted
    assert log == ["delete cut", "delete sketch"]


def test_suppression_assignment_is_verified() -> None:
    backend = make_backend(object())
    cut = FakeCut([])
    backend.set_cut_suppressed(cut, True)
    assert cut.isSuppressed

    class IgnoredSuppression:
        @property
        def isSuppressed(self) -> bool:
            return False

        @isSuppressed.setter
        def isSuppressed(self, _value: bool) -> None:
            pass

    with pytest.raises(BendMarksError, match="Could not suppress bend mark cut"):
        backend.set_cut_suppressed(IgnoredSuppression(), True)


def test_existing_marks_delete_cut_before_sketch() -> None:
    log: list[str] = []
    backend = make_backend(object())
    backend.delete_existing_marks(ExistingMarks(sketch=FakeSketch(log), cut=FakeCut(log)))
    assert log == ["delete cut", "delete sketch"]


def test_parameters_are_deleted_in_reverse_order() -> None:
    log: list[str] = []

    class Parameter:
        def __init__(self, name: str) -> None:
            self.name = name

        def deleteMe(self) -> bool:
            log.append(self.name)
            return True

    backend = make_backend(object())
    backend.delete_parameters((Parameter("first"), Parameter("second")))
    assert log == ["second", "first"]


def test_parameter_delete_failure_still_attempts_all_parameters() -> None:
    log: list[str] = []

    class Parameter:
        def __init__(self, name: str, result: bool) -> None:
            self.name = name
            self.result = result

        def deleteMe(self) -> bool:
            log.append(self.name)
            return self.result

    backend = make_backend(object())
    parameters = (Parameter("first", True), Parameter("second", False))

    with pytest.raises(BendMarksError, match="Could not delete bend mark parameter"):
        backend.delete_parameters(parameters)

    assert log == ["second", "first"]
