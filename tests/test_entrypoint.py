import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from BendMarks import BendMarks
from BendMarks.service import BendMarksError, BuildResult


class FakeEvent:
    def __init__(self) -> None:
        self.handlers: list[object] = []

    def add(self, handler: object) -> bool:
        self.handlers.append(handler)
        return True


class FakeEntity:
    def __init__(self, entity_id: str, events: list[str]) -> None:
        self.id = entity_id
        self.events = events

    def deleteMe(self) -> bool:
        self.events.append(f"delete:{self.id}")
        return True


class FakeCollection:
    def __init__(self, entities: dict[str, object] | None = None) -> None:
        self.entities = entities or {}

    def itemById(self, entity_id: str) -> object | None:
        return self.entities.get(entity_id)


class FakeControls(FakeCollection):
    def __init__(self, events: list[str]) -> None:
        super().__init__()
        self.events = events

    def addCommand(self, definition: object, position_id: str, is_before: bool) -> object:
        del position_id, is_before
        control = FakeEntity(BendMarks.COMMAND_ID, self.events)
        self.entities[BendMarks.COMMAND_ID] = control
        return control


class FakePanel(FakeEntity):
    def __init__(self, events: list[str]) -> None:
        super().__init__(BendMarks.PANEL_ID, events)
        self.controls = FakeControls(events)


class FakePanels(FakeCollection):
    def __init__(self, events: list[str]) -> None:
        super().__init__()
        self.events = events

    def add(self, panel_id: str, name: str, position_id: str, is_before: bool) -> FakePanel:
        assert (panel_id, name, position_id, is_before) == (
            BendMarks.PANEL_ID,
            "Bend Marks",
            "",
            False,
        )
        panel = FakePanel(self.events)
        self.entities[panel_id] = panel
        return panel


class FakeDefinition(FakeEntity):
    def __init__(self, events: list[str]) -> None:
        super().__init__(BendMarks.COMMAND_ID, events)
        self.commandCreated = FakeEvent()


class FakeDefinitions(FakeCollection):
    def __init__(self, events: list[str]) -> None:
        super().__init__()
        self.events = events
        self.added_args: tuple[str, str, str, str] | None = None

    def addButtonDefinition(
        self, command_id: str, name: str, description: str, resources: str
    ) -> FakeDefinition:
        self.added_args = (command_id, name, description, resources)
        definition = FakeDefinition(self.events)
        self.entities[command_id] = definition
        return definition


class FakeUI:
    def __init__(self, *, has_tab: bool = True) -> None:
        self.events: list[str] = []
        self.messages: list[str] = []
        self.commandDefinitions = FakeDefinitions(self.events)
        self.panels = FakePanels(self.events)
        self.allToolbarPanels = self.panels
        tab = SimpleNamespace(toolbarPanels=self.panels) if has_tab else None
        self.allToolbarTabs = FakeCollection({BendMarks.TAB_ID: tab} if tab else {})

    def messageBox(self, message: str) -> None:
        self.messages.append(message)


def _application(ui: FakeUI) -> object:
    return SimpleNamespace(userInterface=ui)


def test_command_uses_stable_ids() -> None:
    assert BendMarks.COMMAND_ID == "zommarin_fusion_break_marks_create"
    assert BendMarks.TAB_ID == "SheetMetalTab"
    assert BendMarks.PANEL_ID == "zommarin_fusion_break_marks_panel"


def test_manifest_defines_cross_platform_addin() -> None:
    manifest = json.loads(Path("BendMarks/BendMarks.manifest").read_text())
    assert manifest == {
        "autodeskProduct": "Fusion360",
        "type": "addin",
        "author": "zommarin",
        "description": {"": "Create alignment cutouts at sheet-metal bend endpoints"},
        "version": "0.1.0",
        "runOnStartup": False,
        "supportedOS": "windows|mac",
    }


def test_repeated_cleanup_tolerates_missing_objects() -> None:
    ui = FakeUI()

    BendMarks._cleanup_ui(ui)
    BendMarks._cleanup_ui(ui)

    assert ui.events == []


def test_cleanup_deletes_control_before_panel_and_definition() -> None:
    ui = FakeUI()
    panel = FakePanel(ui.events)
    panel.controls.entities[BendMarks.COMMAND_ID] = FakeEntity(BendMarks.COMMAND_ID, ui.events)
    ui.panels.entities[BendMarks.PANEL_ID] = panel
    ui.commandDefinitions.entities[BendMarks.COMMAND_ID] = FakeDefinition(ui.events)

    BendMarks._cleanup_ui(ui)

    assert ui.events == [
        f"delete:{BendMarks.COMMAND_ID}",
        f"delete:{BendMarks.PANEL_ID}",
        f"delete:{BendMarks.COMMAND_ID}",
    ]


