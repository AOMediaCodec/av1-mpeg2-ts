"""Table of Changes -- per-section change summary.

Generates a structured table listing which sections of the specification
were modified since a given baseline (git tag, branch, or commit).  The
table is injected into the compiled HTML, typically after the Table of
Contents.

This complements the existing change-bars feature (which marks individual
paragraphs) by providing a high-level overview suitable for ballot
documents and editorial review.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from specbuild.theme import THEME
from specbuild.utils import get_bs4, inject_css, read_html, write_html

# ---------------------------------------------------------------------------
# Section-change analysis
# ---------------------------------------------------------------------------


def get_section_changes(
    soup: Any,
    changed_lines: dict[str, set[int]],
) -> list[dict]:
    """Map changed source lines to specification sections.

    Walks elements with ``data-bs-line`` attributes (set by Bikeshed during
    compilation), determines which section heading they belong to, and
    aggregates change counts per section.

    Args:
        soup: BeautifulSoup document.
        changed_lines: Mapping of ``{filename: {line_numbers}}`` from
            :func:`specbuild.changebars.get_changed_lines`.

    Returns:
        Sorted list of dicts, each with:
        - ``section_id``: the heading's ``id`` attribute
        - ``section_number``: section number string (e.g., "5.2.1")
        - ``section_title``: heading text (e.g., "5.2.1. Frame Geometry")
        - ``change_count``: number of changed elements in this section
    """
    # Pre-flatten all changed lines for elements without filename prefixes
    all_changed_lines: set[int] = set()
    for lines in changed_lines.values():
        all_changed_lines.update(lines)

    if not all_changed_lines:
        return []

    # Build a section map: list of (heading_element, id, position_index)
    # for headings h2-h6 that carry an id attribute.
    heading_tags = {"h2", "h3", "h4", "h5", "h6"}
    headings: list[tuple[Any, str, int]] = []
    for idx, elem in enumerate(soup.find_all(heading_tags)):
        heading_id = elem.get("id")
        if heading_id:
            headings.append((elem, heading_id, idx))

    if not headings:
        logging.info("No section headings found; cannot build table of changes")
        return []

    # Extract section number and full title from each heading
    _secnum_re = re.compile(r"^([\d]+(?:\.[\d]+)*)")

    heading_info: list[dict] = []
    for elem, heading_id, pos_idx in headings:
        title = elem.get_text(strip=True)
        match = _secnum_re.match(title)
        section_number = match.group(1) if match else ""
        heading_info.append(
            {
                "element": elem,
                "section_id": heading_id,
                "section_number": section_number,
                "section_title": title,
                "position": pos_idx,
                "change_count": 0,
            }
        )

    # Walk all elements with data-bs-line and check for changes
    for elem in soup.find_all(attrs={"data-bs-line": True}):
        bs_line = elem["data-bs-line"]

        # Parse "filename.bs:lineno" or just "lineno"
        if ":" in bs_line:
            parts = bs_line.split(":", 1)
            filename = parts[0]
            try:
                line_no = int(parts[1])
            except ValueError:
                continue
        else:
            try:
                line_no = int(bs_line)
            except ValueError:
                continue
            filename = None

        # Check if this line is in the changed set
        if filename and filename in changed_lines:
            is_changed = line_no in changed_lines[filename]
        elif filename is None:
            is_changed = line_no in all_changed_lines
        else:
            is_changed = False

        if not is_changed:
            continue

        # Find the nearest preceding heading for this element.
        # Walk up through parents and preceding siblings to find it.
        owning_section = _find_owning_section(elem, heading_info)
        if owning_section is not None:
            owning_section["change_count"] += 1

    # Filter to sections with at least 1 change, sort by document order
    result = [
        {
            "section_id": h["section_id"],
            "section_number": h["section_number"],
            "section_title": h["section_title"],
            "change_count": h["change_count"],
        }
        for h in heading_info
        if h["change_count"] > 0
    ]

    logging.info(
        f"Table of changes: {len(result)} sections affected, "
        f"{sum(r['change_count'] for r in result)} total changes"
    )
    return result


def _find_owning_section(elem: Any, heading_info: list[dict]) -> dict | None:
    """Find the heading_info entry whose section contains *elem*.

    Walks up the DOM from *elem*, checking if any ancestor or preceding
    sibling is one of the tracked heading elements.  Returns the last
    heading (in document order) that precedes *elem*.

    Args:
        elem: A BeautifulSoup element to locate within a section.
        heading_info: The heading metadata list built by
            :func:`get_section_changes`.

    Returns:
        The matching heading_info dict, or ``None`` if no heading found.
    """
    # Build a lookup from heading element identity to heading_info entry
    elem_to_info = {id(h["element"]): h for h in heading_info}

    # Strategy: walk up through parents.  For each parent, check preceding
    # siblings (in reverse) for heading elements.  The first heading found
    # this way is the nearest preceding heading.
    node = elem
    while node:
        # Check preceding siblings of current node
        sibling = node.previous_sibling
        while sibling is not None:
            # The sibling itself might be a heading
            info = elem_to_info.get(id(sibling))
            if info is not None:
                return info
            # Or a heading might be nested inside the sibling (e.g., inside
            # a <section> wrapper).  Find the *last* heading in document
            # order within this sibling subtree.
            if hasattr(sibling, "find_all"):
                heading_tags = {"h2", "h3", "h4", "h5", "h6"}
                nested = [h for h in sibling.find_all(heading_tags) if id(h) in elem_to_info]
                if nested:
                    # Return the last one (closest preceding in document order)
                    return elem_to_info[id(nested[-1])]
            sibling = sibling.previous_sibling

        # Move up to the parent
        node = node.parent

    return None


# ---------------------------------------------------------------------------
# HTML injection -- file-level entry point
# ---------------------------------------------------------------------------


def inject_table_of_changes(
    html_path: Path,
    changed_lines: dict[str, set[int]],
    baseline_label: str = "previous version",
) -> int:
    """Insert a Table of Changes into a compiled HTML specification file.

    File-based wrapper around :func:`inject_table_of_changes_soup`.

    Args:
        html_path: Path to the compiled ``index.html``.
        changed_lines: Mapping of ``.bs`` filename to set of changed line
            numbers, as returned by
            :func:`specbuild.changebars.get_changed_lines`.
        baseline_label: Human-readable label for the baseline reference.

    Returns:
        Number of sections listed in the table (0 if nothing was inserted).
    """
    try:
        get_bs4()
    except ImportError:
        logging.warning("BeautifulSoup not available, skipping table of changes")
        return 0

    if not changed_lines:
        logging.info("No changed lines; skipping table of changes")
        return 0

    logging.info(f"Generating table of changes for {html_path.name}")

    soup = read_html(html_path)
    changes = get_section_changes(soup, changed_lines)

    if not changes:
        logging.info("No section changes detected; skipping table of changes")
        return 0

    if inject_table_of_changes_soup(soup, changes, baseline_label):
        write_html(html_path, soup)
        return len(changes)

    return 0


# ---------------------------------------------------------------------------
# HTML injection -- soup-level entry point
# ---------------------------------------------------------------------------


def inject_table_of_changes_soup(
    soup: Any,
    changes: list[dict],
    baseline_label: str = "previous version",
) -> bool:
    """Insert a Table of Changes into the specification HTML.

    The table is inserted after the Table of Contents (``<div id="toc">``)
    or after the abstract (``<div id="abstract">``).

    Args:
        soup: BeautifulSoup document to modify.
        changes: Section change list from :func:`get_section_changes`.
        baseline_label: Human-readable label for the baseline reference
            (e.g., "v2.0", "main@abc1234").

    Returns:
        True if the table was successfully injected.
    """
    if not changes:
        return False

    toc_div = _build_table_of_changes(soup, changes, baseline_label)

    if not _insert_toc_div(soup, toc_div):
        return False

    _inject_table_of_changes_css(soup)

    total_changes = sum(c["change_count"] for c in changes)
    logging.info(
        f"Inserted table of changes: {len(changes)} sections, "
        f"{total_changes} total changes (baseline: {baseline_label})"
    )
    return True


# ---------------------------------------------------------------------------
# Table construction helpers
# ---------------------------------------------------------------------------


def _build_table_of_changes(
    soup: Any,
    changes: list[dict],
    baseline_label: str,
) -> Any:
    """Build the ``<div id="table-of-changes">`` element and its table.

    Args:
        soup: BeautifulSoup document used as a tag factory.
        changes: Section change list from :func:`get_section_changes`.
        baseline_label: Human-readable baseline label for the description.

    Returns:
        The constructed ``<div>`` element (not yet inserted into *soup*).
    """
    container = soup.new_tag("div", id="table-of-changes")

    heading = soup.new_tag("h2", **{"class": "no-num no-toc"})
    heading.string = "Table of Changes"
    container.append(heading)

    desc = soup.new_tag("p")
    desc.string = f"The following sections have been modified since {baseline_label}:"
    container.append(desc)

    table = soup.new_tag("table")

    # Header
    thead = soup.new_tag("thead")
    header_row = soup.new_tag("tr")
    for col_name in ("Section", "Changes"):
        th = soup.new_tag("th")
        th.string = col_name
        header_row.append(th)
    thead.append(header_row)
    table.append(thead)

    # Body
    tbody = soup.new_tag("tbody")
    for entry in changes:
        row = soup.new_tag("tr")

        # Section column -- linked to section heading
        td_section = soup.new_tag("td")
        link = soup.new_tag("a", href=f"#{entry['section_id']}")
        link.string = entry["section_title"]
        td_section.append(link)
        row.append(td_section)

        # Change count column
        td_count = soup.new_tag("td", **{"class": "change-count"})
        td_count.string = str(entry["change_count"])
        row.append(td_count)

        tbody.append(row)
    table.append(tbody)

    container.append(table)
    return container


# ---------------------------------------------------------------------------
# Insertion-point detection
# ---------------------------------------------------------------------------


def _insert_toc_div(soup: Any, toc_div: Any) -> bool:
    """Find the best insertion point and place *toc_div* into *soup*.

    Insertion strategy (first match wins):
      1. After ``<div id="toc">`` (Table of Contents)
      2. After ``<div id="abstract">``
      3. Before the first ``<h2>`` inside ``<main>``
      4. At the top of ``<main>``

    Args:
        soup: BeautifulSoup document to insert into.
        toc_div: The table-of-changes ``<div>`` to insert.

    Returns:
        ``True`` if insertion succeeded, ``False`` otherwise.
    """
    # Try after TOC
    anchor = soup.find("div", id="toc")
    if not anchor:
        # Try after abstract
        anchor = soup.find("div", id="abstract")

    if anchor:
        anchor.insert_after(toc_div)
        return True

    # Fallback: insert before the first <h2> in <main>
    main = soup.find("main")
    if main:
        first_h2 = main.find("h2")
        if first_h2:
            first_h2.insert_before(toc_div)
        else:
            main.insert(0, toc_div)
        return True

    logging.warning("Cannot find insertion point for table of changes")
    return False


# ---------------------------------------------------------------------------
# CSS injection
# ---------------------------------------------------------------------------


def _inject_table_of_changes_css(soup: Any) -> None:
    """Inject scoped CSS for the table of changes.

    All values that depend on the active colour theme are interpolated from
    :data:`specbuild.theme.THEME`.

    Args:
        soup: BeautifulSoup document to inject the ``<style>`` block into.
    """
    t = THEME
    css = f"""
