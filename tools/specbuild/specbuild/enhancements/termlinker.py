"""Term auto-linking: hyperlink first occurrences of defined terms to their definitions."""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from specbuild.utils import HEADING_RE, inject_css

if TYPE_CHECKING:
    from bs4 import BeautifulSoup

# CSS injected once per document.
_TERM_LINKER_CSS = (
    "a.term-ref { border-bottom: 1px dotted currentColor; text-decoration: none; }\n"
    "a.term-ref:hover { text-decoration: underline; }"
)

# Tags whose text content must never be auto-linked.
_SKIP_TAGS: frozenset[str] = frozenset(
    ("pre", "code", "a", "dfn", "h1", "h2", "h3", "h4", "h5", "h6")
)

# Prose containers we search for occurrences.
_PROSE_TAGS: tuple[str, ...] = ("p", "li", "td", "dd")

# Heading text pattern identifying the Terms & definitions section.
# Matches "Terms", "Terms and definitions", "3 Terms and definitions", etc.
_TERMS_HEADING_RE = re.compile(r"(?i)^(?:\d+(?:\.\d+)*\s+)?terms?\s*(?:and\s+definitions?)?\s*$")


def build_term_map(soup: BeautifulSoup) -> dict[str, str]:
    """Scan *soup* for term definitions and return a normalised-term → anchor-id map.

    Collects terms from three sources:

    1. ``<dt id="...">`` elements inside a Terms and definitions section
       (heading matches ``r"(?i)terms?\\s*(and\\s*definitions?)?"``).
    2. ``<dfn id="...">`` elements anywhere in the document.
    3. Elements with a ``data-term-id`` attribute.

    Args:
        soup: Parsed BeautifulSoup document (read-only).

    Returns:
        ``{normalized_term: anchor_id}`` where
        ``normalized_term = term.lower().strip()``.
    """
    term_map: dict[str, str] = {}

    # --- 1. <dt> elements inside a Terms section ---
    terms_section = _find_terms_section(soup)
    if terms_section is not None:
        for dt in terms_section.find_all("dt"):
            anchor_id = dt.get("id", "")
            term_text = dt.get_text(strip=True)
            if anchor_id and term_text:
                term_map[term_text.lower().strip()] = anchor_id

    # --- 2. <dfn> elements anywhere ---
    for dfn in soup.find_all("dfn"):
        anchor_id = dfn.get("id", "")
        term_text = dfn.get_text(strip=True)
        if anchor_id and term_text:
            term_map[term_text.lower().strip()] = anchor_id

    # --- 3. data-term-id elements ---
    for elem in soup.find_all(attrs={"data-term-id": True}):
        anchor_id = elem["data-term-id"]
        term_text = elem.get_text(strip=True)
        if anchor_id and term_text:
            term_map[term_text.lower().strip()] = anchor_id

    return term_map


