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
