"""Validate the explicit human approval variables for a release destination."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass(frozen=True, slots=True)
class Approval:
    """Values supplied from a protected GitHub environment."""

    tag: str
    commit: str
    evidence_url: str


def _reviewable_url(value: str) -> bool:
    """Accept only an HTTPS link with a host as reviewable release evidence."""
    parsed = urlparse(value)
    return parsed.scheme == "https" and bool(parsed.netloc)


def validate_approval(*, index: str, tag: str, commit: str, approval: Approval) -> None:
    """Fail closed unless the selected production path has exact approval evidence."""
    if index == "testpypi":
        return
    if index not in {"restricted-alpha", "pypi"}:
        msg = "Unknown release index"
        raise ValueError(msg)
    if not approval.tag or tag != approval.tag:
        msg = "Release tag does not match the approved tag"
        raise ValueError(msg)
    if not approval.commit or commit != approval.commit:
        msg = "Release commit does not match the approved commit"
        raise ValueError(msg)
    if not _reviewable_url(approval.evidence_url):
        msg = "Release requires a reviewable HTTPS evidence URL"
        raise ValueError(msg)


def main() -> None:
    """Read GitHub Action inputs and exit nonzero for incomplete approval."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--approved-tag", default="")
    parser.add_argument("--approved-commit", default="")
    parser.add_argument("--evidence-url", default="")
    args = parser.parse_args()
    validate_approval(
        index=args.index,
        tag=args.tag,
        commit=args.commit,
        approval=Approval(
            tag=args.approved_tag,
            commit=args.approved_commit,
            evidence_url=args.evidence_url,
        ),
    )


if __name__ == "__main__":
    main()
