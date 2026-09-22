import traceback
from typing import Any, cast

import adsk.core

from BendMarks.fusion_adapter import FusionBackend
from BendMarks.service import BendMarksError, BuildResult, rebuild_bend_marks

COMMAND_ID = "zommarin_fusion_break_marks_create"
COMMAND_NAME = "Create Bend Marks"
TAB_ID = "SheetMetalTab"
PANEL_ID = "zommarin_fusion_break_marks_panel"

_COMMAND_DESCRIPTION = "Create rectangular alignment cuts at every flat-pattern bend endpoint"
_handlers: list[object] = []


def _show_message(ui: object, message: str) -> None:
    cast(Any, ui).messageBox(message)


def _success_message(result: BuildResult) -> str:
    message = f"Created {result.created_marks} bend marks across {result.processed_bends} bends."
    if result.skipped_bends:
        message += f"\nSkipped {result.skipped_bends} unsupported curved bends."
    return message


def _cleanup_ui(ui: object) -> None:
    dynamic_ui = cast(Any, ui)
    failures: list[str] = []
    panel = None
    try:
        panel = dynamic_ui.allToolbarPanels.itemById(PANEL_ID)
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
        try:
            if not panel.deleteMe():
                failures.append("toolbar panel: delete returned false")
        except Exception as error:
            failures.append(f"toolbar panel: {error}")

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
    def __init__(self, application: object) -> None:
        super().__init__()
        self.application = application

    def notify(self, eventArgs: adsk.core.CommandEventArgs) -> None:  # noqa: N803
        ui = cast(Any, self.application).userInterface
        try:
            result = rebuild_bend_marks(FusionBackend(cast(Any, self.application)))
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
        command.isAutoExecute = True
        try:
            execute_handler = _ExecuteHandler(self.application)
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
    ui = cast(Any, application).userInterface
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
        if tab is None:
            _cleanup_ui(ui)
            _handlers.clear()
            _show_message(ui, "Sheet Metal tab is unavailable.")
            return

        panel = tab.toolbarPanels.add(PANEL_ID, "Bend Marks", "", False)
        if panel is None:
            raise RuntimeError("Could not create Bend Marks panel")
        if panel.controls.addCommand(definition, "", False) is None:
            raise RuntimeError("Could not create Bend Marks command control")
    except Exception:
        _report_startup_failure(ui, traceback.format_exc())


def stop(context: object) -> None:
    del context
    try:
        application = adsk.core.Application.get()
        _cleanup_ui(cast(Any, application).userInterface)
    finally:
        _handlers.clear()
