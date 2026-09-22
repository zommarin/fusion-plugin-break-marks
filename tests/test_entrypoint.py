import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from BendMarks import BendMarks
from BendMarks.geometry import NotchSide
from BendMarks.service import (
    BendMarksError,
    BuildResult,
    CreateNotchesResult,
    CutNotchesResult,
    ExistingMarks,
    ParameterExpressions,
)
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
        self.values: list[object] = []
        self.dropdowns: list[FakeDropDownInput] = []

    def addValueInput(self, input_id: str, name: str, unit: str, value: object) -> object:
        self.added.append((input_id, name, unit, value))
        if input_id == self.null_on:
            return cast(Any, None)
        command_input = SimpleNamespace(
            id=input_id,
            name=name,
            unit=unit,
            expression=getattr(value, "expression", value),
        )
        self.values.append(command_input)
        return command_input

    def addDropDownCommandInput(
        self, input_id: str, name: str, style: object
    ) -> "FakeDropDownInput":
        del style
        command_input = FakeDropDownInput(input_id, name)
        self.dropdowns.append(command_input)
        return command_input


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


class FakeSelections:
    def __init__(self, entities: list[object]) -> None:
        self.selections = [SimpleNamespace(entity=entity) for entity in entities]

    @property
    def count(self) -> int:
        return len(self.selections)

    def item(self, index: int) -> object:
        return self.selections[index]


class FakeListItems:
    def __init__(self, dropdown: "FakeDropDownInput") -> None:
        self.dropdown = dropdown
        self.items: list[object] = []

    def add(self, name: str, selected: bool, resource: str) -> object:
        del resource
        item = SimpleNamespace(name=name, isSelected=selected)
        self.items.append(item)
        if selected:
            self.dropdown.selectedItem = item
        return item


class FakeDropDownInput:
    def __init__(self, input_id: str, name: str) -> None:
        self.id = input_id
        self.name = name
        self.selectedItem: object | None = None
        self.listItems = FakeListItems(self)


class FakeControls(FakeCollection):
    def __init__(self, events: list[str]) -> None:
        super().__init__()
        self.events = events

    def addCommand(self, definition: object, position_id: str, is_before: bool) -> object:
        del position_id, is_before
        command_id = cast(Any, definition).id
        control = FakeEntity(command_id, self.events)
        self.entities[command_id] = control
        return control


class FakePanel(FakeEntity):
    def __init__(self, events: list[str]) -> None:
        super().__init__(BendMarks.PANEL_ID, events)
        self.controls = FakeControls(events)


class FakeDefinition(FakeEntity):
    def __init__(
        self, command_id: str, events: list[str], command_created_add_result: bool = True
    ) -> None:
        super().__init__(command_id, events)
        self.commandCreated = FakeEvent(command_created_add_result)


class FakeDefinitions(FakeCollection):
    def __init__(self, events: list[str]) -> None:
        super().__init__()
        self.events = events
        self.added_args: list[tuple[str, str, str, str]] = []
        self.command_created_add_result = True

    def addButtonDefinition(
        self, command_id: str, name: str, description: str, resources: str
    ) -> FakeDefinition:
        self.added_args.append((command_id, name, description, resources))
        definition = FakeDefinition(command_id, self.events, self.command_created_add_result)
        self.entities[command_id] = definition
        return definition


class FakeUI:
    def __init__(self, *, has_panel: bool = True) -> None:
        self.events: list[str] = []
        self.messages: list[str] = []
        self.activeSelections = FakeSelections([])
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


def _create_command(created_handler: object) -> Any:
    command = SimpleNamespace(
        isAutoExecute=True,
        commandInputs=FakeCommandInputs(),
        execute=FakeEvent(),
        destroy=FakeEvent(),
    )
    cast(Any, created_handler).notify(SimpleNamespace(command=command))
    return command


