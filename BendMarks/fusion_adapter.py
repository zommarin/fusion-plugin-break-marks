from collections.abc import Callable
from math import isfinite
from typing import Any, cast

import adsk.core
import adsk.fusion

from BendMarks.geometry import Point2, Rectangle, endpoint_rectangles
from BendMarks.service import BendMarksError, BuildArtifacts, BuildResult, ExistingMarks

ATTRIBUTE_GROUP = "fusion-plugin-bend-marks"
SKETCH_ATTRIBUTE = "generated-sketch"
CUT_ATTRIBUTE = "generated-cut"
PARAMETERS = (
    ("bend_mark_width", "1.8 mm", "Bend mark width"),
    ("bend_mark_inset", "1 mm", "Bend mark depth toward bend"),
    ("bend_mark_overhang", "1 mm", "Bend mark extension beyond bend endpoint"),
)

_LENGTH_UNITS = {"mm", "cm", "m", "in", "ft", "yd", "mil", "micron"}


def classify_bend_geometry(geometry: object) -> bool:
    line_type = adsk.core.Line3D.classType() or "adsk::core::Line3D"
    return cast(Any, geometry).objectType == line_type


def validate_parameter(name: str, parameter: object) -> float:
    dynamic_parameter = cast(Any, parameter)
    value = float(dynamic_parameter.value)
    unit = getattr(dynamic_parameter, "unit", None)
    if unit is None:
        unit = getattr(dynamic_parameter, "unitType", None)
    if not isfinite(value) or value <= 0 or (unit is not None and unit not in _LENGTH_UNITS):
        raise BendMarksError(f"{name} must be a positive length")
    return value


def _collection_items(collection: object) -> tuple[object, ...]:
    dynamic_collection = cast(Any, collection)
    if hasattr(dynamic_collection, "count") and hasattr(dynamic_collection, "item"):
        return tuple(dynamic_collection.item(index) for index in range(dynamic_collection.count))
    return tuple(dynamic_collection)


def _owned_parents(attributes: object, expected_type: str) -> tuple[object, ...]:
    parents = (cast(Any, attribute).parent for attribute in _collection_items(attributes))
    return tuple(
        parent
        for parent in parents
        if parent is not None
        and getattr(parent, "isValid", True)
        and getattr(parent, "objectType", None) == expected_type
    )


def _delete_created(entity: object, description: str, error: Exception) -> None:
    try:
        if not cast(Any, entity).deleteMe():
            error.add_note(f"Could not delete {description}: delete returned false")
    except Exception as cleanup_error:
        error.add_note(f"Could not delete {description}: {cleanup_error}")


def _point3d(point: Point2) -> adsk.core.Point3D:
    return adsk.core.Point3D.create(point.x, point.y, 0)


def _is_sketch_line(entity: object) -> bool:
    line_type = adsk.fusion.SketchLine.classType() or "adsk::fusion::SketchLine"
    return getattr(entity, "objectType", None) == line_type


