#!/usr/bin/env python3
"""
Generate List of Figures (LOF) and List of Tables (LOT) for PDF generation.

This script extracts all figures and tables from the compiled HTML specification
and creates dedicated navigable lists with page numbers, similar to the Table of
Contents.  The generated lists are injected into the HTML file after the TOC,
along with companion CSS styles.

Two layout modes are supported:
  - "list"  -- an ordered list styled with CSS leaders (default)
  - "table" -- an HTML table with caption + page-number columns

Usage (standalone):
    python generate_lof_lot.py index.html [--no-lof] [--no-lot] [--format table]
"""

from __future__ import annotations

import logging
import re
import sys
from pathlib import Path

from bs4 import BeautifulSoup, Tag

# Allow importing from the specbuild package when running as a standalone script.
_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from specbuild.theme import THEME  # noqa: E402

logger = logging.getLogger(__name__)
# Add NullHandler to prevent warnings if logging is not configured by the calling code
logger.addHandler(logging.NullHandler())

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Regex that strips a "Figure 3.2:" or "Table A.1." prefix from caption text.
# Handles alphanumeric section/item numbers (e.g. E.1, A.1) and an optional
# colon or period separator.
_FIGURE_PREFIX_RE = re.compile(r"^Figure\s+[\w]+\.[\w]+[:\.]?\s*")
_TABLE_PREFIX_RE = re.compile(r"^Table\s+[\w]+\.[\w]+[:\.]?\s*")

# Column widths for the two-column table layout (caption + page number).
_TABLE_CAPTION_COL_WIDTH = "465pt"
_TABLE_PAGE_COL_WIDTH = "75pt"

# Number of " ." pairs used to fill leader-dot spans in table format.
_LEADER_DOT_COUNT = 100

# CSS table classes that should be skipped when scanning for specification tables.
_SKIP_TABLE_CLASSES = {"toc-table", "sdl-syntax-table"}

# Type alias for the tuple returned by extraction helpers.
# Fields: (element_id, caption_text, section_number, item_number)
CaptionEntry = tuple[str, str, str, str]


# ---------------------------------------------------------------------------
# Extraction helpers -- pull figures / tables from parsed HTML
# ---------------------------------------------------------------------------


def extract_figures_from_html(soup: BeautifulSoup) -> list[CaptionEntry]:
    """Extract all ``<figure>`` elements that have a ``<figcaption>``.

    Args:
        soup: Parsed HTML document.

    Returns:
        List of :pydata:`CaptionEntry` tuples, one per captioned figure.
    """
    figures: list[CaptionEntry] = []

    for figure in soup.find_all("figure"):
        figcaption = figure.find("figcaption")
        if not figcaption:
            continue

        # Bikeshed may place the id on either the <figure> or the <figcaption>.
        figure_id = figure.get("id", "") or figcaption.get("id", "")
        if not figure_id:
            continue

        caption_text = figcaption.get_text(strip=True)
        caption_text = _FIGURE_PREFIX_RE.sub("", caption_text)

        figures.append((figure_id, caption_text, "", ""))

    (logger.info if figures else logger.debug)(f"Extracted {len(figures)} figures from HTML")
    return figures


def _find_table_id(table: Tag, fallback_index: int) -> str:
    """Resolve an id for a ``<table>`` element.

    The lookup order is:
      1. ``id`` attribute on the ``<table>`` itself
      2. ``id`` attribute on its ``<caption>``
      3. ``id`` on the nearest ancestor (up to ``<body>``)
      4. Auto-generated ``table-<fallback_index>`` (also written back onto the element)

    Args:
        table:          A BeautifulSoup ``<table>`` Tag.
        fallback_index: Integer used when no existing id can be found.

    Returns:
        The resolved id string.
    """
    table_id = table.get("id", "")
    if table_id:
        return table_id

    caption = table.find("caption")
    if caption:
        table_id = caption.get("id", "")
        if table_id:
            return table_id

    # Walk ancestors looking for an id.
    parent = table.parent
    while parent and parent.name != "body":
        if parent.get("id"):
            return parent.get("id")
        parent = parent.parent

    # Last resort: generate a synthetic id and write it into the DOM.
    table_id = f"table-{fallback_index}"
    table["id"] = table_id
    return table_id


