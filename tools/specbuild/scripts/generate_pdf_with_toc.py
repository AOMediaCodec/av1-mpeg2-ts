#!/usr/bin/env python3
"""
Generate a well-formatted PDF from a specification HTML with enhanced navigation.

.. deprecated::
    This standalone script is superseded by ``specbuild/pdf.py`` and the
    integrated build pipeline (``python compile.py --pdf``).  It is kept
    for legacy/standalone use but may be removed in a future release.

This script converts the compiled index.html to PDF with:
- Clean table of contents (3 levels) with indentation
- Actual page numbers injected on the right side
- PDF bookmarks for navigation
- "Back to TOC" links at the end of each major section
- Optimized formatting for Letter or A4 paper sizes

Requirements:
    pip install playwright
    playwright install chromium
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import re
import sys
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup, Tag

# Allow importing from the specbuild package when running as a standalone script.
# The project root is one level above the scripts/ directory.
_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from specbuild.enhancements.pagenumbers import (  # noqa: E402
    collect_body_ids,
    has_dual_numbering,
    to_roman,
)
from specbuild.theme import THEME  # noqa: E402
from specbuild.utils import chrome_path as _cached_chrome_path  # noqa: E402

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Sections that should NOT receive "Back to TOC" navigation links.
# These are structural / non-content sections in bikeshed output.
_SKIP_SECTIONS_FOR_BACK_LINKS: set[str] = {
    "abstract",
    "contents",
    "toc",
    "sotd",
    "status",
    "conformance",
    "references",
    "index",
    "issues-index",
    "profile-and-date",
}

# Number of characters to look back before a heading to check whether a
# "Back to TOC" link has already been injected (avoids duplicates).
_BACK_LINK_LOOKBACK_CHARS: int = 500

# Number of non-breaking-space characters used per indentation level when
# flattening the TOC list structure.
_TOC_INDENT_SPACES_PER_LEVEL: int = 6

# Number of dot characters to use for leader dots in the table-format TOC.
# Overflow is hidden by CSS, so this is intentionally generous.
_TOC_LEADER_DOT_COUNT: int = 100

# Glob pattern used to auto-detect the latest build directory when no input
# file is specified on the command line.
_BUILD_DIR_GLOB: str = "????????_*_Spec_Draft"

# Map of CLI paper size names to CSS page size values.
_PAGE_SIZE_MAP: dict[str, str] = {
    "letter": "letter",
    "a4": "A4",
    "legal": "legal",
}


# ---------------------------------------------------------------------------
# CSS Generation
# ---------------------------------------------------------------------------
def _build_print_css(page_size: str = "letter") -> str:
    """Build the print CSS using theme values.

    Args:
        page_size: CSS page size value (e.g. "letter", "A4").

    Returns:
        Complete ``<style>`` block for print and screen media.
    """
    t = THEME
    return f"""
<style media="print">
/* Page setup */
@page {{
    size: {page_size};
    margin: {t.page_margins};
}}

@page :first {{
    margin-top: 0.5in;
}}

/* Force background colors and images to render in print/PDF */
* {{
    color-adjust: exact !important;
    -webkit-print-color-adjust: exact !important;
}}

/* Remove ALL borders from navigation elements */
nav {{
    border: none !important;
    outline: none !important;
    box-shadow: none !important;
}}

nav::before,
nav::after {{
    border: none !important;
    content: none !important;
}}

/* General print styling */
body {{
    font-size: {t.body_font_size}pt;
    line-height: 1.4;
    counter-reset: h2-section table figure;
    max-width: none !important;
    margin: 0 auto !important;
    padding: 0 !important;
}}

/* Enhanced Table of Contents styling */
#toc {{
    margin-bottom: 20pt;
    border: none !important;
    padding: 0 !important;
    outline: none !important;
    box-shadow: none !important;
    /* Always start TOC on a new page so short specs don't share the
       abstract page with the TOC.  No-op when the previous content
       already overflows. */
    page-break-before: always;
    break-before: page;
}}

/* Remove borders from nav pseudo-elements */
#toc::before,
#toc::after {{
    border: none !important;
    content: none !important;
}}

/* TOC list styling with indentation and page numbers */
#toc .toc {{
    font-size: {t.toc_font_size};
    line-height: {t.toc_line_height};
    list-style: none;
    padding: 0;
    margin: 0 !important;
}}

#toc .toc li {{
    margin: 3pt 0;
    position: relative;
}}

/* Special styling for the heading list item (first item) */
#toc .toc li.toc-heading {{
    font-size: {t.toc_heading_font_size};
    font-weight: bold;
    text-align: left;
    margin-top: 0 !important;
    margin-bottom: 16pt !important;
    padding: 0 0 8pt 0 !important;
    border-bottom: {t.toc_heading_border};
    color: #000;
    list-style: none;
    position: relative;
    overflow: hidden;
}}

#toc .toc li.toc-heading::after {{
    content: "";
    display: table;
    clear: both;
}}

#toc .toc li.toc-heading .toc-title {{
    font-size: {t.toc_heading_font_size};
    font-weight: bold;
    float: left;
}}

#toc .toc li.toc-heading .toc-pages-label {{
    font-size: {t.toc_heading_font_size};
    font-weight: bold;
    float: right;
}}

/* First real TOC item */
#toc .toc > li:nth-child(2) {{
    margin-top: 0 !important;
}}

/* Flattened TOC structure - all items at same level, use data-level for styling */
#toc .toc li[data-level] {{
    margin-left: 0 !important;
    padding-left: 0 !important;
}}

/* Level 1 - Main sections */
#toc .toc li[data-level="1"] {{
    font-weight: bold;
    margin-top: 8pt;
    margin-bottom: 4pt;
}}

/* Level 2 - Subsections */
#toc .toc li[data-level="2"] {{
    font-weight: normal;
    margin-top: 2pt;
}}

/* Level 3 - Sub-subsections */
#toc .toc li[data-level="3"] {{
    font-weight: normal;
    font-size: {t.footer_font_size}pt;
}}

/* Hide indent spans - not needed for WeasyPrint */
.toc-indent {{
    display: none !important;
}}

/* TOC links styling - clean layout with right-aligned page numbers */
#toc .toc a {{
    text-decoration: none;
    color: {t.color_accent};
    display: block;
    padding: 2pt 0;
    overflow: hidden;
    white-space: nowrap;
    position: relative;
}}

/* Remove link hover effects */
#toc .toc a:hover {{
    color: {t.color_accent};
    background: none;
}}

/* Section number and content */
#toc .toc a .secno {{
    font-weight: bold;
    display: inline-block;
    color: {t.color_accent};
    margin-right: 0.5em;
}}

#toc .toc a .content {{
    color: {t.color_accent};
}}

/* Page number styling - absolute positioned to stay on same line */
#toc .toc a .toc-page-number {{
    position: absolute;
    right: 0;
    top: 2pt;
    background-color: white;
    padding-left: 0.5em;
    color: #000;
    font-weight: normal;
    min-width: 3em;
    text-align: right;
}}

/* Nested lists */
#toc .toc ol {{
    list-style: none;
    padding: 0;
    margin: 0;
}}

/* Back to TOC links — hidden in PDF (useful in HTML, clutter in print). */
.back-to-toc-wrapper,
.back-to-toc {{
    display: none !important;
}}

/* Headings - allow natural page breaks */
h1, h2, h3, h4, h5, h6 {{
    margin-top: 12pt;
    margin-bottom: 6pt;
}}

/* Reset table counter at each major section */
h2 {{
    counter-increment: h2-section;
    counter-reset: table;
}}

/* Reset section counter after TOC to start at 1 */
#toc {{
    counter-reset: h2-section 0;
}}

/* TOC Table styling - two-column layout for perfect alignment */
table.toc-table {{
    width: 100% !important;
    table-layout: fixed !important;
    border-collapse: collapse;
    border: none !important;
    outline: none !important;
    box-shadow: none !important;
    font-size: {t.toc_font_size};
    line-height: {t.toc_line_height};
    margin: 0;
}}

/* Remove borders from table pseudo-elements */
table.toc-table::before,
table.toc-table::after {{
    border: none !important;
    content: none !important;
}}

/* Remove borders from colgroup */
table.toc-table colgroup,
table.toc-table col {{
    border: none !important;
}}

/* TOC Table heading row */
table.toc-table tr.toc-heading-row {{
    page-break-after: avoid;
}}

table.toc-table td.toc-heading-cell {{
    font-size: {t.toc_heading_font_size};
    font-weight: bold;
    padding: 0 0 12pt 0;
    text-align: center;
    position: relative;
}}

table.toc-table td.toc-heading-cell .toc-title {{
    font-size: {t.toc_heading_font_size};
    font-weight: bold;
    float: left;
}}