class FusionBackend:
    def __init__(self, application: adsk.core.Application) -> None:
        self.application = application
        self.product: object | None = None
        self.flat_pattern: object | None = None
        self.root_component: object | None = None
        self.straight_edges: tuple[object, ...] = ()
        self.skipped_bend_count = 0

    def prepare(self) -> None:
        product: object = cast(Any, self.application).activeProduct
        if getattr(product, "objectType", None) != "adsk::fusion::FlatPatternProduct":
            raise BendMarksError("Open a sheet-metal flat pattern before creating bend marks")

        dynamic_product = cast(Any, product)
        flat_pattern: object = dynamic_product.flatPattern
        edges = _collection_items(cast(Any, flat_pattern).bendLinesBody.edges)
        if not edges:
            raise BendMarksError("The active flat pattern has no bend lines")

        straight_edges = tuple(
            edge for edge in edges if classify_bend_geometry(cast(Any, edge).geometry)
        )
        if not straight_edges:
            raise BendMarksError("The active flat pattern has no supported straight bend lines")

        self.product = product
        self.flat_pattern = flat_pattern
        self.root_component = dynamic_product.rootComponent
        self.straight_edges = straight_edges
        self.skipped_bend_count = len(edges) - len(straight_edges)

    def ensure_parameters(self) -> tuple[object, ...]:
        user_parameters = cast(Any, self.product).userParameters
        created: list[object] = []
        try:
            for name, default_expression, comment in PARAMETERS:
                parameter = user_parameters.itemByName(name)
                if parameter is not None:
                    validate_parameter(name, parameter)
                    continue
                value = adsk.core.ValueInput.createByString(default_expression)
                parameter = user_parameters.add(name, value, "mm", comment)
                if parameter is None:
                    raise BendMarksError(f"Could not create {name}")
                created.append(parameter)
        except Exception as error:
            for parameter in reversed(created):
                try:
                    if not cast(Any, parameter).deleteMe():
                        error.add_note("Parameter rollback failed: delete returned false")
                except Exception as cleanup_error:
                    error.add_note(f"Parameter rollback failed: {cleanup_error}")
            raise
        return tuple(created)

    def find_existing_marks(self) -> ExistingMarks:
        product = cast(Any, self.product)
        sketch_type = adsk.fusion.Sketch.classType() or "adsk::fusion::Sketch"
        cut_type = adsk.fusion.ExtrudeFeature.classType() or "adsk::fusion::ExtrudeFeature"
        sketches = _owned_parents(
            product.findAttributes(ATTRIBUTE_GROUP, SKETCH_ATTRIBUTE), sketch_type
        )
        cuts = _owned_parents(product.findAttributes(ATTRIBUTE_GROUP, CUT_ATTRIBUTE), cut_type)
        if len(sketches) > 1:
            raise BendMarksError("Found multiple owned bend mark sketches")
        if len(cuts) > 1:
            raise BendMarksError("Found multiple owned bend mark cuts")
        return ExistingMarks(
            sketch=sketches[0] if sketches else None,
            cut=cuts[0] if cuts else None,
        )

    def _parameter_values(self) -> dict[str, float]:
        user_parameters = cast(Any, self.product).userParameters
        return {
            name: validate_parameter(name, user_parameters.itemByName(name))
            for name, _, _ in PARAMETERS
        }

    @staticmethod
    def _bend_operation(bend_index: int, operation: str, callback: Callable[[], object]) -> Any:
        try:
            entity = callback()
        except Exception as error:
            raise BendMarksError(f"Bend {bend_index}: {operation}") from error
        if not entity:
            raise BendMarksError(f"Bend {bend_index}: {operation}")
        return cast(Any, entity)

    @staticmethod
    def _set_dimension_expression(dimension: Any, expression: str) -> bool:
        dimension.parameter.expression = expression
        return True

    @staticmethod
    def _project_line(sketch: Any, edge: object, bend_index: int) -> Any:
        message = f"Bend {bend_index}: could not project centerline"
        try:
            projection = sketch.project(edge)
            projected = _collection_items(projection) if projection is not None else ()
        except Exception as error:
            raise BendMarksError(message) from error
        if len(projected) != 1 or not _is_sketch_line(projected[0]):
            raise BendMarksError(message)
        return cast(Any, projected[0])

    def _add_rectangle(
        self,
        sketch: Any,
        projected_line: Any,
        projected_endpoint: Any,
        rectangle: Rectangle,
        bend_index: int,
    ) -> None:
        lines = sketch.sketchCurves.sketchLines
        constraints = sketch.geometricConstraints
        dimensions = sketch.sketchDimensions
        corners = tuple(_point3d(corner) for corner in rectangle.corners)
        first_line = self._bend_operation(
            bend_index,
            "could not create rectangle edge",
            lambda: lines.addByTwoPoints(corners[0], corners[1]),
        )
        second_line = self._bend_operation(
            bend_index,
            "could not create rectangle edge",
            lambda: lines.addByTwoPoints(first_line.endSketchPoint, corners[2]),
        )
        third_line = self._bend_operation(
            bend_index,
            "could not create rectangle edge",
            lambda: lines.addByTwoPoints(second_line.endSketchPoint, corners[3]),
        )
        fourth_line = self._bend_operation(
            bend_index,
            "could not create rectangle edge",
            lambda: lines.addByTwoPoints(third_line.endSketchPoint, first_line.startSketchPoint),
        )
        rectangle_lines = (first_line, second_line, third_line, fourth_line)

        for line in (rectangle_lines[1], rectangle_lines[3]):
            self._bend_operation(
                bend_index,
                "could not add parallel constraint",
                lambda line=line: constraints.addParallel(line, projected_line),
            )
        for line in (rectangle_lines[0], rectangle_lines[2]):
            self._bend_operation(
                bend_index,
                "could not add perpendicular constraint",
                lambda line=line: constraints.addPerpendicular(line, projected_line),
            )

        outer_line = self._bend_operation(
            bend_index,
            "could not create outer construction line",
            lambda: lines.addByTwoPoints(_point3d(rectangle.outer_midpoint), projected_endpoint),
        )
        inner_line = self._bend_operation(
            bend_index,
            "could not create inner construction line",
            lambda: lines.addByTwoPoints(projected_endpoint, _point3d(rectangle.inner_midpoint)),
        )
        outer_line.isConstruction = True
        inner_line.isConstruction = True

        for construction, midpoint, edge in (
            (outer_line, outer_line.startSketchPoint, rectangle_lines[0]),
            (inner_line, inner_line.endSketchPoint, rectangle_lines[2]),
        ):
            self._bend_operation(
                bend_index,
                "could not add midpoint constraint",
                lambda midpoint=midpoint, edge=edge: constraints.addMidPoint(midpoint, edge),
            )
            self._bend_operation(
                bend_index,
                "could not add collinear constraint",
                lambda construction=construction: constraints.addCollinear(
                    construction, projected_line
                ),
            )

        orientation = adsk.fusion.DimensionOrientations.AlignedDimensionOrientation
        dimension_specs = (
            (outer_line, "bend_mark_overhang", rectangle.outer_midpoint),
            (inner_line, "bend_mark_inset", rectangle.inner_midpoint),
            (rectangle_lines[0], "bend_mark_width", rectangle.corners[0]),
        )
        for line, expression, text_position in dimension_specs:
            dimension = self._bend_operation(
                bend_index,
                f"could not add {expression} dimension",
                lambda line=line, text_position=text_position: dimensions.addDistanceDimension(
                    line.startSketchPoint,
                    line.endSketchPoint,
                    orientation,
                    _point3d(text_position),
                    True,
                ),
            )
            self._bend_operation(
                bend_index,
                f"could not set {expression} expression",
                lambda dimension=dimension, expression=expression: self._set_dimension_expression(
                    dimension, expression
                ),
            )

    def _create_sketch(self) -> object:
        sketch: Any = None
        try:
            root_component = cast(Any, self.root_component)
            flat_pattern = cast(Any, self.flat_pattern)
            sketch = root_component.sketches.addWithoutEdges(flat_pattern.topFace)
            if sketch is None:
                raise BendMarksError("Could not create bend mark sketch")
            sketch.name = "Bend Marks"
            if not sketch.attributes.add(ATTRIBUTE_GROUP, SKETCH_ATTRIBUTE, "1"):
                raise BendMarksError("Could not tag bend mark sketch")

            values = self._parameter_values()
            for bend_index, edge in enumerate(self.straight_edges, start=1):
                projected_line = self._project_line(sketch, edge, bend_index)
                projected_line.isConstruction = True
                start_point = projected_line.startSketchPoint
                end_point = projected_line.endSketchPoint
                start_geometry = start_point.geometry
                end_geometry = end_point.geometry
                try:
                    rectangles = endpoint_rectangles(
                        Point2(start_geometry.x, start_geometry.y),
                        Point2(end_geometry.x, end_geometry.y),
                        values["bend_mark_width"],
                        values["bend_mark_inset"],
                        values["bend_mark_overhang"],
                    )
                except Exception as error:
                    raise BendMarksError(
                        f"Bend {bend_index}: could not calculate endpoint rectangles"
                    ) from error
                self._add_rectangle(sketch, projected_line, start_point, rectangles[0], bend_index)
                self._add_rectangle(sketch, projected_line, end_point, rectangles[1], bend_index)
            return sketch
        except Exception as error:
            if sketch is not None:
                _delete_created(sketch, "partial bend mark sketch", error)
            raise

    def build(self) -> BuildArtifacts:
        sketch = self._create_sketch()
        cut: Any = None
        try:
            profiles_source = cast(Any, sketch).profiles
            profiles_count = profiles_source.count
            if profiles_count < 1:
                raise BendMarksError("The bend mark sketch has no profiles")
            profiles = adsk.core.ObjectCollection.create()
            if profiles is None:
                raise BendMarksError("Could not create bend mark profile collection")
            for index in range(profiles_count):
                if not profiles.add(profiles_source.item(index)):
                    raise BendMarksError("Could not collect bend mark profile")

            extrudes = cast(Any, self.root_component).features.extrudeFeatures
            extrude_input = extrudes.createInput(
                profiles, adsk.fusion.FeatureOperations.CutFeatureOperation
            )
            if extrude_input is None:
                raise BendMarksError("Could not create bend mark cut input")
            if not extrude_input.setAllExtent(
                adsk.fusion.ExtentDirections.SymmetricExtentDirection
            ):
                raise BendMarksError("Could not set bend mark cut to through-all")
            cut = extrudes.add(extrude_input)
            if cut is None:
                raise BendMarksError("Could not create bend mark cut")
            cut.name = "Bend Marks Cut"
            if not cut.attributes.add(ATTRIBUTE_GROUP, CUT_ATTRIBUTE, "1"):
                raise BendMarksError("Could not tag bend mark cut")
        except Exception as error:
            if cut is not None:
                _delete_created(cut, "partial bend mark cut", error)
            _delete_created(sketch, "partial bend mark sketch", error)
            raise

        processed = len(self.straight_edges)
        return BuildArtifacts(
            sketch,
            cut,
            BuildResult(processed, processed * 2, self.skipped_bend_count),
        )

    def set_cut_suppressed(self, cut: object, suppressed: bool) -> None:
        dynamic_cut = cast(Any, cut)
        dynamic_cut.isSuppressed = suppressed
        if dynamic_cut.isSuppressed != suppressed:
            action = "suppress" if suppressed else "restore"
            raise BendMarksError(f"Could not {action} bend mark cut")

    def delete_existing_marks(self, marks: ExistingMarks) -> None:
        for entity, description in ((marks.cut, "cut"), (marks.sketch, "sketch")):
            if entity is not None and not cast(Any, entity).deleteMe():
                raise BendMarksError(f"Could not delete existing bend mark {description}")

    def delete_parameters(self, parameters: tuple[object, ...]) -> None:
        failures: list[str] = []
        for index, parameter in reversed(tuple(enumerate(parameters, start=1))):
            dynamic_parameter = cast(Any, parameter)
            name = getattr(dynamic_parameter, "name", f"parameter {index}")
            try:
                if not dynamic_parameter.deleteMe():
                    failures.append(f"{name}: delete returned false")
            except Exception as error:
                failures.append(f"{name}: {error}")
        if failures:
            raise BendMarksError(f"Could not delete bend mark parameters: {'; '.join(failures)}")