def extract_tables_from_html(soup: BeautifulSoup) -> list[CaptionEntry]:
    """Extract all ``<table>`` elements that have a ``<caption>``.

    Tables whose CSS class is in :pydata:`_SKIP_TABLE_CLASSES` (e.g. TOC tables,
    SDL syntax tables) are excluded.

    Args:
        soup: Parsed HTML document.

    Returns:
        List of :pydata:`CaptionEntry` tuples, one per captioned table.
    """
    tables: list[CaptionEntry] = []

    for table in soup.find_all("table"):
        # Skip non-content tables (TOC, SDL syntax, etc.)
        if table.has_attr("class"):
            classes = set(table.get("class", []))
            if classes & _SKIP_TABLE_CLASSES:
                continue

        caption = table.find("caption")
        if not caption:
            continue

        table_id = _find_table_id(table, fallback_index=len(tables))

        caption_text = caption.get_text(strip=True)
        caption_text = _TABLE_PREFIX_RE.sub("", caption_text)

        tables.append((table_id, caption_text, "", ""))

    (logger.info if tables else logger.debug)(f"Extracted {len(tables)} tables from HTML")
    return tables


# ---------------------------------------------------------------------------
# HTML generation helpers -- build LOF / LOT markup
# ---------------------------------------------------------------------------


def _build_table_entry(entry_id: str, caption_text: str, kind: str) -> str:
    """Return an HTML ``<tr>`` for one entry in a table-format LOF/LOT.

    Args:
        entry_id:     The ``id`` attribute of the target element.
        caption_text: Display text for the caption (prefix already stripped).
        kind:         ``"lof"`` or ``"lot"`` -- controls CSS class names.

    Returns:
        HTML fragment for one table row.
    """
    number_class = "figure-number" if kind == "lof" else "table-number"
    leader_dots = " ." * _LEADER_DOT_COUNT

    row = f'<tr class="{kind}-entry">\n'
    row += f'<td class="{kind}-caption">\n'
    row += f'<a href="#{entry_id}">'
    row += f'<span class="{number_class}" data-target="{entry_id}"></span>'
    row += f'<span class="caption-text">{caption_text}</span>'
    row += f'<span class="{kind}-leader">{leader_dots}</span>'
    row += "</a>\n</td>\n"
    row += f'<td class="{kind}-page">'
    row += (
        f'<a href="#{entry_id}">'
        f'<span class="{kind}-page-number" data-target="{entry_id}">000</span></a>'
    )
    row += "</td>\n</tr>\n"
    return row


def _build_list_entry(entry_id: str, caption_text: str, kind: str) -> str:
    """Return an HTML ``<li>`` for one entry in a list-format LOF/LOT.

    Args:
        entry_id:     The ``id`` attribute of the target element.
        caption_text: Display text for the caption (prefix already stripped).
        kind:         ``"lof"`` or ``"lot"`` -- controls CSS class names.

    Returns:
        HTML fragment for one list item.
    """
    number_class = "figure-number" if kind == "lof" else "table-number"

    item = f'<li class="{kind}-entry">\n'
    item += f'<a href="#{entry_id}">'
    item += f'<span class="{number_class}" data-target="{entry_id}"></span>'
    item += f'<span class="caption-text">{caption_text}</span>'
    item += f'<span class="{kind}-page-number" data-target="{entry_id}">0</span>'
    item += "</a>\n</li>\n"
    return item


def _build_nav_html(
    entries: list[CaptionEntry],
    nav_id: str,
    css_class: str,
    heading: str,
    kind: str,
    format_style: str,
) -> str:
    """Build a complete ``<nav>`` block for either LOF or LOT.

    This is the shared core used by :func:`create_lof_html` and
    :func:`create_lot_html` so that both layouts (table / list) are generated
    by the same logic.

    Args:
        entries:      List of :pydata:`CaptionEntry` tuples.
        nav_id:       Value for the ``<nav id="…">`` attribute (e.g. ``"lof"``).
        css_class:    CSS class for the ``<nav>`` wrapper.
        heading:      Text for the ``<h2>`` heading.
        kind:         ``"lof"`` or ``"lot"``.
        format_style: ``"table"`` or ``"list"``.

    Returns:
        Complete HTML string, or ``""`` if *entries* is empty.
    """
    if not entries:
        return ""

    html = f'<nav id="{nav_id}" class="{css_class}">\n'
    html += f"<h2>{heading}</h2>\n"

    if format_style == "table":
        html += f'<table class="{kind}-table">\n'
        html += "<colgroup>\n"
        html += f'<col style="width: {_TABLE_CAPTION_COL_WIDTH};">\n'
        html += f'<col style="width: {_TABLE_PAGE_COL_WIDTH};">\n'
        html += "</colgroup>\n<tbody>\n"
        for _idx, (entry_id, caption_text, _, _) in enumerate(entries, 1):
            html += _build_table_entry(entry_id, caption_text, kind)
        html += "</tbody>\n</table>\n"
    else:
        html += f'<ol class="{kind}">\n'
        for _idx, (entry_id, caption_text, _, _) in enumerate(entries, 1):
            html += _build_list_entry(entry_id, caption_text, kind)
        html += "</ol>\n"

    html += "</nav>\n"
    return html


