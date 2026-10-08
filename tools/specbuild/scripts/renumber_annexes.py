#!/usr/bin/env python3
"""
Renumber Annex sections from numeric to alphabetic notation.

This script post-processes the Bikeshed HTML output to change Annex sections from
numeric numbering to alphabetic numbering (A, B, C, D, E, ...).

The script automatically detects Annex sections by looking for headings that contain
"Annex" in their content, making it flexible for any number of annexes and any project.

It updates:
- Section headings (h2, h3, h4, etc.)
- Cross-references to Annex sections
- Table of contents entries
- Table and figure captions
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
from pathlib import Path

from bs4 import BeautifulSoup, Tag

# Route logging through the shared colored formatter when this script is
# invoked as a subprocess of compile.py.
_repo_root = str(Path(__file__).resolve().parent.parent)
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)
from specbuild.logsetup import setup_logging  # noqa: E402

setup_logging("INFO")

# ---------------------------------------------------------------------------
# Regex patterns for matching section references in text and links
# ---------------------------------------------------------------------------

# Matches "Section 10", "Section 10.1.2", etc. (case-sensitive, capitalized)
SECTION_WORD_PATTERN = r"\bSection\s+(\d+)((?:\.\d+)*)"

# Matches "section 10" (lowercase)
SECTION_WORD_LOWER_PATTERN = r"\bsection\s+(\d+)((?:\.\d+)*)"

# Matches "§10", "§ 10", "§ 10.1.2", etc.
SECTION_SYMBOL_PATTERN = r"§\s*(\d+)((?:\.\d+)*)"

# Matches a bare dotted section number like "10" or "10.1.2"
BARE_SECTION_NUMBER_PATTERN = r"^\d+(?:\.\d+)*$"

# Matches "Annex X:" at the start of a heading (where X is a capital letter)
ANNEX_HEADING_PATTERN = r"^Annex\s+[A-Z]:\s+"

# Matches an optional "Annex" prefix (with or without letter/colon) for stripping
ANNEX_PREFIX_STRIP_PATTERN = r"^Annex\s*[A-Z]?:?\s*"

# Characters to strip from the trailing end of section number spans
SECNO_TRAILING_CHARS = "§ ."

# HTML element parents that contain meaningful text references to scan
TEXT_REFERENCE_PARENTS: list[str] = ["span", "p", "li", "td", "th", "div"]


# ---------------------------------------------------------------------------
# Annex detection and mapping
# ---------------------------------------------------------------------------


def build_annex_mapping(soup: BeautifulSoup) -> dict[str, str]:
    """
    Automatically detect Annex sections and build a mapping from section numbers to letters.

    Scans all h2 headings with class 'heading settled' and identifies those that contain
    "Annex" in their content. Assigns letters A, B, C, ... in the order they appear.

    Supports two Bikeshed output patterns:
    - **Numeric secno:** secno="10.", content="Annex A: Title"
      → mapping: ``{'10': 'A', '11': 'B', ...}``
    - **Empty secno (pre-lettered):** secno="", content="Annex A: Title"
      → mapping: ``{'annex-A': 'A', 'annex-B': 'B', ...}``

    Args:
        soup: BeautifulSoup object of the HTML

    Returns:
        Dictionary mapping section_number -> letter (e.g., {'10': 'A', '11': 'B', ...})
    """
    annex_mapping: dict[str, str] = {}
    letter_index = 0

    # Find all h2 headings with both "heading" and "settled" classes
    h2_elements = soup.select("h2.heading.settled")

    for h2 in h2_elements:
        # Get the content span
        content_span = h2.find("span", class_="content")
        if not content_span:
            continue

        content_text = content_span.get_text().strip()

        # Check if this is an Annex section (contains "Annex" in the content)
        if "Annex" not in content_text:
            continue

        # Get the section number from the secno span
        secno_span = h2.find("span", class_="secno")
        secno_text = secno_span.get_text().strip() if secno_span else ""
        clean_secno = secno_text.rstrip(SECNO_TRAILING_CHARS)

        if clean_secno and clean_secno.isdigit():
            # Pattern 1: Numeric secno (e.g. "10" -> "A")
            letter = chr(ord("A") + letter_index)
            annex_mapping[clean_secno] = letter
            letter_index += 1
            logging.debug(f"Detected Annex section: {clean_secno} -> {letter} ({content_text})")
        elif not clean_secno or not clean_secno.isdigit():
            # Pattern 2: Empty/missing secno — extract letter from "Annex X:" in content
            m = re.match(r"Annex\s+([A-Z])", content_text)
            if m:
                letter = m.group(1)
                key = f"annex-{letter}"
                annex_mapping[key] = letter
                letter_index += 1
                logging.debug(f"Detected pre-lettered Annex: {key} -> {letter} ({content_text})")

    if annex_mapping:
        logging.debug(
            f"Detected {len(annex_mapping)} Annex sections: {', '.join([f'Section {k} -> Annex {v}' for k, v in sorted(annex_mapping.items())])}"
        )
    else:
        logging.debug("No Annex sections detected")

    return annex_mapping


def get_annex_letter(section_num: str, annex_mapping: dict[str, str]) -> str | None:
    """Look up the letter assigned to a numeric Annex section.

    Args:
        section_num: Top-level section number as a string (e.g. ``'10'``).
        annex_mapping: Mapping produced by :func:`build_annex_mapping`.

    Returns:
        The corresponding letter (e.g. ``'A'``), or ``None`` if *section_num*
        is not an Annex.
    """
    return annex_mapping.get(section_num, None)


def is_annex_section(section_num: str, annex_mapping: dict[str, str]) -> bool:
    """Return ``True`` if *section_num* corresponds to an Annex.

    Args:
        section_num: Top-level section number as a string.
        annex_mapping: Mapping produced by :func:`build_annex_mapping`.
    """
    return section_num in annex_mapping


# ---------------------------------------------------------------------------
# Section number conversion helpers
# ---------------------------------------------------------------------------


def convert_section_number(secno: str, annex_mapping: dict[str, str]) -> str:
    """Convert a dotted section number from numeric to alphabetic for Annex sections.

    Non-Annex section numbers are returned unchanged.

    Args:
        secno: Dotted section number string (e.g. ``'10.2.3'``).
        annex_mapping: Mapping produced by :func:`build_annex_mapping`.

    Returns:
        Converted string (e.g. ``'A.2.3'``), or the original if not an Annex.

    Examples:
        >>> convert_section_number("10.1", {"10": "A"})
        'A.1'
        >>> convert_section_number("5", {"10": "A"})
        '5'
    """
    parts = secno.split(".")
    if not parts:
        return secno

    # Check if the main section is an Annex
    main_section = parts[0]
    if is_annex_section(main_section, annex_mapping):
        letter = get_annex_letter(main_section, annex_mapping)
        parts[0] = letter
        return ".".join(parts)

    return secno


# ---------------------------------------------------------------------------
# Heading and TOC updates
# ---------------------------------------------------------------------------


def _annex_secno_label(letter: str, annex_format: str) -> str:
    """Return the secno text for a top-level Annex heading.

    Args:
        letter: The annex letter (e.g. ``'A'``).
        annex_format: ``"prefix"`` or ``"letter"``.
    """
    if annex_format == "letter":
        return f"{letter}. "
    return f"Annex {letter}. "


def _strip_annex_prefix(text: str) -> str:
    """Remove any ``Annex X:`` prefix from heading/TOC text."""
    return re.sub(ANNEX_PREFIX_STRIP_PATTERN, "", text)


def update_section_headings(
    soup: BeautifulSoup, annex_mapping: dict[str, str], annex_format: str = "prefix"
) -> int:
    """
    Update section numbers in heading elements.

    For top-level Annex headings (h2), sets the section number and content
    according to *annex_format*:

    - ``"prefix"`` — secno ``"Annex A. "``, content ``"Assembly Process"``
    - ``"letter"`` — secno ``"A. "``,       content ``"Assembly Process"``

    For subsection headings (h3, h4, etc.), updates section numbers to use letters.

    Args:
        soup: Parsed HTML document.
        annex_mapping: Mapping produced by :func:`build_annex_mapping`.
        annex_format: How to render top-level annex headings (``"prefix"``
            or ``"letter"``).

    Returns:
        Number of headings updated.
    """
    count = 0
    # Check if we have pre-lettered annexes (keys like "annex-A")
    has_prelettered = any(k.startswith("annex-") for k in annex_mapping)

    # Find all headings with section numbers
    for heading in soup.find_all(["h2", "h3", "h4", "h5", "h6"]):
        # Find the section number span
        secno_span = heading.find("span", class_="secno")
        if not secno_span:
            continue

        # Get raw text (preserve trailing whitespace for faithful reconstruction)
        raw_secno = secno_span.get_text()
        current_secno = raw_secno.strip()

        # Remove trailing "§" or other symbols
        clean_secno = current_secno.rstrip(SECNO_TRAILING_CHARS)

        # --- Pre-lettered pattern: empty secno, "Annex X:" in content ---
        if has_prelettered and heading.name == "h2" and not clean_secno:
            content_span = heading.find("span", class_="content")
            if content_span:
                content_text = content_span.get_text().strip()
                m = re.match(r"Annex\s+([A-Z])", content_text)
                if m and f"annex-{m.group(1)}" in annex_mapping:
                    letter = m.group(1)
                    secno_span.string = _annex_secno_label(letter, annex_format)
                    content_text = _strip_annex_prefix(content_text)
                    content_span.string = content_text
                    count += 1
                    logging.debug(
                        f"Updated h2 (pre-lettered): secno={secno_span.string!r}, content={content_text!r}"
                    )
            continue

        # --- Numeric pattern: secno has a digit, "Annex" in content ---
        # Check if this section number starts with an Annex number
        parts = clean_secno.split(".")
        if not parts or not is_annex_section(parts[0], annex_mapping):
            continue

        # Special handling for h2 (top-level Annex headings)
        if heading.name == "h2":
            letter = get_annex_letter(parts[0], annex_mapping)

            # Place the section label in the secno span
            secno_span.string = _annex_secno_label(letter, annex_format)

            # Strip any existing "Annex X:" prefix from the content
            content_span = heading.find("span", class_="content")
            if content_span:
                content_text = content_span.get_text().strip()
                content_text = _strip_annex_prefix(content_text)
                content_span.string = content_text

            count += 1
            logging.debug(f"Updated h2: secno={secno_span.string!r}, content={content_text!r}")
        else:
            # For subsections (h3, h4, etc.), convert to alphabetic notation
            new_secno = convert_section_number(clean_secno, annex_mapping)

            # Update the span content
            if new_secno != clean_secno:
                # Preserve trailing symbols AND whitespace from the raw text
                # (e.g. "15.1. " → trailing is ". " to keep space before content)
                trailing = raw_secno[raw_secno.find(clean_secno) + len(clean_secno) :]
                secno_span.string = new_secno + trailing
                count += 1
                logging.debug(
                    f"Updated heading section number: {current_secno} -> {new_secno + trailing!r}"
                )

    return count


def update_toc_entries(
    soup: BeautifulSoup, annex_mapping: dict[str, str], annex_format: str = "prefix"
) -> int:
    """
    Update section numbers in Table of Contents.

    For top-level Annex entries, sets the secno span to match *annex_format*
    (consistent with the heading) and strips the "Annex X:" prefix from the
    link text so it doesn't appear twice.

    For subsections, shows letter-based numbering (A.1, A.2, etc.)

    Args:
        soup: Parsed HTML document.
        annex_mapping: Mapping produced by :func:`build_annex_mapping`.
        annex_format: ``"prefix"`` or ``"letter"`` (see
            :func:`update_section_headings`).

    Returns:
        Number of TOC entries updated.
    """
    count = 0
    has_prelettered = any(k.startswith("annex-") for k in annex_mapping)

    # Find TOC
    toc = soup.find("nav", id="toc")
    if not toc:
        logging.warning("No TOC found in HTML")
        return 0

    # Find all TOC links
    for link in toc.find_all("a", href=True):
        # Find section number in link
        secno_span = link.find("span", class_="secno")
        if not secno_span:
            continue

        # Get raw text (preserve trailing whitespace)
        raw_secno = secno_span.get_text()
        current_secno = raw_secno.strip()
        clean_secno = current_secno.rstrip(SECNO_TRAILING_CHARS)

        # --- Pre-lettered pattern: empty secno, "Annex X:" in content ---
        if has_prelettered and not clean_secno:
            content_span = link.find("span", class_="content")
            if content_span:
                content_text = content_span.get_text().strip()
                m = re.match(r"Annex\s+([A-Z])", content_text)
                if m and f"annex-{m.group(1)}" in annex_mapping:
                    letter = m.group(1)
                    secno_span.string = _annex_secno_label(letter, annex_format)
                    cleaned = _strip_annex_prefix(content_text)
                    if cleaned != content_text:
                        content_span.string = cleaned
                    count += 1
                    logging.debug(f"Updated TOC (pre-lettered): secno={secno_span.string!r}")
            continue

        # --- Numeric pattern ---
        # Check if this section number starts with an Annex number
        parts = clean_secno.split(".")
        if not parts or not is_annex_section(parts[0], annex_mapping):
            continue

        # For top-level Annex entries (just "10", "11", etc. with no subsections)
        if len(parts) == 1:
            letter = get_annex_letter(parts[0], annex_mapping)

            # Set secno to match the heading format
            secno_span.string = _annex_secno_label(letter, annex_format)

            # Strip any "Annex X:" prefix from the content span
            content_span = link.find("span", class_="content")
            if content_span:
                content_text = content_span.get_text().strip()
                cleaned = _strip_annex_prefix(content_text)
                if cleaned != content_text:
                    content_span.string = cleaned

            count += 1
            logging.debug(f"Updated TOC top-level Annex: secno={secno_span.string!r}")
        else:
            # For subsections, convert to alphabetic notation
            new_secno = convert_section_number(clean_secno, annex_mapping)
            trailing = raw_secno[raw_secno.find(clean_secno) + len(clean_secno) :]
            secno_span.string = new_secno + trailing
            count += 1
            logging.debug(f"Updated TOC entry: {current_secno} -> {new_secno + trailing!r}")

    return count


# ---------------------------------------------------------------------------
# Cross-reference updates (links and plain text)
# ---------------------------------------------------------------------------


def update_cross_references(soup: BeautifulSoup, annex_mapping: dict[str, str]) -> int:
    """
    Update cross-references to Annex sections.

    Changes references from "Section 10" to "Annex A", etc.
    Also handles bare section numbers like "10.1" -> "A.1".

    Args:
        soup: Parsed HTML document.
        annex_mapping: Mapping produced by :func:`build_annex_mapping`.

    Returns:
        Number of cross-references updated.
    """
    count = 0

    # Find all links in the document
    for link in soup.find_all("a", href=True):
        # Get the link text
        link_text = link.get_text().strip()

        if not link_text:
            continue

        # Check if the link text contains a numeric section reference
        patterns = [
            (SECTION_WORD_PATTERN, r"Annex {}{}"),  # "Section 10" -> "Annex A"
            (SECTION_WORD_LOWER_PATTERN, r"Annex {}{}"),  # "section 10" -> "Annex A"
            (SECTION_SYMBOL_PATTERN, r"Annex {}{}"),  # "§10"        -> "Annex A"
        ]

        updated = False
        for pattern, replacement in patterns:
            match = re.search(pattern, link_text)
            if match:
                section_num = match.group(1)
                subsection = match.group(2) if len(match.groups()) > 1 else ""

                # Only update if this is actually an Annex section
                if is_annex_section(section_num, annex_mapping):
                    letter = get_annex_letter(section_num, annex_mapping)
                    new_text = re.sub(pattern, replacement.format(letter, subsection), link_text)
                    # Deduplicate: "Annex A Annex A: ..." → "Annex A: ..."
                    annex_prefix = f"Annex {letter}"
                    dup = f"{annex_prefix} {annex_prefix}"
                    if dup in new_text:
                        new_text = new_text.replace(dup, annex_prefix, 1)
                    link.string = new_text
                    count += 1
                    updated = True
                    logging.debug(f"Updated cross-reference: '{link_text}' -> '{new_text}'")
                    break

        # If link text is just a section number like "10.1" or "14.2" (common in Bikeshed auto-refs)
        # This handles bare section numbers without "Section" prefix
        if not updated and re.match(BARE_SECTION_NUMBER_PATTERN, link_text):
            parts = link_text.split(".")
            # Only update if this is an Annex section
            if is_annex_section(parts[0], annex_mapping):
                new_text = convert_section_number(link_text, annex_mapping)
                link.string = new_text
                count += 1
                logging.debug(f"Updated cross-reference: '{link_text}' -> '{new_text}'")

    return count


def update_text_references(soup: BeautifulSoup, annex_mapping: dict[str, str]) -> int:
    """
    Update Annex section references in text content (non-link elements).

    Handles patterns like:
    - "in § 10.1" -> "in § A.1"
    - "in § 14.2" -> "in § E.2"
    - "Section 10" -> "Annex A"

    This is particularly important for Index sections where references
    appear in ``<span>`` tags rather than ``<a>`` tags.

    Args:
        soup: Parsed HTML document.
        annex_mapping: Mapping produced by :func:`build_annex_mapping`.

    Returns:
        Number of text references updated.
    """
    count = 0

    # Process each unique NavigableString once, limited to the same
    # kinds of containers as before, and skip script/style content.
    processed_ids: set[int] = set()

    for string_node in soup.find_all(string=True):
        # Ensure we only process each string node once
        node_id = id(string_node)
        if node_id in processed_ids:
            continue
        processed_ids.add(node_id)

        # Skip any text that is inside <script> or <style> elements
        if string_node.find_parent(["script", "style"]) is not None:
            continue

        # Only process text inside meaningful container elements
        if string_node.find_parent(TEXT_REFERENCE_PARENTS) is None:
            continue

        original_text = str(string_node)
        modified_text = original_text

        # Pattern 1: "§ 10.1" style references (common in Index)
        def replace_section_symbol(match: re.Match) -> str:
            """Replace ``§ 10.1`` with ``§ A.1`` for Annex sections."""
            section_num = match.group(1)
            subsection = match.group(2)

            if is_annex_section(section_num, annex_mapping):
                letter = get_annex_letter(section_num, annex_mapping)
                return f"§ {letter}{subsection}"
            return match.group(0)

        modified_text = re.sub(SECTION_SYMBOL_PATTERN, replace_section_symbol, modified_text)

        # Pattern 2: "Section 10" style references
        def replace_section_word(match: re.Match) -> str:
            """Replace ``Section 10`` with ``Annex A`` for Annex sections."""
            section_num = match.group(1)
            subsection = match.group(2)

            if is_annex_section(section_num, annex_mapping):
                letter = get_annex_letter(section_num, annex_mapping)
                return f"Annex {letter}{subsection}"
            return match.group(0)

        modified_text = re.sub(
            SECTION_WORD_PATTERN,
            replace_section_word,
            modified_text,
            flags=re.IGNORECASE,
        )

        # If text was modified, replace the string
        if modified_text != original_text:
            string_node.replace_with(modified_text)
            count += 1
            logging.debug(
                f"Updated text reference: '{original_text.strip()}' -> '{modified_text.strip()}'"
            )
    return count


# ---------------------------------------------------------------------------
# Table and figure numbering
# ---------------------------------------------------------------------------


def _is_numbered_h2(elem: Tag) -> bool:
    """Return ``True`` if *elem* is a numbered ``<h2>`` heading.

    Bikeshed emits numbered headings with classes ``heading settled`` and
    *without* the ``no-num`` class.
    """
    return (
        elem.name == "h2"
        and "heading" in elem.get("class", [])
        and "settled" in elem.get("class", [])
        and "no-num" not in elem.get("class", [])
    )


def _section_label_for(section_number: int, annex_mapping: dict[str, str]) -> str:
    """Return the display label for a section: a letter for Annexes, a digit string otherwise.

    Args:
        section_number: 1-based ordinal position of the ``<h2>`` heading.
        annex_mapping: Mapping produced by :func:`build_annex_mapping`.
    """
    sec_str = str(section_number)
    if is_annex_section(sec_str, annex_mapping):
        return get_annex_letter(sec_str, annex_mapping)
    return sec_str


def _update_caption_cross_refs(
    soup: BeautifulSoup, css_class: str, label: str, number_map: dict[str, str]
) -> int:
    """Update ``<a class="{css_class}">`` links to ``"{label} X.Y"``.

    Args:
        soup: BeautifulSoup document.
        css_class: CSS class selector (e.g. ``'table-ref'``).
        label: Display prefix (e.g. ``'Table'`` or ``'Figure'``).
        number_map: Mapping of element IDs to display references.

    Returns:
        Number of cross-references updated.
    """
    refs = soup.find_all("a", class_=css_class)
    updated = 0
    for link in refs:
        href = link.get("href", "")
        if href.startswith("#"):
            target_id = href[1:]
            if target_id in number_map:
                old_text = link.get_text()
                new_text = f"{label} {number_map[target_id]}"
                if old_text != new_text:
                    link.string = new_text
                    updated += 1
                    logging.debug(
                        f"Updated {label.lower()} cross-reference: '{old_text}' -> '{new_text}'"
                    )
    if refs:
        logging.debug(f"Updated {updated} of {len(refs)} {label.lower()} cross-references")
    return updated


def update_table_numbers(soup: BeautifulSoup, annex_mapping: dict[str, str]) -> int:
    """
    Update table numbers in captions and cross-references.

    For Annex sections, uses letter-based numbering (A, B, C, ...).
    For other sections, uses numeric numbering.

    Args:
        soup: Parsed HTML document.
        annex_mapping: Mapping produced by :func:`build_annex_mapping`.

    Returns:
        Number of tables updated.
    """
    count = 0

    # Find main element
    main = soup.find("main")
    if not main:
        logging.warning("No <main> element found")
        return 0

    section_number = 0
    table_number = 0
    table_numbers = {}  # Map caption IDs to their numbers

    # Process all children of main
    for elem in main.children:
        if not hasattr(elem, "name"):
            continue

        # Track which h2 section we are in
        if _is_numbered_h2(elem):
            section_number += 1
            table_number = 0

        # Check if this is a table with a caption (skip SDL syntax tables)
        if elem.name == "table":
            caption = elem.find("caption")
            if caption and "sdl-syntax-table" not in elem.get("class", []):
                table_number += 1

                section_label = _section_label_for(section_number, annex_mapping)
                table_ref = f"{section_label}.{table_number}"

                # Store the table number for this caption ID
                if caption.get("id"):
                    table_numbers[caption.get("id")] = table_ref

                # Check if number is already added
                caption_text = caption.get_text()
                if not caption_text.startswith("Table "):
                    # Add the table number at the beginning
                    prefix = soup.new_tag("strong")
                    prefix.string = f"Table {table_ref}: "
                    caption.insert(0, prefix)
                    count += 1
                    logging.debug(f"Added table number: Table {table_ref}")
                else:
                    # Update existing table number
                    strong = caption.find("strong")
                    if strong:
                        old_text = strong.get_text()
                        if not old_text.startswith(f"Table {table_ref}"):
                            strong.string = f"Table {table_ref}: "
                            count += 1
                            logging.debug(f"Updated table number: {old_text} -> Table {table_ref}")

                # Add the has-table-number class to suppress CSS auto-numbering
                # This prevents CSS counter from adding a duplicate prefix
                current_classes = caption.get("class", [])
                if "has-table-number" not in current_classes:
                    current_classes.append("has-table-number")
                    caption["class"] = current_classes
                    logging.debug("Added has-table-number class to caption")

    # Update table cross-references (a.table-ref elements)
    count += _update_caption_cross_refs(soup, "table-ref", "Table", table_numbers)

    return count


def update_figure_numbers(soup: BeautifulSoup, annex_mapping: dict[str, str]) -> int:
    """
    Update figure numbers in captions and cross-references.

    For Annex sections, uses letter-based numbering (A-E).
    For other sections, uses numeric numbering.
    Also updates ``<a class="figure-ref">`` cross-references.

    Args:
        soup: Parsed HTML document.
        annex_mapping: Mapping produced by :func:`build_annex_mapping`.

    Returns:
        Number of figures updated.
    """
    count = 0
    figure_numbers: dict[str, str] = {}  # figure id -> display ref "5.1"

    # Find main element
    main = soup.find("main")
    if not main:
        logging.warning("No <main> element found")
        return 0

    section_number = 0
    figure_number = 0

    # Process all children of main
    for elem in main.children:
        if not hasattr(elem, "name"):
            continue

        # Track which h2 section we are in
        if _is_numbered_h2(elem):
            section_number += 1
            figure_number = 0

        # Check if this is a figure with a figcaption
        if elem.name == "figure":
            figcaption = elem.find("figcaption")
            if figcaption:
                figure_number += 1

                # Build the display reference for all figures
                section_label = _section_label_for(section_number, annex_mapping)
                figure_ref = f"{section_label}.{figure_number}"

                # Store the figure number for cross-reference updates
                fig_id = elem.get("id")
                if fig_id:
                    figure_numbers[fig_id] = figure_ref

                # Hardcode figure numbers for all sections (same approach
                # as table numbering) so Bikeshed's flat CSS counter is
                # overridden consistently.
                # Check if number is already added
                caption_text = figcaption.get_text()
                if not caption_text.startswith("Figure "):
                    # Add the figure number at the beginning
                    prefix = soup.new_tag("strong")
                    prefix.string = f"Figure {figure_ref}: "
                    figcaption.insert(0, prefix)
                    count += 1
                    logging.debug(f"Added figure number: Figure {figure_ref}")

                # Add the has-figure-number class to suppress CSS auto-numbering
                current_classes = figcaption.get("class", [])
                if "has-figure-number" not in current_classes:
                    current_classes.append("has-figure-number")
                    figcaption["class"] = current_classes
                    logging.debug("Added has-figure-number class to figcaption")

    # Update figure cross-references (a.figure-ref elements)
    count += _update_caption_cross_refs(soup, "figure-ref", "Figure", figure_numbers)

    return count


# ---------------------------------------------------------------------------
# Caption text fixup (post-numbering pass)
# ---------------------------------------------------------------------------


def update_table_figure_captions(soup: BeautifulSoup, annex_mapping: dict[str, str]) -> int:
    """
    Update table and figure captions to use letter-based numbering in Annex sections.

    This is a second pass that fixes any captions whose numeric prefix was inserted
    before the annex mapping was applied.

    Args:
        soup: Parsed HTML document.
        annex_mapping: Mapping produced by :func:`build_annex_mapping`.

    Returns:
        Number of captions updated.
    """
    count = 0

    # Process table captions
    for caption in soup.find_all("caption"):
        text = caption.get_text()

        # Check if the caption starts with "Table X." where X is a number or annex letter
        match = re.match(r"^Table\s+([A-Z]?\d+)((?:\.\d+)*)", text)
        if match:
            section_num = match.group(1)
            if is_annex_section(section_num, annex_mapping):
                # Replace the numeric section with the letter
                new_prefix = f"Table {convert_section_number(match.group(1) + match.group(2), annex_mapping)}"
                new_text = re.sub(r"^Table\s+[A-Z]?\d+(?:\.\d+)*", new_prefix, text)

                # Find the strong tag and update it
                strong = caption.find("strong")
                if strong:
                    strong.string = new_text.split(":")[0] + ": "
                    count += 1
                    logging.debug(f"Updated table caption: {text[:50]} -> {new_text[:50]}")

    # Process figure captions (if any)
    for figcaption in soup.find_all("figcaption"):
        text = figcaption.get_text()

        # Check if the caption starts with "Figure X." where X is a number or annex letter
        match = re.match(r"^Figure\s+([A-Z]?\d+)((?:\.\d+)*)", text)
        if match:
            section_num = match.group(1)
            if is_annex_section(section_num, annex_mapping):
                # Replace the numeric section with the letter
                new_prefix = f"Figure {convert_section_number(match.group(1) + match.group(2), annex_mapping)}"
                new_text = re.sub(r"^Figure\s+[A-Z]?\d+(?:\.\d+)*", new_prefix, text)
                figcaption.string = new_text
                count += 1
                logging.debug(f"Updated figure caption: {text[:50]} -> {new_text[:50]}")

    return count


# ---------------------------------------------------------------------------
# CSS injection for suppressing duplicate auto-numbering
# ---------------------------------------------------------------------------


def inject_figure_suppression_css(soup: BeautifulSoup) -> None:
    """
    Inject CSS to suppress auto-numbering for figures with hardcoded numbers.

    This prevents Bikeshed's CSS counter from adding "Figure X" when we've
    already added "Figure E.1:" manually for Annex figures.
    """
    # Check if CSS already exists
    head = soup.find("head")
    if not head:
        logging.warning("No <head> element found, cannot inject CSS")
        return

    # Check if our CSS is already present
    existing_style = head.find("style", id="annex-figure-suppression")
    if existing_style:
        logging.debug("Figure suppression CSS already present")
        return

    # Create new style element
    style_tag = soup.new_tag("style", id="annex-figure-suppression")
    style_tag.string = "\nfigcaption.has-figure-number::before { content: none !important; }\n"

    # Insert at the end of head (before </head>)
    head.insert(len(head.contents), style_tag)
    logging.debug("Injected figure suppression CSS")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def _apply_annex_transforms(
    soup: BeautifulSoup,
    annex_mapping: dict,
    annex_format: str = "prefix",
) -> str:
    """Apply all annex-renumbering transforms to *soup* and return the HTML string.

    Extracts the soup-mutation logic from :func:`renumber_annexes` so it can
    be shared with :func:`renumber_all` without intermediate file writes.
    """
    heading_count = update_section_headings(soup, annex_mapping, annex_format)
    if heading_count:
        logging.debug(f"Updated {heading_count} section headings")

    toc_count = update_toc_entries(soup, annex_mapping, annex_format)
    if toc_count:
        logging.debug(f"Updated {toc_count} TOC entries")

    xref_count = update_cross_references(soup, annex_mapping)
    if xref_count:
        logging.debug(f"Updated {xref_count} cross-references")

    text_ref_count = update_text_references(soup, annex_mapping)
    if text_ref_count:
        logging.debug(f"Updated {text_ref_count} text references")

    table_count = update_table_numbers(soup, annex_mapping)
    if table_count:
        logging.debug(f"Updated {table_count} table numbers")

    figure_count = update_figure_numbers(soup, annex_mapping)
    if figure_count:
        logging.debug(f"Updated {figure_count} figure numbers")

    caption_count = update_table_figure_captions(soup, annex_mapping)
    if caption_count:
        logging.debug(f"Updated {caption_count} table/figure captions")

    html_output = str(soup)
    if "has-figure-number" in html_output and "annex-figure-suppression" not in html_output:
        css_injection = '<style id="annex-figure-suppression">\nfigcaption.has-figure-number::before { content: none !important; }\n</style>\n</head>'
        html_output = html_output.replace("</head>", css_injection)
        logging.debug("Injected figure suppression CSS via string replacement")

    total = (
        heading_count
        + toc_count
        + xref_count
        + text_ref_count
        + table_count
        + figure_count
        + caption_count
    )
    logging.debug(f"Total updates: {total}")
    return html_output


def renumber_annexes(html_path: Path, annex_format: str = "prefix") -> None:
    """
    Main function to renumber Annex sections in HTML.

    Reads the HTML file, detects Annex sections, applies all renumbering
    transforms (headings, TOC, cross-references, captions), injects CSS
    overrides, and writes the result back to the same file.

    Args:
        html_path: Path to the HTML file to process (modified in place).
        annex_format: ``"prefix"`` for ``"Annex A. Title"`` or ``"letter"``
            for ``"A. Title"`` in headings and TOC.
    """
    logging.debug("=" * 60)
    logging.debug("Renumbering Annex sections to alphabetic notation")
    logging.debug("=" * 60)

    with open(html_path, encoding="utf-8") as f:
        html_content = f.read()

    soup = BeautifulSoup(html_content, "html.parser")
    annex_mapping = build_annex_mapping(soup)

    if not annex_mapping:
        # No Annex sections: the alphabetic-renumbering transforms are all
        # no-ops, but figure/table numbering and the ``figure-ref``/``table-ref``
        # cross-reference text fixups must still run (otherwise HTML cross-refs
        # render as a bare "Figure"/"Table" while the PDF path numbers them).
        # Apply the transforms with an empty mapping → numeric numbering only.
        logging.debug("No Annex sections found - applying numeric numbering only")

    html_output = _apply_annex_transforms(soup, annex_mapping, annex_format)

    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html_output)

    logging.debug("Annex renumbering completed successfully")
    logging.debug("=" * 60)


# ---------------------------------------------------------------------------
# Note and example numbering (ISO rules: reset per top-level clause)
# ---------------------------------------------------------------------------


def update_note_numbers(soup: BeautifulSoup) -> int:
    """Number NOTE divs per top-level clause following ISO style.

    Per ISO rules notes are numbered NOTE, NOTE 2, NOTE 3 … within each
    top-level clause (reset at each new h2).  The label text inside each
    ``.note`` div (``<p class="marker">NOTE</p>`` or the first text node
    starting with "NOTE") is updated to reflect the counter.

    Returns:
        Number of note elements relabelled.
    """
    count = 0
    note_counter = 0

    def _reset():
        nonlocal note_counter
        note_counter = 0

    main = soup.find("main") or soup.find("body")
    if not main:
        return 0

    for elem in main.descendants:
        if not isinstance(elem, Tag):
            continue

        # Reset counter at each top-level h2 (new clause)
        if elem.name == "h2" and "heading" in elem.get("class", []):
            _reset()
            continue

        # Detect note divs (various class forms used by Bikeshed)
        classes = elem.get("class", [])
        is_note = elem.name in ("div", "aside") and any(
            c in classes for c in ("note", "note-block", "advisement")
        )
        if not is_note:
            # Also check <p class="note">
            is_note = elem.name == "p" and "note" in classes

        if not is_note:
            continue

        note_counter += 1
        label_text = "NOTE" if note_counter == 1 else f"NOTE {note_counter}"
        _inject_block_label(elem, "NOTE", label_text)
        count += 1

    return count


def update_example_numbers(soup: BeautifulSoup) -> int:
    """Number EXAMPLE divs per top-level clause following ISO style.

    Returns:
        Number of example elements relabelled.
    """
    count = 0
    example_counter = 0

    main = soup.find("main") or soup.find("body")
    if not main:
        return 0

    for elem in main.descendants:
        if not isinstance(elem, Tag):
            continue

        if elem.name == "h2" and "heading" in elem.get("class", []):
            example_counter = 0
            continue

        classes = elem.get("class", [])
        is_example = elem.name in ("div", "aside") and any(
            c in classes for c in ("example", "example-block")
        )
        if not is_example:
            continue

        example_counter += 1
        label_text = "EXAMPLE" if example_counter == 1 else f"EXAMPLE {example_counter}"
        _inject_block_label(elem, "EXAMPLE", label_text)
        count += 1

    return count


def _inject_block_label(elem: Tag, old_prefix: str, new_label: str) -> None:
    """Update or inject a label into a note/example block element.

    Looks for an existing label span/p whose text starts with *old_prefix*
    and replaces its text.  If none is found, prepends a ``<p>`` label.
    """
    # Look for an existing marker paragraph or span
    for candidate in elem.find_all(["p", "span", "strong"], limit=5):
        text = candidate.get_text(strip=True)
        if text.upper().startswith(old_prefix):
            # Preserve trailing colon/dash if present
            suffix = text[len(old_prefix) :].lstrip()
            if suffix and suffix[0] in (":", "—", "–", "-"):
                candidate.string = f"{new_label}{suffix[0]} "
            else:
                candidate.string = new_label
            return

    # No existing label — prepend one
    from bs4 import BeautifulSoup as _BS

    label_frag = _BS(f"<p><strong>{new_label}</strong></p>", "html.parser")
    first_child = next((c for c in elem.children if isinstance(c, Tag)), None)
    if first_child:
        first_child.insert_before(label_frag)
    else:
        elem.append(label_frag)


def update_equation_numbers(soup: BeautifulSoup, annex_map: dict[str, str]) -> int:
    """Renumber display equations using annex letter mapping.

    Scans for ``.equation-wrapper`` divs (as injected by ``equations.py``)
    and updates the ``.equation-number`` span text and ``id`` attribute to
    use annex letter labels (e.g. ``(A.1)`` instead of ``(10.1)``).

    Args:
        soup:       BeautifulSoup document (mutated in place).
        annex_map:  Mapping from numeric section number to annex letter,
                    e.g. ``{'10': 'A', '11': 'B'}``.  From
                    :func:`build_annex_mapping`.

    Returns:
        Number of equation labels updated.
    """
    if not annex_map:
        return 0

    count = 0
    for span in soup.find_all("span", class_="equation-number"):
        eq_id = span.get("id", "")
        # ID format: eq-10-3 → eq-A-3
        id_parts = eq_id.split("-") if eq_id else []
        if len(id_parts) >= 3 and id_parts[0] == "eq":
            sec_num = id_parts[1]
            if sec_num in annex_map:
                letter = annex_map[sec_num]
                new_id = f"eq-{letter}-{id_parts[2]}"
                span["id"] = new_id
                # Update text: (10.3) → (A.3)
                text = span.get_text(strip=True)
                new_text = re.sub(
                    r"\(" + re.escape(sec_num) + r"\.",
                    f"({letter}.",
                    text,
                )
                span.string = new_text
                # Also update any parent wrapper
                parent = span.parent
                if parent and "equation-wrapper" in parent.get("class", []):
                    # Update data-eq-id if present
                    if parent.get("id") == eq_id:
                        parent["id"] = new_id
                count += 1

    # Update cross-references to renamed equation IDs
    for link in soup.find_all("a", href=True):
        href = link["href"]
        if href.startswith("#eq-"):
            parts = href[1:].split("-")
            if len(parts) >= 3 and parts[1] in annex_map:
                letter = annex_map[parts[1]]
                new_href = f"#eq-{letter}-{parts[2]}"
                link["href"] = new_href
                # Update link text if it contains the old number
                text = link.get_text(strip=True)
                new_text = re.sub(
                    r"\(" + re.escape(parts[1]) + r"\.",
                    f"({letter}.",
                    text,
                )
                if new_text != text:
                    link.string = new_text

    return count


def renumber_all(html_path: Path, annex_format: str = "prefix") -> None:
    """Run all renumbering passes: annexes, equations, notes, and examples.

    This is the recommended entry point when all numbering must be updated
    together.  Equivalent to calling :func:`renumber_annexes` plus the
    note/example/equation passes in one go.

    Args:
        html_path:    Path to the HTML file to process (modified in place).
        annex_format: ``"prefix"`` or ``"letter"`` — passed to
                      :func:`_apply_annex_transforms`.
    """
    with open(html_path, encoding="utf-8") as f:
        soup = BeautifulSoup(f.read(), "html.parser")

    annex_mapping = build_annex_mapping(soup)

    note_count = update_note_numbers(soup)
    example_count = update_example_numbers(soup)
    logging.info(f"Note/example numbering: {note_count} notes, {example_count} examples")

    if annex_mapping:
        eq_count = update_equation_numbers(soup, annex_mapping)
        if eq_count:
            logging.info(f"Equation renumbering: {eq_count} equation labels updated")
        html_output = _apply_annex_transforms(soup, annex_mapping, annex_format)
    else:
        html_output = str(soup)

    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html_output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Renumber Annex sections from numeric to alphabetic notation."
    )
    parser.add_argument("html_file", type=Path, help="Path to the HTML file to process.")
    parser.add_argument(
        "--format",
        choices=["prefix", "letter"],
        default="prefix",
        help=(
            'Annex heading format: "prefix" for "Annex A. Title", '
            '"letter" for "A. Title" (default: prefix).'
        ),
    )
    args = parser.parse_args()

    if not args.html_file.exists():
        logging.error(f"HTML file not found: {args.html_file}")
        sys.exit(1)

    renumber_annexes(args.html_file, annex_format=args.format)
