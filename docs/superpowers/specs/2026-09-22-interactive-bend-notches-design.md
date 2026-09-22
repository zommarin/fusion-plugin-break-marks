# Interactive Bend Notches Design

## Goal

Add an interactive workflow for creating bend notches from selected sketch centerlines in an active sheet-metal flat pattern. Users can choose which centerlines and endpoints receive notch geometry, inspect or edit that geometry, and cut the generated notch profiles with a separate command.

The existing **Create Bend Marks** command remains available and unchanged for automatic processing of every flat-pattern bend.

## User Experience

The Bend Marks panel gains two commands:

- **Create Selected Notches** creates notch rectangles in the sketch containing the selected centerlines.
- **Cut Selected Notches** creates a through-all cut from generated notch profiles in the active sketch.

### Create Selected Notches

Before invoking the command, the user selects one or more sketch lines from one sketch in the active flat pattern. The command dialog contains:

- Width, initialized from `bend_mark_width` or its `1.8 mm` default.
- Inset, initialized from `bend_mark_inset` or its `1 mm` default.
- Overhang, initialized from `bend_mark_overhang` or its `1 mm` default.
- Side: **Both**, **Left**, or **Right**, defaulting to **Both**.

The values update the same named user parameters used by **Create Bend Marks**. All values must be finite, positive lengths.

The command converts selected lines to construction geometry when necessary. It then creates constrained notch rectangles in the same sketch. **Left** means the endpoint with lower sketch X coordinate. If both endpoints have equal X coordinates, the endpoint with lower sketch Y coordinate is left. **Right** means the opposite endpoint. This ordering is independent of each line's creation direction.

Running the command again for an already processed centerline replaces generated rectangles for that centerline and leaves generated rectangles for other centerlines unchanged. The selected side controls the complete replacement: rerunning with **Left** removes prior generated left and right rectangles for that centerline, then creates only the left rectangle.

### Cut Selected Notches

The user activates the sketch containing generated notches and invokes **Cut Selected Notches**. The command automatically discovers closed profiles bounded by plugin-tagged notch edges. It creates one through-all cut from all discovered notch profiles in that sketch.

Running the command again replaces the prior plugin-owned interactive cut associated with that sketch. Cuts created by the existing automatic workflow and untagged user features are not changed.

## Architecture

The existing automatic command, service path, and backend behavior remain isolated. The add-in entrypoint registers all three commands in the existing Bend Marks panel and retains separate command-created, execute, and destroy handlers for each command.

New interactive orchestration responsibilities are separated from Fusion API access:

- Pure geometry orders endpoints and selects left, right, or both rectangles.
- An interactive service validates workflow state and coordinates replacement.
- The Fusion adapter reads preselection, manages command inputs and shared parameters, creates sketch geometry, tags entities, discovers profiles, and builds cuts.

The command captures preselected entities when the command opens. Selection must contain at least one `SketchLine`, every selected entity must be a sketch line, and all selected lines must belong to one sketch in the active flat-pattern product. Unsupported selection fails before mutation.

## Ownership And Identity

Entity attributes provide persistent ownership metadata that survives save and reopen:

- Each selected source centerline receives a stable generated source ID if it does not already have one.
- Every generated rectangle edge is tagged with its source ID and endpoint side.
- The source sketch receives a stable sketch ID.
- Each interactive cut is tagged with its source sketch ID.

Tags, not names or geometric similarity, establish ownership. Replacement deletes only generated rectangle edges whose source IDs match selected centerlines. Cut replacement affects only the tagged interactive cut whose source sketch ID matches the active sketch.

If duplicate source IDs, multiple cuts for one sketch ID, or malformed ownership metadata are found, the command fails rather than guessing which entities to modify.

## Geometry And Constraints

The interactive workflow reuses the existing endpoint rectangle calculation. Width is perpendicular to the selected centerline. Inset extends from the endpoint toward the opposite endpoint, and overhang extends outward from the endpoint.

Each generated rectangle uses the existing named parameter expressions for width, inset, and overhang. Constraints keep long edges parallel to the source centerline, end edges perpendicular, width centered on the source centerline, and inner and outer depths dimensioned. Selected centerlines become construction geometry before profiles are evaluated so they cannot split notch rectangles.

Zero-length selected lines are invalid. Processing multiple selected lines occurs in one command transaction.

## Profile Discovery And Cut Replacement

The cut command examines profiles in the active sketch and accepts only closed notch profiles whose boundary sketch entities all carry valid generated-notch ownership tags. It ignores unrelated closed profiles, construction geometry, and partially edited or incomplete generated geometry. If no valid generated notch profile remains, the command reports an error and creates no cut.

Before creating a replacement, the command suppresses the existing interactive cut for that sketch so removed material is restored. It creates the new through-all cut from all valid generated profiles, tags the cut with the sketch ID, then deletes the prior cut. Failure before successful creation restores suppression explicitly. Failure after creation marks command execution failed so Fusion aborts the transaction and restores the complete prior state.

## Transaction And Error Handling

Both commands use Fusion command transactions. Expected failures produce concise actionable messages and set `executeFailed` so no partial state commits.

**Create Selected Notches** rejects:

- A product outside an active sheet-metal flat pattern.
- No preselected entities.
- Any selected entity that is not a sketch line.
- Lines from multiple sketches or from a sketch outside the active flat pattern.
- Invalid shared parameter expressions or non-positive values.
- Degenerate lines or malformed ownership metadata.
- Constraint, dimension, attribute, or geometry creation failures.

Rollback covers shared parameter updates, source-line construction conversion, ownership tags, deletion of prior generated edges, and newly generated geometry.

**Cut Selected Notches** rejects:

- No active sketch in the active flat pattern.
- No valid plugin-generated notch profiles.
- Ambiguous prior owned cuts.
- Profile collection, extent, tagging, deletion, or feature creation failures.

Untagged user geometry and features are never deleted.

## Testing

Automated pure geometry tests cover:

- Horizontal, vertical, diagonal, and reversed centerlines.
- Stable left/right endpoint ordering, including the vertical Y tie-break.
- Both, left-only, and right-only rectangle selection.
- Degenerate centerlines.

Interactive service and Fusion adapter tests cover:

- Empty, invalid, and mixed-sketch selection rejection before mutation.
- Shared parameter creation, display, validation, and updates.
- Conversion of selected lines to construction geometry.
- Stable source and sketch identity attributes.
- Per-centerline replacement that preserves other generated notches.
- Side changes removing obsolete generated rectangles.
- Tagged profile discovery excluding unrelated or incomplete profiles.
- Per-sketch cut creation and replacement without affecting automatic cuts.
- Recovery from geometry, tagging, cut creation, and cleanup failures.
- Registration, handler lifetime, startup rollback, and shutdown cleanup for all commands.
- Regression coverage for the existing automatic **Create Bend Marks** workflow.

Manual Fusion verification covers multi-selection, command dialog defaults and expressions, all side choices, vertical lines, conversion to construction geometry, repeated notch creation, active-sketch cut discovery, repeated cut replacement, save and reopen persistence, one-step undo, DXF output, and isolation from the folded model and automatic workflow.

## Documentation

The README describes both workflows, command names, side ordering, shared parameters, same-sketch selection requirement, active-sketch cut behavior, and rerun semantics. The manual verification checklist gains interactive command scenarios.
