import uuid
from typing import Any, cast

import adsk.core
import adsk.fusion

from .fusion_adapter import (
    ATTRIBUTE_GROUP,
    PARAMETERS,
    _collection_items,
    add_constrained_rectangle,
    validate_parameter,
)
from .geometry import NotchSide, Point2, selected_endpoint_rectangles
from .service import BendMarksError, CreateNotchesResult, ParameterExpressions

SOURCE_ID_ATTRIBUTE = "interactive-source-id"
SKETCH_ID_ATTRIBUTE = "interactive-sketch-id"
GEOMETRY_SOURCE_ATTRIBUTE = "interactive-geometry-source"
GEOMETRY_SIDE_ATTRIBUTE = "interactive-geometry-side"
NOTCH_EDGE_ATTRIBUTE = "interactive-notch-edge"
INTERACTIVE_CUT_ATTRIBUTE = "interactive-cut-sketch"


def _attribute_value(entity: object, name: str) -> str | None:
    attribute = cast(Any, entity).attributes.itemByName(ATTRIBUTE_GROUP, name)
    if attribute is None:
        return None
    return cast(str, attribute.value)


def _set_attribute(entity: object, name: str, value: str) -> None:
    if not cast(Any, entity).attributes.add(ATTRIBUTE_GROUP, name, value):
        raise BendMarksError(f"Could not set {name}")


def parameter_expressions(application: object) -> ParameterExpressions:
    user_parameters = cast(Any, application).activeProduct.userParameters
    expressions: list[str] = []
    for name, default_expression, _ in PARAMETERS:
        parameter = user_parameters.itemByName(name)
        if parameter is None:
            expressions.append(default_expression)
        else:
            validate_parameter(name, parameter)
            expressions.append(cast(str, parameter.expression))
    return ParameterExpressions(*expressions)


