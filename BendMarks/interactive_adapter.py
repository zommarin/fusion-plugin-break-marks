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
from .service import BendMarksError, CreateNotchesResult, CutNotchesResult, ParameterExpressions

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


class InteractiveCutBackend:
    def __init__(self, application: object) -> None:
        self.application = application
        self.product: object | None = None
        self.sketch: object | None = None
        self.sketch_id = ""

    def prepare(self) -> None:
        product = cast(Any, self.application).activeProduct
        if getattr(product, "objectType", None) != "adsk::fusion::FlatPatternProduct":
            raise BendMarksError("Open a sheet-metal flat pattern before cutting selected notches")

        sketch = cast(Any, self.application).activeEditObject
        sketch_type = adsk.fusion.Sketch.classType() or "adsk::fusion::Sketch"
        if sketch is None or getattr(sketch, "objectType", None) != sketch_type:
            raise BendMarksError("Activate the sketch containing generated notches")
        if sketch.parentComponent is not product.rootComponent:
            raise BendMarksError("Active sketch must belong to the active flat pattern")

        sketch_id = _attribute_value(sketch, SKETCH_ID_ATTRIBUTE)
        if not sketch_id:
            raise BendMarksError("Active sketch has no valid generated notch sketch ID")

        self.product = product
        self.sketch = sketch
        self.sketch_id = sketch_id

    def discover_profiles(self) -> tuple[object, ...]:
        discovered: list[object] = []
        for profile in _collection_items(cast(Any, self.sketch).profiles):
            loops = _collection_items(cast(Any, profile).profileLoops)
            loop_curves = tuple(
                _collection_items(cast(Any, loop).profileCurves) for loop in loops
            )
            entities = [
                cast(Any, curve).sketchEntity
                for curves in loop_curves
                for curve in curves
            ]
            if len(loops) != 1:
                metadata_names = (
                    NOTCH_EDGE_ATTRIBUTE,
                    GEOMETRY_SOURCE_ATTRIBUTE,
                    GEOMETRY_SIDE_ATTRIBUTE,
                )
                if any(
                    _attribute_value(entity, name) is not None
                    for entity in entities
                    for name in metadata_names
                ):
                    raise BendMarksError(
                        "Generated notch profile must contain exactly one loop"
                    )
                continue
            curves = loop_curves[0]
            if len(curves) != 4:
                continue

            notch_tags = [_attribute_value(entity, NOTCH_EDGE_ATTRIBUTE) for entity in entities]
            source_ids = [
                _attribute_value(entity, GEOMETRY_SOURCE_ATTRIBUTE) for entity in entities
            ]
            sides = [_attribute_value(entity, GEOMETRY_SIDE_ATTRIBUTE) for entity in entities]
            if all(tag is None for tag in notch_tags):
                if any(value is not None for value in (*source_ids, *sides)):
                    raise BendMarksError("Profile has invalid generated notch metadata")
                continue
            if any(tag is None for tag in notch_tags):
                continue
            if any(tag != "1" for tag in notch_tags):
                raise BendMarksError("Profile has invalid generated notch metadata")

            if any(not source_id for source_id in source_ids) or any(
                side not in (NotchSide.LEFT.value, NotchSide.RIGHT.value) for side in sides
            ):
                raise BendMarksError("Profile has invalid generated notch metadata")
            if len(set(source_ids)) != 1 or len(set(sides)) != 1:
                continue
            discovered.append(profile)

        if not discovered:
            raise BendMarksError("The active sketch has no generated notch profiles")
        return tuple(discovered)

    def find_existing_cut(self) -> object | None:
        cut_type = adsk.fusion.ExtrudeFeature.classType() or "adsk::fusion::ExtrudeFeature"
        attributes = cast(Any, self.product).findAttributes(
            ATTRIBUTE_GROUP, INTERACTIVE_CUT_ATTRIBUTE
        )
        matches: list[object] = []
        for attribute in _collection_items(attributes):
            dynamic_attribute = cast(Any, attribute)
            parent = dynamic_attribute.parent
            if (
                dynamic_attribute.value == self.sketch_id
                and getattr(parent, "isValid", False)
                and getattr(parent, "objectType", None) == cut_type
            ):
                matches.append(parent)
        if len(matches) > 1:
            raise BendMarksError("Found multiple interactive cuts for the active sketch")
        return matches[0] if matches else None

    def build(self) -> CutNotchesResult:
        discovered = self.discover_profiles()
        profiles = cast(Any, adsk.core.ObjectCollection.create())
        if profiles is None:
            raise BendMarksError("Could not create generated notch profile collection")
        for profile in discovered:
            if not profiles.add(profile):
                raise BendMarksError("Could not collect generated notch profile")

        extrudes = cast(Any, self.product).rootComponent.features.extrudeFeatures
        extrude_input = extrudes.createInput(
            profiles, adsk.fusion.FeatureOperations.CutFeatureOperation
        )
        if extrude_input is None:
            raise BendMarksError("Could not create interactive cut input")
        through_all = adsk.fusion.ThroughAllExtentDefinition.create()
        if through_all is None or not extrude_input.setOneSideExtent(
            through_all, adsk.fusion.ExtentDirections.NegativeExtentDirection
        ):
            raise BendMarksError("Could not set interactive cut to through-all")

        cut: Any = None
        try:
            cut = extrudes.add(extrude_input)
            if cut is None:
                raise BendMarksError("Could not create interactive cut")
            cut.name = "Selected Notches Cut"
            _set_attribute(cut, INTERACTIVE_CUT_ATTRIBUTE, self.sketch_id)
        except Exception as error:
            if cut is not None:
                try:
                    if not cut.deleteMe():
                        error.add_note(
                            "Partial interactive cut cleanup failed: delete returned false"
                        )
                except Exception as cleanup_error:
                    error.add_note(f"Partial interactive cut cleanup failed: {cleanup_error}")
            raise
        return CutNotchesResult(len(discovered))

    def set_cut_suppressed(self, cut: object, suppressed: bool) -> None:
        dynamic_cut = cast(Any, cut)
        dynamic_cut.isSuppressed = suppressed
        if dynamic_cut.isSuppressed != suppressed:
            action = "suppress" if suppressed else "restore"
            raise BendMarksError(f"Could not {action} interactive cut")

    def delete_cut(self, cut: object) -> None:
        try:
            if not cast(Any, cut).deleteMe():
                raise BendMarksError("Could not delete existing interactive cut")
        except BendMarksError:
            raise
        except Exception as error:
            raise BendMarksError("Could not delete existing interactive cut") from error
