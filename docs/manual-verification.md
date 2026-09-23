# Manual Fusion Verification

Use this checklist after installing or reloading `BendMarks`. Record the environment and result
below. Complete every item in one Fusion session; any failed item blocks acceptance.

## Fixture

Prepare a sheet-metal fixture containing:

- One horizontal straight bend.
- One diagonal straight bend.
- One irregular or angled outside edge.
- At least one curved bend, if the installed Fusion version permits one in the fixture.

## Checklist

- [ ] 1. Close the flat pattern and inspect the folded model. Confirm it has no generated bend
  marks or cutouts.
- [ ] 2. Open the existing flat pattern. Confirm it is the active flat pattern, then run **Create
  Bend Marks** from the **FLAT PATTERN SOLID** tab's **Create** panel. Confirm a dialog shows width
  `1.8 mm`, inset `1 mm`, and overhang `1 mm`, then select **OK**.
- [ ] 3. Confirm two marks exist for each straight bend. If the fixture has curved bends, confirm
  they produce no marks and the completion message reports the curved skip count.
- [ ] 4. Measure the generated marks. Confirm width is `1.8 mm`, inset is `1 mm`, and overhang is
  `1 mm`.
- [ ] 5. Create a positive length user parameter and rerun **Create Bend Marks**. Enter an
  expression referencing it for width and formulas for inset and overhang. Confirm the dialog
  accepts them and generated marks use their resolved values.
- [ ] 6. **Rerun** **Create Bend Marks**. Confirm exactly one tagged `Bend Marks` sketch and one
  tagged `Bend Marks Cut` remain, with no duplicate marks. Confirm the dialog retains the current
  parameter expressions. Cancel once and confirm marks and parameters remain unchanged.
- [ ] 7. Use **Undo** once. Confirm the complete rerun reverses as one user action and restores the
  pre-rerun marks.
- [ ] 8. Temporarily set one bend-mark parameter to zero and run the command. Confirm the command
  fails, the error identifies that parameter and requires a positive length, and all prior marks
  remain. Restore a positive value afterward.
- [ ] 9. Export the flat pattern as DXF. Open or inspect the DXF and confirm physical cutout
  outlines exist at both endpoints of each straight bend.
- [ ] 10. Return to the folded model. Confirm all generated cutouts remain absent there.

## Verification Record

- Fusion version: Pending, Fusion desktop unavailable
- Operating system: Pending
- Fixture name: Pending
- Overall result: Pending runtime execution
- Failed checklist items and notes: Not run