table.toc-table td.toc-heading-cell .toc-pages-label {{
    font-size: {t.body_font_size}pt;
    font-weight: normal;
    float: right;
}}

table.toc-table tr {{
    page-break-inside: avoid;
    border: none !important;
}}

table.toc-table td {{
    padding: 3pt 0;
    vertical-align: top;
    border: none !important;
}}

table.toc-table tbody {{
    border: none !important;
}}

/* First column: section + dots (takes remaining space) */
table.toc-table td.toc-section {{
    width: 94% !important;
    padding-right: 5pt;
    overflow: hidden;
    white-space: nowrap;
}}

table.toc-table td.toc-section a {{
    color: {t.color_accent};
    text-decoration: none;
    display: block;
    overflow: hidden;
    white-space: nowrap;
    /* Plain clip, not ellipsis — avoids the '…' character clustering
       at the right edge that reads as "dots getting closer". */
    text-overflow: clip;
}}

table.toc-table td.toc-section .secno {{
    font-weight: bold;
    color: {t.color_accent};
}}

table.toc-table td.toc-section .content {{
    color: {t.color_accent};
}}

table.toc-table td.toc-section .toc-leaders {{
    color: {t.color_muted};
    font-weight: normal;
}}

/* Second column: page number (narrow, right-aligned next to the dots) */
table.toc-table td.toc-page {{
    width: 6% !important;
    min-width: 28pt !important;
    text-align: right;
    white-space: nowrap;
    padding-left: 0.25em;
    padding-right: 0.25em;
}}

table.toc-table td.toc-page a {{
    color: #000;
    text-decoration: none;
    font-weight: normal;
}}

/* Indentation for different levels */
table.toc-table tr.toc-level-1 td.toc-section {{
    padding-left: 0 !important;
    font-weight: bold;
}}

table.toc-table tr.toc-level-2 td.toc-section {{
    padding-left: {t.toc_indent_level2} !important;
    font-weight: normal;
}}

table.toc-table tr.toc-level-3 td.toc-section {{
    padding-left: {t.toc_indent_level3} !important;
    font-weight: normal;
    font-size: {t.footer_font_size}pt;
}}

/* Syntax tables - allow natural breaking */
table.def {{
    width: 100% !important;
    font-size: 8.5pt;
    margin: 8pt 0;
}}

table.def th {{
    background-color: #e0eeff !important;
    -webkit-print-color-adjust: exact;
    print-color-adjust: exact;
    padding: 4pt 6pt;
    font-size: {t.table_font_size}pt;
}}

table.def td {{
    padding: 3pt 6pt;
    font-size: 8.5pt;
    word-wrap: break-word;
    overflow-wrap: break-word;
}}

table.def td.syntax-element {{
    width: 65%;
}}

table.def td.syntax-descriptor {{
    width: 35%;
    background-color: #f8fbff !important;
    -webkit-print-color-adjust: exact;
    print-color-adjust: exact;
}}

/* Other tables */
table {{
    width: 100% !important;
    font-size: {t.table_font_size}pt;
}}

/* Table captions */
table:has(caption) {{
    counter-increment: table;
}}

caption {{
    font-weight: bold;
    font-size: {t.toc_font_size};
    margin: 6pt 0;
    text-align: center;
    caption-side: top;
}}

caption::before {{
    content: "Table " counter(h2-section) "." counter(table) ". ";
}}

/* Skip auto-numbering for captions that already have hardcoded numbers */
caption.has-table-number::before {{
    content: none;
}}

figcaption.has-figure-number::before {{
    content: none;
}}

figcaption {{
    font-weight: bold;
    font-size: {t.toc_font_size};
    margin: 6pt 0;
    text-align: center;
}}

/* Code blocks */
pre, code {{
    font-size: {t.code_font_size}pt;
    line-height: 1.3;
    word-wrap: break-word;
    overflow-wrap: break-word;
    white-space: pre-wrap;
}}

pre {{
    margin: 6pt 0;
    padding: 6pt;
    background-color: #f5f5f5 !important;
    -webkit-print-color-adjust: exact;
    print-color-adjust: exact;
}}

/* Figures and images */
figure {{
    margin: 12pt 0;
}}

img {{
    max-width: 100%;
}}

/* Lists */
ul, ol {{
}}

li {{
}}

/* Paragraphs */
p {{
    orphans: 2;
    widows: 2;
}}

/* Links */
a[href]:after {{
    content: "";
}}

/* Section numbers and references */
.secno {{
    font-weight: bold;
}}

/* Definition lists */
dl {{
}}

dt {{
    font-weight: bold;
}}

dd {{
    margin-left: 20pt;
}}

/* Notes and warnings - green styling for visibility */
.note, .warning, .issue {{
    margin: 8pt 0;
    padding: 6pt;
    border-right: 3pt solid #52e052;
    background-color: #e9fbe9 !important;
    -webkit-print-color-adjust: exact;
    print-color-adjust: exact;
}}

/* Reduce margins for print */
main {{
    max-width: 100%;
    margin: 0;
    padding: 0;
}}

/* Ensure colors print correctly */
* {{
    -webkit-print-color-adjust: exact;
    print-color-adjust: exact;
}}
</style>

<style media="screen">
/* Screen-only styling */
.back-to-toc-wrapper {{
    text-align: right;
    margin: 1em 0;
}}

.back-to-toc {{
    display: inline-block;
    padding: 0.5em 1em;
    background-color: #e8f4f8;
    border: 1px solid {t.color_link};
    border-radius: 4px;
    font-size: 0.9em;
    text-decoration: none;
    color: {t.color_link};
    transition: background-color 0.2s;
}}

.back-to-toc:hover {{
    background-color: #d0e8f0;
}}

.back-to-toc::before {{
    content: "";
}}

/* Enhanced TOC for screen */
#toc .toc {{
    line-height: 1.6;
}}

#toc .toc > li {{
    margin-top: 0.5em;
}}

#toc .toc > li > ol > li {{
    margin-left: {t.toc_indent_level2};
}}

#toc .toc > li > ol > li > ol > li {{
    margin-left: {t.toc_indent_level3};
}}

/* Hide levels 4+ on screen too */
#toc .toc > li > ol > li > ol > li > ol {{
    display: none;
}}

/* Clean TOC links on screen */
#toc .toc a {{
    display: flex;
    justify-content: space-between;
    color: #000;
    text-decoration: none;
}}

#toc .toc a:hover {{
    color: #000;
}}
</style>

<script>
// Add page numbers to TOC entries using Playwright's page evaluation
async function addPageNumbersToTOC() {{
    const tocLinks = document.querySelectorAll('#toc .toc a[href^="#"]');

    tocLinks.forEach(link => {{
        const href = link.getAttribute('href');
        if (!href) return;

        const targetId = href.substring(1);
        const targetElement = document.getElementById(targetId);

        if (targetElement && !link.querySelector('.toc-page-number')) {{
            const pageNumSpan = document.createElement('span');
            pageNumSpan.className = 'toc-page-number';
            pageNumSpan.setAttribute('data-target', targetId);
            pageNumSpan.textContent = '...';
            link.appendChild(pageNumSpan);
        }}
    }});
}}

