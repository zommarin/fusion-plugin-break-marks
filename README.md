# fusion-plugin-break-marks

Autodesk Fusion Plugin to create break marks for bending sheetgoods

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
