"""Bibliography normalization for standards specifications.

Provides flavor-aware reformatting of bibliography entries that have been
enriched with ``data-relaton-*`` attributes by the Relaton enrichment pass,
and deduplication of duplicate entries.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bs4 import BeautifulSoup, Tag

# Heading text patterns that identify bibliography sections
_BIB_HEADING_RE = re.compile(
    r"^(normative\s+references?|informative\s+references?|references?|bibliography)$",
    re.IGNORECASE,
)

# Flavors that use ISO citation style
_ISO_FLAVORS = {"iso", "iec", "iso-iec", "iso-video", "itu-video"}

# Flavors that use IETF citation style
_IETF_FLAVORS = {"ietf"}


def normalize_bibliography_soup(
    soup: BeautifulSoup,
    flavor_name: str,
    relaton_cache: dict | None = None,
) -> int:
    """Normalize bibliography entry formatting to match the target flavor style.

    Operates only on ``<li>`` elements that have a ``data-relaton-docid``
    attribute (set by :func:`specbuild.standards.relaton.enrich_bibliography_soup`).

    ISO/IEC style::

        ISO/IEC 14496-10:2022, *Information technology — Coding of audio-visual
        objects — Part 10: Advanced Video Coding*

    IETF style::

        [RFC2119] Bradner, S., "Key words for use in RFCs to Indicate
        Requirement Levels", BCP 14, RFC 2119, March 1997.

    Args:
        soup:          BeautifulSoup document (mutated in place).
        flavor_name:   Active flavor identifier string (e.g. ``"iso"``, ``"ietf"``).
        relaton_cache: Optional pre-fetched mapping of docid → dict with
                       title/publisher/year keys (avoids re-fetching).

    Returns:
        Count of entries normalized.
    """
    flavor_lc = flavor_name.lower()
    bib_lis = _find_bibliography_lis(soup)
    if not bib_lis:
        return 0

    count = 0
    for li in bib_lis:
        docid = li.get("data-relaton-docid", "")
        if not docid:
            continue

        # Prefer relaton_cache override, then fall back to data-* attrs on the element
        if relaton_cache and docid in relaton_cache:
            entry = relaton_cache[docid]
            title = entry.get("title", li.get("data-relaton-title", ""))
            publisher = entry.get("publisher", li.get("data-relaton-publisher", ""))
            year = str(entry.get("year", li.get("data-relaton-year", "") or ""))
        else:
            title = li.get("data-relaton-title", "")
            publisher = li.get("data-relaton-publisher", "")
            year = li.get("data-relaton-year", "") or ""

        if flavor_lc in _ISO_FLAVORS:
            formatted = _format_iso(docid, title, year)
        elif flavor_lc in _IETF_FLAVORS:
            formatted = _format_ietf(docid, title, publisher, year)
        else:
            # Generic: docid + title
            parts = [docid]
            if title:
                parts.append(f"*{title}*")
            if year:
                parts.append(f"({year})")
            formatted = ", ".join(parts)

        _replace_li_text(li, formatted)
        count += 1
        logging.debug(f"bibformat: normalized '{docid}' for flavor '{flavor_name}'")

    if count:
        logging.info(f"bibformat: normalized {count} bibliography entries")
    return count


def deduplicate_bibliography_soup(soup: BeautifulSoup) -> int:
    """Remove duplicate bibliography entries that share the same docid.

    Keeps the first occurrence of each ``data-relaton-docid`` value and
    removes subsequent duplicates.

    Args:
        soup: BeautifulSoup document (mutated in place).

    Returns:
        Count of entries removed.
    """
    bib_lis = _find_bibliography_lis(soup)
    seen: set[str] = set()
    removed = 0
    for li in bib_lis:
        docid = li.get("data-relaton-docid", "")
        if not docid:
            continue
        if docid in seen:
            li.decompose()
            removed += 1
        else:
            seen.add(docid)

    if removed:
        logging.info(f"bibformat: removed {removed} duplicate bibliography entries")
    return removed


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _find_bibliography_lis(soup: BeautifulSoup) -> list[Tag]:
    """Return all <li> elements inside bibliography sections."""
    results: list[Tag] = []
    for tag in soup.find_all(re.compile(r"^h[1-6]$")):
        if _BIB_HEADING_RE.match(tag.get_text(strip=True)):
            section = tag.find_parent("section") or tag.find_next_sibling(re.compile(r"^(ul|ol)$"))
            if section is None:
                # Try: heading followed by a list
                sibling = tag.find_next_sibling()
                while sibling and sibling.name not in ("h1", "h2", "h3", "h4", "h5", "h6"):
                    if sibling.name in ("ul", "ol"):
                        results.extend(sibling.find_all("li"))
                    elif hasattr(sibling, "find_all"):
                        results.extend(sibling.find_all("li"))
                    sibling = sibling.find_next_sibling()
            else:
                results.extend(section.find_all("li"))

    # Fallback: any <li data-relaton-docid>
    if not results:
        results = list(soup.find_all("li", attrs={"data-relaton-docid": True}))

    return results


def _format_iso(docid: str, title: str, year: str) -> str:
    """Format a bibliography entry in ISO/IEC citation style."""
    parts = [docid]
    if title:
        parts.append(f"*{title}*")
    return ", ".join(parts)


def _format_ietf(docid: str, title: str, publisher: str, year: str) -> str:
    """Format a bibliography entry in IETF RFC citation style."""
    parts = [f"[{docid}]"]
    if publisher:
        parts.append(f"{publisher},")
    if title:
        parts.append(f'"{title}"')
    if year:
        parts[-1] = parts[-1].rstrip(",") + ","
        parts.append(year + ".")
    return " ".join(parts)


def _replace_li_text(li: Tag, new_text: str) -> None:
    """Replace the text content of a <li>, preserving any <a> anchor child."""
    from bs4 import NavigableString

    # Collect anchor elements to preserve
    anchors = li.find_all("a")

    # Clear children
    for child in list(li.children):
        child.extract()

    # Re-add anchors first (they serve as named anchors / backlinks)
    for a in anchors:
        li.append(a)

    # Append the formatted text
    li.append(NavigableString(" " + new_text if anchors else new_text))