def test_command_uses_stable_ids() -> None:
    assert BendMarks.COMMAND_ID == "zommarin_fusion_break_marks_create"
    assert BendMarks.CREATE_SELECTED_COMMAND_ID == "zommarin_fusion_break_marks_create_selected"
    assert BendMarks.CUT_SELECTED_COMMAND_ID == "zommarin_fusion_break_marks_cut_selected"
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
    for command_id in BendMarks.COMMAND_IDS:
        panel.controls.entities[command_id] = FakeEntity(command_id, ui.events)
        ui.commandDefinitions.entities[command_id] = FakeDefinition(command_id, ui.events)
    ui.panels.entities[BendMarks.PANEL_ID] = panel

    BendMarks._cleanup_ui(ui)

    assert ui.events == [f"delete:{command_id}" for command_id in BendMarks.COMMAND_IDS] * 2
    assert ui.panels.itemById(BendMarks.PANEL_ID) is panel


def test_cleanup_aggregates_failures_after_attempting_every_deletion() -> None:
    ui = FakeUI()
    panel = FakePanel(ui.events)
    for command_id in BendMarks.COMMAND_IDS:
        panel.controls.entities[command_id] = FakeEntity(
            command_id,
            ui.events,
            delete_result=command_id != BendMarks.COMMAND_ID,
        )
        ui.commandDefinitions.entities[command_id] = FakeEntity(
            command_id,
            ui.events,
            delete_result=command_id != BendMarks.COMMAND_ID,
        )
    ui.panels.entities[BendMarks.PANEL_ID] = panel

    with pytest.raises(RuntimeError) as error:
        BendMarks._cleanup_ui(ui)

    assert ui.events == [f"delete:{command_id}" for command_id in BendMarks.COMMAND_IDS] * 2
    assert str(error.value) == (
        "Bend Marks cleanup failed: zommarin_fusion_break_marks_create control: "
        "delete returned false; zommarin_fusion_break_marks_create definition: "
        "delete returned false"
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


def test_run_registers_all_commands_in_specification_order(monkeypatch: Any) -> None:
    ui = FakeUI()
    application = _application(ui)
    monkeypatch.setattr(BendMarks.adsk.core.Application, "get", lambda: application)
    BendMarks._handlers.clear()

    BendMarks.run(object())
    assert [args[:2] for args in ui.commandDefinitions.added_args] == [
        (BendMarks.COMMAND_ID, "Create Bend Marks"),
        (BendMarks.CREATE_SELECTED_COMMAND_ID, "Create Selected Notches"),
        (BendMarks.CUT_SELECTED_COMMAND_ID, "Cut Selected Notches"),
    ]
    panel = cast(Any, ui.panels.itemById(BendMarks.PANEL_ID))
    assert list(panel.controls.entities) == list(BendMarks.COMMAND_IDS)
    assert all(control.isPromoted for control in panel.controls.entities.values())
    assert len(BendMarks._handlers) == 3
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

    assert ui.events == []
    assert "Flat Pattern Solid Create panel is unavailable" in ui.messages[0]
    assert BendMarks._handlers == []


def test_stale_cleanup_failure_is_reported_and_retried_during_startup(monkeypatch: Any) -> None:
    ui = FakeUI()
    panel = FakePanel(ui.events)
    panel.controls.entities[BendMarks.COMMAND_ID] = FakeEntity(
        BendMarks.COMMAND_ID, ui.events, delete_result=False
    )
    ui.panels.entities[BendMarks.PANEL_ID] = panel
    ui.commandDefinitions.entities[BendMarks.COMMAND_ID] = FakeDefinition(
        BendMarks.COMMAND_ID, ui.events
    )
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
    assert f"{BendMarks.COMMAND_ID} control: delete returned false" in ui.messages[0]
    assert BendMarks._handlers == []


def test_rejected_command_created_handler_cleans_registration(monkeypatch: Any) -> None:
    ui = FakeUI()
    ui.commandDefinitions.command_created_add_result = False
    monkeypatch.setattr(BendMarks.adsk.core.Application, "get", lambda: _application(ui))
    BendMarks._handlers.clear()

    BendMarks.run(object())

    assert ui.panels.itemById(BendMarks.PANEL_ID) is not None
    assert ui.events == [f"delete:{BendMarks.COMMAND_ID}"]
    assert "Could not register Create Bend Marks command-created handler" in ui.messages[0]
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

    assert ui.events == [f"delete:{command_id}" for command_id in BendMarks.COMMAND_IDS] * 2
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
    assert ui.events == [f"delete:{command_id}" for command_id in BendMarks.COMMAND_IDS] * 2
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
        assert len(BendMarks._handlers) == 5

        destroy_handler: Any = command.destroy.handlers[0]
        destroy_handler.notify(cast(Any, object()))
        assert BendMarks._handlers == [
            cast(Any, definition).commandCreated.handlers[0]
            for definition in ui.commandDefinitions.entities.values()
        ]


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


def test_create_selected_builds_dialog_and_executes_captured_selection(monkeypatch: Any) -> None:
    ui = FakeUI()
    selected = [object(), object()]
    ui.activeSelections = FakeSelections(selected)
    application = _application(ui)
    monkeypatch.setattr(BendMarks.adsk.core.Application, "get", lambda: application)
    monkeypatch.setattr(
        BendMarks,
        "parameter_expressions",
        lambda _application: ParameterExpressions("1.8 mm", "1 mm", "2 mm"),
        raising=False,
    )
    monkeypatch.setattr(
        BendMarks.adsk.core.ValueInput, "createByString", lambda expression: expression
    )
    backend_calls: list[tuple[object, tuple[object, ...]]] = []
    service_calls: list[tuple[object, ParameterExpressions, NotchSide]] = []

    def backend_factory(received_application: object, entities: tuple[object, ...]) -> object:
        backend_calls.append((received_application, entities))
        return "interactive-backend"

    def create_notches(
        backend: object, expressions: ParameterExpressions, side: NotchSide
    ) -> CreateNotchesResult:
        service_calls.append((backend, expressions, side))
        return CreateNotchesResult(2, 3)

    monkeypatch.setattr(BendMarks, "InteractiveNotchBackend", backend_factory, raising=False)
    monkeypatch.setattr(BendMarks, "create_selected_notches", create_notches, raising=False)
    BendMarks._handlers.clear()
    BendMarks.run(object())
    definition = cast(Any, ui.commandDefinitions.itemById(BendMarks.CREATE_SELECTED_COMMAND_ID))

    command = _create_command(definition.commandCreated.handlers[0])
    ui.activeSelections.selections.clear()

    assert command.isAutoExecute is False
    assert [
        (value.id, value.name, value.unit, value.expression)
        for value in command.commandInputs.values
    ] == [
        ("width", "Width", "mm", "1.8 mm"),
        ("inset", "Inset", "mm", "1 mm"),
        ("overhang", "Overhang", "mm", "2 mm"),
    ]
    dropdown = command.commandInputs.dropdowns[0]
    assert [item.name for item in dropdown.listItems.items] == ["Both", "Left", "Right"]
    assert dropdown.selectedItem.name == "Both"

    command.commandInputs.values[0].expression = "2.5 mm"
    command.commandInputs.values[1].expression = "0.8 mm"
    command.commandInputs.values[2].expression = "1.2 mm"
    dropdown.selectedItem = dropdown.listItems.items[2]
    event_args = SimpleNamespace(executeFailed=False)
    command.execute.handlers[0].notify(event_args)

    assert backend_calls == [(application, tuple(selected))]
    assert service_calls == [
        (
            "interactive-backend",
            ParameterExpressions("2.5 mm", "0.8 mm", "1.2 mm"),
            NotchSide.RIGHT,
        )
    ]
    assert event_args.executeFailed is False
    assert ui.messages == ["Created 3 notches from 2 selected centerlines."]
    assert len(BendMarks._handlers) == 5
    command.destroy.handlers[0].notify(object())
    assert len(BendMarks._handlers) == 3


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (BendMarksError("Select centerlines"), "Select centerlines"),
        (RuntimeError("API exploded"), "Create Selected Notches failed:\nTraceback"),
    ],
)
def test_create_selected_reports_failures(
    monkeypatch: Any, failure: Exception, expected: str
) -> None:
    ui = FakeUI()
    application = _application(ui)
    monkeypatch.setattr(BendMarks.adsk.core.Application, "get", lambda: application)
    monkeypatch.setattr(
        BendMarks,
        "parameter_expressions",
        lambda _application: ParameterExpressions("1 mm", "1 mm", "1 mm"),
        raising=False,
    )
    monkeypatch.setattr(BendMarks.adsk.core.ValueInput, "createByString", lambda value: value)

    def fail(*_args: object) -> CreateNotchesResult:
        raise failure

    monkeypatch.setattr(BendMarks, "create_selected_notches", fail, raising=False)
    BendMarks._handlers.clear()
    BendMarks.run(object())
    definition = cast(Any, ui.commandDefinitions.itemById(BendMarks.CREATE_SELECTED_COMMAND_ID))
    command = _create_command(definition.commandCreated.handlers[0])
    event_args = SimpleNamespace(executeFailed=False)

    command.execute.handlers[0].notify(event_args)

    assert event_args.executeFailed is True
    assert expected in ui.messages[-1]