if (document.readyState === 'loading') {{
    document.addEventListener('DOMContentLoaded', addPageNumbersToTOC);
}} else {{
    addPageNumbersToTOC();
}}
</script>
"""


# ---------------------------------------------------------------------------
# TOC Structure Manipulation
# ---------------------------------------------------------------------------


def limit_toc_depth(html_content: str, max_depth: int = 3) -> str:
    """Add a ``data-max-depth`` attribute to the TOC ``<nav>`` element.

    Downstream CSS uses this attribute to hide heading levels deeper than
    *max_depth*.

    Args:
        html_content: Full HTML source string.
        max_depth: Maximum heading depth to display (1-6).

    Returns:
        Modified HTML with the attribute added.
    """
    html_content = html_content.replace(
        '<nav data-fill-with="table-of-contents" id="toc">',
        f'<nav data-fill-with="table-of-contents" id="toc" data-max-depth="{max_depth}">',
    )
    return html_content


def inject_toc_heading_as_first_item(html_content: str) -> str:
    """Move the TOC ``<h2>`` heading inside the ``.toc`` list as the first ``<li>``.

    This prevents page breaks between the TOC heading and its first entry by
    making the heading part of the list flow.  A "Pages" label is added on the
    right side of the heading row.

    Args:
        html_content: Full HTML source string.

    Returns:
        Modified HTML with the heading relocated.
    """
    # Regex captures: (1) <nav…>, (2) opening <h2…>, (3) h2 inner content,
    # (4) closing </h2> + whitespace, (5) opening <ol class="toc"…>
    pattern = r'(<nav[^>]*id="toc"[^>]*>\s*)(<h2[^>]*>)(.*?)(</h2>\s*)(<ol class="toc"[^>]*>)'

    def replace_toc(match):
        nav_start = match.group(1)
        h2_content = match.group(3)
        ol_start = match.group(5)

        # Create a special first list item with the heading and "Pages" label
        heading_li = f'<li class="toc-heading"><span class="toc-title">{h2_content}</span><span class="toc-pages-label">Pages</span></li>\n'

        # Return nav WITHOUT the h2, just the ol with heading as first li
        return f"{nav_start}{ol_start}\n{heading_li}"

    modified_html = re.sub(pattern, replace_toc, html_content, count=1, flags=re.DOTALL)
    return modified_html


def inject_back_to_toc_links(html_content: str) -> str:
    """Inject "Back to TOC" navigation links before each numbered ``<h2>`` section.

    Only adds links to numbered sections (``<h2>`` with class ``heading settled``).
    Skips non-content sections (abstract, references, index, etc.) and the very
    first content section (level 1).

    Args:
        html_content: Full HTML source string.

    Returns:
        Modified HTML with "Back to TOC" links inserted.
    """
    # Match h2 elements with Bikeshed "heading settled" class and a data-level attribute.
    # Groups: (1) full h2 tag, (2) data-level value, (3) id attribute value.
    h2_pattern = r'(<h2[^>]*class="[^"]*heading settled[^"]*"[^>]*data-level="(\d+)"[^>]*id="([^"]+)"[^>]*>.*?</h2>)'

    matches = list(re.finditer(h2_pattern, html_content, re.DOTALL))

    modified_html = html_content
    # Iterate in reverse so that earlier insertion positions remain valid.
    for match in reversed(matches):
        section_id = match.group(3)
        section_level = match.group(2)

        if section_id in _SKIP_SECTIONS_FOR_BACK_LINKS:
            continue

        # Don't add a link before the very first content section.
        if section_level == "1":
            continue

        start_pos = match.start()

        # Check whether a "Back to TOC" link already exists in the
        # preceding text to avoid duplicates.
        check_start = max(0, start_pos - _BACK_LINK_LOOKBACK_CHARS)
        preceding_text = modified_html[check_start:start_pos]

        if "back-to-toc" in preceding_text.lower() or "Back to Table of Contents" in preceding_text:
            # Link already exists, skip
            continue

        back_link = '<p class="back-to-toc-wrapper"><a href="#toc" class="back-to-toc">Back to Table of Contents</a></p>\n\n'

        modified_html = modified_html[:start_pos] + back_link + modified_html[start_pos:]

    return modified_html


# ---------------------------------------------------------------------------
# CSS Injection
# ---------------------------------------------------------------------------


def inject_print_css(html_content: str, page_size: str = "letter", toc_leaders: str = "css") -> str:
    """Inject print-specific CSS into the ``<head>`` of the HTML content.

    Args:
        html_content: Full HTML source string.
        page_size: Paper size name (``"letter"``, ``"a4"``, ``"legal"``).
        toc_leaders: Leader dot style — ``"css"`` for CSS ``::after`` dots,
            ``"table"`` for table-format dots, or ``"none"`` for no dots.

    Returns:
        HTML with a ``<style>`` block inserted before ``</head>``.
    """
    css_size = _PAGE_SIZE_MAP.get(page_size.lower(), "letter")
    css = _build_print_css(css_size)

    # Add TOC leaders CSS if using CSS method
    if toc_leaders == "css":
        toc_leaders_css = f"""
/* TOC leader dots - will be clipped by overflow:hidden on parent */
#toc .toc a .content::after {{
    content: ' . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . ';
    color: {THEME.color_muted};
    font-weight: normal;
}}
"""
        css = css.replace("</style>", toc_leaders_css + "</style>")

    if "</head>" in html_content:
        return html_content.replace("</head>", f"{css}\n</head>")
    elif "<body>" in html_content:
        return html_content.replace("<body>", f"<body>\n{css}")
    else:
        return css + "\n" + html_content


# ---------------------------------------------------------------------------
# Heading / Bookmark Extraction
# ---------------------------------------------------------------------------


def extract_headings_for_bookmarks(html_content: str) -> list[tuple[str, str, int]]:
    """Extract headings from the HTML for use as PDF bookmark entries.

    Args:
        html_content: Full HTML source string.

    Returns:
        List of ``(title_text, anchor_id, heading_level)`` tuples, where
        *heading_level* is 1-6 corresponding to ``<h1>``-``<h6>``.
    """
    bookmarks: list[tuple[str, str, int]] = []
    # Match <hN id="…">…</hN> for N in 1-6.
    heading_pattern = r'<h([1-6])[^>]*id="([^"]+)"[^>]*>(.*?)</h\1>'

    for match in re.finditer(heading_pattern, html_content, re.DOTALL):
        level = int(match.group(1))
        anchor = match.group(2)
        title_html = match.group(3)

        # Strip HTML tags from title
        title = re.sub(r"<[^>]+>", "", title_html)
        title = " ".join(title.split())

        bookmarks.append((title, anchor, level))

    return bookmarks


# ---------------------------------------------------------------------------
# Playwright PDF Generation
# ---------------------------------------------------------------------------


def _prepare_html_for_pdf(
    input_html: Path,
    toc_depth: int,
    add_toc_links: bool,
    toc_leaders: str,
) -> tuple[str, list[tuple[str, str, str]]]:
    """Read and prepare HTML content for PDF generation.

    Applies TOC restructuring, depth limiting, flattening, and optional
    "Back to TOC" link injection.

    Args:
        input_html: Path to the source HTML file.
        toc_depth: Maximum TOC heading depth (1-6).
        add_toc_links: Whether to inject "Back to TOC" navigation links.
        toc_leaders: Leader dot style (``"css"``, ``"table"``, or ``"none"``).

    Returns:
        Tuple of (modified_html_content, toc_entries) where *toc_entries* is a
        list of ``(section_number, title, anchor_id)`` tuples.
    """
    print("Reading HTML file...")
    html_content = input_html.read_text(encoding="utf-8")

    print(f"Limiting TOC depth to {toc_depth} levels...")
    html_content = limit_toc_depth(html_content, toc_depth)

    print("Restructuring TOC to prevent page breaks...")
    html_content = inject_toc_heading_as_first_item(html_content)

    print("Flattening TOC structure for consistent alignment...")
    html_content = flatten_toc_structure(html_content)

    if add_toc_links:
        print("Adding 'Back to TOC' links...")
        html_content = inject_back_to_toc_links(html_content)

    print("Extracting TOC structure...")
    toc_entries = extract_toc_entries_from_html(html_content)
    print(f"  Found {len(toc_entries)} TOC entries")

    # For table-format TOC, inject dummy page numbers to establish structure.
    # Real page numbers cannot be known until the document is rendered.
    if toc_leaders == "table":
        print("Converting TOC to table format with leader dots...")
        dummy_page_numbers = {entry[2]: 0 for entry in toc_entries}
        html_content = inject_page_numbers_into_html(
            html_content, dummy_page_numbers, add_leaders=True
        )

    return html_content, toc_entries


def _build_playwright_pdf_options(
    output_pdf: Path,
    page_size: str,
    landscape: bool,
) -> dict[str, Any]:
    """Build the options dict for Playwright's ``page.pdf()`` call.

    Args:
        output_pdf: Destination PDF file path.
        page_size: Paper size name (``"letter"``, ``"a4"``, ``"legal"``).
        landscape: Whether to use landscape orientation.

    Returns:
        Dict of keyword arguments for ``page.pdf()``.
    """
    pdf_options: dict[str, Any] = {
        "path": str(output_pdf),
        "format": page_size.upper() if page_size.lower() in ["a4", "letter", "legal"] else "Letter",
        "print_background": True,
        "margin": {
            "top": "0.75in",
            "right": "0.5in",
            "bottom": "0.75in",
            "left": "0.5in",
        },
        "prefer_css_page_size": True,
        "display_header_footer": True,
        "header_template": (
            '<div style="font-size:9pt; width:100%; text-align:center; '
            'color:#666;">Specification</div>'
        ),
        "footer_template": (
            '<div style="font-size:9pt; width:100%; text-align:center; '
            'color:#666;"><span class="pageNumber"></span> / '
            '<span class="totalPages"></span></div>'
        ),
        "outline": True,
        "tagged": True,
    }
    if landscape:
        pdf_options["landscape"] = True
    return pdf_options


async def generate_pdf_playwright(
    input_html: Path,
    output_pdf: Path,
    page_size: str = "letter",
    landscape: bool = False,
    add_toc_links: bool = True,
    toc_depth: int = 3,
    toc_leaders: str = "css",
) -> bool:
    """Generate PDF using Playwright (Chromium) with enhanced navigation.

    Playwright provides a headless Chromium instance to render the HTML and
    produce a PDF.  Page numbers in the TOC are placeholders (a known
    limitation); use the WeasyPrint engine for accurate page numbers.

    Args:
        input_html: Path to the compiled specification HTML.
        output_pdf: Destination PDF file path.
        page_size: Paper size (``"letter"``, ``"a4"``, ``"legal"``).
        landscape: Use landscape orientation.
        add_toc_links: Inject "Back to TOC" navigation links.
        toc_depth: Maximum TOC heading depth (1-6).
        toc_leaders: Leader dot style (``"css"``, ``"table"``, ``"none"``).

    Returns:
        ``True`` on success, ``False`` on failure.
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("Error: playwright not installed", file=sys.stderr)
        print(
            "Install with: pip install playwright && playwright install chromium", file=sys.stderr
        )
        return False

    html_content, toc_entries = _prepare_html_for_pdf(
        input_html, toc_depth, add_toc_links, toc_leaders
    )

    # Add print CSS
    print("Injecting enhanced print CSS...")
    html_with_print_css = inject_print_css(html_content, page_size, toc_leaders)

    # Extract headings for bookmarks
    print("Extracting document structure for PDF bookmarks...")
    bookmarks = extract_headings_for_bookmarks(html_with_print_css)
    print(f"  Found {len(bookmarks)} headings for navigation")

    # Create temporary file with modified HTML
    temp_html = input_html.parent / f"{input_html.stem}_print_temp.html"
    temp_html.write_text(html_with_print_css, encoding="utf-8")

    try:
        async with async_playwright() as p:
            print("Launching Chromium...")
            browser = await p.chromium.launch()
            page = await browser.new_page()

            print(f"Loading {input_html.name}...")
            await page.goto(f"file://{temp_html.absolute()}")

            # Wait for page to fully load
            await page.wait_for_load_state("networkidle")

            # Wait a bit for any JavaScript to execute
            await asyncio.sleep(1)

            print("Injecting page numbers into TOC...")
            # Inject placeholder page numbers into TOC links via JavaScript.
            # Handle both table format and list format.
            if toc_leaders == "table":
                # Table format: update td.toc-page cells
                await page.evaluate("""
                    () => {
                        const pageNumCells = document.querySelectorAll('table.toc-table td.toc-page a');
                        pageNumCells.forEach(cell => {
                            cell.textContent = '\u2022';  // Bullet placeholder
                            cell.style.fontSize = '10pt';
                            cell.style.color = '#000';
                        });
                    }
                """)
            else:
                # List format (for "none" and "css" modes): append spans to links
                await page.evaluate("""
                    () => {
                        const tocLinks = document.querySelectorAll('#toc .toc a[href^="#"]');
                        tocLinks.forEach(link => {
                            const href = link.getAttribute('href');
                            if (!href) return;

                            const targetId = href.substring(1);

                            if (!link.querySelector('.toc-page-number')) {
                                const pageNumSpan = document.createElement('span');
                                pageNumSpan.className = 'toc-page-number';
                                pageNumSpan.textContent = '\u2022';  // Bullet placeholder
                                link.appendChild(pageNumSpan);
                            }
                        });
                    }
                """)

            pdf_options = _build_playwright_pdf_options(output_pdf, page_size, landscape)

            print("Generating PDF with:")
            if toc_leaders == "table":
                print("  - Table of Contents (table format with leader dots)")
            elif toc_leaders == "css":
                print("  - Table of Contents (list format with CSS leader dots)")
            else:
                print("  - Table of Contents (list format, no leader dots)")
            print("  - Page numbers on the right side")
            print("  - PDF bookmarks for navigation")
            if add_toc_links:
                print("  - 'Back to TOC' links at section ends")
            print(f"  - {len(bookmarks)} document sections")
            print()

            await page.pdf(**pdf_options)

            await browser.close()
            print(f"✓ PDF generated: {output_pdf}")
            print("\nNote: Page numbers in TOC show placeholders (•)")
            print("      This is a known limitation of PDF generation.")
            print("      The TOC links are still clickable and functional.")
            return True

    finally:
        if temp_html.exists():
            temp_html.unlink()


