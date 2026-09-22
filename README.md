# Fusion Bend Marks

Autodesk Fusion add-in that creates physical alignment cutouts at the endpoints of sheet-metal
bends. The cutouts appear in the flat pattern and its DXF export without changing the folded model.

## Requirements

- Autodesk Fusion October 2022 or newer on macOS or Windows.
- A sheet-metal design with an existing flat pattern and at least one straight bend.

## Installation

Copy or symlink this repository's `BendMarks` directory into Fusion's `API/AddIns` directory:

- macOS: `~/Library/Application Support/Autodesk/Autodesk Fusion 360/API/AddIns/`
- Windows: `%APPDATA%\Autodesk\Autodesk Fusion 360\API\AddIns\`

Alternatively, leave `BendMarks` anywhere and link it in Fusion. Open **Utilities > Add-Ins >
Scripts and Add-Ins** (shown as **Utilities > Scripts and Add-Ins** in some Fusion versions), use
the add/link control, and select the `BendMarks` directory. Current Fusion versions label this
choice **Script or add-in from device**.

After copying or linking, open **Scripts and Add-Ins**, select `BendMarks`, and start it. Stop and
start it again after updating the add-in files. You may also enable startup loading in that dialog.

## Usage

All three commands appear in Fusion's existing **FLAT PATTERN SOLID > Create** panel.

### Automatic bend marks

1. Open an existing sheet-metal design and activate its flat pattern.
2. On the **FLAT PATTERN SOLID** tab, open the **Create** panel and run **Create Bend Marks**.
3. Enter the mark width, inset, and overhang in the command dialog, then select **OK**. Each field
   accepts Fusion length expressions, including references to other user parameters.
4. Review the result message. Each supported straight bend produces two marks; unsupported curved
   bends are skipped and counted.

The command requires an active flat pattern. It creates one tagged `Bend Marks` sketch and one
tagged `Bend Marks Cut` through-all cut. Running **Create Bend Marks** again builds replacement
geometry first, then removes the previous tagged sketch and cut. Any failure, including failure to
remove previous owned entities, aborts the command transaction so Fusion restores the pre-command
marks. The add-in never treats replacement geometry as committed after cleanup fails.

### Interactive selected notches

Use this workflow when a sketch's straight lines, rather than every detected bend, should control
the notches:

1. Open the flat pattern, edit one sketch, and select one or more straight centerlines from the
   same sketch.
2. Run **Create Selected Notches** from the **Create** panel. Enter the shared width, inset, and
   overhang parameter expressions, then choose **Both**, **Left**, or **Right**.
3. Fusion converts each selected centerline to construction geometry and creates constrained notch
   rectangles at the requested endpoints. **Left** means the endpoint with lower sketch X, using
   lower sketch Y when both X coordinates match; **Right** means the opposite endpoint. Endpoint
   choice therefore does not depend on the line's drawing direction.
4. Inspect or edit the generated geometry as needed. Keep the sketch active, then run **Cut
   Selected Notches** from the **Create** panel to make through-all cuts from generated profiles.

Running **Create Selected Notches** again replaces generated geometry only for the selected
centerlines; generated notches belonging to other lines in the sketch remain. Running **Cut
Selected Notches** again replaces the prior interactive cut owned by the active sketch, while
unrelated closed profiles are ignored. Ownership metadata is stored on the sketch, source lines,
generated geometry, and cut, so replacement behavior persists after saving and reopening the
design.

### Parameters

The command dialog shows these values, prefilled from existing user-parameter expressions when
available. The first run creates any missing parameters:

| Parameter | Default | Controls |
| --- | --- | --- |
| `bend_mark_width` | `1.8 mm` | Cutout width perpendicular to the bend |
| `bend_mark_inset` | `1 mm` | Distance extending inward from the bend endpoint |
| `bend_mark_overhang` | `1 mm` | Distance extending beyond the bend endpoint |

All three expressions must resolve to finite, positive lengths. Selecting **OK** creates or updates
the corresponding user parameters; selecting **Cancel** changes nothing. You can also edit them in
Fusion's Parameters dialog and compute the design; constrained mark geometry updates without
rerunning the command.

## Limitations

- Only straight bend lines are processed. Curved bends are skipped.
- The flat pattern must already exist and be active when the command runs.
- Each **Create Selected Notches** invocation accepts straight `SketchLine` centerlines from one
  source sketch; selections spanning sketches are rejected.
- **Cut Selected Notches** requires the generated-notch sketch to be the active sketch.
- Marks and cutouts exist only in the flat pattern, not in the folded model.

See [`docs/manual-verification.md`](docs/manual-verification.md) for the Fusion acceptance checklist.

## Development

Allow the direnv environment once, then install the Python dependencies:

```sh
direnv allow
just dev
```

Run all checks with `just check`. Run `just` to list the available actions.

Fusion supplies the `adsk` module at runtime. The development dependency provides an offline
copy for imports, editor completion, type checking, and tests; it must not be bundled with the
add-in.
