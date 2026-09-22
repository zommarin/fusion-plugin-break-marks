import traceback
from typing import Any, cast

import adsk.core

from .fusion_adapter import PARAMETERS, FusionBackend
from .geometry import NotchSide
from .interactive_adapter import (
    InteractiveCutBackend,
    InteractiveNotchBackend,
    parameter_expressions,
)
from .service import (
    BendMarksError,
    BuildResult,
    ParameterExpressions,
    create_selected_notches,
    cut_selected_notches,
    rebuild_bend_marks,
)

COMMAND_ID = "zommarin_fusion_break_marks_create"
COMMAND_NAME = "Create Bend Marks"
CREATE_SELECTED_COMMAND_ID = "zommarin_fusion_break_marks_create_selected"
CUT_SELECTED_COMMAND_ID = "zommarin_fusion_break_marks_cut_selected"
TAB_ID = "FlatPatternSolidTab"
PANEL_ID = "SolidCreatePanel"

_COMMAND_DESCRIPTION = "Create rectangular alignment cuts at every flat-pattern bend endpoint"
_INPUT_LABELS = {
    "bend_mark_width": "Width",
    "bend_mark_inset": "Inset",
    "bend_mark_overhang": "Overhang",
}
_CREATE_SELECTED_DESCRIPTION = "Create bend notches from selected sketch centerlines"
_CUT_SELECTED_DESCRIPTION = "Cut generated notch profiles in the active sketch"
COMMAND_SPECS = (
    (COMMAND_ID, COMMAND_NAME, _COMMAND_DESCRIPTION),
    (CREATE_SELECTED_COMMAND_ID, "Create Selected Notches", _CREATE_SELECTED_DESCRIPTION),
    (CUT_SELECTED_COMMAND_ID, "Cut Selected Notches", _CUT_SELECTED_DESCRIPTION),
)
COMMAND_IDS = tuple(command_id for command_id, _, _ in COMMAND_SPECS)
_handlers: list[object] = []


def _show_message(ui: object, message: str) -> None:
    cast(Any, ui).messageBox(message)


def _success_message(result: BuildResult) -> str:
    message = f"Created {result.created_marks} bend marks across {result.processed_bends} bends."
    if result.skipped_bends:
        message += f"\nSkipped {result.skipped_bends} unsupported curved bends."
    return message


def _parameter_expressions(application: object) -> dict[str, str]:
    product = getattr(application, "activeProduct", None)
    user_parameters = getattr(product, "userParameters", None)
    expressions: dict[str, str] = {}
    for name, default_expression, _comment in PARAMETERS:
        parameter = user_parameters.itemByName(name) if user_parameters is not None else None
        expressions[name] = getattr(parameter, "expression", None) or default_expression
    return expressions


def _cleanup_ui(ui: object) -> None:
    dynamic_ui = cast(Any, ui)
    failures: list[str] = []
    panel = None
    try:
        tab = dynamic_ui.allToolbarTabs.itemById(TAB_ID)
        if tab is not None:
            panel = tab.toolbarPanels.itemById(PANEL_ID)
    except Exception as error:
        failures.append(f"toolbar panel lookup: {error}")

    if panel is not None:
        for command_id in COMMAND_IDS:
            control = None
            try:
                control = panel.controls.itemById(command_id)
            except Exception as error:
                failures.append(f"{command_id} control lookup: {error}")
            if control is not None:
                try:
                    if not control.deleteMe():
                        failures.append(f"{command_id} control: delete returned false")
                except Exception as error:
                    failures.append(f"{command_id} control: {error}")

    for command_id in COMMAND_IDS:
        definition = None
        try:
            definition = dynamic_ui.commandDefinitions.itemById(command_id)
        except Exception as error:
            failures.append(f"{command_id} definition lookup: {error}")
        if definition is not None:
            try:
                if not definition.deleteMe():
                    failures.append(f"{command_id} definition: delete returned false")
            except Exception as error:
                failures.append(f"{command_id} definition: {error}")

    if failures:
        raise RuntimeError(f"Bend Marks cleanup failed: {'; '.join(failures)}")


def _report_startup_failure(ui: object, failure: str) -> None:
    try:
        _cleanup_ui(ui)
    except Exception as cleanup_error:
        failure += f"\nCleanup also failed: {cleanup_error}"
    finally:
        _handlers.clear()
    _show_message(ui, f"Create Bend Marks failed to start:\n{failure}")


def _report_command_creation_failure(ui: object, command_name: str, failure: str) -> None:
    _show_message(ui, f"{command_name} failed to create command:\n{failure}")