# ---------------------------------------------------------------------------
# TOC Entry Extraction and Page Number Injection
# ---------------------------------------------------------------------------


def extract_toc_entries_from_html(html_content: str) -> list[tuple[str, str, str]]:
    """Extract TOC entries from HTML using BeautifulSoup.

    Args:
        html_content: Full HTML source string.

    Returns:
        List of ``(section_number, title, anchor_id)`` tuples.  The
        *section_number* may be empty for unnumbered headings.
    """
    soup = BeautifulSoup(html_content, "html.parser")
    toc_nav = soup.find("nav", id="toc")

    if not toc_nav:
        return []

    entries = []
    toc_links = toc_nav.find_all("a", href=lambda x: x and x.startswith("#"))

    for link in toc_links:
        href = link.get("href", "").lstrip("#")
        if not href:
            continue

        # Get section number
        secno = link.find("span", class_="secno")
        section_num = secno.get_text(strip=True) if secno else ""

        # Get title
        content = link.find("span", class_="content")
        title = content.get_text(strip=True) if content else link.get_text(strip=True)

        entries.append((section_num, title, href))

    return entries


def inject_lof_lot_page_numbers(soup: BeautifulSoup, page_numbers: dict[str, int]) -> None:
    """Inject page numbers into List of Figures and List of Tables.

    Args:
        soup: BeautifulSoup object
        page_numbers: dict mapping anchor_id to page number
    """
    # Process List of Figures
    lof_nav = soup.find("nav", id="lof")
    if lof_nav:
        for page_span in lof_nav.find_all("span", class_="lof-page-number"):
            target_id = page_span.get("data-target")
            if target_id and target_id in page_numbers:
                page_span.string = str(page_numbers[target_id])

    # Process List of Tables
    lot_nav = soup.find("nav", id="lot")
    if lot_nav:
        for page_span in lot_nav.find_all("span", class_="lot-page-number"):
            target_id = page_span.get("data-target")
            if target_id and target_id in page_numbers:
                page_span.string = str(page_numbers[target_id])


def inject_figure_table_numbers(soup: BeautifulSoup, label_soup: BeautifulSoup = None) -> None:
    """Inject figure and table numbers into the LOF/LOT entries.

    Extracts the label (e.g. "Figure F.1:" or "Table 3.1:") directly from the
    caption text in the document, which is already correctly numbered by bikeshed
    and the annex renumbering step.

    Args:
        soup: BeautifulSoup object to inject numbers into (the working PDF soup)
        label_soup: Optional soup to read caption labels from (e.g. original index.html
                    before table-number stripping). Falls back to soup if not provided.
    """
    import re

    src = label_soup if label_soup is not None else soup

    # Build map: element_id -> label, reading from figcaption/caption text
    figure_numbers = {}
    table_numbers = {}

    for figure in src.find_all("figure"):
        figcaption = figure.find("figcaption")
        if not figcaption:
            continue
        # ID is on either the figure or the figcaption
        element_id = figure.get("id") or figcaption.get("id")
        if not element_id:
            continue
        cap_text = figcaption.get_text(strip=True)
        # Match "Figure X.Y:" or "Figure X.Y." prefix from caption text.
        # The \w+ segments match alphanumeric section/figure numbers (e.g. "F.1", "3.2").
        m = re.match(r"^(Figure\s+[\w]+\.[\w]+)[:\.]?", cap_text)
        if m:
            figure_numbers[element_id] = m.group(1) + ":"

    for table in src.find_all("table"):
        caption = table.find("caption")
        if not caption:
            continue
        # ID is on either the table or the caption
        element_id = table.get("id") or caption.get("id")
        if not element_id:
            continue
        # Skip TOC/SDL tables
        classes = table.get("class", [])
        if "toc-table" in classes or "sdl-syntax-table" in classes:
            continue
        cap_text = caption.get_text(strip=True)
        # Match "Table X.Y:" or "Table X.Y." prefix from caption text.
        m = re.match(r"^(Table\s+[\w]+\.[\w]+)[:\.]?", cap_text)
        if m:
            table_numbers[element_id] = m.group(1) + ":"

    # Inject figure numbers into LOF
    lof_nav = soup.find("nav", id="lof")
    if lof_nav:
        for fig_num_span in lof_nav.find_all("span", class_="figure-number"):
            target_id = fig_num_span.get("data-target")
            if target_id and target_id in figure_numbers:
                fig_num_span.string = figure_numbers[target_id] + " "

    # Inject table numbers into LOT
    lot_nav = soup.find("nav", id="lot")
    if lot_nav:
        for tbl_num_span in lot_nav.find_all("span", class_="table-number"):
            target_id = tbl_num_span.get("data-target")
            if target_id and target_id in table_numbers:
                tbl_num_span.string = table_numbers[target_id] + " "


