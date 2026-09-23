import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from BendMarks import BendMarks
from BendMarks.service import BendMarksError, BuildResult, ExistingMarks
from tests.test_service import FakeBackend


class FakeEvent:
    def __init__(
        self,
        add_result: bool = True,
        *,
        remove_result: bool = True,
        remove_error: Exception | None = None,
    ) -> None:
        self.handlers: list[object] = []
        self.add_result = add_result
        self.remove_result = remove_result
        self.remove_error = remove_error
        self.remove_calls = 0

    def add(self, handler: object) -> bool:
        if self.add_result:
            self.handlers.append(handler)
        return self.add_result

    def remove(self, handler: object) -> bool:
        self.remove_calls += 1
        if self.remove_error is not None:
            raise self.remove_error
        if not self.remove_result or handler not in self.handlers:
            return False
        self.handlers.remove(handler)
        return True


class FakeCommandInputs:
    def __init__(self, null_on: str | None = None) -> None:
        self.added: list[tuple[str, str, str, object]] = []
        self.null_on = null_on

    def addValueInput(self, input_id: str, name: str, unit: str, value: object) -> SimpleNamespace:
        self.added.append((input_id, name, unit, value))
        if input_id == self.null_on:
            return cast(Any, None)
        return SimpleNamespace(expression=getattr(value, "expression", ""))


class FakeEntity:
    def __init__(
        self,
        entity_id: str,
        events: list[str],
        *,
        delete_result: bool = True,
        delete_error: Exception | None = None,
    ) -> None:
        self.id = entity_id
        self.events = events
        self.delete_result = delete_result
        self.delete_error = delete_error
        self.isPromoted = False

    def deleteMe(self) -> bool:
        self.events.append(f"delete:{self.id}")
        if self.delete_error is not None:
            raise self.delete_error
        return self.delete_result


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


class FakeDefinition(FakeEntity):
    def __init__(self, events: list[str], command_created_add_result: bool = True) -> None:
        super().__init__(BendMarks.COMMAND_ID, events)
        self.commandCreated = FakeEvent(command_created_add_result)


class FakeDefinitions(FakeCollection):
    def __init__(self, events: list[str]) -> None:
        super().__init__()
        self.events = events
        self.added_args: tuple[str, str, str, str] | None = None
        self.command_created_add_result = True

    def addButtonDefinition(
        self, command_id: str, name: str, description: str, resources: str
    ) -> FakeDefinition:
        self.added_args = (command_id, name, description, resources)
        definition = FakeDefinition(self.events, self.command_created_add_result)
        self.entities[command_id] = definition
        return definition


class FakeUI:
    def __init__(self, *, has_panel: bool = True) -> None:
        self.events: list[str] = []
        self.messages: list[str] = []
        self.commandDefinitions = FakeDefinitions(self.events)
        self.flat_pattern_panels = FakeCollection(
            {"SolidCreatePanel": FakePanel(self.events)} if has_panel else {}
        )
        self.sheet_metal_panels = FakeCollection(
            {"SolidCreatePanel": FakePanel(self.events)} if has_panel else {}
        )
        self.panels = self.flat_pattern_panels
        self.allToolbarPanels = self.panels
        self.allToolbarTabs = FakeCollection(
            {"FlatPatternSolidTab": SimpleNamespace(toolbarPanels=self.flat_pattern_panels)}
        )

    def messageBox(self, message: str) -> None:
        self.messages.append(message)


def _application(ui: FakeUI) -> Any:
    logs: list[str] = []
    return SimpleNamespace(userInterface=ui, log=logs.append, logs=logs)


def test_command_uses_stable_ids() -> None:
    assert BendMarks.COMMAND_ID == "zommarin_fusion_break_marks_create"
    assert BendMarks.TAB_ID == "FlatPatternSolidTab"
    assert BendMarks.PANEL_ID == "SolidCreatePanel"


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


