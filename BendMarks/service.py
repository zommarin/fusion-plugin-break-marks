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

    def ensure_parameters(
        self, expressions: dict[str, str] | None = None
    ) -> tuple[object, ...]: ...

    def find_existing_marks(self) -> ExistingMarks: ...

    def set_cut_suppressed(self, cut: object, suppressed: bool) -> None: ...

    def build(self) -> BuildArtifacts: ...

    def delete_existing_marks(self, marks: ExistingMarks) -> None: ...

    def delete_parameters(self, parameters: tuple[object, ...]) -> None: ...


def rebuild_bend_marks(
    backend: BendMarksBackend, expressions: dict[str, str] | None = None
) -> BuildResult:
    backend.prepare()
    created_parameters = backend.ensure_parameters(expressions)
    existing = ExistingMarks()
    cut_to_restore: object | None = None
    try:
        existing = backend.find_existing_marks()
        if existing.cut is not None:
            cut_to_restore = existing.cut
            backend.set_cut_suppressed(existing.cut, True)
        artifacts = backend.build()
    except Exception as error:
        if cut_to_restore is not None:
            try:
                backend.set_cut_suppressed(cut_to_restore, False)
            except Exception as cleanup_error:
                error.add_note(f"Cut restoration failed: {cleanup_error}")
        try:
            backend.delete_parameters(created_parameters)
        except Exception as cleanup_error:
            error.add_note(f"Parameter cleanup failed: {cleanup_error}")
        raise

    backend.delete_existing_marks(existing)
    return artifacts.result