# ---------------------------------------------------------------------------
# Dual Page Numbering (Roman / Arabic)
# ---------------------------------------------------------------------------


def restyle_dual_page_numbers(html_content: str, all_page_numbers: dict[str, int]) -> str:
    """Convert absolute page numbers to dual style (roman front-matter, arabic body).

    Only runs when dual page numbering is active (detected by the presence
    of ``page: front-matter`` in element styles).

    Args:
        html_content: HTML string with absolute page numbers already injected.
        all_page_numbers: dict mapping anchor_id to absolute page number.

    Returns:
        HTML with page numbers restyled, or unmodified if dual numbering is
        not active.
    """
    soup = BeautifulSoup(html_content, "html.parser")

    if not has_dual_numbering(soup):
        return html_content

    main = soup.find("main")
    if not main:
        return html_content

    body_ids = collect_body_ids(soup, main)

    # Determine front-matter page count from the page number map
    body_abs_pages = [p for aid, p in all_page_numbers.items() if aid in body_ids]
    if not body_abs_pages:
        return html_content

    front_matter_pages = min(body_abs_pages) - 1
    print(f"  Dual page numbering: {front_matter_pages} front-matter pages")

    # Restyle page numbers in TOC, LOF, LOT
    span_selectors = [
        ("nav", "toc", "toc-page-number"),
        ("nav", "lof", "lof-page-number"),
        ("nav", "lot", "lot-page-number"),
    ]

    restyled = 0
    for tag, nav_id, span_class in span_selectors:
        container = soup.find(tag, id=nav_id)
        if not container:
            continue
        for span in container.find_all("span", class_=span_class):
            text = span.string
            if not text or not text.strip().isdigit():
                continue
            abs_page = int(text.strip())
            # Determine target ID
            target_id = span.get("data-target", "")
            if not target_id:
                parent_a = span.find_parent("a", href=True)
                if parent_a:
                    target_id = parent_a["href"].lstrip("#")
            # Convert
            if target_id in body_ids:
                span.string = str(abs_page - front_matter_pages)
            else:
                span.string = to_roman(abs_page)
            restyled += 1

    # Also restyle page numbers in table format TOC (td.toc-page-number)
    toc_nav = soup.find("nav", id="toc")
    if toc_nav:
        for td in toc_nav.find_all("td", class_="toc-page-number"):
            text = td.string
            if not text or not text.strip().isdigit():
                continue
            abs_page = int(text.strip())
            # Find the link in the same row to get the target
            tr = td.find_parent("tr")
            if tr:
                link = tr.find("a", href=True)
                if link:
                    target_id = link["href"].lstrip("#")
                    if target_id in body_ids:
                        td.string = str(abs_page - front_matter_pages)
                    else:
                        td.string = to_roman(abs_page)
                    restyled += 1

    if restyled:
        print(f"  Restyled {restyled} page numbers for dual numbering")
        return str(soup)
    return html_content


# ---------------------------------------------------------------------------
# Page Number Injection
# ---------------------------------------------------------------------------


