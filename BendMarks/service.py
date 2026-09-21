from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class BendMarksError(RuntimeError):
    pass


@dataclass(frozen=True)
class BuildResult:
    processed_bends: int
    created_marks: int
    skipped_bends: int


@dataclass(frozen=True)
class ExistingMarks:
    sketch: object | None = None
    cut: object | None = None


@dataclass(frozen=True)
class BuildArtifacts:
    sketch: object
    cut: object
    result: BuildResult


class BendMarksBackend(Protocol):
    def prepare(self) -> None: ...

    def ensure_parameters(self) -> tuple[object, ...]: ...

    def find_existing_marks(self) -> ExistingMarks: ...

    def set_cut_suppressed(self, cut: object, suppressed: bool) -> None: ...

    def build(self) -> BuildArtifacts: ...

    def delete_existing_marks(self, marks: ExistingMarks) -> None: ...

    def delete_artifacts(self, artifacts: BuildArtifacts) -> None: ...

    def delete_parameters(self, parameters: tuple[object, ...]) -> None: ...


def rebuild_bend_marks(backend: BendMarksBackend) -> BuildResult:
    backend.prepare()
    created_parameters = backend.ensure_parameters()
    existing = backend.find_existing_marks()
    artifacts: BuildArtifacts | None = None
    suppressed = existing.cut is not None
    try:
        if existing.cut is not None:
            backend.set_cut_suppressed(existing.cut, True)
        artifacts = backend.build()
        backend.delete_existing_marks(existing)
        return artifacts.result
    except Exception:
        if artifacts is not None:
            backend.delete_artifacts(artifacts)
        if suppressed and existing.cut is not None:
            backend.set_cut_suppressed(existing.cut, False)
        backend.delete_parameters(created_parameters)
        raise