/* Table of Changes - per-section change summary */
#table-of-changes {{
    margin: 2em 0;
    padding: 1em 1.5em;
    border: 1px solid {t.color_border};
    border-radius: 4px;
    background: {t.color_bg_subtle};
}}
#table-of-changes h2 {{
    font-size: {t.rev_heading_font_size};
    margin-top: 0;
}}
#table-of-changes p {{
    margin: 0.5em 0;
    color: {t.color_muted};
}}
#table-of-changes table {{
    width: 100%;
    border-collapse: collapse;
    margin-top: 0.5em;
    font-size: {t.rev_table_font_size};
}}
#table-of-changes th,
#table-of-changes td {{
    padding: 0.4em 0.8em;
    border: 1px solid {t.color_border_light};
    text-align: left;
}}
#table-of-changes th {{
    background: {t.color_bg_muted};
    font-weight: 600;
}}
#table-of-changes tr:nth-child(even) td {{
    background: #f8f8f8;
}}
#table-of-changes .change-count {{
    text-align: center;
    font-weight: 500;
}}
#table-of-changes a {{
    color: {t.color_accent};
    text-decoration: none;
}}
#table-of-changes a:hover {{
    text-decoration: underline;
}}
@media print {{
    #table-of-changes {{
        border: 1pt solid {t.color_border};
        background: white;
        page-break-inside: avoid;
    }}
    #table-of-changes table {{
        font-size: {t.footer_font_size}pt;
    }}
}}
"""
    inject_css(soup, "table-of-changes-css", css)
