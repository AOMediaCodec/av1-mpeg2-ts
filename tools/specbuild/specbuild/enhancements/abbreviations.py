"""Abbreviation extraction and `<abbr>` injection.

Scans the document for abbreviations and acronyms from three sources:

- Existing ``<abbr title="...">`` elements
- Inline ``<strong>XYZ</strong> (expansion)`` patterns
- ALL_CAPS inline patterns such as ``XYZ (expansion)``

If the document contains an *Abbreviations* or *Acronyms* section that does
not yet have a ``<dl>`` block, a sorted ``<dl>`` is inserted.  If the section
already contains a ``<dl>`` the module does nothing (manual content wins).

If no abbreviations section exists, the module is a no-op for the ``<dl>``
but still injects ``<abbr>`` wrappers on the first bare occurrence of each
acronym in body prose, improving accessibility.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bs4 import BeautifulSoup, Tag

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Matches ALL_CAPS acronyms (2-6 chars) followed by parenthesised expansion.
_INLINE_ABBR_RE = re.compile(r"\b([A-Z][A-Z0-9]{1,5})\s*\(([^)]{3,80})\)")

# Tags whose text content must not be modified when wrapping bare acronyms.
_SKIP_WRAP_TAGS: frozenset[str] = frozenset(
    ("abbr", "script", "style", "code", "pre", "title", "head")
)


# ---------------------------------------------------------------------------
# Internal helpers — collection
# ---------------------------------------------------------------------------


def _collect_from_abbr_tags(soup: BeautifulSoup) -> dict[str, str]:
    """Collect (term → expansion) pairs from existing ``<abbr>`` elements."""
    found: dict[str, str] = {}
    for abbr in soup.find_all("abbr"):
        term = abbr.get_text(strip=True)
        title = abbr.get("title", "").strip()
        if term and title:
            found.setdefault(term, title)
    return found


def _collect_from_inline_patterns(soup: BeautifulSoup) -> dict[str, str]:
    """Collect abbreviations from ``<strong>XYZ</strong> (expansion)`` and
    plain ``XYZ (expansion)`` text patterns inside ``<p>`` elements.

    Only considers paragraphs to avoid spurious matches in code or metadata.
    """
    from bs4 import NavigableString

    found: dict[str, str] = {}

    for p in soup.find_all("p"):
        # --- Pattern 1: <strong>XYZ</strong> (expansion in following text) ---
        for strong in p.find_all("strong"):
            term = strong.get_text(strip=True)
            if not re.match(r"^[A-Z][A-Z0-9]{1,5}$", term):
                continue
            # Look for parenthesised text in the next sibling text nodes
            next_sib = strong.next_sibling
            while next_sib is not None:
                if isinstance(next_sib, NavigableString):
                    m = re.match(r"\s*\(([^)]{3,80})\)", str(next_sib))
                    if m:
                        found.setdefault(term, m.group(1).strip())
                    break
                # Stop if we hit another non-text element (not whitespace-only)
                if hasattr(next_sib, "get_text") and next_sib.get_text(strip=True):
                    break
                next_sib = next_sib.next_sibling

        # --- Pattern 2: ALL_CAPS (expansion) anywhere in the paragraph text --
        full_text = p.get_text()
        for m in _INLINE_ABBR_RE.finditer(full_text):
            term, expansion = m.group(1), m.group(2).strip()
            found.setdefault(term, expansion)

    return found


# ---------------------------------------------------------------------------
# Internal helpers — section discovery
# ---------------------------------------------------------------------------


def _find_abbreviations_section(soup: BeautifulSoup) -> Tag | None:
    """Return the ``<section>`` whose heading matches *abbreviations* or
    *acronyms* (case-insensitive), or ``None`` if not found.
    """
    heading_re = re.compile(r"(?i)\b(abbreviations?|acronyms?)\b")
    for heading in soup.find_all(re.compile(r"^h[1-6]$")):
        if heading_re.search(heading.get_text(strip=True)):
            section = heading.find_parent("section")
            if section is not None:
                return section
    return None


# ---------------------------------------------------------------------------
# Internal helpers — DOM mutation
# ---------------------------------------------------------------------------


def _build_dl(soup: BeautifulSoup, abbrevs: dict[str, str]) -> Tag:
    """Build a sorted ``<dl>`` element from a {term: expansion} mapping."""
    dl = soup.new_tag("dl", **{"class": "abbreviations-list"})
    for term in sorted(abbrevs.keys(), key=str.upper):
        dt = soup.new_tag("dt")
        dt.string = term
        dl.append(dt)
        dd = soup.new_tag("dd")
        dd.string = abbrevs[term]
        dl.append(dd)
    return dl


def _wrap_first_occurrences(soup: BeautifulSoup, abbrevs: dict[str, str]) -> int:
    """Inject ``<abbr title="...">`` around the first bare occurrence of each
    acronym in body prose text nodes (skipping code, script, existing abbr
    elements, etc.).

    Returns the number of new ``<abbr>`` wrappers inserted.
    """
    from bs4 import NavigableString

    wrapped = 0
    body = soup.find("body")
    if body is None:
        return 0

    # Process each term independently so we accurately track "first occurrence".
    for term, expansion in abbrevs.items():
        # Build a regex that matches the bare term surrounded by word boundaries
        # but NOT already inside an <abbr> tag.
        term_re = re.compile(r"\b" + re.escape(term) + r"\b")
        done = False

        for text_node in body.find_all(string=True):
            if done:
                break
            if not isinstance(text_node, NavigableString):
                continue
            # Skip disallowed ancestor tags
            if any(getattr(p, "name", None) in _SKIP_WRAP_TAGS for p in text_node.parents):
                continue
            text = str(text_node)
            m = term_re.search(text)
            if not m:
                continue

            # Split the text node and insert <abbr> wrapper around the match
            start, end = m.start(), m.end()
            before = text[:start]
            after = text[end:]

            abbr_tag = soup.new_tag("abbr", title=expansion)
            abbr_tag.string = term

            parent = text_node.parent
            if parent is None:
                continue

            # Replace original text node with three nodes: before, abbr, after
            if after:
                text_node.insert_after(NavigableString(after))
            text_node.insert_after(abbr_tag)
            if before:
                text_node.replace_with(NavigableString(before))
            else:
                text_node.extract()

            wrapped += 1
            done = True  # Only wrap the first occurrence

    return wrapped


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def extract_abbreviations_soup(soup: BeautifulSoup) -> int:
    """Extract abbreviations and populate the Abbreviations section.

    Steps:

    1. Collect pairs from ``<abbr>`` tags, ``<strong>`` patterns, and
       inline ALL_CAPS patterns.
    2. Find the abbreviations/acronyms section.  If it already has a
       ``<dl>``, leave it untouched and return 0.
    3. If the section exists but has no ``<dl>``, insert a sorted ``<dl>``.
    4. Wrap the first bare occurrence of each acronym with ``<abbr title>``.

    Args:
        soup: BeautifulSoup document (mutated in place).

    Returns:
        Number of abbreviations added to the ``<dl>`` (or 0 if the section
        already had a ``<dl>`` or no section was found).  Note: ``<abbr>``
        wrapping happens regardless and does not contribute to the count.
    """
    # 1. Collect abbreviations from all sources
    abbrevs: dict[str, str] = {}
    abbrevs.update(_collect_from_abbr_tags(soup))
    for k, v in _collect_from_inline_patterns(soup).items():
        abbrevs.setdefault(k, v)

    # Re-apply abbr-tag collection so that terms found via inline patterns
    # don't override explicit titles set by the author (setdefault above
    # means first-wins; re-running abbr collection with update() would
    # override, so we collect them first instead — already done above).

    if not abbrevs:
        logging.debug("No abbreviations found in document")
        return 0

    # 4. Wrap first bare occurrences (regardless of whether a section exists)
    _wrap_first_occurrences(soup, abbrevs)

    # 2. Find the abbreviations section
    section = _find_abbreviations_section(soup)
    if section is None:
        logging.debug("No abbreviations section found; skipping <dl> insertion")
        return 0

    # 3. If a <dl> already exists, respect manual content
    if section.find("dl"):
        logging.debug("Abbreviations section already has a <dl>; skipping")
        return 0

    # Build and insert the sorted <dl>
    dl = _build_dl(soup, abbrevs)
    section.append(dl)
    count = len(abbrevs)
    logging.info(f"Inserted abbreviations <dl> with {count} entries")
    return count


def generate_abbreviations_list(soup: BeautifulSoup) -> list[tuple[str, str]]:
    """Return a sorted list of (abbreviation, expansion) pairs found in the
    document.

    Collects from ``<abbr>`` tags and inline patterns (same sources as
    :func:`extract_abbreviations_soup`) without mutating the document.

    Args:
        soup: Parsed BeautifulSoup document.

    Returns:
        Alphabetically sorted list of ``(term, expansion)`` tuples.
    """
    abbrevs: dict[str, str] = {}
    abbrevs.update(_collect_from_abbr_tags(soup))
    abbrevs.update(_collect_from_inline_patterns(soup))
    return sorted(abbrevs.items(), key=lambda pair: pair[0].upper())
