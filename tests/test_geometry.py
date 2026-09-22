from math import sqrt

import pytest

from BendMarks.geometry import (
    DegenerateBendError,
    NotchSide,
    Point2,
    endpoint_rectangles,
    selected_endpoint_rectangles,
)


def test_horizontal_bend_creates_outward_and_inward_extents() -> None:
    start, end = endpoint_rectangles(Point2(0, 0), Point2(10, 0), 2, 3, 1)

    assert start.corners == (Point2(-1, -1), Point2(-1, 1), Point2(3, 1), Point2(3, -1))
    assert end.corners == (Point2(11, 1), Point2(11, -1), Point2(7, -1), Point2(7, 1))


def test_vertical_bend_has_width_and_extents_at_both_endpoints() -> None:
    start, end = endpoint_rectangles(Point2(2, -3), Point2(2, 7), 4, 3, 1)

    assert start.corners == (Point2(4, -4), Point2(0, -4), Point2(0, 0), Point2(4, 0))
    assert end.corners == (Point2(0, 8), Point2(4, 8), Point2(4, 4), Point2(0, 4))
    assert start.width == 4
    assert end.width == 4
    assert (start.outer_midpoint, start.inner_midpoint) == (Point2(2, -4), Point2(2, 0))
    assert (end.outer_midpoint, end.inner_midpoint) == (Point2(2, 8), Point2(2, 4))


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
