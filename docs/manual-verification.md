# Manual Fusion Verification

Use this checklist after installing or reloading `BendMarks`. Record the environment and result
below. Complete every item in one Fusion session; any failed item blocks acceptance.

## Fixture

Prepare a sheet-metal fixture containing:

- One horizontal straight bend.
- One diagonal straight bend.
- One irregular or angled outside edge.
- At least one curved bend, if the installed Fusion version permits one in the fixture.
- One flat-pattern sketch with a horizontal line, a horizontal line drawn in reverse, a vertical
  line drawn from top to bottom, and a diagonal line. Keep the lines separate.
- One unrelated closed profile in that same sketch. Do not add generated-notch metadata to it.

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

### Interactive workflow

- [ ] 11. Open the flat pattern and edit the fixture sketch. Multi-select its horizontal and
  diagonal lines, then run **Create Selected Notches** from the **FLAT PATTERN SOLID > Create**
  panel.
- [ ] 12. Enter distinct valid expressions for width, inset, and overhang, choose **Both**, and
  finish the command. Confirm both selected centerlines become construction geometry, both
  endpoints receive notches, and every notch uses the same three dialog expressions.
- [ ] 13. Use **Undo** once. Confirm the entire **Create Selected Notches** result, including
  parameter and construction-state changes, reverses as one user action. Run it again with the
  same settings before continuing.
- [ ] 14. Select the reversed horizontal line and run **Create Selected Notches** with **Left**.
  Confirm only its lower-X endpoint receives a notch, regardless of line drawing direction.
- [ ] 15. Select the top-to-bottom vertical line and run **Create Selected Notches** with **Right**.
  Confirm only its higher-Y endpoint receives a notch: equal X coordinates use lower Y for Left
  and higher Y for Right.
- [ ] 16. Use **Undo** once and confirm the complete vertical-line command reverses as one user
  action. Run it again with **Right** before continuing.
- [ ] 17. Record the reversed, vertical, and diagonal lines' generated geometry. Select only the
  horizontal line used in step 11, change one shared expression, and rerun **Create Selected
  Notches** with **Both**. Confirm only that line's old notches are replaced. Confirm another
  line's notches remain unchanged and no unselected source line receives geometry.
- [ ] 18. Confirm the sketch is still active, then run **Cut Selected Notches**. Confirm every
  generated notch profile is cut and the unrelated closed profile is ignored.
- [ ] 19. Use **Undo** once. Confirm the entire **Cut Selected Notches** result reverses as one user
  action while generated sketch geometry remains. Run the cut command again before continuing.
- [ ] 20. Rerun **Cut Selected Notches**. Confirm the prior cut is replaced and exactly one
  interactive cut owned by this sketch remains.
- [ ] 21. Use **Undo** once. Confirm cut replacement reverses as one user action and restores the
  previous cut. Redo or rerun the replacement before continuing.
- [ ] 22. In Fusion, save and reopen the design. Edit the same sketch, rerun **Create Selected
  Notches** for one previously processed line, and confirm its geometry is replaced while another
  line's notches remain. Run **Cut Selected Notches** and confirm the reopened sketch's prior cut
  is replaced rather than duplicated.
- [ ] 23. Export the reopened flat pattern as DXF. Confirm the output contains all generated
  physical notch cutouts and does not contain a cutout from the unrelated closed profile.
- [ ] 24. Return to the folded model. Confirm interactive notch geometry and cuts remain isolated
  to the flat pattern.

## Verification Record

- Fusion version: Pending, Fusion desktop unavailable
- Operating system: Pending, Fusion desktop unavailable
- Fixture name: Pending, fixture not created
- Overall result: Pending runtime execution; manual acceptance not claimed
- Failed checklist items and notes: Not run; complete items 1-24 in Fusion
