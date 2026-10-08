"""Smart cross-reference text: auto-compose 'Table 3', 'Clause 7.3.2', 'Figure A.1' display text."""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bs4 import BeautifulSoup

# Pattern matching generic link display text (bare section numbers, empty, or §-prefixed).
_GENERIC_TEXT_RE = re.compile(r"^§?\s*\d[\d.]*$")

# Captures a leading number/label from caption text (e.g. "Figure 1", "Table A.2").
_CAPTION_LABEL_RE = re.compile(
    r"(?:Figure|Table|Equation|Eq\.?)\s+([A-Za-z0-9]+(?:\.[A-Za-z0-9]+)*)",
    re.IGNORECASE,
)

# Bare number extracted from caption text (fallback when type keyword missing).
_BARE_NUMBER_RE = re.compile(r"\b([A-Za-z]?\d+(?:\.\d+)*)\b")

# Section number from the start of a heading string (e.g. "7.3.2 Codec").
_HEADING_NUM_RE = re.compile(r"^([A-Za-z]?\d+(?:\.\d+)*)\s+")


def process_smart_xrefs_soup(soup: BeautifulSoup) -> int:
    """Enrich cross-reference anchor links with composed display text.

    Finds ``<a href="#some-id">`` elements whose display text is generic
    (bare section number, matches ``§?\\s*\\d[\\d.]*``, is empty, or equals
    the href fragment) and replaces the text with descriptive labels such as
    "Table 3", "Clause 7.3.2", or "Figure A.1".

    Also handles ``<a href="#term-X">`` links that target ``<dfn>`` or ``<dt>``
    elements — these get type "term", display text taken from the target, and
    ``class="term-ref"`` added.

    Args:
        soup: BeautifulSoup document modified in-place.

    Returns:
        Count of links whose display text was rewritten.
    """
    count = 0

    for link in soup.find_all("a", href=True):
        href: str = link["href"]
        if not href.startswith("#"):
            continue

        fragment = href[1:]
        if not fragment:
            continue

        current_text = link.get_text(strip=True)

        # Decide whether the link text is generic enough to rewrite.
        is_generic = (
            not current_text
            or current_text == fragment
            or bool(_GENERIC_TEXT_RE.match(current_text))
        )
        if not is_generic:
            continue

        target = soup.find(id=fragment)
        if target is None:
            continue

        xref_type, display = _classify_target(target, soup)
        if xref_type is None or display is None:
            continue

        if xref_type == "term":
            # Set italic display, add term-ref class.
            link.clear()
            em = soup.new_tag("em")
            em.string = display
            link.append(em)
            existing_classes = link.get("class") or []
            if "term-ref" not in existing_classes:
                link["class"] = list(existing_classes) + ["term-ref"]
            link["data-xref-type"] = "term"
        else:
            link.string = display
            link["data-xref-type"] = xref_type

        count += 1

    if count:
        logging.info(f"Smart xref: rewrote {count} cross-reference link(s)")

    return count


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _classify_target(target: object, soup: BeautifulSoup) -> tuple[str | None, str | None]:
    """Determine the type and composed label for a target element.

    Args:
        target: The resolved BeautifulSoup element with the matching id.
        soup: Root document (unused currently, kept for extension).

    Returns:
        ``(xref_type, display_text)`` — both ``None`` when classification fails.
    """
    tag_name: str = target.name or ""
    classes: list[str] = target.get("class") or []
    target_id: str = target.get("id") or ""

    # --- term: <dfn> or <dt> ---
    if tag_name in ("dfn", "dt"):
        term_text = target.get_text(strip=True)
        return ("term", term_text) if term_text else (None, None)

    # --- figure ---
    if tag_name == "figure" or any("fig" in c.lower() for c in classes):
        figcaption = target.find("figcaption")
        number = _extract_number_from_caption(figcaption) if figcaption else None
        if number:
            return ("Figure", f"Figure {number}")
        return ("Figure", "Figure")

    # --- table ---
    if tag_name == "table":
        caption = target.find("caption")
        number = _extract_number_from_caption(caption) if caption else None
        if number:
            return ("Table", f"Table {number}")
        return ("Table", "Table")

    # caption element whose parent is a table
    if tag_name == "caption":
        parent = target.parent
        if parent and parent.name == "table":
            number = _extract_number_from_caption(target)
            if number:
                return ("Table", f"Table {number}")
            return ("Table", "Table")

    # --- equation ---
    if target_id.startswith("eq-") or tag_name == "p" and any("formula" in c for c in classes):
        eq_span = target.find(class_="eq-number")
        if eq_span:
            eq_text = eq_span.get_text(strip=True)
            m = _BARE_NUMBER_RE.search(eq_text)
            if m:
                return ("Equation", f"Equation {m.group(1)}")
        return ("Equation", "Equation")

    if tag_name == "p" and any("formula" in c for c in classes):
        return ("Equation", "Equation")

    # --- note ---
    if target_id.startswith("note-"):
        return ("Note", "Note")

    # --- example ---
    if target_id.startswith("ex-"):
        return ("Example", "Example")

    # --- section / div.section → Clause ---
    if tag_name == "section" or (tag_name == "div" and "section" in classes):
        number = _section_number(target)
        if number:
            return ("Clause", f"Clause {number}")
        return ("Clause", "Clause")

    return (None, None)


def _extract_number_from_caption(caption_elem: object) -> str | None:
    """Return the label number from a ``<figcaption>`` or ``<caption>`` element."""
    if caption_elem is None:
        return None
    text = caption_elem.get_text(strip=True)
    # Try "Figure 1 — ..." or "Table A.2 — ..." style.
    m = _CAPTION_LABEL_RE.search(text)
    if m:
        return m.group(1)
    # Fallback: first bare number.
    m2 = _BARE_NUMBER_RE.search(text)
    if m2:
        return m2.group(1)
    return None


def _section_number(section_elem: object) -> str | None:
    """Extract the section number from a section element.

    Checks ``data-section-number`` attribute first, then looks for a
    numbered heading child.

    Args:
        section_elem: A ``<section>`` or ``<div class="section">`` element.

    Returns:
        Section number string (e.g. ``"7.3.2"``) or ``None``.
    """
    # 1. Explicit data attribute.
    data_num = section_elem.get("data-section-number")  # type: ignore[attr-defined]
    if data_num:
        return str(data_num)

    # 2. First child heading.
    for heading_tag in ("h2", "h3", "h4", "h5", "h6", "h1"):
        heading = section_elem.find(heading_tag)  # type: ignore[attr-defined]
        if heading:
            text = heading.get_text(strip=True)
            m = _HEADING_NUM_RE.match(text)
            if m:
                return m.group(1)

    return None
