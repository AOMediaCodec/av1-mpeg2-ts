"""Bibliography formatting per standards citation styles.

Reformats bibliography entries to match ISO 690, IEEE, ITU, or RFC
citation styles as specified by the active flavor.

Also provides :func:`inject_bib_hyperlinks_soup` which scans bibliography
``<li>`` elements and wraps recognised identifiers (DOI, RFC, Internet-Draft,
W3C spec URLs, URN-RFC) in clickable ``<a>`` hyperlinks.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from specbuild.utils import HEADING_RE

if TYPE_CHECKING:
    from bs4 import BeautifulSoup, NavigableString, Tag

    from specbuild.standards.flavors import FlavorSpec


def format_bibliography_soup(soup: BeautifulSoup, flavor: FlavorSpec) -> int:
    """Reformat bibliography sections per the flavor's citation style.

    Adds CSS classes for normative/informative distinction, ensures
    proper heading text, and adds sequential numbering to entries.

    Returns the number of modifications made.
    """
    count = 0

    norm_heading = flavor.bibliography.normative_heading
    info_heading = flavor.bibliography.informative_heading

    for tag in soup.find_all(HEADING_RE):
        text = tag.get_text(strip=True)

        if re.match(re.escape(norm_heading), text, re.IGNORECASE):
            section = tag.find_parent("section")
            if section:
                _add_bib_class(section, "normative-references")
                count += _number_entries(section)

        elif re.match(re.escape(info_heading), text, re.IGNORECASE):
            section = tag.find_parent("section")
            if section:
                _add_bib_class(section, "informative-references")
                count += _number_entries(section)

    if count:
        logging.info(f"Formatted {count} bibliography element(s)")
    return count


def _add_bib_class(section, class_name: str) -> None:
    """Add a CSS class to a bibliography section."""
    classes = section.get("class", [])
    if class_name not in classes:
        section["class"] = classes + [class_name]


def _number_entries(section) -> int:
    """Add sequential numbering data attributes to bibliography entries."""
    count = 0
    for i, li in enumerate(section.find_all("li"), 1):
        if not li.get("data-bib-number"):
            li["data-bib-number"] = str(i)
            count += 1
    return count


# ---------------------------------------------------------------------------
# Hyperlink injection for bibliography entries
# ---------------------------------------------------------------------------

# Heading text patterns that identify a bibliography / references section.
_BIB_HEADING_RE = re.compile(r"(?:references|bibliography)", re.IGNORECASE)


def _overlaps(start: int, replacements: list) -> bool:
    return any(s <= start < e for s, e, _, _ in replacements)


# --- individual identifier patterns ---

# DOI: "doi: 10.xxxx/..." or plain "10.xxxx/..."
_DOI_RE = re.compile(r"(?:doi:\s*)?(10\.\d{4,}/[^\s,;)\]>]+)", re.IGNORECASE)

# RFC number: "RFC 2119", "RFC2119"
_RFC_RE = re.compile(r"\bRFC\s*(\d{4,})\b", re.IGNORECASE)

# Internet-Draft slug: draft-<word-chars-and-dashes>
_DRAFT_RE = re.compile(r"\b(draft-[\w-]+)", re.IGNORECASE)

# W3C TR URL (bare or already in text)
_W3C_RE = re.compile(r"https?://www\.w3\.org/TR/\S+")

# URN-based RFC reference: urn:ietf:rfc:<N>
_URN_RFC_RE = re.compile(r"\burn:ietf:rfc:(\d+)\b", re.IGNORECASE)


def _is_inside_anchor(node) -> bool:
    """Return True if *node* is already wrapped inside an ``<a>`` element."""
    for parent in node.parents:
        if getattr(parent, "name", None) == "a":
            return True
    return False


def _find_bib_sections(soup: BeautifulSoup) -> list[Tag]:
    """Return all sections that look like a bibliography / references section.

    Detection criteria (any one is sufficient):

    * The section (or any ancestor) has ``class="references"``.
    * A heading inside the section matches ``references`` or ``bibliography``.
    """
    from bs4 import Tag as BS4Tag

    sections: list[Tag] = []

    # 1. Sections/divs with class "references"
    for el in soup.find_all(class_="references"):
        if isinstance(el, BS4Tag):
            sections.append(el)

    # 2. Headings matching the pattern — walk up to the nearest section/div
    for heading in soup.find_all(HEADING_RE):
        text = heading.get_text(strip=True)
        if _BIB_HEADING_RE.search(text):
            container = heading.find_parent(["section", "div"])
            if container and isinstance(container, BS4Tag) and container not in sections:
                sections.append(container)

    return sections


def _make_link(soup: BeautifulSoup, text: str, href: str) -> Tag:
    """Create a bibliography hyperlink ``<a>`` element."""
    tag = soup.new_tag(
        "a",
        href=href,
        **{"class": "bib-link", "target": "_blank", "rel": "noopener"},
    )
    tag.string = text
    return tag


def _inject_links_in_text_node(
    text_node: NavigableString,
    soup: BeautifulSoup,
) -> int:
    """Replace identifiers in a single text node with hyperlinked versions.

    Applies patterns in priority order:  URN-RFC, RFC, Internet-Draft, W3C
    URL, then DOI.  Returns the number of links created.
    """
    from bs4 import NavigableString as NS

    if _is_inside_anchor(text_node):
        return 0

    text = str(text_node)
    count = 0

    # Build a list of (start, end, href, matched_text) replacements.
    replacements: list[tuple[int, int, str, str]] = []

    # URN RFC
    for m in _URN_RFC_RE.finditer(text):
        url = f"https://www.rfc-editor.org/rfc/rfc{m.group(1)}"
        replacements.append((m.start(), m.end(), url, m.group(0)))

    # RFC number (only if not already covered by a URN match)
    for m in _RFC_RE.finditer(text):
        if not _overlaps(m.start(), replacements):
            url = f"https://www.rfc-editor.org/rfc/rfc{m.group(1).lower()}"
            replacements.append((m.start(), m.end(), url, m.group(0)))

    # Internet-Draft
    for m in _DRAFT_RE.finditer(text):
        if not _overlaps(m.start(), replacements):
            name = m.group(1)
            url = f"https://datatracker.ietf.org/doc/html/{name}"
            replacements.append((m.start(), m.end(), url, m.group(0)))

    # W3C URL
    for m in _W3C_RE.finditer(text):
        if not _overlaps(m.start(), replacements):
            replacements.append((m.start(), m.end(), m.group(0), m.group(0)))

    # DOI — only match if preceded by "doi:" prefix or as a standalone DOI
    for m in _DOI_RE.finditer(text):
        if not _overlaps(m.start(), replacements):
            doi_value = m.group(1)
            url = f"https://doi.org/{doi_value}"
            replacements.append((m.start(), m.end(), url, m.group(0)))

    if not replacements:
        return 0

    # Sort by position
    replacements.sort(key=lambda x: x[0])

    # Build replacement nodes
    parent = text_node.parent
    if parent is None:
        return 0

    cursor = 0
    new_nodes = []
    for start, end, href, matched in replacements:
        if cursor < start:
            new_nodes.append(NS(text[cursor:start]))
        new_nodes.append(_make_link(soup, matched, href))
        count += 1
        cursor = end
    if cursor < len(text):
        new_nodes.append(NS(text[cursor:]))

    # Insert replacements after the original node, then remove the original
    for node in reversed(new_nodes):
        text_node.insert_after(node)
    text_node.extract()

    return count


def inject_bib_hyperlinks_soup(soup: BeautifulSoup) -> int:
    """Scan bibliography ``<li>`` entries and inject hyperlinks for known identifiers.

    Recognised patterns (in priority order within each text node):

    * **URN-RFC**: ``urn:ietf:rfc:<N>`` → rfc-editor.org
    * **RFC**: ``RFC 2119`` / ``RFC2119`` → rfc-editor.org
    * **Internet-Draft**: ``draft-ietf-…`` → IETF datatracker
    * **W3C spec URL**: ``https://www.w3.org/TR/…`` → same URL
    * **DOI**: ``doi:10.xxxx/…`` or standalone ``10.xxxx/…`` → doi.org

    Already-linked text (wrapped in an ``<a>``) is left untouched.  Only
    ``<li>`` elements inside the detected bibliography section(s) are
    processed.

    Args:
        soup: BeautifulSoup document (mutated in place).

    Returns:
        Total number of hyperlinks injected across all bibliography entries.
    """
    from bs4 import NavigableString

    bib_sections = _find_bib_sections(soup)
    if not bib_sections:
        return 0

    total = 0
    for section in bib_sections:
        for li in section.find_all("li"):
            # Collect text nodes inside this li (snapshot before mutation)
            text_nodes = [n for n in li.find_all(string=True) if isinstance(n, NavigableString)]
            for node in text_nodes:
                total += _inject_links_in_text_node(node, soup)

    if total:
        logging.info(f"Injected {total} bibliography hyperlink(s)")
    return total
