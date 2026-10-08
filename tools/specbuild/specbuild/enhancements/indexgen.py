"""Index generation: manage the document's term index.

Supports three modes:

- ``bikeshed``     -- keep Bikeshed's auto-generated flat index (default; no-op)
- ``alphabetical`` -- replace it with a grouped, letter-navigable index
- ``none``         -- remove the index entirely

The alphabetical index is built by scanning all ``<dfn>`` elements in the
document, grouping them by initial letter, and emitting a ``<section>`` with
a clickable letter-navigation bar followed by ``<dl>`` definition lists.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING

from specbuild.theme import THEME
from specbuild.utils import get_bs4, inject_css, read_html, write_html

if TYPE_CHECKING:
    from bs4 import BeautifulSoup, Tag

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Terms longer than this are skipped (likely noise, not meaningful definitions).
_MAX_TERM_LENGTH = 80

# When a heading has no <span class="secno">, fall back to raw heading text
# truncated to this many characters to keep labels reasonable.
_HEADING_TEXT_TRUNCATION = 40

# Unicode section sign (§) used as a prefix for section references in the
# generated definition-list entries.
_SECTION_SIGN = "\u00a7"

# Non-alphabetic terms are bucketed under this character in the letter index.
_NON_ALPHA_BUCKET = "#"

# ---------------------------------------------------------------------------
# Helpers — section lookup
# ---------------------------------------------------------------------------


def _find_nearest_section(element: Tag) -> str:
    """Walk up the DOM to find the nearest section number or label.

    Searches ancestor ``<section>`` and ``<div id="...">`` elements for a
    heading (``<h2>``--``<h6>``) and extracts its ``<span class="secno">``
    text.  Falls back to the raw heading text (truncated) if no section
    number span is present.

    Args:
        element: A BeautifulSoup tag whose ancestors will be inspected.

    Returns:
        Section number string (e.g. ``"5.2"``), truncated heading text, or
        an empty string if no enclosing section is found.
    """
    for parent in element.parents:
        if parent is None or parent.name == "[document]":
            break
        if parent.name == "section" or (parent.name == "div" and parent.get("id")):
            heading = parent.find(["h2", "h3", "h4", "h5", "h6"])
            if heading:
                sec_num = heading.find("span", class_="secno")
                if sec_num:
                    return sec_num.get_text(strip=True)
                return heading.get_text(strip=True)[:_HEADING_TEXT_TRUNCATION]
    return ""


# ---------------------------------------------------------------------------
# Helpers — Bikeshed index removal
# ---------------------------------------------------------------------------


def _remove_bikeshed_index(soup: BeautifulSoup) -> bool:
    """Remove Bikeshed's auto-generated index section from the document.

    Bikeshed generates an index with ``id="index"`` containing an ``<h2>``
    heading, an optional ``<h3 id="index-defined-here">``, and a ``<ul
    class="index">`` list -- all as siblings outside ``<main>``.

    Args:
        soup: BeautifulSoup document (mutated in place).

    Returns:
        ``True`` if the Bikeshed index was found and removed.
    """
    index_heading = soup.find("h2", id="index")
    if not index_heading:
        return False

    # Collect the heading and all following siblings up to the next <h2>
    # (or end of parent).  Bikeshed places these outside <main>.
    to_remove = [index_heading]
    for sibling in index_heading.find_next_siblings():
        if sibling.name == "h2":
            break
        to_remove.append(sibling)

    for elem in to_remove:
        elem.decompose()

    logging.info("Removed Bikeshed's auto-generated index")
    return True


# ---------------------------------------------------------------------------
# Helpers — term collection
# ---------------------------------------------------------------------------


def _collect_terms(soup: BeautifulSoup) -> dict[str, list[dict[str, str]]]:
    """Scan all ``<dfn>`` elements and group them by initial letter.

    Each entry is a dict with keys ``"text"``, ``"id"``, and ``"section"``.
    Duplicate IDs and terms exceeding :data:`_MAX_TERM_LENGTH` are skipped.
    Non-alphabetic terms are bucketed under :data:`_NON_ALPHA_BUCKET`.

    Args:
        soup: Parsed HTML document to scan.

    Returns:
        Mapping from uppercase letter (or ``"#"``) to a list of term dicts.
    """
    terms: dict[str, list[dict[str, str]]] = defaultdict(list)
    seen_ids: set[str] = set()

    for dfn in soup.find_all("dfn"):
        dfn_id = dfn.get("id", "")
        if not dfn_id or dfn_id in seen_ids:
            continue
        seen_ids.add(dfn_id)

        term_text = dfn.get_text(strip=True)
        if not term_text or len(term_text) > _MAX_TERM_LENGTH:
            continue

        section_label = _find_nearest_section(dfn)

        first_char = term_text[0].upper()
        if not first_char.isalpha():
            first_char = _NON_ALPHA_BUCKET

        terms[first_char].append(
            {
                "text": term_text,
                "id": dfn_id,
                "section": section_label,
            }
        )

    return terms


# ---------------------------------------------------------------------------
# Helpers — index HTML construction
# ---------------------------------------------------------------------------


def _build_letter_nav(soup: BeautifulSoup, sorted_letters: list[str]) -> Tag:
    """Build the clickable letter-navigation bar (``<p class="index-nav">``).

    Args:
        soup: BeautifulSoup document (used as a tag factory).
        sorted_letters: Ordered list of letter bucket keys.

    Returns:
        A ``<p>`` tag containing ``<a>`` links separated by ``" | "``.
    """
    nav = soup.new_tag("p", **{"class": "index-nav"})
    for i, letter in enumerate(sorted_letters):
        if i > 0:
            nav.append(" | ")
        link = soup.new_tag("a", href=f"#index-{letter}")
        link.string = letter
        nav.append(link)
    return nav


def _build_letter_group(
    soup: BeautifulSoup,
    letter: str,
    entries: list[dict[str, str]],
) -> tuple[Tag, Tag, int]:
    """Build the heading and definition list for one letter group.

    Args:
        soup: BeautifulSoup document (used as a tag factory).
        letter: The uppercase letter (or ``"#"``) for this group.
        entries: Term dicts to include, each with ``"text"``, ``"id"``,
            and ``"section"`` keys.

    Returns:
        A tuple of ``(letter_heading, dl_element, entry_count)``.
    """
    letter_heading = soup.new_tag("h3", id=f"index-{letter}", **{"class": "index-letter"})
    letter_heading.string = letter

    dl = soup.new_tag("dl", **{"class": "index-entries"})
    sorted_entries = sorted(entries, key=lambda e: e["text"].lower())
    count = 0

    for entry in sorted_entries:
        dt = soup.new_tag("dt")
        link = soup.new_tag("a", href=f"#{entry['id']}")
        link.string = entry["text"]
        dt.append(link)
        dl.append(dt)

        if entry["section"]:
            dd = soup.new_tag("dd")
            dd.string = f"{_SECTION_SIGN} {entry['section']}"
            dl.append(dd)

        count += 1

    return letter_heading, dl, count


def _insert_index_section(soup: BeautifulSoup, index_section: Tag) -> None:
    """Insert the generated index into the document at the correct position.

    The index is placed just before the References heading (matching
    Bikeshed's own placement), falling back to after ``<main>`` or at the
    end of ``<body>``.

    Args:
        soup: BeautifulSoup document (mutated in place).
        index_section: The fully-built ``<section>`` tag to insert.
    """
    refs_heading = soup.find("h2", id="references")
    if not refs_heading:
        refs_heading = soup.find("h2", id="normative")

    if refs_heading:
        refs_heading.insert_before(index_section)
    else:
        main = soup.find("main")
        if main:
            main.insert_after(index_section)
        else:
            body = soup.find("body")
            if body:
                body.append(index_section)


# ---------------------------------------------------------------------------
# Public API — file-based entry point
# ---------------------------------------------------------------------------


def manage_index(html_path: Path, mode: str) -> int:
    """Manage the document term index.

    File-based wrapper around :func:`manage_index_soup`.

    Args:
        html_path: Path to the compiled HTML file.
        mode: One of ``"bikeshed"`` (keep default), ``"alphabetical"``
            (replace with grouped index), or ``"none"`` (remove index).

    Returns:
        Number of index entries in the final index (0 for ``"none"``
        and ``"bikeshed"``).
    """
    if mode == "bikeshed":
        logging.info("Keeping Bikeshed's default index")
        return 0

    try:
        get_bs4()
    except ImportError:
        logging.warning("BeautifulSoup not available, skipping index management")
        return 0

    soup = read_html(html_path)
    result = manage_index_soup(soup, mode)
    write_html(html_path, soup)
    return result


# ---------------------------------------------------------------------------
# Public API — soup-based entry point
# ---------------------------------------------------------------------------


def manage_index_soup(soup: BeautifulSoup, mode: str) -> int:
    """Manage the document term index on a pre-parsed soup object.

    Args:
        soup: BeautifulSoup document (mutated in place).
        mode: ``"alphabetical"`` or ``"none"``.

    Returns:
        Number of index entries (0 for ``"none"``).
    """
    if mode == "none":
        _remove_bikeshed_index(soup)
        return 0

    # mode == 'alphabetical': replace Bikeshed's index with ours
    logging.info("Generating alphabetical index from definitions")

    _remove_bikeshed_index(soup)

    # -- Collect terms from <dfn> elements ------------------------------------
    terms = _collect_terms(soup)

    if not terms:
        logging.info("No <dfn> terms found; no index to generate")
        return 0

    # Sort letter buckets: alphabetic first, '#' (non-alpha) last.
    sorted_letters = sorted(terms.keys(), key=lambda c: (c == _NON_ALPHA_BUCKET, c))

    # -- Build index section --------------------------------------------------
    index_section = soup.new_tag("section", id="generated-index", **{"class": "generated-index"})
    heading = soup.new_tag("h2")
    heading.string = "Index"
    index_section.append(heading)

    index_section.append(_build_letter_nav(soup, sorted_letters))

    total_entries = 0
    for letter in sorted_letters:
        letter_heading, dl, count = _build_letter_group(soup, letter, terms[letter])
        index_section.append(letter_heading)
        index_section.append(dl)
        total_entries += count

    # -- Insert into document and inject CSS ----------------------------------
    _insert_index_section(soup, index_section)
    _inject_index_css(soup)

    logging.info(
        f"Generated alphabetical index with {total_entries} entries "
        f"across {len(sorted_letters)} letter groups"
    )
    return total_entries


# Backward-compatible alias
generate_index = manage_index


# ---------------------------------------------------------------------------
# CSS injection
# ---------------------------------------------------------------------------


def _inject_index_css(soup: BeautifulSoup) -> None:
    """Inject scoped CSS for the generated alphabetical index.

    Args:
        soup: BeautifulSoup document (mutated in place via
            :func:`specbuild.utils.inject_css`).
    """
    t = THEME
    css = f"""
/* Generated Alphabetical Index */
.generated-index {{
  margin: 2em 0;
}}
.generated-index h2 {{
  text-align: center;
  page-break-before: always;
}}
.index-nav {{
  text-align: center;
  margin: 1em 0;
  font-size: {t.index_font_size};
}}
.index-nav a {{
  text-decoration: none;
  font-weight: bold;
  padding: 0 2px;
}}
.index-letter {{
  border-bottom: {t.index_heading_border};
  margin-top: 1.5em;
  padding-bottom: 0.2em;
  color: {t.color_meta};
}}
.index-entries {{
  margin: 0.5em 0 1em 1em;
  font-size: {t.index_font_size};
}}
.index-entries dt {{
  margin-top: 0.3em;
}}
.index-entries dt a {{
  text-decoration: none;
  color: {t.color_accent};
}}
.index-entries dt a:hover {{
  text-decoration: underline;
}}
.index-entries dd {{
  margin-left: 1.5em;
  color: {t.index_label_color};
  font-size: {t.index_header_font_size};
}}
@media print {{
  .generated-index h2 {{
    page-break-before: always;
  }}
  .index-entries {{
    font-size: {t.footer_font_size}pt;
  }}
  .index-nav {{
    font-size: {t.section_header_font_size};
  }}
}}
"""
    inject_css(soup, "generated-index-css", css)
