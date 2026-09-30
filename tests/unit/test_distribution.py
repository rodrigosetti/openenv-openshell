"""Release checks fail closed before any upload."""

from email.message import EmailMessage

import pytest

from scripts.check_distribution import check_metadata, check_version


@pytest.mark.parametrize("tag", ["v0.0.1", "0.0.0", "v0.0.0; echo unsafe"])
def test_tag_must_match_source(tag: str) -> None:
    """An unrelated or shell-shaped tag cannot select an artifact."""
    with pytest.raises(ValueError, match="Tag"):
        check_version("0.0.0", tag, "testpypi")


@pytest.mark.parametrize("version", ["0.0.0", "0.1.0rc1", "0.1.0.dev1", "0.1.0+local"])
def test_production_rejects_placeholder_and_unstable_versions(version: str) -> None:
    """A development build cannot become the first production release."""
    with pytest.raises(ValueError, match=r"Production|canonical"):
        check_version(version, f"v{version}", "pypi")


def test_stable_release_and_rehearsal_versions() -> None:
    """Rehearsals can exercise packaging before the usable release exists."""
    check_version("0.0.0", "v0.0.0", "testpypi")
    check_version("0.1.0", "v0.1.0", "pypi")


def test_index_metadata_rejects_direct_reference() -> None:
    """Reintroducing an SDK URL in Requires-Dist blocks release validation."""
    metadata = EmailMessage()
    metadata["Name"] = "openenv-openshell"
    metadata["Version"] = "0.0.0"
    metadata["Requires-Python"] = ">=3.11"
    metadata["License-Expression"] = "Apache-2.0"
    metadata["Project-URL"] = (
        "Repository, https://github.com/rodrigosetti/openenv-openshell"
    )
    for value in ("httpx", "openenv==0.6.0", "pyyaml"):
        metadata["Requires-Dist"] = value
    check_metadata(metadata.as_bytes(), "0.0.0")
    metadata["Requires-Dist"] = "openshell @ https://example.com/sdk.whl"
    with pytest.raises(ValueError, match="direct URL"):
        check_metadata(metadata.as_bytes(), "0.0.0")