def create_lof_html(figures: list[CaptionEntry], format_style: str = "list") -> str:
    """Create HTML for a List of Figures.

    Args:
        figures:      List of :pydata:`CaptionEntry` tuples as returned by
                      :func:`extract_figures_from_html`.
        format_style: ``"list"`` for an ordered-list layout or ``"table"`` for
                      a two-column table layout with leader dots.

    Returns:
        Complete ``<nav>`` HTML string, or ``""`` when *figures* is empty.
    """
    return _build_nav_html(
        figures,
        nav_id="lof",
        css_class="list-of-figures",
        heading="List of Figures",
        kind="lof",
        format_style=format_style,
    )


def create_lot_html(tables: list[CaptionEntry], format_style: str = "list") -> str:
    """Create HTML for a List of Tables.

    Args:
        tables:       List of :pydata:`CaptionEntry` tuples as returned by
                      :func:`extract_tables_from_html`.
        format_style: ``"list"`` for an ordered-list layout or ``"table"`` for
                      a two-column table layout with leader dots.

    Returns:
        Complete ``<nav>`` HTML string, or ``""`` when *tables* is empty.
    """
    return _build_nav_html(
        tables,
        nav_id="lot",
        css_class="list-of-tables",
        heading="List of Tables",
        kind="lot",
        format_style=format_style,
    )


# ---------------------------------------------------------------------------
# HTML injection -- insert LOF / LOT into the specification document
# ---------------------------------------------------------------------------


def inject_lof_lot_into_html(
    html_path: Path, lof_enabled: bool = True, lot_enabled: bool = True, format_style: str = "list"
) -> bool:
    """Inject List of Figures and List of Tables into an HTML file.

    Both lists are inserted immediately after the Table of Contents
    (``<nav id="toc">``), with the LOF first and the LOT second.

    Args:
        html_path:    Path to the HTML file to modify in place.
        lof_enabled:  Whether to generate the List of Figures.
        lot_enabled:  Whether to generate the List of Tables.
        format_style: ``"list"`` or ``"table"`` layout.

    Returns:
        ``True`` if at least one list was injected successfully.
    """
    logger.info(f"Injecting LOF/LOT into {html_path}")

    try:
        with open(html_path, encoding="utf-8") as f:
            html_content = f.read()

        soup = BeautifulSoup(html_content, "html.parser")

        # Extract figures and tables
        figures = extract_figures_from_html(soup) if lof_enabled else []
        tables = extract_tables_from_html(soup) if lot_enabled else []

        if not figures and not tables:
            logger.warning("No figures or tables found to create lists")
            return False

        # Find the TOC to insert LOF/LOT after it
        toc = soup.find("nav", id="toc")
        if not toc:
            logger.warning("No TOC found, cannot insert LOF/LOT")
            return False

        # Create LOF HTML
        if lof_enabled and figures:
            lof_html = create_lof_html(figures, format_style)
            lof_soup = BeautifulSoup(lof_html, "html.parser")
            lof_nav = lof_soup.find("nav", id="lof")
            if lof_nav:
                toc.insert_after(lof_nav)
                logger.info(f"Inserted List of Figures with {len(figures)} entries")

        # Create LOT HTML (insert after LOF if both enabled)
        if lot_enabled and tables:
            lot_html = create_lot_html(tables, format_style)
            lot_soup = BeautifulSoup(lot_html, "html.parser")
            lot_nav = lot_soup.find("nav", id="lot")
            if lot_nav:
                # Insert after LOF if it exists, otherwise after TOC
                insert_after = soup.find("nav", id="lof") or toc
                insert_after.insert_after(lot_nav)
                logger.info(f"Inserted List of Tables with {len(tables)} entries")

        # Write back to file
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(str(soup))

        logger.info("Successfully injected LOF/LOT into HTML")
        return True

    except Exception as e:
        logger.error(f"Failed to inject LOF/LOT: {e}")
        import traceback

        traceback.print_exc()
        return False