def inject_page_numbers_into_html(
    html_content: str, page_numbers: dict[str, int], add_leaders: bool = False
) -> str:
    """Inject page numbers into the TOC, optionally converting to table format.

    When *add_leaders* is ``True``, the nested ``<ol>`` TOC is replaced with a
    two-column ``<table>`` where the first column contains the section title
    with trailing leader dots and the second column contains the page number.

    Args:
        html_content: Full HTML source string.
        page_numbers: Mapping of anchor ID to page number (1-indexed).
        add_leaders: Convert TOC to table format with leader dots.

    Returns:
        Modified HTML with page numbers added.
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html_content, "html.parser")
    toc_nav = soup.find("nav", id="toc")

    if not toc_nav:
        return html_content

    if add_leaders:
        # Convert TOC to table format for perfect alignment
        # Find the TOC list
        toc_list = toc_nav.find("ol", class_="toc")
        if not toc_list:
            return html_content

        # Create table structure
        table = soup.new_tag("table", **{"class": "toc-table"})

        # Add colgroup to explicitly define column widths.
        # Letter-size page with 0.5in margins gives ~540pt usable width.
        # Page-number column is sized to fit 1-3 digit numbers (28pt) so
        # the number sits right next to the leader dots — no wide gap.
        colgroup = soup.new_tag("colgroup")
        col1 = soup.new_tag("col", style="width: 510pt;")  # Section + dots column
        col2 = soup.new_tag("col", style="width: 30pt;")  # Page number column
        colgroup.append(col1)
        colgroup.append(col2)
        table.append(colgroup)

        tbody = soup.new_tag("tbody")
        table.append(tbody)

        # First, check if there's a toc-heading li and add it as the first row
        heading_li = toc_list.find("li", class_="toc-heading")
        if heading_li:
            # Extract the heading text
            toc_title_span = heading_li.find("span", class_="toc-title")
            pages_label_span = heading_li.find("span", class_="toc-pages-label")

            if toc_title_span and pages_label_span:
                # Create heading row
                heading_row = soup.new_tag("tr", **{"class": "toc-heading-row"})
                heading_cell = soup.new_tag("td", colspan="2", **{"class": "toc-heading-cell"})

                # Add title on left
                title_span = soup.new_tag("span", **{"class": "toc-title"})
                title_span.string = toc_title_span.get_text(strip=True)
                heading_cell.append(title_span)

                # Add "Pages" label on right
                pages_span = soup.new_tag("span", **{"class": "toc-pages-label"})
                pages_span.string = pages_label_span.get_text(strip=True)
                heading_cell.append(pages_span)

                heading_row.append(heading_cell)
                tbody.append(heading_row)

        # Get all links in the TOC (bikeshed generates flat link list with nested <ol>s)
        all_links = toc_list.find_all("a", href=lambda x: x and x.startswith("#"))

        for link in all_links:
            anchor_id = link.get("href", "").lstrip("#")
            if anchor_id not in page_numbers:
                continue

            # Extract section number and title
            secno_span = link.find("span", class_="secno")
            content_span = link.find("span", class_="content")

            secno_text = secno_span.get_text(strip=True) if secno_span else ""
            content_text = content_span.get_text(strip=True) if content_span else ""
            page_num = page_numbers[anchor_id]

            # Determine level from section number (1 = level 1, 4.2 = level 2, 4.2.1 = level 3)
            level = 1
            if secno_text:
                level = secno_text.count(".") + 1
                # Cap at level 3
                level = min(level, 3)

            # Create table row
            tr = soup.new_tag("tr", **{"class": f"toc-level-{level}"})

            # First column: section info + leader dots
            td1 = soup.new_tag("td", **{"class": "toc-section"})

            # Create link for the section
            section_link = soup.new_tag("a", href=link.get("href"))

            if secno_text:
                secno_new = soup.new_tag("span", **{"class": "secno"})
                secno_new.string = secno_text
                section_link.append(secno_new)
                section_link.append(" ")

            content_new = soup.new_tag("span", **{"class": "content"})
            content_new.string = content_text
            section_link.append(content_new)

            # Add leader dots (overflow hidden by CSS, so use generous count)
            dots_span = soup.new_tag("span", **{"class": "toc-leaders"})
            dots_span.string = " ." * _TOC_LEADER_DOT_COUNT
            section_link.append(dots_span)

            td1.append(section_link)

            # Second column: page number
            td2 = soup.new_tag("td", **{"class": "toc-page"})
            page_link = soup.new_tag("a", href=link.get("href"))
            page_link.string = str(page_num)
            td2.append(page_link)

            tr.append(td1)
            tr.append(td2)
            tbody.append(tr)

        # Replace the list with the table
        toc_list.replace_with(table)

        return str(soup)
    else:
        # Original approach: inject page number spans
        for anchor_id, page_num in page_numbers.items():
            # Match TOC links with this anchor
            pattern = f'(<a href="#{re.escape(anchor_id)}"[^>]*>.*?)(</a>)'
            replacement = f'\\1<span class="toc-page-number">{page_num}</span>\\2'
            html_content = re.sub(pattern, replacement, html_content, count=1, flags=re.DOTALL)

        return html_content


# ---------------------------------------------------------------------------
# WeasyPrint Page Number Extraction
# ---------------------------------------------------------------------------


def get_page_numbers_from_weasyprint_document(temp_html: Path) -> dict[str, int]:
    """Extract page numbers for all anchor IDs from a WeasyPrint-rendered document.

    Uses WeasyPrint's box tree traversal to accurately determine which page
    each element lands on.  This is more reliable than text-extraction methods.

    Args:
        temp_html: Path to the HTML file to render.

    Returns:
        Mapping of anchor ID to 1-indexed page number.
    """
    try:
        from weasyprint import HTML
    except ImportError:
        print("Warning: weasyprint not installed", file=sys.stderr)
        return {}

    # Silence WeasyPrint's CSS warnings about unsupported properties / media
    # queries.  Bikeshed's CSS includes lots of features WeasyPrint can't
    # render (box-shadow, prefers-color-scheme, @keyframes, etc.) and the
    # warnings drown out actual build output.  Set SPECBUILD_WEASYPRINT_VERBOSE=1
    # to see them.
    import os as _os

    if not _os.environ.get("SPECBUILD_WEASYPRINT_VERBOSE"):
        logging.getLogger("weasyprint").setLevel(logging.ERROR)
        logging.getLogger("weasyprint.css").setLevel(logging.ERROR)
        logging.getLogger("fontTools").setLevel(logging.ERROR)

    # Render the HTML to get the box tree
    html = HTML(filename=str(temp_html))
    document = html.render(presentational_hints=True)

    # Build a map of anchor IDs to page numbers by traversing the box tree
    page_map: dict[str, int] = {}

    def find_anchors_in_box(box: Any, page_num: int) -> None:
        """Recursively find all anchor targets in a WeasyPrint box."""
        # Check if this box has an ID (potential anchor target)
        if hasattr(box, "element") and box.element is not None:
            element_id = box.element.get("id")
            # Skip bikeshed cross-reference anchors and TOC-internal anchors
            if element_id and not element_id.startswith("ref-for-"):
                if not element_id.startswith("toc"):
                    page_map[element_id] = page_num

        # Recursively check children
        if hasattr(box, "children"):
            for child in box.children:
                find_anchors_in_box(child, page_num)

    # Traverse all pages
    for page_num, page in enumerate(document.pages, start=1):
        # Start from the page's root box
        find_anchors_in_box(page._page_box, page_num)

    return page_map


def flatten_toc_structure(html_content: str) -> str:
    """
    Flatten nested TOC list structure into a single-level list with explicit level markers.

    This ensures all TOC entries are at the same DOM level, preventing CSS nesting issues
    that cause page number alignment problems.

    Args:
        html_content: The HTML content string

    Returns:
        Modified HTML with flattened TOC structure
    """
    soup = BeautifulSoup(html_content, "html.parser")
    toc_nav = soup.find("nav", id="toc")

    if not toc_nav:
        return html_content

    # Find the top-level TOC list
    top_ol = toc_nav.find("ol", class_="toc")
    if not top_ol:
        return html_content

    # Collect all entries by walking all <a> tags directly.
    # We cannot use recursive=False on <li> elements because bikeshed emits
    # unclosed <li> tags, which BeautifulSoup nests all under the first one.
    entries = []

    # Check for a toc-heading li first (inserted by inject_toc_heading_as_first_item)
    toc_heading_li = toc_nav.find("li", class_="toc-heading")
    if toc_heading_li:
        entries.append({"level": 0, "link": None, "is_heading": True, "li": toc_heading_li})

    for link in toc_nav.find_all("a", href=lambda x: x and x.startswith("#")):
        secno = link.find("span", class_="secno")
        secno_text = secno.get_text(strip=True).rstrip(".") if secno else ""
        if secno_text:
            # Infer nesting level from the section number (e.g. "4.1.2" -> level 3)
            level = len(secno_text.split("."))
        else:
            # Unnumbered entries (empty secno): infer level from DOM nesting depth
            depth = sum(1 for p in link.parents if p.name == "ol" and p is not toc_nav)
            level = max(1, depth)
        entries.append({"level": level, "link": link, "is_heading": False, "li": None})

    if not entries:
        return html_content

    print(
        f"  Flattening TOC structure: {len(entries)} entries across {max((e['level'] for e in entries if not e['is_heading']), default=1)} levels"
    )

    # Create new flat list
    new_ol = soup.new_tag("ol", **{"class": "toc", "role": "directory"})

    for entry in entries:
        if entry["is_heading"]:
            # Preserve the toc-heading li as-is
            new_ol.append(entry["li"].__copy__())
            continue

        level = entry["level"]
        link = entry["link"]

        # Create new list item with level marker
        new_li = soup.new_tag("li")
        new_li["data-level"] = str(level)

        # Create new link
        new_link = soup.new_tag("a", href=link.get("href"))

        # Add indent span at the beginning (with nbsp for WeasyPrint)
        indent_span = soup.new_tag("span", **{"class": "toc-indent", "data-level": str(level)})
        indent_span.string = "\u00a0"  # Non-breaking space for WeasyPrint rendering
        new_link.append(indent_span)

        # Copy existing spans (secno, content)
        for child in link.children:
            if child.name == "span" and child.get("class"):
                classes = child.get("class")
                if "secno" in classes:
                    # Add indentation by prepending non-breaking spaces to section number
                    secno_copy = child.__copy__()
                    num_spaces = _TOC_INDENT_SPACES_PER_LEVEL * (level - 1)
                    indent_spaces = "\xa0" * num_spaces  # Use actual nbsp character
                    original_text = secno_copy.get_text()
                    # Clear and rebuild to preserve single string structure
                    secno_copy.clear()
                    secno_copy.string = indent_spaces + original_text
                    new_link.append(secno_copy)
                elif "content" in classes:
                    new_link.append(child.__copy__())

        new_li.append(new_link)
        new_ol.append(new_li)

    # Replace the old nested structure with the new flat structure
    top_ol.replace_with(new_ol)

    return str(soup)


# ---------------------------------------------------------------------------
# WeasyPrint PDF Generation
# ---------------------------------------------------------------------------


def _prerender_mathjax(html_content: str, input_html: Path) -> str:
    """Pre-render MathJax equations using Chrome if available.

    WeasyPrint does not execute JavaScript, so MathJax must be rendered to
    static SVG/HTML beforehand using a headless Chrome instance.

    Args:
        html_content: HTML source with raw MathJax markup.
        input_html: Path to the original HTML file (used for temp file placement).

    Returns:
        HTML with MathJax equations rendered, or the original content if
        Chrome is unavailable or pre-rendering fails.
    """
    # If MathJax equations were already pre-rendered to SVG by Zone A (the
    # main process ran Puppeteer on the HTML before passing it here), the
    # <mjx-container> wrappers will be present — skip the redundant second pass.
    if "<mjx-container" in html_content:
        return html_content

    detected_chrome = _cached_chrome_path()
    if not detected_chrome:
        print("  Warning: Chrome not found - skipping MathJax pre-rendering", file=sys.stderr)
        return html_content

    print("Pre-rendering MathJax equations...")
    mathjax_script = Path(__file__).parent / "prerender_mathjax_for_weasyprint.py"
    if not mathjax_script.exists():
        print("  Warning: MathJax pre-rendering script not found", file=sys.stderr)
        return html_content

    try:
        import subprocess

        temp_mathjax_html = input_html.parent / f"{input_html.stem}_mathjax_temp.html"
        temp_mathjax_html.write_text(html_content, encoding="utf-8")

        try:
            subprocess.run(
                [sys.executable, str(mathjax_script), str(temp_mathjax_html), detected_chrome],
                check=True,
                capture_output=True,
            )
            html_content = temp_mathjax_html.read_text(encoding="utf-8")
            print("  MathJax equations pre-rendered")
        except Exception as exc:
            print(f"  Warning: Failed to pre-render MathJax: {exc}", file=sys.stderr)
            print("  Continuing without MathJax pre-rendering (equations may appear as raw LaTeX)")
        finally:
            temp_mathjax_html.unlink(missing_ok=True)
    except Exception as exc:
        print(f"  Warning: Failed to pre-render MathJax: {exc}", file=sys.stderr)
        print("  Continuing without MathJax pre-rendering (equations may appear as raw LaTeX)")

    return html_content


def _generate_lof_lot(
    html_content: str,
    input_html: Path,
    generate_lof: bool,
    generate_lot: bool,
    toc_leaders: str,
    front_matter_order: list[str] | None,
) -> str:
    """Generate and inject List of Figures / List of Tables into the HTML.

    Args:
        html_content: HTML source string (with TOC already restructured).
        input_html: Path to the original HTML (used for temp file placement).
        generate_lof: Whether to generate a List of Figures.
        generate_lot: Whether to generate a List of Tables.
        toc_leaders: Leader dot style (determines LOF/LOT format).
        front_matter_order: Ordered list of front-matter keys
            (e.g. ``['toc', 'lof', 'lot']``), or ``None`` for defaults.

    Returns:
        Modified HTML with LOF/LOT injected.
    """
    soup = BeautifulSoup(html_content, "html.parser")

    script_dir = Path(__file__).parent
    sys.path.insert(0, str(script_dir))
    try:
        from generate_lof_lot import (
            create_lof_html,
            create_lot_html,
            extract_figures_from_html,
            extract_tables_from_html,
        )

        format_style = "table" if toc_leaders == "table" else "list"
        nav_elements: dict[str, Tag] = {}

        if generate_lof:
            print("Generating List of Figures...")
            figures = extract_figures_from_html(soup)
            if figures:
                lof_html = create_lof_html(figures, format_style)
                lof_soup = BeautifulSoup(lof_html, "html.parser")
                lof_nav = lof_soup.find("nav", id="lof")
                if lof_nav:
                    nav_elements["lof"] = lof_nav
                    print(f"  Added List of Figures with {len(figures)} entries")

        if generate_lot:
            print("Generating List of Tables...")
            tables = extract_tables_from_html(soup)
            if tables:
                lot_html = create_lot_html(tables, format_style)
                lot_soup = BeautifulSoup(lot_html, "html.parser")
                lot_nav = lot_soup.find("nav", id="lot")
                if lot_nav:
                    nav_elements["lot"] = lot_nav
                    print(f"  Added List of Tables with {len(tables)} entries")

        # Insert nav elements after the TOC in the specified order
        toc = soup.find("nav", id="toc")
        if toc and nav_elements:
            # Mark LOF/LOT as front-matter for dual page numbering if needed
            toc_style = toc.get("style", "")
            if "page: front-matter" in toc_style:
                for nav in nav_elements.values():
                    nav["style"] = nav.get("style", "") + "page: front-matter;"

            order = front_matter_order if front_matter_order else ["toc", "lof", "lot"]
            insert_order = [k for k in order if k in nav_elements]
            for k in nav_elements:
                if k not in insert_order:
                    insert_order.append(k)
            for key in reversed(insert_order):
                toc.insert_after(nav_elements[key])
            print(f"  Front-matter order: {', '.join(insert_order)}")

        # Inject LOF/LOT CSS into the soup directly (avoids re-parsing which
        # can collapse bikeshed's unclosed <li> tags)
        if generate_lof or generate_lot:
            from generate_lof_lot import inject_lof_lot_css

            use_leaders = toc_leaders in ["css", "table"]
            temp_path = input_html.parent / "temp_lof_lot_css.html"
            dummy_html = "<html><head></head><body></body></html>"
            temp_path.write_text(dummy_html, encoding="utf-8")
            inject_lof_lot_css(temp_path, format_style, use_leaders)
            css_soup = BeautifulSoup(temp_path.read_text(encoding="utf-8"), "html.parser")
            temp_path.unlink()
            style_tag = css_soup.find("style", id="lof-lot-styles")
            if style_tag and soup.head:
                soup.head.append(style_tag)
            html_content = str(soup)

    except Exception as exc:
        print(f"Warning: Failed to generate LOF/LOT: {exc}", file=sys.stderr)
        import traceback

        traceback.print_exc()
    finally:
        sys.path.pop(0)

    return html_content


def _weasyprint_first_pass(
    html_content: str,
    input_html: Path,
    page_size: str,
    toc_entries: list[tuple[str, str, str]],
) -> tuple[dict[str, int], dict[str, int], Path]:
    """Perform the first WeasyPrint render pass to extract page numbers.

    The first pass renders the document *without* page numbers in the TOC,
    then uses box-tree traversal to determine which page each anchor lands on.

    Args:
        html_content: HTML source (with TOC restructured but no page numbers).
        input_html: Path to the original HTML file (for temp file placement).
        page_size: Paper size name.
        toc_entries: TOC entries as returned by :func:`extract_toc_entries_from_html`.

    Returns:
        Tuple of ``(toc_page_numbers, all_page_numbers, temp_html_path)``
        where *toc_page_numbers* is filtered to TOC anchors only and
        *all_page_numbers* includes every anchor in the document.
    """
    print("First pass: Rendering HTML to extract page numbers...")
    temp_html = input_html.parent / f"{input_html.stem}_print_temp.html"

    # Use "none" leader style for the first pass to avoid layout artifacts
    html_with_print_css = inject_print_css(html_content, page_size, "none")
    temp_html.write_text(html_with_print_css, encoding="utf-8")

    print("  Extracting page numbers from rendered document...")
    all_page_numbers = get_page_numbers_from_weasyprint_document(temp_html)

    # Filter to only the TOC entry anchors
    toc_anchor_ids = {anchor_id for _, _, anchor_id in toc_entries}
    toc_page_numbers = {k: v for k, v in all_page_numbers.items() if k in toc_anchor_ids}

    print(f"  Mapped {len(toc_page_numbers)} sections to page numbers")

    if not toc_page_numbers:
        print("Warning: Could not extract page numbers from PDF", file=sys.stderr)

    return toc_page_numbers, all_page_numbers, temp_html


def generate_pdf_weasyprint(
    input_html: Path,
    output_pdf: Path,
    page_size: str = "letter",
    add_toc_links: bool = True,
    toc_depth: int = 3,
    toc_leaders: str = "css",
    generate_lof: bool = False,
    generate_lot: bool = False,
    front_matter_order: list[str] | None = None,
) -> bool:
    """Generate PDF using WeasyPrint with two-pass page number injection.

    Pass 1 renders the document to extract accurate page numbers via box-tree
    traversal.  Pass 2 injects those page numbers into the TOC (and optionally
    LOF/LOT) and renders the final PDF.

    Args:
        input_html: Path to the compiled specification HTML.
        output_pdf: Destination PDF file path.
        page_size: Paper size (``"letter"``, ``"a4"``, ``"legal"``).
        add_toc_links: Inject "Back to TOC" navigation links.
        toc_depth: Maximum TOC heading depth (1-6).
        toc_leaders: Leader dot style (``"css"``, ``"table"``, ``"none"``).
        generate_lof: Generate a List of Figures with page numbers.
        generate_lot: Generate a List of Tables with page numbers.
        front_matter_order: Insertion order for front-matter elements
            (e.g. ``['toc', 'lof', 'lot']``).

    Returns:
        ``True`` on success, ``False`` on failure.
    """
    try:
        from weasyprint import HTML
    except ImportError:
        print("Error: weasyprint not installed", file=sys.stderr)
        print("Install with: pip install weasyprint", file=sys.stderr)
        return False

    # --- Stage 1: Read and pre-process HTML ---
    print("Reading HTML file...")
    html_content = input_html.read_text(encoding="utf-8")

    html_content = _prerender_mathjax(html_content, input_html)

    print(f"Limiting TOC depth to {toc_depth} levels...")
    html_content = limit_toc_depth(html_content, toc_depth)

    print("Restructuring TOC to prevent page breaks...")
    html_content = inject_toc_heading_as_first_item(html_content)

    print("Flattening TOC structure for consistent alignment...")
    html_content = flatten_toc_structure(html_content)

    if add_toc_links:
        print("Adding 'Back to TOC' links...")
        html_content = inject_back_to_toc_links(html_content)

    # --- Stage 2: Generate LOF/LOT if requested ---
    if generate_lof or generate_lot:
        html_content = _generate_lof_lot(
            html_content,
            input_html,
            generate_lof,
            generate_lot,
            toc_leaders,
            front_matter_order,
        )

    # --- Stage 3: First WeasyPrint pass — extract page numbers ---
    print("Extracting TOC structure...")
    toc_entries = extract_toc_entries_from_html(html_content)
    print(f"  Found {len(toc_entries)} TOC entries")

    page_numbers, all_page_numbers, temp_html = _weasyprint_first_pass(
        html_content, input_html, page_size, toc_entries
    )

    # --- Stage 4: Inject page numbers into HTML ---
    if page_numbers:
        print("Injecting page numbers into TOC...")
        use_table_format = toc_leaders == "table"
        html_content = inject_page_numbers_into_html(
            html_content, page_numbers, add_leaders=use_table_format
        )

        # Inject page numbers and figure/table numbers into LOF/LOT
        if generate_lof or generate_lot:
            print("Injecting page numbers into LOF/LOT...")
            soup = BeautifulSoup(html_content, "html.parser")
            # The working soup already has "Figure X.Y:" and "Table X.Y:"
            # prefixes from add_table_numbers_for_pdf.py preprocessing.
            inject_figure_table_numbers(soup, soup)
            inject_lof_lot_page_numbers(soup, all_page_numbers)
            html_content = str(soup)
            print("  Injected numbers and page numbers into LOF/LOT")

        # Apply dual page numbering if active (roman front-matter, arabic body)
        html_content = restyle_dual_page_numbers(html_content, all_page_numbers)

    # --- Stage 5: Second WeasyPrint pass — generate final PDF ---
    print("Second pass: Generating final PDF with TOC page numbers...")
    html_with_print_css = inject_print_css(html_content, page_size, toc_leaders)
    temp_html.write_text(html_with_print_css, encoding="utf-8")

    try:
        html_obj = HTML(filename=str(temp_html))
        html_obj.write_pdf(str(output_pdf), presentational_hints=True)
        print(f"PDF generated: {output_pdf}")

        if page_numbers:
            print(f"  TOC page numbers: Added ({len(page_numbers)} entries)")
        if toc_leaders == "table":
            print("  TOC leaders: Added (table format)")
        elif toc_leaders == "css":
            print("  TOC leaders: Added (CSS ::after)")
        return True

    except Exception as exc:
        print(f"Error generating final PDF: {exc}", file=sys.stderr)
        return False

    finally:
        # Clean up the temp HTML — it's an internal working file, not
        # part of the deliverable.  Set SPECBUILD_KEEP_DEBUG=1 to keep it.
        import os as _os

        if temp_html.exists():
            if _os.environ.get("SPECBUILD_KEEP_DEBUG"):
                print(f"Debug: Temporary HTML kept at {temp_html}")
            else:
                temp_html.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# CLI Entry Point
# ---------------------------------------------------------------------------


def _build_argument_parser() -> argparse.ArgumentParser:
    """Build and return the command-line argument parser."""
    parser = argparse.ArgumentParser(
        description="Generate PDF with clean TOC: indented 3-level depth, right-aligned page numbers",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Generate PDF with clean 3-level TOC (Playwright)
  python3 scripts/generate_pdf_with_toc.py

  # Use WeasyPrint for better page number support
  python3 scripts/generate_pdf_with_toc.py --engine weasyprint

  # Generate PDF with TOC leader dots (using CSS method)
  python3 scripts/generate_pdf_with_toc.py --toc-leaders=css

  # Generate A4 size PDF
  python3 scripts/generate_pdf_with_toc.py --size a4

  # Custom TOC depth (2-6 levels)
  python3 scripts/generate_pdf_with_toc.py --toc-depth 2

  # Without 'Back to TOC' links
  python3 scripts/generate_pdf_with_toc.py --no-toc-links

Note on Page Numbers:
  - Playwright: Page numbers show as placeholders due to CSS limitations
  - WeasyPrint: Better CSS Paged Media support, page numbers should work
  - Recommendation: Try WeasyPrint if page numbers are critical

Features:
  - Table of contents limited to 3 levels (h1, h2, h3)
  - Proper indentation for each level
  - Page numbers on the right side (clickable)
  - Optional leader dots between entries and page numbers (--toc-leaders)
  - Clean, simple layout without highlighting
  - PDF bookmarks (outline) for easy navigation
  - "Back to TOC" links at the end of each major section
  - Smart page breaks and optimized table formatting

Page sizes: letter (8.5x11"), a4 (210x297mm), legal (8.5x14")
        """,
    )

    parser.add_argument(
        "-i", "--input", type=Path, help="Input HTML file (default: auto-detect latest build)"
    )
    parser.add_argument(
        "-o", "--output", type=Path, help="Output PDF file (default: Specification.pdf)"
    )
    parser.add_argument(
        "--size",
        choices=["letter", "a4", "legal"],
        default="letter",
        help="Paper size (default: letter)",
    )
    parser.add_argument("--landscape", action="store_true", help="Use landscape orientation")
    parser.add_argument(
        "--engine",
        choices=["playwright", "weasyprint"],
        default="weasyprint",
        help="PDF generation engine (default: weasyprint - better page numbers)",
    )
    parser.add_argument(
        "--no-toc-links", action="store_true", help="Don't add 'Back to TOC' links at section ends"
    )
    parser.add_argument(
        "--toc-depth",
        type=int,
        default=3,
        choices=[1, 2, 3, 4, 5, 6],
        help="Maximum TOC depth (default: 3 = h1, h2, h3)",
    )
    parser.add_argument(
        "--toc-leaders",
        choices=["none", "css", "table"],
        default="css",
        help="TOC leader dot style: 'css' (default), 'none', or 'table'",
    )
    parser.add_argument(
        "--lof", action="store_true", help="Generate List of Figures with page numbers"
    )
    parser.add_argument(
        "--lot", action="store_true", help="Generate List of Tables with page numbers"
    )
    parser.add_argument(
        "--front-matter-order",
        type=str,
        default=None,
        metavar="ORDER",
        help="Comma-separated order of front-matter elements (e.g. 'toc,lot,lof')",
    )

    return parser


