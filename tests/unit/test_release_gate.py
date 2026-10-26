"""Release destinations require distinct, reviewable approval evidence."""

from pathlib import Path

import pytest

from scripts.release_gate import Approval, validate_approval

_ROOT = Path(__file__).parents[2]


def test_testpypi_needs_no_production_approval() -> None:
    """The rehearsal route remains independently usable."""
    validate_approval(
        index="testpypi", tag="v0.1.0", commit="a" * 40, approval=Approval("", "", "")
    )


@pytest.mark.parametrize("index", ["restricted-alpha", "pypi"])
def test_production_routes_require_exact_tag_commit_and_evidence(index: str) -> None:
    """Neither path can upload from an unapproved revision."""
    approval = Approval("v0.1.0", "a" * 40, "https://example.test/evidence")
    validate_approval(index=index, tag="v0.1.0", commit="a" * 40, approval=approval)
    with pytest.raises(ValueError, match="tag"):
        validate_approval(index=index, tag="v0.1.1", commit="a" * 40, approval=approval)
    with pytest.raises(ValueError, match="commit"):
        validate_approval(index=index, tag="v0.1.0", commit="b" * 40, approval=approval)
    with pytest.raises(ValueError, match="HTTPS"):
        validate_approval(
            index=index,
            tag="v0.1.0",
            commit="a" * 40,
            approval=Approval("v0.1.0", "a" * 40, "not-a-link"),
        )


def test_unknown_destination_fails_closed() -> None:
    """A workflow input cannot create an unreviewed upload route."""
    with pytest.raises(ValueError, match="Unknown"):
        validate_approval(
            index="other",
            tag="v0.1.0",
            commit="a" * 40,
            approval=Approval("v0.1.0", "a" * 40, "https://example.test/evidence"),
        )


def test_workflow_keeps_restricted_alpha_separate_from_m3_production() -> None:
    """The dispatch route wires the dedicated approval values to real PyPI only."""
    workflow = (_ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    for required in (
        "options: [testpypi, restricted-alpha, pypi]",
        "RESTRICTED_ALPHA_RELEASE_TAG",
        "RESTRICTED_ALPHA_RELEASE_COMMIT",
        "RESTRICTED_ALPHA_EVIDENCE_URL",
        '--approved-tag "$RESTRICTED_ALPHA_TAG"',
        "inputs.index == 'pypi' || inputs.index == 'restricted-alpha'",
    ):
        assert required in workflow