def process_term_links_soup(
    soup: BeautifulSoup,
    term_map: dict[str, str] | None = None,
    max_per_term: int = 1,
) -> int:
    """Auto-link first (or all) occurrences of defined terms in body prose.

    For each term in *term_map* (sorted longest-first to avoid prefix collisions),
    scans ``<p>``, ``<li>``, ``<td>``, ``<dd>`` text nodes in the document body
    and inserts ``<a href="#{anchor_id}" class="term-ref">`` wrappers around
    whole-word matches.

    The Terms & definitions section itself is excluded, as are text nodes already
    inside ``<pre>``, ``<code>``, ``<a>``, ``<dfn>``, or heading tags.

    Args:
        soup: BeautifulSoup document modified in-place.
        term_map: Mapping ``{normalized_term: anchor_id}`` as returned by
            :func:`build_term_map`.  Built automatically when *None*.
        max_per_term: Maximum links to create per term.  ``0`` means unlimited.

    Returns:
        Total number of links created.
    """

    if term_map is None:
        term_map = build_term_map(soup)

    if not term_map:
        return 0

    # Identify elements inside the Terms section so we can skip them.
    terms_section = _find_terms_section(soup)

    # Sort terms longest-first to prevent "encoder" matching inside "video encoder".
    sorted_terms = sorted(term_map.keys(), key=len, reverse=True)

    # Per-term occurrence counters (mutable, shared across the whole document).
    occurrence_count: dict[str, int] = {t: 0 for t in sorted_terms}

    # Build per-term compiled regex (whole-word, case-insensitive).
    term_patterns: dict[str, re.Pattern[str]] = {
        term: re.compile(rf"\b{re.escape(term)}\b", re.IGNORECASE) for term in sorted_terms
    }

    body = soup.find("body") or soup
    total_links = 0

    # Collect all text nodes in the body up front so we don't iterate a
    # live tree while mutating it.
    text_nodes = list(body.find_all(string=True))

    for text_node in text_nodes:
        # --- Guard: skip text nodes inside skip-tag ancestors ---
        if _is_in_skip_ancestor(text_node):
            continue

        # --- Guard: skip text nodes inside the Terms section ---
        if terms_section is not None and _is_inside(text_node, terms_section):
            continue

        # --- Guard: text node must live inside a prose container ---
        if not _in_prose_container(text_node):
            continue

        text = str(text_node)
        if not text.strip():
            continue

        links_here = _replace_text_node(
            text_node,
            text,
            sorted_terms,
            term_patterns,
            term_map,
            occurrence_count,
            max_per_term,
            soup,
        )
        total_links += links_here

    # Inject CSS once.
    inject_css(soup, "term-linker-css", _TERM_LINKER_CSS)

    if total_links:
        logging.info(f"Term linker: created {total_links} term reference link(s)")

    return total_links


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _replace_text_node(
    text_node: object,
    text: str,
    sorted_terms: list[str],
    term_patterns: dict[str, re.Pattern[str]],
    term_map: dict[str, str],
    occurrence_count: dict[str, int],
    max_per_term: int,
    soup: BeautifulSoup,
) -> int:
    """Replace term occurrences inside a single text node with ``<a>`` elements.

    Finds all non-overlapping matches across all terms in document order,
    respecting ``max_per_term``.  Builds replacement segments (plain text +
    ``<a>`` tags) and splices them into the tree in a single operation.

    Returns:
        Number of links created.
    """
    from bs4 import NavigableString

    # Collect all candidate matches: (start, end, term, matched_text).
    # We want the longest-first term to win over shorter prefix terms, so
    # sort candidates by start position, and for ties by length descending.
    candidates: list[tuple[int, int, str, str]] = []

    for term in sorted_terms:
        if max_per_term != 0 and occurrence_count[term] >= max_per_term:
            continue
        for m in term_patterns[term].finditer(text):
            candidates.append((m.start(), m.end(), term, m.group(0)))

    if not candidates:
        return 0

    # Resolve non-overlapping matches in left-to-right order.
    # For overlapping candidates at the same position, prefer longest (already
    # guaranteed by sorted_terms order, but we enforce it here too).
    candidates.sort(key=lambda c: (c[0], -(c[1] - c[0])))

    resolved: list[tuple[int, int, str, str]] = []
    last_end = 0

    for start, end, term, matched in candidates:
        if start < last_end:
            # Overlapping with an already-accepted match: skip.
            continue
        if max_per_term != 0 and occurrence_count[term] >= max_per_term:
            continue
        resolved.append((start, end, term, matched))
        occurrence_count[term] += 1
        last_end = end

    if not resolved:
        return 0

    # Build replacement fragment: interleave plain text strings and <a> tags.
    new_nodes = []
    pos = 0

    for start, end, term, matched in resolved:
        if start > pos:
            new_nodes.append(NavigableString(text[pos:start]))
        anchor_id = term_map[term]
        a_tag = soup.new_tag("a", href=f"#{anchor_id}")
        a_tag["class"] = "term-ref"
        a_tag["title"] = term
        a_tag.string = matched
        new_nodes.append(a_tag)
        pos = end

    if pos < len(text):
        new_nodes.append(NavigableString(text[pos:]))

    # Splice the new nodes in place of the original text node.
    parent = text_node.parent
    if parent is None:
        return 0

    # Insert all new nodes before the text node, then remove it.
    for node in reversed(new_nodes):
        text_node.insert_before(node)
    text_node.extract()

    return len(resolved)


def _is_in_skip_ancestor(node: object) -> bool:
    """Return True if *node* has an ancestor tag in *_SKIP_TAGS*."""
    for parent in node.parents:
        if hasattr(parent, "name") and parent.name in _SKIP_TAGS:
            return True
    return False


def _is_inside(element: object, section: object) -> bool:
    """Return True if *element* is a descendant of *section*."""
    for parent in element.parents:
        if parent is section:
            return True
    return False


def _in_prose_container(node: object) -> bool:
    """Return True if *node* has a prose-container ancestor (p, li, td, dd)."""
    for parent in node.parents:
        if hasattr(parent, "name") and parent.name in _PROSE_TAGS:
            return True
    return False


def _find_terms_section(soup: BeautifulSoup) -> object | None:
    """Return the section element containing the Terms and definitions heading, or None."""
    for tag in soup.find_all(HEADING_RE):
        text = tag.get_text(" ", strip=True)
        if _TERMS_HEADING_RE.search(text):
            section = tag.find_parent("section")
            if section is not None:
                return section
    return None
