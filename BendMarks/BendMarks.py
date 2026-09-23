import traceback
from typing import Any, cast

import adsk.core

from .fusion_adapter import PARAMETERS, FusionBackend
from .service import BendMarksError, BuildResult, rebuild_bend_marks

COMMAND_ID = "zommarin_fusion_break_marks_create"
COMMAND_NAME = "Create Bend Marks"
TAB_ID = "FlatPatternSolidTab"
PANEL_ID = "SolidCreatePanel"

_COMMAND_DESCRIPTION = "Create rectangular alignment cuts at every flat-pattern bend endpoint"
_INPUT_LABELS = {
    "bend_mark_width": "Width",
    "bend_mark_inset": "Inset",
    "bend_mark_overhang": "Overhang",
}
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
        control = None
        try:
            control = panel.controls.itemById(COMMAND_ID)
        except Exception as error:
            failures.append(f"command control lookup: {error}")
        if control is not None:
            try:
                if not control.deleteMe():
                    failures.append("command control: delete returned false")
            except Exception as error:
                failures.append(f"command control: {error}")
    definition = None
    try:
        definition = dynamic_ui.commandDefinitions.itemById(COMMAND_ID)
    except Exception as error:
        failures.append(f"command definition lookup: {error}")
    if definition is not None:
        try:
            if not definition.deleteMe():
                failures.append("command definition: delete returned false")
        except Exception as error:
            failures.append(f"command definition: {error}")

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
    def __init__(self, execute_handler: _ExecuteHandler) -> None:
        super().__init__()
        self.execute_handler = execute_handler

    def notify(self, eventArgs: adsk.core.CommandEventArgs) -> None:  # noqa: N803
        del eventArgs
        for handler in (self.execute_handler, self):
            if handler in _handlers:
                _handlers.remove(handler)


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
            if not command.execute.add(execute_handler):
                raise RuntimeError("Could not register execute handler")
            destroy_handler = _CommandDestroyHandler(execute_handler)
            if not command.destroy.add(destroy_handler):
                registration_error = RuntimeError("Could not register command-destroy handler")
                try:
                    if not command.execute.remove(execute_handler):
                        registration_error.add_note(
                            "Execute-handler rollback failed: remove returned false"
                        )
                except Exception as rollback_error:
                    registration_error.add_note(
                        f"Execute-handler rollback failed: {rollback_error}"
                    )
                raise registration_error
            _handlers.extend((execute_handler, destroy_handler))
        except Exception:
            ui = cast(Any, self.application).userInterface
            _report_startup_failure(ui, traceback.format_exc())


def run(context: object) -> None:
    del context
    application = adsk.core.Application.get()
    dynamic_application = cast(Any, application)
    ui = dynamic_application.userInterface
    _handlers.clear()

    try:
        _cleanup_ui(ui)
        definition = ui.commandDefinitions.addButtonDefinition(
            COMMAND_ID,
            COMMAND_NAME,
            _COMMAND_DESCRIPTION,
            "",
        )
        if definition is None:
            raise RuntimeError("Could not create command definition")

        created_handler = _CommandCreatedHandler(application)
        if not definition.commandCreated.add(created_handler):
            raise RuntimeError("Could not register command-created handler")
        _handlers.append(created_handler)

        tab = ui.allToolbarTabs.itemById(TAB_ID)
        panel = None if tab is None else tab.toolbarPanels.itemById(PANEL_ID)
        if panel is None:
            raise RuntimeError("Flat Pattern Solid Create panel is unavailable")
        control = panel.controls.addCommand(definition, "", False)
        if control is None:
            raise RuntimeError("Could not create Bend Marks command control")
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