def test_cleanup_deletes_control_and_definition_but_preserves_builtin_panel() -> None:
    ui = FakeUI()
    panel = FakePanel(ui.events)
    panel.controls.entities[BendMarks.COMMAND_ID] = FakeEntity(BendMarks.COMMAND_ID, ui.events)
    ui.panels.entities[BendMarks.PANEL_ID] = panel
    ui.commandDefinitions.entities[BendMarks.COMMAND_ID] = FakeDefinition(ui.events)

    BendMarks._cleanup_ui(ui)

    assert ui.events == [
        f"delete:{BendMarks.COMMAND_ID}",
        f"delete:{BendMarks.COMMAND_ID}",
    ]
    assert ui.panels.itemById(BendMarks.PANEL_ID) is panel


def test_cleanup_aggregates_failures_after_attempting_every_deletion() -> None:
    ui = FakeUI()
    panel = FakePanel(ui.events)
    panel.controls.entities[BendMarks.COMMAND_ID] = FakeEntity(
        BendMarks.COMMAND_ID, ui.events, delete_result=False
    )
    ui.panels.entities[BendMarks.PANEL_ID] = panel
    ui.commandDefinitions.entities[BendMarks.COMMAND_ID] = FakeEntity(
        BendMarks.COMMAND_ID, ui.events, delete_result=False
    )

    with pytest.raises(RuntimeError) as error:
        BendMarks._cleanup_ui(ui)

    assert ui.events == [
        f"delete:{BendMarks.COMMAND_ID}",
        f"delete:{BendMarks.COMMAND_ID}",
    ]
    assert str(error.value) == (
        "Bend Marks cleanup failed: command control: delete returned false; "
        "command definition: delete returned false"
    )


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


def test_run_registers_dialog_inputs_and_retains_handlers(monkeypatch: Any) -> None:
    ui = FakeUI()
    application = _application(ui)
    monkeypatch.setattr(BendMarks.adsk.core.Application, "get", lambda: application)
    monkeypatch.setattr(
        BendMarks.adsk.core.ValueInput,
        "createByString",
        lambda expression: SimpleNamespace(expression=expression),
    )
    BendMarks._handlers.clear()

    BendMarks.run(object())
    definition = ui.commandDefinitions.itemById(BendMarks.COMMAND_ID)
    assert isinstance(definition, FakeDefinition)
    created_handler: Any = definition.commandCreated.handlers[0]
    execute_event = FakeEvent()
    destroy_event = FakeEvent()
    command_inputs = FakeCommandInputs()
    command = SimpleNamespace(
        isAutoExecute=True,
        commandInputs=command_inputs,
        execute=execute_event,
        destroy=destroy_event,
    )
    created_handler.notify(SimpleNamespace(command=command))

    assert ui.commandDefinitions.added_args == (
        BendMarks.COMMAND_ID,
        "Create Bend Marks",
        "Create rectangular alignment cuts at every flat-pattern bend endpoint",
        "",
    )
    assert command.isAutoExecute is False
    assert [item[:3] for item in command_inputs.added] == [
        ("bend_mark_width", "Width", "mm"),
        ("bend_mark_inset", "Inset", "mm"),
        ("bend_mark_overhang", "Overhang", "mm"),
    ]
    assert [cast(Any, item[3]).expression for item in command_inputs.added] == [
        "1.8 mm",
        "1 mm",
        "1 mm",
    ]
    assert BendMarks._handlers == [
        created_handler,
        execute_event.handlers[0],
        destroy_event.handlers[0],
    ]
    panel = cast(Any, ui.panels.itemById(BendMarks.PANEL_ID))
    control = panel.controls.itemById(BendMarks.COMMAND_ID)
    assert control.isPromoted is True
    assert application.logs == ["Bend Marks registered in FlatPatternSolidTab/SolidCreatePanel."]


def test_run_registers_command_in_flat_pattern_create_panel(monkeypatch: Any) -> None:
    ui = FakeUI()
    application = _application(ui)
    monkeypatch.setattr(BendMarks.adsk.core.Application, "get", lambda: application)
    BendMarks._handlers.clear()

    BendMarks.run(object())

    flat_panel = cast(Any, ui.flat_pattern_panels.itemById("SolidCreatePanel"))
    sheet_metal_panel = cast(Any, ui.sheet_metal_panels.itemById("SolidCreatePanel"))
    assert flat_panel.controls.itemById(BendMarks.COMMAND_ID) is not None
    assert sheet_metal_panel.controls.itemById(BendMarks.COMMAND_ID) is None


