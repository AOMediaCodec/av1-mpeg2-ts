"""Bibliography auto-expansion from the reference database.

Automatically expands short bibliography references (e.g., "ISO 14496-10")
to full ISO 690 citations using metadata from the standards reference
database.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from specbuild.standards.refdb import extract_doc_identifier, lookup_standard
from specbuild.utils import HEADING_RE

if TYPE_CHECKING:
    from bs4 import BeautifulSoup

    from specbuild.standards.flavors import FlavorSpec


def auto_expand_bibliography_soup(
    soup: BeautifulSoup,
    flavor: FlavorSpec | None = None,
) -> int:
    """Auto-expand short bibliography entries to full citations.

    Scans bibliography sections for entries that contain only a document
    identifier (e.g., "ISO 14496-10" or "RFC 2119") and expands them
    to full citations using the standards reference database.

    Returns the number of entries expanded.
    """
    bib_sections = _find_bibliography_sections(soup, flavor)
    if not bib_sections:
        return 0

    count = 0
    for section in bib_sections:
        count += _expand_entries_in_section(section)

    if count:
        logging.info(f"Auto-expanded {count} bibliography reference(s) from database")
    return count


def _find_bibliography_sections(
    soup: BeautifulSoup,
    flavor: FlavorSpec | None,
) -> list:
    """Find bibliography/references sections in the document."""
    targets = ["normative references", "bibliography", "references", "informative references"]
    if flavor and getattr(flavor, "bibliography", None):
        bib = flavor.bibliography
        if getattr(bib, "normative_heading", None):
            targets.append(bib.normative_heading.lower())
        if getattr(bib, "informative_heading", None):
            targets.append(bib.informative_heading.lower())

    sections = []
    for tag in soup.find_all(HEADING_RE):
        text = tag.get_text(strip=True).lower()
        text_no_num = re.sub(r"^\d+\s+", "", text)
        if text_no_num in targets:
            section = tag.find_parent("section")
            if section:
                sections.append(section)
    return sections


def _expand_entries_in_section(section) -> int:
    """Expand short entries within a bibliography section."""
    count = 0

    for li in section.find_all("li"):
        text = li.get_text(strip=True)
        if _is_short_entry(text):
            expanded = _expand_entry(text)
            if expanded and expanded != text:
                _replace_entry_text(li, expanded)
                count += 1

    for dt in section.find_all("dt"):
        dd = dt.find_next_sibling("dd")
        if dd:
            text = f"{dt.get_text(strip=True)} {dd.get_text(strip=True)}"
        else:
            text = dt.get_text(strip=True)
        if _is_short_entry(text):
            expanded = _expand_entry(text)
            if expanded and expanded != text:
                target = dd if dd else dt
                _replace_entry_text(target, expanded)
                count += 1

    return count


def _is_short_entry(text: str) -> bool:
    """Check if an entry is short enough to be auto-expanded."""
    return len(text) < 60 and bool(extract_doc_identifier(text))


def _expand_entry(text: str) -> str | None:
    """Expand a short reference to a full citation."""
    identifier = extract_doc_identifier(text)
    if not identifier:
        return None

    ref = lookup_standard(identifier)
    if not ref:
        return None

    return format_full_citation(ref)


def format_full_citation(ref) -> str:
    """Format a StandardRef as a full ISO 690-style citation.

    Examples:
        ISO/IEC 14496-10:2022, Information technology — Coding of
        audio-visual objects — Part 10: Advanced video coding
    """
    from specbuild.standards.refdb import StandardRef

    if not isinstance(ref, StandardRef):
        return ""

    parts = []

    if ref.body:
        doc_id = f"{ref.body} {ref.docnumber}"
    else:
        doc_id = ref.docnumber

    if ref.current_year:
        doc_id += f":{ref.current_year}"

    parts.append(doc_id)

    if ref.title:
        parts.append(ref.title)

    citation = ", ".join(parts)

    if ref.status == "withdrawn":
        citation += " [withdrawn]"
    elif ref.status == "superseded" and ref.successor:
        citation += f" [superseded by {ref.successor}]"

    return citation


def _replace_entry_text(element, new_text: str) -> None:
    """Replace the text content of a bibliography entry element."""
    from bs4 import NavigableString

    element.clear()
    element.append(NavigableString(new_text))
