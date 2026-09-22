import os
import subprocess
import sys
import textwrap
from pathlib import Path


def test_deploy_syncs_only_runtime_files_and_removes_stale_files(tmp_path: Path) -> None:
    destination = tmp_path / "BendMarks"
    destination.mkdir()
    (destination / "stale.py").write_text("stale")

    environment = os.environ | {"FUSION_ADDINS_DIR": str(tmp_path)}
    subprocess.run(["just", "deploy"], check=True, env=environment)

    deployed_files = {
        path.relative_to(destination).as_posix()
        for path in destination.rglob("*")
        if path.is_file()
    }
    assert deployed_files == {
        "BendMarks.manifest",
        "BendMarks.py",
        "__init__.py",
        "fusion_adapter.py",
        "geometry.py",
        "service.py",
    }


def test_deployed_entrypoint_imports_with_fusion_style_package_loading(tmp_path: Path) -> None:
    environment = os.environ | {"FUSION_ADDINS_DIR": str(tmp_path)}
    subprocess.run(["just", "deploy"], check=True, env=environment)
    isolated_directory = tmp_path / "isolated"
    isolated_directory.mkdir()
    script = textwrap.dedent(
        """
        import importlib.util
        import pathlib
        import sys

        addin = pathlib.Path(sys.argv[1])
        package_spec = importlib.util.spec_from_file_location(
            "_fusion_addin",
            addin / "__init__.py",
            submodule_search_locations=[str(addin)],
        )
        package = importlib.util.module_from_spec(package_spec)
        sys.modules[package_spec.name] = package
        package_spec.loader.exec_module(package)

        entry_spec = importlib.util.spec_from_file_location(
            "_fusion_addin.BendMarks",
            addin / "BendMarks.py",
        )
        entry = importlib.util.module_from_spec(entry_spec)
        sys.modules[entry_spec.name] = entry
        entry_spec.loader.exec_module(entry)
        """
    )
    clean_environment = environment | {"PYTHONPATH": ""}

    subprocess.run(
        [sys.executable, "-c", script, str(tmp_path / "BendMarks")],
        cwd=isolated_directory,
        env=clean_environment,
        check=True,
    )