def test_command_dialog_prefills_existing_parameter_expressions(monkeypatch: Any) -> None:
    ui = FakeUI()
    parameters = {
        "bend_mark_width": SimpleNamespace(expression="stock_thickness * 2"),
        "bend_mark_inset": SimpleNamespace(expression="2.5 mm"),
        "bend_mark_overhang": SimpleNamespace(expression="bend_mark_inset / 2"),
    }
    application = SimpleNamespace(
        userInterface=ui,
        activeProduct=SimpleNamespace(
            userParameters=SimpleNamespace(itemByName=lambda name: parameters.get(name))
        ),
    )
    monkeypatch.setattr(
        BendMarks.adsk.core.ValueInput,
        "createByString",
        lambda expression: SimpleNamespace(expression=expression),
    )
    command_inputs = FakeCommandInputs()
    command = SimpleNamespace(
        isAutoExecute=True,
        commandInputs=command_inputs,
        execute=FakeEvent(),
        destroy=FakeEvent(),
    )

    BendMarks._CommandCreatedHandler(application).notify(
        cast(Any, SimpleNamespace(command=command))
    )

    assert [cast(Any, item[3]).expression for item in command_inputs.added] == [
        "stock_thickness * 2",
        "2.5 mm",
        "bend_mark_inset / 2",
    ]


def test_null_command_input_aborts_dialog_creation(monkeypatch: Any) -> None:
    ui = FakeUI()
    application = _application(ui)
    monkeypatch.setattr(
        BendMarks.adsk.core.ValueInput,
        "createByString",
        lambda expression: SimpleNamespace(expression=expression),
    )
    command = SimpleNamespace(
        isAutoExecute=True,
        commandInputs=FakeCommandInputs(null_on="bend_mark_inset"),
        execute=FakeEvent(),
        destroy=FakeEvent(),
    )

    BendMarks._CommandCreatedHandler(application).notify(
        cast(Any, SimpleNamespace(command=command))
    )

    assert "Could not create Inset input" in ui.messages[0]
    assert command.execute.handlers == []
    assert command.destroy.handlers == []


def test_run_removes_definition_and_reports_missing_flat_pattern_panel(monkeypatch: Any) -> None:
    ui = FakeUI(has_panel=False)
    monkeypatch.setattr(BendMarks.adsk.core.Application, "get", lambda: _application(ui))
    BendMarks._handlers.clear()

    BendMarks.run(object())

    assert ui.events == [f"delete:{BendMarks.COMMAND_ID}"]
    assert "Flat Pattern Solid Create panel is unavailable" in ui.messages[0]
    assert BendMarks._handlers == []


def test_stale_cleanup_failure_is_reported_and_retried_during_startup(monkeypatch: Any) -> None:
    ui = FakeUI()
    panel = FakePanel(ui.events)
    panel.controls.entities[BendMarks.COMMAND_ID] = FakeEntity(
        BendMarks.COMMAND_ID, ui.events, delete_result=False
    )
    ui.panels.entities[BendMarks.PANEL_ID] = panel
    ui.commandDefinitions.entities[BendMarks.COMMAND_ID] = FakeDefinition(ui.events)
    monkeypatch.setattr(BendMarks.adsk.core.Application, "get", lambda: _application(ui))
    BendMarks._handlers[:] = [object()]

    BendMarks.run(object())

    assert ui.events == [
        f"delete:{BendMarks.COMMAND_ID}",
        f"delete:{BendMarks.COMMAND_ID}",
        f"delete:{BendMarks.COMMAND_ID}",
        f"delete:{BendMarks.COMMAND_ID}",
    ]
    assert ui.messages[0].startswith("Create Bend Marks failed to start:\nTraceback")
    assert "command control: delete returned false" in ui.messages[0]
    assert BendMarks._handlers == []


