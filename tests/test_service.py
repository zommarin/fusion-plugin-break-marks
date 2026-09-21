from dataclasses import dataclass, field

import pytest

from BendMarks.service import (
    BuildArtifacts,
    BuildResult,
    ExistingMarks,
    rebuild_bend_marks,
)


@dataclass
class FakeBackend:
    existing: ExistingMarks = ExistingMarks()
    fail_build: bool = False
    fail_delete_existing: bool = False
    calls: list[str] = field(default_factory=list)
    created_parameters: tuple[object, ...] = ()

    def prepare(self) -> None:
        self.calls.append("prepare")

    def ensure_parameters(self) -> tuple[object, ...]:
        self.calls.append("ensure_parameters")
        return self.created_parameters

    def find_existing_marks(self) -> ExistingMarks:
        self.calls.append("find_existing_marks")
        return self.existing

    def set_cut_suppressed(self, cut: object, suppressed: bool) -> None:
        self.calls.append(f"suppress:{suppressed}")

    def build(self) -> BuildArtifacts:
        self.calls.append("build")
        if self.fail_build:
            raise RuntimeError("profile creation failed")
        return BuildArtifacts("new-sketch", "new-cut", BuildResult(2, 4, 1))

    def delete_existing_marks(self, marks: ExistingMarks) -> None:
        self.calls.append("delete_existing")
        if self.fail_delete_existing:
            raise RuntimeError("existing mark deletion failed")

    def delete_artifacts(self, artifacts: BuildArtifacts) -> None:
        self.calls.append("delete_artifacts")

    def delete_parameters(self, parameters: tuple[object, ...]) -> None:
        self.calls.append("delete_parameters")


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


def test_failed_existing_mark_deletion_cleans_new_state_before_restoring_old_cut() -> None:
    parameter = object()
    backend = FakeBackend(
        existing=ExistingMarks("old-sketch", "old-cut"),
        fail_delete_existing=True,
        created_parameters=(parameter,),
    )

    with pytest.raises(RuntimeError, match="existing mark deletion failed"):
        rebuild_bend_marks(backend)

    assert backend.calls[-3:] == [
        "delete_artifacts",
        "suppress:False",
        "delete_parameters",
    ]