def _resolve_input_html(args: argparse.Namespace) -> Path | None:
    """Resolve the input HTML path from CLI args or auto-detection.

    Args:
        args: Parsed command-line arguments.

    Returns:
        Path to the input HTML file, or ``None`` if not found.
    """
    if args.input:
        return args.input

    # Auto-detect: find the latest build directory matching the expected pattern
    build_dirs = sorted(Path(".").glob(_BUILD_DIR_GLOB))
    if build_dirs:
        input_html = build_dirs[-1] / "index.html"
        print(f"Auto-detected input: {input_html}")
        return input_html

    print("Error: No build directory found and no input specified", file=sys.stderr)
    print("Run 'python compile.py' first or specify input with -i", file=sys.stderr)
    return None


def _print_run_summary(args: argparse.Namespace, input_html: Path, output_pdf: Path) -> None:
    """Print a summary of the PDF generation settings before running.

    Args:
        args: Parsed command-line arguments.
        input_html: Resolved input HTML path.
        output_pdf: Resolved output PDF path.
    """
    separator = "=" * 60
    print(f"\n{separator}")
    print("PDF Generation with Clean TOC")
    print(separator)
    print(f"  Input:     {input_html}")
    print(f"  Output:    {output_pdf}")
    print(f"  Size:      {args.size.upper()}")
    print(f"  Engine:    {args.engine}")
    print(f"  TOC depth: {args.toc_depth} levels")
    print(f"  TOC links: {'No' if args.no_toc_links else 'Yes'}")
    print(f"  TOC leaders: {'Yes' if args.toc_leaders != 'none' else 'No'}")
    if args.lof:
        print("  List of Figures: Yes")
    if args.lot:
        print("  List of Tables: Yes")
    if args.front_matter_order:
        print(f"  Front-matter order: {args.front_matter_order}")
    print(f"{separator}\n")


