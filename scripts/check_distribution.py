"""Validate release identity and index-safe wheel/sdist contents."""

from __future__ import annotations

import argparse
import tarfile
import tomllib
from email.parser import BytesParser
from pathlib import Path
from zipfile import ZipFile

from packaging.requirements import Requirement
from packaging.version import Version

_ARTIFACT_COUNT = 2


def check_metadata(raw: bytes, expected_version: str) -> None:
    """Reject wrong identity, incomplete metadata, and URL dependencies."""
    metadata = BytesParser().parsebytes(raw)
    if metadata["Name"] != "openenv-openshell":
        msg = "Unexpected distribution name"
        raise ValueError(msg)
    if metadata["Version"] != expected_version:
        msg = "Artifact version differs from source"
        raise ValueError(msg)
    for field in ("Requires-Python", "License-Expression", "Project-URL"):
        if not metadata[field]:
            msg = f"Missing {field}"
            raise ValueError(msg)
    requirements = [
        Requirement(value) for value in metadata.get_all("Requires-Dist", [])
    ]
    if any(item.url for item in requirements):
        msg = "Package indexes reject direct URL dependencies"
        raise ValueError(msg)
    if {item.name for item in requirements} != {"httpx", "openenv", "pyyaml"}:
        msg = "Unexpected runtime dependencies"
        raise ValueError(msg)


def check_version(version: str, tag: str | None, index: str) -> None:
    """Require exact canonical tag/version agreement and usable production versions."""
    parsed = Version(version)
    if str(parsed) != version or parsed.local:
        msg = "Version must be canonical and have no local suffix"
        raise ValueError(msg)
    if tag is not None and tag != f"v{version}":
        msg = "Tag must equal v plus the source version"
        raise ValueError(msg)
    if index == "pypi" and (
        parsed.release < (0, 1) or parsed.is_prerelease or parsed.is_devrelease
    ):
        msg = "Production requires a stable version of at least 0.1.0"
        raise ValueError(msg)


def check_artifacts(directory: Path, version: str) -> None:
    """Require one wheel and sdist, package typing, metadata, README and license."""
    wheels = list(directory.glob("*.whl"))
    sdists = list(directory.glob("*.tar.gz"))
    if (
        len(wheels) != 1
        or len(sdists) != 1
        or len([path for path in directory.iterdir() if path.name != ".gitignore"])
        != _ARTIFACT_COUNT
    ):
        msg = "Expected exactly one wheel and one sdist in a clean directory"
        raise ValueError(msg)
    with ZipFile(wheels[0]) as wheel:
        names = wheel.namelist()
        metadata = [name for name in names if name.endswith(".dist-info/METADATA")]
        if len(metadata) != 1:
            msg = "Expected one wheel metadata file"
            raise ValueError(msg)
        check_metadata(wheel.read(metadata[0]), version)
        if "openenv_openshell/py.typed" not in names or not any(
            name.endswith("/LICENSE") for name in names
        ):
            msg = "Wheel lacks typing marker or license"
            raise ValueError(msg)
    with tarfile.open(sdists[0]) as sdist:
        names = sdist.getnames()
        roots = {name.split("/")[0] for name in names}
        if len(roots) != 1:
            msg = "Expected one sdist root"
            raise ValueError(msg)
        root = roots.pop()
        for required in (
            "PKG-INFO",
            "README.md",
            "LICENSE",
            "pyproject.toml",
            "src/openenv_openshell/py.typed",
            "src/openenv_openshell/provider.py",
        ):
            if f"{root}/{required}" not in names:
                msg = f"Sdist lacks {required}"
                raise ValueError(msg)
        member = sdist.extractfile(f"{root}/PKG-INFO")
        if member is None:
            msg = "Unreadable sdist metadata"
            raise ValueError(msg)
        with member:
            check_metadata(member.read(), version)


def main() -> None:
    """Check source identity and both release artifacts."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, default=Path("dist"))
    parser.add_argument("--tag")
    parser.add_argument("--index", choices=("testpypi", "pypi"), default="testpypi")
    args = parser.parse_args()
    source = tomllib.loads(Path("pyproject.toml").read_text())
    version = source["project"]["version"]
    check_version(version, args.tag, args.index)
    check_artifacts(args.dist, version)


if __name__ == "__main__":
    main()
