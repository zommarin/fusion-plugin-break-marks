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

1. Open an existing sheet-metal design and activate its flat pattern.
2. On the Sheet Metal tab, open the Bend Marks panel and run **Create Bend Marks**.
3. Review the result message. Each supported straight bend produces two marks; unsupported curved
   bends are skipped and counted.

The command requires an active flat pattern. It creates one tagged `Bend Marks` sketch and one
tagged `Bend Marks Cut` through-all cut. Running **Create Bend Marks** again builds replacement
geometry first, then removes the previous tagged sketch and cut. A failed rerun preserves the
previous marks.

### Parameters

The first run creates these user parameters if they do not exist:

| Parameter | Default | Controls |
| --- | --- | --- |
| `bend_mark_width` | `1.8 mm` | Cutout width perpendicular to the bend |
| `bend_mark_inset` | `1 mm` | Distance extending inward from the bend endpoint |
| `bend_mark_overhang` | `1 mm` | Distance extending beyond the bend endpoint |

All three parameters must be finite, positive lengths. Existing valid parameters are reused rather
than reset. Edit them in Fusion's Parameters dialog and compute the design; constrained mark
geometry updates without rerunning the command.

## Limitations

- Only straight bend lines are processed. Curved bends are skipped.
- The flat pattern must already exist and be active when the command runs.
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