# ---------------------------------------------------------------------------
# CSS generation -- companion styles for LOF / LOT markup
# ---------------------------------------------------------------------------


def _css_table_format(use_leaders: bool) -> str:
    """Return CSS for the table-based LOF/LOT layout.

    Args:
        use_leaders: When ``False``, leader-dot spans are hidden via
                     ``display: none``.

    Returns:
        CSS string (without enclosing ``<style>`` tags).
    """
    theme = THEME

    css = f"""
/* List of Figures and List of Tables - Table Format (Chrome Headless PDF) */

#lof, #lot {{
    border: none !important;
    outline: none !important;
    box-shadow: none !important;
}}

#lof h2, #lot h2 {{
    text-align: center;
    margin-bottom: 12pt;
    font-size: {theme.toc_heading_font_size};
    font-weight: bold;
}}

table.lof-table, table.lot-table {{
    width: 100% !important;
    table-layout: fixed !important;
    border-collapse: collapse;
    border: none !important;
    outline: none !important;
    box-shadow: none !important;
    font-size: {theme.toc_font_size};
    line-height: {theme.toc_line_height};
    margin: 0;
}}

table.lof-table tr, table.lot-table tr {{
    page-break-inside: avoid;
    border: none !important;
}}

table.lof-table td, table.lot-table td {{
    padding: 3pt 0;
    vertical-align: top;
    border: none !important;
}}

table.lof-table td.lof-caption,
table.lot-table td.lot-caption {{
    width: 86% !important;
    padding-right: 5pt;
    overflow: hidden;
    white-space: nowrap;
}}

table.lof-table td.lof-caption a,
table.lot-table td.lot-caption a {{
    color: {theme.color_accent};
    text-decoration: none !important;
    display: block;
    overflow: hidden;
    white-space: nowrap;
    text-overflow: ellipsis;
}}

table.lof-table td.lof-caption .figure-number,
table.lot-table td.lot-caption .table-number {{
    font-weight: bold;
    color: {theme.color_accent};
    margin-right: 0.5em;
    white-space: nowrap;
}}

table.lof-table td.lof-caption .caption-text,
table.lot-table td.lot-caption .caption-text {{
    color: {theme.color_accent};
}}

.lof-leader, .lot-leader {{
    color: {theme.color_muted};
    font-weight: normal;
    overflow: hidden;
    white-space: nowrap;
}}
"""

    if not use_leaders:
        css += """
.lof-leader, .lot-leader {
    display: none;
}
"""

    css += f"""
table.lof-table td.lof-page,
table.lot-table td.lot-page {{
    width: 14% !important;
    min-width: 70pt !important;
    text-align: right;
    white-space: nowrap;
    padding-left: 0;
    padding-right: 0.5em;
    position: relative;
    left: -10pt;
}}

table.lof-table td.lof-page a,
table.lot-table td.lot-page a {{
    color: {theme.color_text};
    text-decoration: none !important;
    font-weight: normal;
    display: inline-block;
}}
"""
    return css


def _css_list_format(use_leaders: bool) -> str:
    """Return CSS for the list-based LOF/LOT layout.

    Args:
        use_leaders: When ``True``, leader dots are generated via a
                     ``::after`` pseudo-element on ``.caption-text``.

    Returns:
        CSS string (without enclosing ``<style>`` tags).
    """
    theme = THEME

    css = f"""
/* List of Figures and List of Tables - List Format (Chrome Headless PDF) */

#lof h2, #lot h2 {{
    text-align: center;
    margin-bottom: 16pt;
    font-size: {theme.toc_heading_font_size};
    font-weight: bold;
}}

#lof .lof, #lot .lot {{
    list-style: none;
    padding: 0;
    margin: 0;
    font-size: {theme.toc_font_size};
    line-height: {theme.toc_line_height};
}}

#lof .lof li, #lot .lot li {{
    margin: 3pt 0;
    page-break-inside: avoid;
}}

/* Mirror TOC CSS leader approach: block link, overflow hidden, page number absolute */
#lof .lof a, #lot .lot a {{
    text-decoration: none !important;
    color: {theme.color_accent};
    display: block;
    overflow: hidden;
    white-space: nowrap;
    position: relative;
    padding: 2pt 0;
}}

.figure-number, .table-number {{
    font-weight: bold;
    color: {theme.color_accent};
    margin-right: 0.5em;
}}

.caption-text {{
    color: {theme.color_accent};
}}

/* Page number: absolute positioned on right, white background hides leader dots */
.lof-page-number, .lot-page-number {{
    position: absolute;
    right: 0;
    top: 2pt;
    background-color: white;
    padding-left: 0.5em;
    color: {theme.color_text};
    font-weight: normal;
    min-width: 3em;
    text-align: right;
}}
"""

    if use_leaders:
        css += f"""
/* Leader dots via ::after on caption-text, clipped by overflow:hidden on parent <a> */
#lof .lof a .caption-text::after,
#lot .lot a .caption-text::after {{
    content: ' . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . ';
    color: {theme.color_muted};
    font-weight: normal;
}}
"""

    return css


