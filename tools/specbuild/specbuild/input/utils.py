"""Shared utilities for the specbuild.input package."""

from __future__ import annotations

import re

#: Clean HTML id: lowercase, hyphens, no leading/trailing hyphens.
_ID_CLEAN_RE = re.compile(r"[^a-z0-9]+")

#: Word XML namespace tag prefix (for element lookups like f"{W_TAG}tcPr").
W_TAG = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def make_html_id(text: str) -> str:
    """Generate a clean HTML id from arbitrary text."""
    return _ID_CLEAN_RE.sub("-", text.lower()).strip("-")


def sanitize_filename(text: str) -> str:
    """Convert heading text to a filesystem-safe filename segment."""
    text = re.sub(r"^[\d\.]+\s*", "", text)
    text = re.sub(r"^[A-Z]\.\d+[\.\d]*\s*", "", text)
    name = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return name[:60] if name else "section"
