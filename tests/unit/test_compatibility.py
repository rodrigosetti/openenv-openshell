"""Dependency bounds must match the reviewed client/SDK compatibility matrix."""

import os
import tomllib
from importlib.metadata import version
from pathlib import Path
from typing import TypedDict, cast

import pytest

from openenv_openshell._adapter import SDK_VERSION

ROOT = Path(__file__).parents[2]
SDK_REQUIREMENT = (
    "openshell @ https://github.com/NVIDIA/OpenShell/releases/download/v0.1.2/"
    "openshell-0.1.2-py3-none-any.whl#sha256="
    "8c409da4f176d42418d92366fe201f47cceef2c0fa432bfbce2bf938649d59cf"
)


class Project(TypedDict):
    """The dependency metadata under review."""

    dependencies: list[str]


@pytest.mark.parametrize(("openenv_version", "openshell_version"), [("0.6.0", "0.1.2")])
def test_supported_pair(openenv_version: str, openshell_version: str) -> None:
    """An unreviewed range, wheel substitution, or CI pair fails offline."""
    project = cast(
        "Project", tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    )
    requirements = project["dependencies"]
    assert [item for item in requirements if item.startswith("openenv")] == [
        f"openenv=={openenv_version}"
    ]
    assert not any(item.startswith("openshell") for item in requirements)
    groups = cast(
        "dict[str, list[str]]",
        tomllib.loads((ROOT / "pyproject.toml").read_text())["dependency-groups"],
    )
    assert [item for item in groups["dev"] if item.startswith("openshell")] == [
        SDK_REQUIREMENT
    ]
    prerequisite = [
        line
        for line in (ROOT / "requirements-openshell.txt").read_text().splitlines()
        if line and not line.startswith("#")
    ]
    assert prerequisite == [SDK_REQUIREMENT]
    assert version("openenv") == openenv_version
    assert version("openshell") == openshell_version == SDK_VERSION
    assert os.environ.get("COMPAT_OPENENV", openenv_version) == openenv_version
    assert os.environ.get("COMPAT_OPENSHELL", openshell_version) == openshell_version