class InteractiveNotchBackend:
    def __init__(self, application: object, selected_entities: tuple[object, ...]) -> None:
        self.application = application
        self.selected_entities = selected_entities
        self.product: object | None = None
        self.sketch: object | None = None
        self.lines: tuple[object, ...] = ()

    def prepare(self) -> None:
        product = cast(Any, self.application).activeProduct
        if getattr(product, "objectType", None) != "adsk::fusion::FlatPatternProduct":
            raise BendMarksError("Open a sheet-metal flat pattern before creating bend marks")
        if not self.selected_entities:
            raise BendMarksError("Select one or more sketch centerlines")

        line_type = adsk.fusion.SketchLine.classType() or "adsk::fusion::SketchLine"
        if any(
            getattr(entity, "objectType", None) != line_type for entity in self.selected_entities
        ):
            raise BendMarksError("Select one or more sketch centerlines")

        sketch = cast(Any, self.selected_entities[0]).parentSketch
        if any(
            cast(Any, entity).parentSketch is not sketch for entity in self.selected_entities[1:]
        ):
            raise BendMarksError("Selected centerlines must belong to the same sketch")
        if sketch.parentComponent is not product.rootComponent:
            raise BendMarksError("Selected sketch must belong to the active flat pattern")

        self.product = product
        self.sketch = sketch
        self.lines = self.selected_entities

    def update_parameters(self, expressions: ParameterExpressions) -> None:
        user_parameters = cast(Any, self.product).userParameters
        entered = (expressions.width, expressions.inset, expressions.overhang)
        for (name, _, comment), expression in zip(PARAMETERS, entered, strict=True):
            parameter = user_parameters.itemByName(name)
            if parameter is None:
                value = adsk.core.ValueInput.createByString(expression)
                parameter = user_parameters.add(name, value, "mm", comment)
                if parameter is None:
                    raise BendMarksError(f"Could not create {name}")
            else:
                parameter.expression = expression
            validate_parameter(name, parameter)

    def _ensure_ownership(self) -> tuple[str, ...]:
        sketch = cast(Any, self.sketch)
        source_ids = [
            value
            for line in _collection_items(sketch.sketchCurves.sketchLines)
            if (value := _attribute_value(line, SOURCE_ID_ATTRIBUTE))
        ]
        if len(source_ids) != len(set(source_ids)):
            raise BendMarksError("Found duplicate interactive source IDs")

        if not _attribute_value(sketch, SKETCH_ID_ATTRIBUTE):
            _set_attribute(sketch, SKETCH_ID_ATTRIBUTE, uuid.uuid4().hex)

        selected_ids: list[str] = []
        for line in self.lines:
            source_id = _attribute_value(line, SOURCE_ID_ATTRIBUTE)
            if not source_id:
                source_id = uuid.uuid4().hex
                _set_attribute(line, SOURCE_ID_ATTRIBUTE, source_id)
            selected_ids.append(source_id)
        return tuple(selected_ids)

    def find_existing_geometry(self) -> tuple[object, ...]:
        selected_ids = set(self._ensure_ownership())
        existing: list[object] = []
        sketch_lines = cast(Any, self.sketch).sketchCurves.sketchLines
        for line in _collection_items(sketch_lines):
            source_id = _attribute_value(line, GEOMETRY_SOURCE_ATTRIBUTE)
            if source_id not in selected_ids:
                continue
            side = _attribute_value(line, GEOMETRY_SIDE_ATTRIBUTE)
            if side not in (NotchSide.LEFT.value, NotchSide.RIGHT.value):
                raise BendMarksError("Interactive notch geometry has an invalid side")
            existing.append(line)
        return tuple(existing)

    def delete_geometry(self, geometry: tuple[object, ...]) -> None:
        failed = False
        first_error: Exception | None = None
        for line in geometry:
            try:
                if not cast(Any, line).deleteMe():
                    failed = True
            except Exception as error:
                failed = True
                if first_error is None:
                    first_error = error
        if failed:
            raise BendMarksError("Could not delete selected notch geometry") from first_error

    def _parameter_values(self) -> dict[str, float]:
        user_parameters = cast(Any, self.product).userParameters
        return {
            name: validate_parameter(name, user_parameters.itemByName(name))
            for name, _, _ in PARAMETERS
        }

    def build(self, side: NotchSide) -> CreateNotchesResult:
        source_ids = self._ensure_ownership()
        values = self._parameter_values()
        created_rectangle_count = 0
        for index, (line, source_id) in enumerate(
            zip(self.lines, source_ids, strict=True), start=1
        ):
            dynamic_line = cast(Any, line)
            dynamic_line.isConstruction = True
            if not dynamic_line.isConstruction:
                raise BendMarksError(f"Centerline {index}: could not convert line to construction")

            start = dynamic_line.startSketchPoint.geometry
            end = dynamic_line.endSketchPoint.geometry
            try:
                rectangles = selected_endpoint_rectangles(
                    Point2(start.x, start.y),
                    Point2(end.x, end.y),
                    values["bend_mark_width"],
                    values["bend_mark_inset"],
                    values["bend_mark_overhang"],
                    side,
                )
            except Exception as error:
                raise BendMarksError(
                    f"Centerline {index}: could not calculate endpoint rectangles"
                ) from error

            for endpoint_rectangle in rectangles:
                endpoint = (
                    dynamic_line.startSketchPoint
                    if endpoint_rectangle.side is NotchSide.LEFT
                    and (start.x, start.y) <= (end.x, end.y)
                    or endpoint_rectangle.side is NotchSide.RIGHT
                    and (start.x, start.y) > (end.x, end.y)
                    else dynamic_line.endSketchPoint
                )
                generated = add_constrained_rectangle(
                    cast(Any, self.sketch),
                    dynamic_line,
                    endpoint,
                    endpoint_rectangle.rectangle,
                    f"Centerline {index}",
                )
                for generated_line in generated:
                    _set_attribute(generated_line, GEOMETRY_SOURCE_ATTRIBUTE, source_id)
                    _set_attribute(
                        generated_line, GEOMETRY_SIDE_ATTRIBUTE, endpoint_rectangle.side.value
                    )
                for profile_edge in generated[:4]:
                    _set_attribute(profile_edge, NOTCH_EDGE_ATTRIBUTE, "1")
                created_rectangle_count += 1

        return CreateNotchesResult(len(self.lines), created_rectangle_count)
