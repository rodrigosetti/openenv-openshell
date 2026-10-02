"""Render the user journey from the README without maintaining a second copy."""

# Loaded by MkDocs as a standalone hook, not an importable package.
# ruff: noqa: INP001

import re
from pathlib import Path

from mkdocs.config.defaults import MkDocsConfig
from mkdocs.structure.files import Files
from mkdocs.structure.pages import Page

_ROOT = Path(__file__).resolve().parents[2]
_SOURCE = "https://github.com/rodrigosetti/openenv-openshell/blob/main/"
_SECTIONS = ("Requirements", "Install", "Quickstart", "Known limitations")


def _site_link(match: re.Match[str]) -> str:
    target = match.group(1)
    if target.startswith("docs/"):
        return f"]({target.removeprefix('docs/')})"
    if target.startswith(("https://", "http://", "#")):
        return match.group(0)
    return f"]({_SOURCE}{target})"


def on_page_markdown(
    markdown: str,
    page: Page,
    config: MkDocsConfig,  # noqa: ARG001 — MkDocs hook signature.
    files: Files,  # noqa: ARG001 — MkDocs hook signature.
) -> str:
    """Insert README sections and resolve their links relative to the manual."""
    if page.file.src_uri != "getting-started.md":
        return markdown
    readme = (_ROOT / "README.md").read_text(encoding="utf-8")
    sections: list[str] = []
    for title in _SECTIONS:
        match = re.search(
            rf"^## {re.escape(title)}\n.*?(?=^## |\Z)",
            readme,
            re.MULTILINE | re.DOTALL,
        )
        if match is None:
            msg = f"Missing README user guide section: {title}"
            raise ValueError(msg)
        sections.append(re.sub(r"\]\(([^)]+)\)", _site_link, match.group(0)))
    return markdown.replace("<!-- README_USER_GUIDE -->", "\n".join(sections))