def _print_success_summary(
    output_pdf: Path,
    args: argparse.Namespace,
    add_toc_links: bool,
) -> None:
    """Print the post-generation success summary.

    Args:
        output_pdf: Path to the generated PDF.
        args: Parsed command-line arguments.
        add_toc_links: Whether "Back to TOC" links were added.
    """
    size_mb = output_pdf.stat().st_size / (1024 * 1024)
    separator = "=" * 60
    print(f"\n{separator}")
    print("Success! PDF generated with clean TOC")
    print(separator)
    print(f"  File: {output_pdf}")
    print(f"  Size: {size_mb:.2f} MB")
    print("\nTOC features:")
    print(f"  - Limited to {args.toc_depth} levels")
    print("  - Indented hierarchy (0em, 1.5em, 3em)")
    print("  - Page numbers on the right side")
    if args.toc_leaders != "none":
        print("  - Leader dots between entries and page numbers")
    print("  - Clean layout without highlighting")
    print("  - PDF bookmarks for easy navigation")
    if add_toc_links:
        print("  - 'Back to TOC' links at section ends")
    print("  - Smart page breaks")
    print("  - Optimized table formatting")
    print(f"{separator}\n")

    if args.engine == "playwright":
        print("Tip: Try --engine weasyprint for actual page numbers in TOC")
        print("    (Playwright has limited CSS Paged Media support)\n")


async def main_async() -> int:
    """Main async entry point.

    Parses command-line arguments, resolves input/output paths, and
    dispatches to the appropriate PDF generation engine.

    Returns:
        Exit code: 0 on success, 1 on failure.
    """
    parser = _build_argument_parser()
    args = parser.parse_args()

    input_html = _resolve_input_html(args)
    if input_html is None:
        return 1

    if not input_html.exists():
        print(f"Error: Input file not found: {input_html}", file=sys.stderr)
        return 1

    output_pdf = args.output if args.output else Path("Specification.pdf")
    add_toc_links = not args.no_toc_links
    fm_order = args.front_matter_order.split(",") if args.front_matter_order else None

    _print_run_summary(args, input_html, output_pdf)

    # Dispatch to the selected PDF engine
    if args.engine == "playwright":
        success = await generate_pdf_playwright(
            input_html,
            output_pdf,
            args.size,
            args.landscape,
            add_toc_links,
            args.toc_depth,
            args.toc_leaders,
        )
    else:
        success = generate_pdf_weasyprint(
            input_html,
            output_pdf,
            args.size,
            add_toc_links,
            args.toc_depth,
            args.toc_leaders,
            args.lof,
            args.lot,
            fm_order,
        )

    if success:
        _print_success_summary(output_pdf, args, add_toc_links)
        return 0
    else:
        print("\nFailed to generate PDF", file=sys.stderr)
        return 1


def main() -> int:
    """Synchronous main entry point."""
    return asyncio.run(main_async())


if __name__ == "__main__":
    sys.exit(main())