def test_rejected_command_created_handler_cleans_registration(monkeypatch: Any) -> None:
    ui = FakeUI()
    ui.commandDefinitions.command_created_add_result = False
    monkeypatch.setattr(BendMarks.adsk.core.Application, "get", lambda: _application(ui))
    BendMarks._handlers.clear()

    BendMarks.run(object())

    assert ui.panels.itemById(BendMarks.PANEL_ID) is not None
    assert ui.events == [f"delete:{BendMarks.COMMAND_ID}"]
    assert "Could not register command-created handler" in ui.messages[0]
    assert BendMarks._handlers == []


def test_rejected_execute_handler_cleans_registration(monkeypatch: Any) -> None:
    ui = FakeUI()
    application = _application(ui)
    monkeypatch.setattr(BendMarks.adsk.core.Application, "get", lambda: application)
    BendMarks._handlers.clear()
    BendMarks.run(object())
    definition = ui.commandDefinitions.itemById(BendMarks.COMMAND_ID)
    assert isinstance(definition, FakeDefinition)
    created_handler: Any = definition.commandCreated.handlers[0]
    command = SimpleNamespace(
        isAutoExecute=False,
        commandInputs=FakeCommandInputs(),
        execute=FakeEvent(add_result=False),
        destroy=FakeEvent(),
    )

    created_handler.notify(SimpleNamespace(command=command))

    assert ui.events == [
        f"delete:{BendMarks.COMMAND_ID}",
        f"delete:{BendMarks.COMMAND_ID}",
    ]
    assert "Could not register execute handler" in ui.messages[0]
    assert BendMarks._handlers == []


@pytest.mark.parametrize(
    ("remove_result", "remove_error", "secondary_diagnostic"),
    [
        (False, None, "Execute-handler rollback failed: remove returned false"),
        (True, RuntimeError("remove exploded"), "Execute-handler rollback failed: remove exploded"),
    ],
)
def test_destroy_handler_rejection_preserves_error_when_execute_rollback_fails(
    monkeypatch: Any,
    remove_result: bool,
    remove_error: Exception | None,
    secondary_diagnostic: str,
) -> None:
    ui = FakeUI()
    application = _application(ui)
    monkeypatch.setattr(BendMarks.adsk.core.Application, "get", lambda: application)
    BendMarks._handlers.clear()
    BendMarks.run(object())
    definition = ui.commandDefinitions.itemById(BendMarks.COMMAND_ID)
    assert isinstance(definition, FakeDefinition)
    created_handler: Any = definition.commandCreated.handlers[0]
    execute_event = FakeEvent(
        remove_result=remove_result,
        remove_error=remove_error,
    )
    command = SimpleNamespace(
        isAutoExecute=False,
        commandInputs=FakeCommandInputs(),
        execute=execute_event,
        destroy=FakeEvent(add_result=False),
    )

    created_handler.notify(SimpleNamespace(command=command))

    assert execute_event.remove_calls == 1
    assert "Could not register command-destroy handler" in ui.messages[0]
    assert secondary_diagnostic in ui.messages[0]
    assert ui.events == [
        f"delete:{BendMarks.COMMAND_ID}",
        f"delete:{BendMarks.COMMAND_ID}",
    ]
    assert BendMarks._handlers == []


def test_destroy_releases_handlers_between_command_invocations(monkeypatch: Any) -> None:
    ui = FakeUI()
    application = _application(ui)
    monkeypatch.setattr(BendMarks.adsk.core.Application, "get", lambda: application)
    BendMarks._handlers.clear()
    BendMarks.run(object())
    definition = ui.commandDefinitions.itemById(BendMarks.COMMAND_ID)
    assert isinstance(definition, FakeDefinition)
    created_handler: Any = definition.commandCreated.handlers[0]

    for _ in range(2):
        command = SimpleNamespace(
            isAutoExecute=False,
            commandInputs=FakeCommandInputs(),
            execute=FakeEvent(),
            destroy=FakeEvent(),
        )
        created_handler.notify(SimpleNamespace(command=command))
        assert len(BendMarks._handlers) == 3

        destroy_handler: Any = command.destroy.handlers[0]
        destroy_handler.notify(cast(Any, object()))
        assert BendMarks._handlers == [created_handler]