class _ExecuteHandler(adsk.core.CommandEventHandler):
    def __init__(
        self, application: object, parameter_inputs: dict[str, object] | None = None
    ) -> None:
        super().__init__()
        self.application = application
        self.parameter_inputs = parameter_inputs or {}

    def notify(self, eventArgs: adsk.core.CommandEventArgs) -> None:  # noqa: N803
        ui = cast(Any, self.application).userInterface
        try:
            backend = FusionBackend(cast(Any, self.application))
            if self.parameter_inputs:
                expressions = {
                    name: cast(Any, command_input).expression
                    for name, command_input in self.parameter_inputs.items()
                }
                result = rebuild_bend_marks(backend, expressions)
            else:
                result = rebuild_bend_marks(backend)
        except BendMarksError as error:
            eventArgs.executeFailed = True
            _show_message(ui, str(error))
        except Exception:
            eventArgs.executeFailed = True
            _show_message(ui, f"Create Bend Marks failed:\n{traceback.format_exc()}")
        else:
            _show_message(ui, _success_message(result))


class _CommandDestroyHandler(adsk.core.CommandEventHandler):
    def __init__(self, execute_handler: object) -> None:
        super().__init__()
        self.execute_handler = execute_handler

    def notify(self, eventArgs: adsk.core.CommandEventArgs) -> None:  # noqa: N803
        del eventArgs
        for handler in (self.execute_handler, self):
            if handler in _handlers:
                _handlers.remove(handler)


def _retain_command_handlers(command: object, execute_handler: object) -> None:
    dynamic_command = cast(Any, command)
    if not dynamic_command.execute.add(execute_handler):
        raise RuntimeError("Could not register execute handler")
    destroy_handler = _CommandDestroyHandler(execute_handler)
    if not dynamic_command.destroy.add(destroy_handler):
        registration_error = RuntimeError("Could not register command-destroy handler")
        try:
            if not dynamic_command.execute.remove(execute_handler):
                registration_error.add_note(
                    "Execute-handler rollback failed: remove returned false"
                )
        except Exception as rollback_error:
            registration_error.add_note(f"Execute-handler rollback failed: {rollback_error}")
        raise registration_error
    _handlers.extend((execute_handler, destroy_handler))


class _CommandCreatedHandler(adsk.core.CommandCreatedEventHandler):
    def __init__(self, application: object) -> None:
        super().__init__()
        self.application = application

    def notify(self, eventArgs: adsk.core.CommandCreatedEventArgs) -> None:  # noqa: N803
        command = cast(Any, eventArgs).command
        command.isAutoExecute = False
        try:
            expressions = _parameter_expressions(self.application)
            parameter_inputs: dict[str, object] = {}
            for name, _default_expression, _comment in PARAMETERS:
                command_input = command.commandInputs.addValueInput(
                    name,
                    _INPUT_LABELS[name],
                    "mm",
                    adsk.core.ValueInput.createByString(expressions[name]),
                )
                if command_input is None:
                    raise RuntimeError(f"Could not create {_INPUT_LABELS[name]} input")
                parameter_inputs[name] = command_input
            execute_handler = _ExecuteHandler(self.application, parameter_inputs)
            _retain_command_handlers(command, execute_handler)
        except Exception:
            ui = cast(Any, self.application).userInterface
            _report_command_creation_failure(ui, COMMAND_NAME, traceback.format_exc())


class _CreateSelectedExecuteHandler(adsk.core.CommandEventHandler):
    def __init__(
        self,
        application: object,
        selected_entities: tuple[object, ...],
        value_inputs: tuple[object, object, object],
        side_input: object,
    ) -> None:
        super().__init__()
        self.application = application
        self.selected_entities = selected_entities
        self.value_inputs = value_inputs
        self.side_input = side_input

    def notify(self, eventArgs: adsk.core.CommandEventArgs) -> None:  # noqa: N803
        ui = cast(Any, self.application).userInterface
        try:
            expressions = ParameterExpressions(
                *(cast(Any, value_input).expression for value_input in self.value_inputs)
            )
            side_name = cast(Any, self.side_input).selectedItem.name
            side = NotchSide(side_name.casefold())
            result = create_selected_notches(
                InteractiveNotchBackend(self.application, self.selected_entities),
                expressions,
                side,
            )
        except BendMarksError as error:
            eventArgs.executeFailed = True
            _show_message(ui, str(error))
        except Exception:
            eventArgs.executeFailed = True
            _show_message(ui, f"Create Selected Notches failed:\n{traceback.format_exc()}")
        else:
            _show_message(
                ui,
                f"Created {result.created_notches} notches from "
                f"{result.processed_lines} selected centerlines.",
            )


