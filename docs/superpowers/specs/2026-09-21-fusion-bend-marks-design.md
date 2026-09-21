# Fusion Bend Marks Add-In Design

## Goal

Create rectangular alignment cutouts at both ends of every straight bend centerline in an active Autodesk Fusion sheet-metal flat pattern. The cutouts provide physical marks for aligning the sheet in a bending machine, independent of bend direction.

## Scope

The first version processes all straight bends in the active flat pattern. It does not create or activate a flat pattern and does not support selecting individual bend lines. Generated cuts affect only the flat-pattern representation.

Each bend receives two rectangular cutouts, one at each centerline endpoint. Three named user parameters control their shape:

- `bend_mark_width`, default `1.8 mm`: rectangle width perpendicular to the bend centerline.
- `bend_mark_inset`, default `1 mm`: distance from the bend endpoint toward the opposite endpoint.
- `bend_mark_overhang`, default `1 mm`: distance from the bend endpoint outward along the centerline.

All values must be positive lengths. Existing parameters with these names are reused; missing parameters are created.

## User Experience

The add-in registers a **Create Bend Marks** command in Fusion's Sheet Metal workspace. Running the command while a flat pattern is active rebuilds all bend marks using the current named parameter values. Running it outside an active `FlatPatternProduct` shows an actionable error and leaves the model unchanged.

After success, the command reports bends processed, marks created, and unsupported bends skipped. A normal successful bend produces two marks.

## Fusion Architecture

The add-in consists of these responsibilities:

- Fusion entrypoint and manifest: register and remove the command, retain event handlers for their required lifetime, and expose installable add-in metadata.
- Command module: validate context and parameters, coordinate replacement of existing marks, and report results.
- Geometry module: perform unit-independent vector calculations for endpoint-local rectangle geometry.
- Fusion adapter: read bend lines, create projected and constrained sketch geometry, manage parameters and ownership attributes, and create the cut feature.

The Fusion adapter reads bend centerlines from `FlatPattern.bendLinesBody` and uses `FlatPattern.topFace` as the sketch plane. This avoids inferring bends from the flat body's ordinary edges.

The published Python `adsk` development stubs currently omit newer flat-pattern classes that exist in Fusion's runtime API. Dynamic access is isolated inside the adapter behind narrow local protocols or boundary casts. Type checking remains strict elsewhere.

## Geometry

Each straight bend edge is projected into the generated sketch as construction geometry. For each endpoint, the vector toward the opposite endpoint defines the inward direction. Its negative defines the outward direction. A perpendicular sketch-plane vector defines rectangle width.

The rectangle spans from `bend_mark_overhang` outward to `bend_mark_inset` inward and is centered on the bend centerline. Its constraints preserve this relationship:

- Long sides are parallel to the projected bend line.
- End edges are perpendicular to the projected bend line.
- Width is dimensioned with `bend_mark_width`.
- Inward depth is dimensioned with `bend_mark_inset`.
- Outward extension is dimensioned with `bend_mark_overhang`.
- Rectangle width center remains coincident with the projected bend centerline.

Placement depends on the bend endpoint rather than the sheet boundary. The rectangle therefore still reaches beyond the bend endpoint when the outside sheet edge is angled, curved, or locally irregular.

Zero-length bend edges are invalid. Curved bend centerlines are skipped with a warning in the first version; only straight bend centerlines generate marks.

## Cut Feature

All valid endpoint rectangles form closed profiles in one sketch named `Bend Marks`. One cut extrude consumes those profiles using a through-all extent directed into the flat body. The sketch and cut are created in the active flat-pattern product, so they alter the manufacturing flat pattern without changing the folded representation.

## Ownership And Reruns

Generated sketch and cut entities receive add-in-specific Fusion attributes. Names remain human-readable but are not used to establish ownership.

Before mutation, the command validates active context, parameter values, bend availability, and supported geometry. On rerun it temporarily suppresses the previously tagged cut so the removed material is restored, builds the replacement sketch and cut, then deletes the old cut and sketch only after the replacement succeeds. It never deletes untagged user geometry, even if names match.

Execution occurs within the command's single undoable transaction. If replacement fails, the adapter deletes any partially created entities, restores the prior cut's suppression state, and removes user parameters created by the failed attempt. This explicit cleanup preserves the previous result without relying on exception-driven Fusion rollback.

## Error Handling

The command leaves the design unchanged and reports a clear message when:

- No flat pattern is actively open.
- A required named parameter exists but is not a positive length.
- No bend lines exist.
- No supported straight bend lines remain after filtering.
- Sketch profiles or the cut feature cannot be created.

If straight and curved bends coexist, straight bends are processed and curved bends are counted as skipped. Unexpected Fusion API failures include operation context in the displayed error and are not silently ignored.

## Testing

Automated tests cover pure geometry independently of Fusion:

- Horizontal, vertical, diagonal, and reversed bend directions.
- Both endpoints of each line.
- Width centering and asymmetric inset/overhang distances.
- Degenerate zero-length input.

Command orchestration tests use test doubles to cover context rejection, parameter creation and reuse, ownership-based replacement, partial bend skipping, and failure propagation. The existing `adsk` import smoke test remains.

Manual Fusion verification covers:

- Active-flat-pattern guard.
- Two marks per straight bend.
- Angled and irregular sheet boundaries.
- Named parameter edits updating generated geometry.
- Reruns replacing rather than duplicating marks.
- Curved-bend warning behavior.
- Single-step undo and restoration of prior marks after failure.
- Cutouts appearing in flat-pattern and DXF output but not the folded representation.

The README documents installation, add-in reload, usage, parameter defaults, and first-version limitations.
