"""Per-clause note and example numbering for HTML output.

Numbers ``<div class="note">``, ``<p class="note">``, ``<div class="example">``,
and ``<p class="example">`` elements sequentially within each top-level section,
resetting the counter at each section boundary (ISO rules).

The admonitions module (``specbuild/enhancements/admonitions.py``) adds a static
``<span class="admonition-label">NOTE</span>`` — this module upgrades those labels
to ``NOTE 1``, ``NOTE 2``, …  (and likewise for examples) without touching elements
that already carry a numeric suffix.

Authoring example (bikeshed source)::

    <div class="note">
      <p>A single note in this clause — will become "NOTE 1".</p>
    </div>

    <div class="example">
      <p>An example — will become "EXAMPLE 1".</p>
    </div>

After processing the admonition-label spans will read ``NOTE 1`` and
``EXAMPLE 1`` respectively.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bs4 import BeautifulSoup, Tag

from specbuild.utils import inject_css

# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------

_NOTE_CSS = """\
/* Note and example numbering */
.note-label, .example-label { font-weight: bold; }
"""

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_NOTE_CLASSES = {"note"}
_EXAMPLE_CLASSES = {"example"}

# Regex that detects an existing numeric suffix (e.g. "NOTE 1", "EXAMPLE 2")
_ALREADY_NUMBERED_RE = re.compile(r"\d")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _has_number(label_text: str) -> bool:
    """Return True if the label text already contains a digit."""
    return bool(_ALREADY_NUMBERED_RE.search(label_text))


def _find_label_span(element: Tag) -> Tag | None:
    """Return the admonition-label span inside *element*, if present."""
    return element.find("span", class_="admonition-label")


def _set_label(soup: BeautifulSoup, element: Tag, text: str) -> None:
    """Set (or create) the admonition-label span text in *element*.

    If a ``<span class="admonition-label">`` already exists its text is
    replaced.  Otherwise a new span is prepended to the first ``<p>`` child
    (or to the element itself if it is a ``<p>`` or has no ``<p>`` child).
    """
    span = _find_label_span(element)
    if span is not None:
        span.string = text
        return

    # Create a new label span.
    span = soup.new_tag("span", **{"class": "admonition-label"})
    span.string = text

    if element.name == "p":
        element.insert(0, span)
    else:
        first_p = element.find("p")
        if first_p is not None:
            first_p.insert(0, span)
        else:
            element.insert(0, span)


def _get_top_level_sections(soup: BeautifulSoup) -> list[Tag]:
    """Collect all top-level section containers for counter-reset boundaries.

    A *top-level section* is any ``<section>`` that is a direct child of
    ``<body>`` or ``<main>``, or — if neither is present — any ``<section>``
    with no ``<section>`` ancestor.  When no ``<section>`` tags exist at all
    the entire document is treated as a single boundary.
    """
    body = soup.find("body") or soup.find("main")

    if body is not None:
        # Prefer direct-child <section> elements of <body>/<main>.
        direct_sections = [c for c in body.children if getattr(c, "name", None) == "section"]
        if direct_sections:
            return direct_sections
        # Fallback: treat the whole body as one boundary.
        return [body]

    # No <body>: use top-most <section> elements (no <section> ancestor).
    all_sections = soup.find_all("section")
    top = [s for s in all_sections if s.find_parent("section") is None]
    if top:
        return top

    # Last resort: treat the whole document as one boundary.
    return [soup]


def _process_admonitions_in_section(
    soup: BeautifulSoup,
    section: Tag,
    classes: set[str],
    prefix: str,
) -> int:
    """Number all matching admonition elements within *section*.

    Finds ``<div>`` and ``<p>`` elements whose class list intersects *classes*,
    numbers them sequentially (1, 2, …), and updates their admonition-label
    span.  Elements that already have a numeric label are skipped.

    Args:
        soup: Document root (used for tag creation).
        section: Container whose descendants are scanned.
        classes: Set of CSS class names that identify this admonition type
            (e.g. ``{"note"}`` or ``{"example"}``).
        prefix: Label prefix text (e.g. ``"NOTE"`` or ``"EXAMPLE"``).

    Returns:
        Number of labels updated or added.
    """
    count = 0
    serial = 0

    for element in section.find_all(["div", "p"]):
        element_classes = set(element.get("class") or [])
        if not element_classes.intersection(classes):
            continue

        # Skip if enclosed within another matching element in this section
        _is_nested = False
        for _anc in element.parents:
            if _anc is section:
                break
            if classes.intersection(set(_anc.get("class") or [])):
                _is_nested = True
                break
        if _is_nested:
            continue

        # Check existing label for a digit — skip if already numbered.
        span = _find_label_span(element)
        if span is not None and _has_number(span.get_text(strip=True)):
            continue

        serial += 1
        _set_label(soup, element, f"{prefix} {serial}")
        count += 1

    return count


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def process_note_numbers_soup(soup: BeautifulSoup) -> int:
    """Number NOTE and EXAMPLE admonitions per top-level section (ISO rules).

    Walks all top-level sections and assigns sequential numbers to
    ``<div class="note">``, ``<p class="note">``, ``<div class="example">``,
    and ``<p class="example">`` elements.  Counters reset at each top-level
    section boundary.  Elements whose admonition-label span already contains a
    digit are left unchanged.

    Returns:
        Total number of labels updated or added across the whole document.
    """
    sections = _get_top_level_sections(soup)
    total = 0

    for section in sections:
        total += _process_admonitions_in_section(soup, section, _NOTE_CLASSES, "NOTE")
        total += _process_admonitions_in_section(soup, section, _EXAMPLE_CLASSES, "EXAMPLE")

    if total:
        logging.info(f"Numbered {total} note/example label(s)")

    return total


def inject_note_numbering_css(soup: BeautifulSoup) -> None:
    """Inject minimal CSS to bold note and example labels."""
    inject_css(soup, "note-numbering-css", _NOTE_CSS)