@pytest.mark.parametrize(
    ("skipped", "expected"),
    [
        (0, "Created 6 bend marks across 3 bends."),
        (
            2,
            "Created 6 bend marks across 3 bends.\nSkipped 2 unsupported curved bends.",
        ),
    ],
)
def test_success_message_includes_skipped_line_only_when_nonzero(
    skipped: int, expected: str
) -> None:
    assert BendMarks._success_message(BuildResult(3, 6, skipped)) == expected


def test_run_registers_command_and_retains_created_and_execute_handlers(monkeypatch: Any) -> None:
    ui = FakeUI()
    application = _application(ui)
    monkeypatch.setattr(BendMarks.adsk.core.Application, "get", lambda: application)
    BendMarks._handlers.clear()

    BendMarks.run(object())
    definition = ui.commandDefinitions.itemById(BendMarks.COMMAND_ID)
    assert isinstance(definition, FakeDefinition)
    created_handler: Any = definition.commandCreated.handlers[0]
    execute_event = FakeEvent()
    command = SimpleNamespace(isAutoExecute=False, execute=execute_event)
    created_handler.notify(SimpleNamespace(command=command))

    assert ui.commandDefinitions.added_args == (
        BendMarks.COMMAND_ID,
        "Create Bend Marks",
        "Create rectangular alignment cuts at every flat-pattern bend endpoint",
        "",
    )
    assert command.isAutoExecute is True
    assert BendMarks._handlers == [created_handler, execute_event.handlers[0]]
    assert ui.panels.itemById(BendMarks.PANEL_ID) is not None


def test_run_removes_definition_and_reports_missing_sheet_metal_tab(monkeypatch: Any) -> None:
    ui = FakeUI(has_tab=False)
    monkeypatch.setattr(BendMarks.adsk.core.Application, "get", lambda: _application(ui))
    BendMarks._handlers.clear()

    BendMarks.run(object())

    assert ui.events == [f"delete:{BendMarks.COMMAND_ID}"]
    assert ui.messages == ["Sheet Metal tab is unavailable."]
    assert BendMarks._handlers == []


def test_execute_reports_success(monkeypatch: Any) -> None:
    ui = FakeUI()
    application = _application(ui)
    monkeypatch.setattr(BendMarks, "FusionBackend", lambda received: ("backend", received))
    monkeypatch.setattr(BendMarks, "rebuild_bend_marks", lambda backend: BuildResult(2, 4, 1))

    BendMarks._ExecuteHandler(application).notify(cast(Any, object()))

    assert ui.messages == [
        "Created 4 bend marks across 2 bends.\nSkipped 1 unsupported curved bends."
    ]


def test_execute_reports_domain_error(monkeypatch: Any) -> None:
    ui = FakeUI()
    application = _application(ui)

    def fail(_backend: object) -> BuildResult:
        raise BendMarksError("Open a flat pattern")

    monkeypatch.setattr(BendMarks, "rebuild_bend_marks", fail)

    BendMarks._ExecuteHandler(application).notify(cast(Any, object()))

    assert ui.messages == ["Open a flat pattern"]


def test_execute_reports_unexpected_traceback(monkeypatch: Any) -> None:
    ui = FakeUI()
    application = _application(ui)

    def fail(_backend: object) -> BuildResult:
        raise RuntimeError("API exploded")

    monkeypatch.setattr(BendMarks, "rebuild_bend_marks", fail)

    BendMarks._ExecuteHandler(application).notify(cast(Any, object()))

    assert ui.messages[0].startswith(
        "Create Bend Marks failed:\nTraceback (most recent call last):"
    )
    assert "RuntimeError: API exploded" in ui.messages[0]


def test_stop_cleans_ui_and_handler_references(monkeypatch: Any) -> None:
    ui = FakeUI()
    panel = FakePanel(ui.events)
    panel.controls.entities[BendMarks.COMMAND_ID] = FakeEntity(BendMarks.COMMAND_ID, ui.events)
    ui.panels.entities[BendMarks.PANEL_ID] = panel
    ui.commandDefinitions.entities[BendMarks.COMMAND_ID] = FakeDefinition(ui.events)
    monkeypatch.setattr(BendMarks.adsk.core.Application, "get", lambda: _application(ui))
    BendMarks._handlers[:] = [object(), object()]

    BendMarks.stop(object())

    assert ui.events == [
        f"delete:{BendMarks.COMMAND_ID}",
        f"delete:{BendMarks.PANEL_ID}",
        f"delete:{BendMarks.COMMAND_ID}",
    ]
    assert BendMarks._handlers == []