class _CreateSelectedCommandCreatedHandler(adsk.core.CommandCreatedEventHandler):
    def __init__(self, application: object) -> None:
        super().__init__()
        self.application = application

    def notify(self, eventArgs: adsk.core.CommandCreatedEventArgs) -> None:  # noqa: N803
        command = cast(Any, eventArgs).command
        command.isAutoExecute = False
        try:
            ui = cast(Any, self.application).userInterface
            selections = ui.activeSelections
            selected_entities = tuple(
                selections.item(index).entity for index in range(selections.count)
            )
            defaults = parameter_expressions(self.application)
            inputs = command.commandInputs
            value_inputs = tuple(
                inputs.addValueInput(
                    input_id,
                    name,
                    "mm",
                    adsk.core.ValueInput.createByString(expression),
                )
                for input_id, name, expression in (
                    ("width", "Width", defaults.width),
                    ("inset", "Inset", defaults.inset),
                    ("overhang", "Overhang", defaults.overhang),
                )
            )
            side_input = inputs.addDropDownCommandInput(
                "side",
                "Side",
                adsk.core.DropDownStyles.TextListDropDownStyle,
            )
            for name in ("Both", "Left", "Right"):
                side_input.listItems.add(name, name == "Both", "")

            execute_handler = _CreateSelectedExecuteHandler(
                self.application,
                selected_entities,
                cast(tuple[object, object, object], value_inputs),
                side_input,
            )
            _retain_command_handlers(command, execute_handler)
        except Exception:
            ui = cast(Any, self.application).userInterface
            _report_command_creation_failure(ui, "Create Selected Notches", traceback.format_exc())


class _CutSelectedExecuteHandler(adsk.core.CommandEventHandler):
    def __init__(self, application: object) -> None:
        super().__init__()
        self.application = application

    def notify(self, eventArgs: adsk.core.CommandEventArgs) -> None:  # noqa: N803
        ui = cast(Any, self.application).userInterface
        try:
            result = cut_selected_notches(InteractiveCutBackend(self.application))
        except BendMarksError as error:
            eventArgs.executeFailed = True
            _show_message(ui, str(error))
        except Exception:
            eventArgs.executeFailed = True
            _show_message(ui, f"Cut Selected Notches failed:\n{traceback.format_exc()}")
        else:
            _show_message(ui, f"Cut {result.cut_profiles} generated notch profiles.")


class _CutSelectedCommandCreatedHandler(adsk.core.CommandCreatedEventHandler):
    def __init__(self, application: object) -> None:
        super().__init__()
        self.application = application

    def notify(self, eventArgs: adsk.core.CommandCreatedEventArgs) -> None:  # noqa: N803
        command = cast(Any, eventArgs).command
        command.isAutoExecute = False
        try:
            execute_handler = _CutSelectedExecuteHandler(self.application)
            _retain_command_handlers(command, execute_handler)
        except Exception:
            ui = cast(Any, self.application).userInterface
            _report_command_creation_failure(ui, "Cut Selected Notches", traceback.format_exc())


def run(context: object) -> None:
    del context
    application = adsk.core.Application.get()
    dynamic_application = cast(Any, application)
    ui = dynamic_application.userInterface
    _handlers.clear()

    try:
        _cleanup_ui(ui)
        tab = ui.allToolbarTabs.itemById(TAB_ID)
        panel = None if tab is None else tab.toolbarPanels.itemById(PANEL_ID)
        if panel is None:
            raise RuntimeError("Flat Pattern Solid Create panel is unavailable")

        for command_id, name, description in COMMAND_SPECS:
            definition = ui.commandDefinitions.addButtonDefinition(
                command_id,
                name,
                description,
                "",
            )
            if definition is None:
                raise RuntimeError(f"Could not create {name} command definition")

            handler_type = {
                COMMAND_ID: _CommandCreatedHandler,
                CREATE_SELECTED_COMMAND_ID: _CreateSelectedCommandCreatedHandler,
                CUT_SELECTED_COMMAND_ID: _CutSelectedCommandCreatedHandler,
            }[command_id]
            created_handler = handler_type(application)
            if not definition.commandCreated.add(created_handler):
                raise RuntimeError(f"Could not register {name} command-created handler")
            _handlers.append(created_handler)

            control = panel.controls.addCommand(definition, "", False)
            if control is None:
                raise RuntimeError(f"Could not create {name} command control")
            control.isPromoted = True
        dynamic_application.log(f"Bend Marks registered in {TAB_ID}/{PANEL_ID}.")
    except Exception:
        failure = traceback.format_exc()
        dynamic_application.log(failure)
        _report_startup_failure(ui, failure)


def stop(context: object) -> None:
    del context
    try:
        application = adsk.core.Application.get()
        _cleanup_ui(cast(Any, application).userInterface)
    finally:
        _handlers.clear()
