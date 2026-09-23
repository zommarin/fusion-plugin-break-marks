from dataclasses import dataclass, field

import pytest

from BendMarks.service import (
    BendMarksError,
    BuildArtifacts,
    BuildResult,
    ExistingMarks,
    rebuild_bend_marks,
)


@dataclass
class FakeBackend:
    existing: ExistingMarks = ExistingMarks()
    fail_find_existing: bool = False
    fail_suppress: bool = False
    fail_unsuppress: bool = False
    fail_build: bool = False
    fail_delete_existing: bool = False
    fail_delete_parameters: bool = False
    calls: list[str] = field(default_factory=list)
    created_parameters: tuple[object, ...] = ()
    expressions: dict[str, str] | None = None

    def prepare(self) -> None:
        self.calls.append("prepare")

    def ensure_parameters(self, expressions: dict[str, str] | None = None) -> tuple[object, ...]:
        self.calls.append("ensure_parameters")
        self.expressions = expressions
        return self.created_parameters

    def find_existing_marks(self) -> ExistingMarks:
        self.calls.append("find_existing_marks")
        if self.fail_find_existing:
            raise RuntimeError("ownership lookup failed")
        return self.existing

    def set_cut_suppressed(self, cut: object, suppressed: bool) -> None:
        self.calls.append(f"suppress:{suppressed}")
        if suppressed and self.fail_suppress:
            raise RuntimeError("suppression failed")
        if not suppressed and self.fail_unsuppress:
            raise RuntimeError("restoration failed")

    def build(self) -> BuildArtifacts:
        self.calls.append("build")
        if self.fail_build:
            raise RuntimeError("profile creation failed")
        return BuildArtifacts("new-sketch", "new-cut", BuildResult(2, 4, 1))

    def delete_existing_marks(self, marks: ExistingMarks) -> None:
        self.calls.append("delete_existing")
        if self.fail_delete_existing:
            raise BendMarksError("existing mark deletion failed")

    def delete_parameters(self, parameters: tuple[object, ...]) -> None:
        self.calls.append("delete_parameters")
        if self.fail_delete_parameters:
            raise RuntimeError("parameter cleanup failed")


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


def test_rebuild_applies_submitted_parameter_expressions() -> None:
    backend = FakeBackend()
    expressions = {
        "bend_mark_width": "stock_thickness * 2",
        "bend_mark_inset": "2.5 mm",
        "bend_mark_overhang": "bend_mark_inset / 2",
    }

    rebuild_bend_marks(backend, expressions)

    assert backend.expressions == expressions


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


def test_find_failure_removes_new_parameters() -> None:
    backend = FakeBackend(
        fail_find_existing=True,
        created_parameters=(object(),),
    )

    with pytest.raises(RuntimeError, match="ownership lookup failed"):
        rebuild_bend_marks(backend)

    assert backend.calls[-1] == "delete_parameters"


def test_parameter_cleanup_failure_preserves_find_error() -> None:
    backend = FakeBackend(
        fail_find_existing=True,
        fail_delete_parameters=True,
        created_parameters=(object(),),
    )

    with pytest.raises(RuntimeError, match="ownership lookup failed") as raised:
        rebuild_bend_marks(backend)

    assert backend.calls[-1] == "delete_parameters"
    assert raised.value.__notes__ == ["Parameter cleanup failed: parameter cleanup failed"]


def test_suppression_failure_restores_possibly_mutated_cut() -> None:
    backend = FakeBackend(
        existing=ExistingMarks("old-sketch", "old-cut"),
        fail_suppress=True,
        created_parameters=(object(),),
    )

    with pytest.raises(RuntimeError, match="suppression failed"):
        rebuild_bend_marks(backend)

    assert backend.calls[-2:] == ["suppress:False", "delete_parameters"]


@pytest.mark.parametrize(
    ("fail_unsuppress", "fail_delete_parameters", "expected_notes"),
    [
        (True, False, ["Cut restoration failed: restoration failed"]),
        (False, True, ["Parameter cleanup failed: parameter cleanup failed"]),
        (
            True,
            True,
            [
                "Cut restoration failed: restoration failed",
                "Parameter cleanup failed: parameter cleanup failed",
            ],
        ),
    ],
)
def test_cleanup_failures_preserve_build_error_and_attempt_all_recovery(
    fail_unsuppress: bool,
    fail_delete_parameters: bool,
    expected_notes: list[str],
) -> None:
    backend = FakeBackend(
        existing=ExistingMarks("old-sketch", "old-cut"),
        fail_build=True,
        fail_unsuppress=fail_unsuppress,
        fail_delete_parameters=fail_delete_parameters,
        created_parameters=(object(),),
    )

    with pytest.raises(RuntimeError, match="profile creation failed") as raised:
        rebuild_bend_marks(backend)

    assert backend.calls[-2:] == ["suppress:False", "delete_parameters"]
    assert raised.value.__notes__ == expected_notes


def test_existing_mark_deletion_failure_propagates_without_manual_recovery() -> None:
    backend = FakeBackend(
        existing=ExistingMarks("old-sketch", "old-cut"),
        fail_delete_existing=True,
        created_parameters=(object(),),
    )

    with pytest.raises(RuntimeError, match="existing mark deletion failed"):
        rebuild_bend_marks(backend)

    assert backend.calls[-3:] == [
        "suppress:True",
        "build",
        "delete_existing",
    ]
    assert "suppress:False" not in backend.calls
    assert "delete_parameters" not in backend.calls
