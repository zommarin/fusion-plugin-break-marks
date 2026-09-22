from pathlib import Path


def test_readme_documents_required_workflow() -> None:
    readme = Path("README.md").read_text()
    for phrase in (
        "Create Bend Marks",
        "bend_mark_width",
        "bend_mark_inset",
        "bend_mark_overhang",
        "active flat pattern",
        "October 2022",
        "aborts the command transaction",
        "Create Selected Notches",
        "Cut Selected Notches",
        "construction geometry",
        "same sketch",
        "lower sketch X",
        "active sketch",
    ):
        assert phrase in readme


def test_manual_verification_covers_model_safety() -> None:
    checklist = Path("docs/manual-verification.md").read_text()
    for phrase in (
        "irregular",
        "Rerun",
        "Undo",
        "DXF",
        "folded",
        "Both",
        "Left",
        "Right",
        "save and reopen",
        "selected centerlines",
    ):
        assert phrase in checklist