def test_cut_selected_executes_without_dialog_inputs(monkeypatch: Any) -> None:
    ui = FakeUI()
    application = _application(ui)
    monkeypatch.setattr(BendMarks.adsk.core.Application, "get", lambda: application)
    backend_calls: list[object] = []
    service_calls: list[object] = []

    def backend_factory(received_application: object) -> object:
        backend_calls.append(received_application)
        return "cut-backend"

    def cut_notches(backend: object) -> CutNotchesResult:
        service_calls.append(backend)
        return CutNotchesResult(4)

    monkeypatch.setattr(BendMarks, "InteractiveCutBackend", backend_factory)
    monkeypatch.setattr(BendMarks, "cut_selected_notches", cut_notches)
    BendMarks._handlers.clear()
    BendMarks.run(object())
    definition = cast(Any, ui.commandDefinitions.itemById(BendMarks.CUT_SELECTED_COMMAND_ID))

    command = _create_command(definition.commandCreated.handlers[0])

    assert command.isAutoExecute is False
    assert command.commandInputs.values == []
    assert command.commandInputs.dropdowns == []
    assert len(BendMarks._handlers) == 5

    event_args = SimpleNamespace(executeFailed=False)
    command.execute.handlers[0].notify(event_args)

    assert backend_calls == [application]
    assert service_calls == ["cut-backend"]
    assert event_args.executeFailed is False
    assert ui.messages == ["Cut 4 generated notch profiles."]
    command.destroy.handlers[0].notify(object())
    assert len(BendMarks._handlers) == 3


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (BendMarksError("Activate the sketch"), "Activate the sketch"),
        (RuntimeError("API exploded"), "Cut Selected Notches failed:\nTraceback"),
    ],
)
def test_cut_selected_reports_failures(monkeypatch: Any, failure: Exception, expected: str) -> None:
    ui = FakeUI()
    application = _application(ui)
    monkeypatch.setattr(BendMarks.adsk.core.Application, "get", lambda: application)

    def fail(_backend: object) -> CutNotchesResult:
        raise failure

    monkeypatch.setattr(BendMarks, "cut_selected_notches", fail)
    BendMarks._handlers.clear()
    BendMarks.run(object())
    definition = cast(Any, ui.commandDefinitions.itemById(BendMarks.CUT_SELECTED_COMMAND_ID))
    command = _create_command(definition.commandCreated.handlers[0])
    event_args = SimpleNamespace(executeFailed=False)

    command.execute.handlers[0].notify(event_args)

    assert event_args.executeFailed is True
    assert expected in ui.messages[-1]


def test_stop_cleans_ui_and_handler_references(monkeypatch: Any) -> None:
    ui = FakeUI()
    panel = FakePanel(ui.events)
    for command_id in BendMarks.COMMAND_IDS:
        panel.controls.entities[command_id] = FakeEntity(command_id, ui.events)
        ui.commandDefinitions.entities[command_id] = FakeDefinition(command_id, ui.events)
    ui.panels.entities[BendMarks.PANEL_ID] = panel
    monkeypatch.setattr(BendMarks.adsk.core.Application, "get", lambda: _application(ui))
    BendMarks._handlers[:] = [object(), object()]

    BendMarks.stop(object())

    assert ui.events == [f"delete:{command_id}" for command_id in BendMarks.COMMAND_IDS] * 2
    assert BendMarks._handlers == []