def build_lof_lot_css(format_style: str = "list", use_leaders: bool = False) -> str:
    """Build CSS for List of Figures and List of Tables.

    Delegates to :func:`_css_table_format` or :func:`_css_list_format`
    depending on *format_style*.

    Args:
        format_style: ``"list"`` or ``"table"`` layout.
        use_leaders:  Whether to render leader dots between caption and page
                      number.

    Returns:
        Complete CSS string ready for injection into a ``<style>`` element.
    """
    if format_style == "table":
        return _css_table_format(use_leaders)
    return _css_list_format(use_leaders)


# ---------------------------------------------------------------------------
# CSS injection
# ---------------------------------------------------------------------------


def inject_lof_lot_css(
    html_path: Path, format_style: str = "list", use_leaders: bool = False
) -> bool:
    """Inject a ``<style>`` block with LOF/LOT styles into *html_path*.

    The style element is appended to the ``<head>`` of the document.

    Args:
        html_path:    Path to the HTML file to modify in place.
        format_style: ``"list"`` or ``"table"`` layout.
        use_leaders:  Whether to include leader-dot styles.

    Returns:
        ``True`` if CSS was injected successfully.
    """
    logger.info("Injecting LOF/LOT CSS")

    try:
        with open(html_path, encoding="utf-8") as f:
            html_content = f.read()

        soup = BeautifulSoup(html_content, "html.parser")

        # Create style tag with shared CSS builder
        style_tag = soup.new_tag("style", id="lof-lot-styles")
        style_tag.string = build_lof_lot_css(format_style, use_leaders)

        # Insert style tag in head
        head = soup.find("head")
        if head:
            head.append(style_tag)
            logger.info("Injected LOF/LOT CSS")
        else:
            logger.warning("No <head> found, cannot inject CSS")
            return False

        # Write back to file
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(str(soup))

        return True

    except Exception as e:
        logger.error(f"Failed to inject LOF/LOT CSS: {e}")
        import traceback

        traceback.print_exc()
        return False


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> int:
    """Command-line entry point.

    Parses arguments, injects LOF/LOT CSS and HTML into the given file,
    and returns an exit code (0 on success, 1 on failure).
    """
    import argparse

    from specbuild.logsetup import setup_logging

    setup_logging("INFO")
    parser = argparse.ArgumentParser(
        description="Generate List of Figures and List of Tables for PDF"
    )
    parser.add_argument("html_file", type=Path, help="HTML file to process")
    parser.add_argument(
        "--lof", action="store_true", default=True, help="Generate List of Figures (default: True)"
    )
    parser.add_argument(
        "--lot", action="store_true", default=True, help="Generate List of Tables (default: True)"
    )
    parser.add_argument(
        "--no-lof", action="store_false", dest="lof", help="Disable List of Figures"
    )
    parser.add_argument("--no-lot", action="store_false", dest="lot", help="Disable List of Tables")
    parser.add_argument(
        "--format",
        choices=["list", "table"],
        default="list",
        help="Output format: list or table (default: list)",
    )
    parser.add_argument(
        "--leaders", action="store_true", help="Use leader dots (only for list format)"
    )

    args = parser.parse_args()

    if not args.html_file.exists():
        logger.error(f"File not found: {args.html_file}")
        return 1

    # Inject LOF/LOT CSS
    use_leaders = args.leaders and args.format == "list"
    if not inject_lof_lot_css(args.html_file, args.format, use_leaders):
        logger.error("Failed to inject CSS")
        return 1

    # Inject LOF/LOT HTML
    if not inject_lof_lot_into_html(args.html_file, args.lof, args.lot, args.format):
        logger.error("Failed to inject LOF/LOT")
        return 1

    logger.info("Successfully generated LOF/LOT")
    return 0


if __name__ == "__main__":
    sys.exit(main())
