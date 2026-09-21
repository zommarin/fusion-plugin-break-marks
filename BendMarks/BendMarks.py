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
    panel = dynamic_ui.allToolbarPanels.itemById(PANEL_ID)
    if panel is not None:
        control = panel.controls.itemById(COMMAND_ID)
        if control is not None:
            control.deleteMe()
        panel.deleteMe()

    definition = dynamic_ui.commandDefinitions.itemById(COMMAND_ID)
    if definition is not None:
        definition.deleteMe()


class _ExecuteHandler(adsk.core.CommandEventHandler):
    def __init__(self, application: object) -> None:
        super().__init__()
        self.application = application

    def notify(self, eventArgs: adsk.core.CommandEventArgs) -> None:  # noqa: N803
        del eventArgs
        ui = cast(Any, self.application).userInterface
        try:
            result = rebuild_bend_marks(FusionBackend(cast(Any, self.application)))
        except BendMarksError as error:
            _show_message(ui, str(error))
        except Exception:
            _show_message(ui, f"Create Bend Marks failed:\n{traceback.format_exc()}")
        else:
            _show_message(ui, _success_message(result))


class _CommandCreatedHandler(adsk.core.CommandCreatedEventHandler):
    def __init__(self, application: object) -> None:
        super().__init__()
        self.application = application

    def notify(self, eventArgs: adsk.core.CommandCreatedEventArgs) -> None:  # noqa: N803
        command = cast(Any, eventArgs).command
        command.isAutoExecute = True
        execute_handler = _ExecuteHandler(self.application)
        command.execute.add(execute_handler)
        _handlers.append(execute_handler)


def run(context: object) -> None:
    del context
    application = adsk.core.Application.get()
    ui = cast(Any, application).userInterface
    _cleanup_ui(ui)
    _handlers.clear()

    definition: Any = None
    try:
        definition = ui.commandDefinitions.addButtonDefinition(
            COMMAND_ID,
            COMMAND_NAME,
            _COMMAND_DESCRIPTION,
            "",
        )
        if definition is None:
            raise RuntimeError("Could not create command definition")

        created_handler = _CommandCreatedHandler(application)
        definition.commandCreated.add(created_handler)
        _handlers.append(created_handler)

        tab = ui.allToolbarTabs.itemById(TAB_ID)
        if tab is None:
            definition.deleteMe()
            _handlers.clear()
            _show_message(ui, "Sheet Metal tab is unavailable.")
            return

        panel = tab.toolbarPanels.add(PANEL_ID, "Bend Marks", "", False)
        if panel is None:
            raise RuntimeError("Could not create Bend Marks panel")
        if panel.controls.addCommand(definition, "", False) is None:
            raise RuntimeError("Could not create Bend Marks command control")
    except Exception:
        _cleanup_ui(ui)
        _handlers.clear()
        _show_message(ui, f"Create Bend Marks failed to start:\n{traceback.format_exc()}")


def stop(context: object) -> None:
    del context
    try:
        application = adsk.core.Application.get()
        _cleanup_ui(cast(Any, application).userInterface)
    finally:
        _handlers.clear()