def test_execute_reports_success(monkeypatch: Any) -> None:
    ui = FakeUI()
    application = _application(ui)
    monkeypatch.setattr(BendMarks, "FusionBackend", lambda received: ("backend", received))
    monkeypatch.setattr(BendMarks, "rebuild_bend_marks", lambda backend: BuildResult(2, 4, 1))

    event_args = SimpleNamespace(executeFailed=False)
    BendMarks._ExecuteHandler(application).notify(cast(Any, event_args))

    assert event_args.executeFailed is False
    assert ui.messages == [
        "Created 4 bend marks across 2 bends.\nSkipped 1 unsupported curved bends."
    ]


def test_execute_forwards_edited_parameter_expressions(monkeypatch: Any) -> None:
    ui = FakeUI()
    application = _application(ui)
    received: list[dict[str, str]] = []

    def rebuild(_backend: object, expressions: dict[str, str]) -> BuildResult:
        received.append(expressions)
        return BuildResult(1, 2, 0)

    monkeypatch.setattr(BendMarks, "FusionBackend", lambda received: ("backend", received))
    monkeypatch.setattr(BendMarks, "rebuild_bend_marks", rebuild)
    inputs: dict[str, object] = {
        "bend_mark_width": SimpleNamespace(expression="stock_thickness * 2"),
        "bend_mark_inset": SimpleNamespace(expression="2.5 mm"),
        "bend_mark_overhang": SimpleNamespace(expression="bend_mark_inset / 2"),
    }

    event_args = SimpleNamespace(executeFailed=False)
    BendMarks._ExecuteHandler(application, inputs).notify(cast(Any, event_args))

    assert event_args.executeFailed is False
    assert received == [
        {
            "bend_mark_width": "stock_thickness * 2",
            "bend_mark_inset": "2.5 mm",
            "bend_mark_overhang": "bend_mark_inset / 2",
        }
    ]


def test_execute_reports_domain_error(monkeypatch: Any) -> None:
    ui = FakeUI()
    application = _application(ui)

    def fail(_backend: object) -> BuildResult:
        raise BendMarksError("Open a flat pattern")

    monkeypatch.setattr(BendMarks, "rebuild_bend_marks", fail)

    event_args = SimpleNamespace(executeFailed=False)
    BendMarks._ExecuteHandler(application).notify(cast(Any, event_args))

    assert event_args.executeFailed is True
    assert ui.messages == ["Open a flat pattern"]


def test_existing_mark_deletion_failure_aborts_command_with_primary_diagnostic(
    monkeypatch: Any,
) -> None:
    ui = FakeUI()
    application = _application(ui)
    backend = FakeBackend(
        existing=ExistingMarks(sketch="old-sketch", cut="old-cut"),
        fail_delete_existing=True,
    )
    monkeypatch.setattr(BendMarks, "FusionBackend", lambda _application: backend)

    event_args = SimpleNamespace(executeFailed=False)
    BendMarks._ExecuteHandler(application).notify(cast(Any, event_args))

    assert event_args.executeFailed is True
    assert backend.calls[-2:] == ["build", "delete_existing"]
    assert ui.messages == ["existing mark deletion failed"]


def test_execute_reports_unexpected_traceback(monkeypatch: Any) -> None:
    ui = FakeUI()
    application = _application(ui)

    def fail(_backend: object) -> BuildResult:
        raise RuntimeError("API exploded")

    monkeypatch.setattr(BendMarks, "rebuild_bend_marks", fail)

    event_args = SimpleNamespace(executeFailed=False)
    BendMarks._ExecuteHandler(application).notify(cast(Any, event_args))

    assert event_args.executeFailed is True
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
        f"delete:{BendMarks.COMMAND_ID}",
    ]
    assert BendMarks._handlers == []
