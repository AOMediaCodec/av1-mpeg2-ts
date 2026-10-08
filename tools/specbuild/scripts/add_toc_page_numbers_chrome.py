#!/usr/bin/env python3
"""
Add page numbers to Table of Contents for Chrome headless PDF generation.

This script uses a two-pass approach:
1. Generate initial PDF with annotated anchors
2. Extract page numbers from PDF by finding anchor annotations
3. Update HTML with hardcoded page numbers
4. Final PDF will be regenerated with page numbers in TOC

This is specifically for basic Chrome headless (--pdf mode), not Paged.js.
"""

import logging
import re
import subprocess
import sys
from pathlib import Path

from bs4 import BeautifulSoup, Tag

# Allow importing from the specbuild package when running as a standalone script.
_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from specbuild.logsetup import setup_logging  # noqa: E402
from specbuild.theme import THEME  # noqa: E402

setup_logging("INFO")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Chrome virtual time budget (ms) — gives JS/rendering time to finish before PDF capture
CHROME_VIRTUAL_TIME_BUDGET_MS = 30000

# Front-matter skip heuristic: skip total_pages // FRONT_MATTER_DIVISOR pages,
# clamped to [FRONT_MATTER_SKIP_MIN, FRONT_MATTER_SKIP_MAX].
FRONT_MATTER_DIVISOR = 20
FRONT_MATTER_SKIP_MIN = 2
FRONT_MATTER_SKIP_MAX = 10

# When matching short unnumbered headings (e.g. "Index", "References"),
# only scan this many lines from the top of each page.
SHORT_HEADING_MAX_SCAN_LINES = 100

# For long headings that may wrap in the PDF, use the first N characters.
LONG_HEADING_CHAR_THRESHOLD = 50

# Placeholder page number width — three digits keeps TOC column width stable.
PAGE_NUMBER_PLACEHOLDER = "000"

# How many characters before an <h2> to check for an existing "back to TOC" link.
BACK_TO_TOC_LOOKBACK_CHARS = 500

# Unicode ligature → ASCII decomposition map used during PDF text extraction.
# PDF renderers often embed ligature glyphs, but HTML IDs use plain ASCII.
LIGATURE_MAP: dict[str, str] = {
    "\ufb01": "fi",  # ﬁ
    "\ufb02": "fl",  # ﬂ
    "\ufb03": "ffi",  # ﬃ
    "\ufb04": "ffl",  # ﬄ
    "\ufb00": "ff",  # ﬀ
    "\ufb05": "ft",  # ﬅ
    "\ufb06": "st",  # ﬆ
}

# Regex matching numbered <h2> section headings with a data-level attribute.
# Groups: (1) full <h2>…</h2>, (2) data-level value, (3) id attribute value.
H2_SECTION_PATTERN = re.compile(
    r'(<h2[^>]*class="[^"]*heading settled[^"]*"[^>]*data-level="(\d+)"'
    r'[^>]*id="([^"]+)"[^>]*>.*?</h2>)',
    re.DOTALL,
)

# Section IDs that should NOT receive "Back to TOC" links (non-content sections).
SKIP_BACK_TO_TOC_SECTIONS = frozenset(
    {
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
)

# ---------------------------------------------------------------------------
# PDF generation helpers
# ---------------------------------------------------------------------------


def generate_temp_pdf_with_markers(html_path: Path, chrome_path: str, output_pdf: Path) -> bool:
    """
    Generate a temporary PDF directly from the HTML (no markers needed).

    We'll extract page numbers by finding section headings in the PDF text.
    """
    logging.info("Generating temporary PDF for page number extraction...")

    # Generate PDF directly from the HTML (with placeholders already in place)
    command = [
        chrome_path,
        "--headless",
        "--no-pdf-header-footer",
        "--disable-gpu",
        "--run-all-compositor-stages-before-draw",
        f"--virtual-time-budget={CHROME_VIRTUAL_TIME_BUDGET_MS}",
        f"--print-to-pdf={output_pdf}",
        str(html_path),
    ]

    try:
        subprocess.run(command, check=True, capture_output=True)
        logging.info(f"Generated temporary PDF: {output_pdf}")
        return True
    except subprocess.CalledProcessError as e:
        logging.error(f"Failed to generate temporary PDF: {e}")
        return False


def normalize_ligatures(text: str) -> str:
    """
    Normalize Unicode ligatures to their component characters.

    PDF text extraction often returns ligatures (ﬁ, ﬂ, etc.) but HTML IDs use separate characters.

    Args:
        text: Input string potentially containing Unicode ligature characters.

    Returns:
        String with all known ligatures replaced by their ASCII equivalents.
    """
    for ligature, replacement in LIGATURE_MAP.items():
        text = text.replace(ligature, replacement)
    return text


# ---------------------------------------------------------------------------
# Section-heading matching helpers (used by extract_page_numbers_from_pdf)
# ---------------------------------------------------------------------------


def _clean_line(line: str) -> str:
    """Strip section signs and whitespace, then normalize ligatures."""
    return normalize_ligatures(line.replace("§", "").strip())


def _has_leader_dots(text: str) -> bool:
    """Return True if text contains leader dots typical of TOC/LOT/LOF entries."""
    return ". . " in text


def _should_log_match(match_count: int) -> bool:
    """Return True if this match should be logged (first 20, then every 50th)."""
    return match_count <= 20 or match_count % 50 == 0


def _try_match_long_caption(
    text: str, pattern_prefix: str, section_id: str, page_num: int, page_map: dict[str, int]
) -> bool:
    """
    Try to match a long table/figure caption by scanning individual lines.

    Scans line-by-line to avoid matching TOC/LOT entries that contain leader dots.

    Returns:
        True if a match was found and added to page_map.
    """
    for line in text.split("\n"):
        line_clean = _clean_line(line)
        if _has_leader_dots(line_clean):
            continue
        if pattern_prefix.lower() in line_clean.lower():
            page_map[section_id] = page_num
            if _should_log_match(len(page_map)):
                logging.debug(f"Found caption '{section_id}' on page {page_num}")
            return True
    return False


def _try_match_long_heading(
    text: str, pattern_prefix: str, section_id: str, page_num: int, page_map: dict[str, int]
) -> bool:
    """
    Try to match a long section heading by joining lines (headings may wrap in PDF).

    Returns:
        True if a match was found and added to page_map.
    """
    text_clean = text.replace("\n", " ").replace("§", "").strip()
    if pattern_prefix.lower() in text_clean.lower():
        page_map[section_id] = page_num
        if _should_log_match(len(page_map)):
            logging.debug(f"Found section '{section_id}' on page {page_num}")
        return True
    return False


def _try_match_short_unnumbered(
    text: str, pattern_clean: str, section_id: str, page_num: int, page_map: dict[str, int]
) -> bool:
    """
    Try to match a short unnumbered heading (e.g. "Index", "References") via exact match.

    Only scans the first SHORT_HEADING_MAX_SCAN_LINES lines of the page.

    Returns:
        True if a match was found and added to page_map.
    """
    lines = text.split("\n")
    for line_idx, line in enumerate(lines[:SHORT_HEADING_MAX_SCAN_LINES]):
        line_clean = _clean_line(line)
        if line_clean.lower() == pattern_clean.lower():
            page_map[section_id] = page_num
            if _should_log_match(len(page_map)):
                logging.debug(f"Found section '{section_id}' on page {page_num} (line {line_idx})")
            return True
    return False


def _try_match_standard_heading(
    text: str, pattern_clean: str, section_id: str, page_num: int, page_map: dict[str, int]
) -> bool:
    """
    Try to match a numbered or multi-word heading using strict line-based matching.

    Requires the line to start with the pattern (exact or followed by a space),
    which avoids false positives like matching "9.1. General" inside
    "6.19.1. General tile group...".

    Returns:
        True if a match was found and added to page_map.
    """
    for line in text.split("\n"):
        line_clean = _clean_line(line)
        if _has_leader_dots(line_clean):
            continue
        if line_clean.lower() == pattern_clean.lower() or line_clean.lower().startswith(
            pattern_clean.lower() + " "
        ):
            page_map[section_id] = page_num
            if _should_log_match(len(page_map)):
                logging.debug(f"Found section '{section_id}' on page {page_num}")
            return True
    return False


def _match_section_on_page(
    section_id: str,
    section_pattern: str,
    page_text: str,
    page_num: int,
    page_map: dict[str, int],
) -> None:
    """
    Attempt to locate *section_pattern* within *page_text* and, on success,
    record the mapping ``section_id -> page_num`` in *page_map*.

    The matching strategy varies by heading type:
    - Long headings (>50 chars) that may wrap across PDF lines
    - Short unnumbered headings matched via exact line comparison
    - Standard numbered/multi-word headings matched at line start
    """
    if section_id in page_map:
        return  # Already located on an earlier page

    pattern_clean = _clean_line(section_pattern)
    word_count = len(pattern_clean.split())
    has_section_number = bool(pattern_clean) and pattern_clean[0].isdigit()
    is_caption = pattern_clean.startswith("Table ") or pattern_clean.startswith("Figure ")

    # --- Long headings may wrap across lines in the PDF ---
    if len(pattern_clean) > LONG_HEADING_CHAR_THRESHOLD:
        pattern_prefix = pattern_clean[:LONG_HEADING_CHAR_THRESHOLD]
        if is_caption:
            _try_match_long_caption(page_text, pattern_prefix, section_id, page_num, page_map)
        else:
            _try_match_long_heading(page_text, pattern_prefix, section_id, page_num, page_map)
        return

    # --- Short unnumbered headings (e.g. "Index", "References") ---
    if not has_section_number and word_count <= 3 and len(pattern_clean) < 40:
        _try_match_short_unnumbered(page_text, pattern_clean, section_id, page_num, page_map)
        return

    # --- Standard numbered or multi-word headings ---
    _try_match_standard_heading(page_text, pattern_clean, section_id, page_num, page_map)


def _write_page_map_debug(pdf_path: Path, page_map: dict[str, int]) -> None:
    """Write the section-to-page mapping to a text file for debugging."""
    debug_file = pdf_path.parent / "page_map_debug.txt"
    with open(debug_file, "w", encoding="utf-8") as f:
        for section_id, page_num in sorted(page_map.items(), key=lambda x: x[1]):
            f.write(f"{section_id} -> page {page_num}\n")
    logging.info(f"Saved page map to {debug_file} for debugging")


# ---------------------------------------------------------------------------
# Page number extraction
# ---------------------------------------------------------------------------


def extract_page_numbers_from_pdf(pdf_path: Path) -> dict[str, int]:
    """
    Extract page numbers by finding section headings in the PDF.

    Instead of using markers, we look for the actual section headings
    which appear as "1. Scope", "2. Terms and definitions", etc.

    Returns:
        Dictionary mapping section IDs to page numbers
    """
    try:
        import pypdf
    except ImportError:
        logging.error("=" * 60)
        logging.error("pypdf library not installed!")
        logging.error("")
        logging.error("To enable page numbers in --pdf mode, install pypdf:")
        logging.error("  pip install pypdf")
        logging.error("")
        logging.error("Alternatively, use --pagedjs or --weasyprint for page numbers:")
        logging.error("  python3 compile.py --pagedjs")
        logging.error("  python3 compile.py --weasyprint")
        logging.error("=" * 60)
        return {}

    logging.info(f"Extracting page numbers from PDF: {pdf_path}")

    # First, get a mapping of section numbers/titles from the HTML
    html_path = pdf_path.parent / (pdf_path.stem.removesuffix("_temp") + ".html")
    section_info = get_section_info_from_html(html_path)

    page_map: dict[str, int] = {}

    try:
        reader = pypdf.PdfReader(str(pdf_path))
        total_pages = len(reader.pages)

        # Dynamically calculate pages to skip based on document size.
        # Front matter (TOC, LOF, LOT) scales roughly with document size.
        skip_pages = max(
            FRONT_MATTER_SKIP_MIN,
            min(FRONT_MATTER_SKIP_MAX, total_pages // FRONT_MATTER_DIVISOR),
        )
        logging.info(f"PDF has {total_pages} pages, skipping first {skip_pages} (front matter)")

        for page_num, page in enumerate(reader.pages, start=1):
            if page_num <= skip_pages:
                continue  # Skip front-matter pages to avoid false TOC matches

            try:
                page_text = page.extract_text()
            except Exception as e:
                logging.debug(f"Failed to extract text from page {page_num}: {e}")
                page_text = ""

            page_text = normalize_ligatures(page_text)

            # Try to locate each not-yet-found section on this page
            for section_id, section_pattern in section_info.items():
                _match_section_on_page(
                    section_id,
                    section_pattern,
                    page_text,
                    page_num,
                    page_map,
                )

        logging.info(f"Extracted page numbers for {len(page_map)} sections")

        # Log first 10 sections found for debugging
        logging.debug("First 10 sections found:")
        for i, (sid, pnum) in enumerate(list(page_map.items())[:10], 1):
            logging.debug(f"  {i}. {sid} -> page {pnum}")

        _write_page_map_debug(pdf_path, page_map)

        return page_map

    except Exception as e:
        logging.error(f"Failed to extract page numbers: {e}")
        return {}


# ---------------------------------------------------------------------------
# HTML section / caption info extraction
# ---------------------------------------------------------------------------


def get_section_info_from_html(html_path: Path) -> dict[str, str]:
    """
    Get section IDs and their heading text from HTML.

    Scans headings (h2-h6), table captions, and figure captions to build a
    mapping used by the PDF page-number extraction pass.

    Args:
        html_path: Path to the compiled HTML specification file.

    Returns:
        Dictionary mapping element IDs to their visible text
        (e.g. ``{"scope": "1. Scope", "table-1": "Table 1 — Symbol list"}``).
    """
    with open(html_path, encoding="utf-8") as f:
        html = f.read()

    soup = BeautifulSoup(html, "html.parser")

    section_info: dict[str, str] = {}

    # Find all section headings
    for heading in soup.find_all(["h2", "h3", "h4", "h5", "h6"], id=True):
        section_id = heading.get("id")
        if section_id and not section_id.startswith("ref-for-"):
            # Get the heading text (section number + content)
            heading_text = heading.get_text().strip()
            section_info[section_id] = heading_text

    heading_count = len(section_info)
    logging.info(f"Extracted {heading_count} section headings from HTML")

    # Find all table captions with IDs (for LOT page number extraction)
    table_count = 0
    for caption in soup.find_all("caption", id=True):
        caption_id = caption.get("id")
        if caption_id:
            caption_text = caption.get_text().strip()
            section_info[caption_id] = caption_text
            table_count += 1

    # Also check table elements with IDs that have captions
    for table in soup.find_all("table", id=True):
        table_id = table.get("id")
        if table_id and table_id not in section_info:
            caption = table.find("caption")
            if caption:
                caption_text = caption.get_text().strip()
                section_info[table_id] = caption_text
                table_count += 1

    if table_count > 0:
        logging.info(f"Extracted {table_count} table captions from HTML")

    # Find all figure captions with IDs (for LOF page number extraction)
    figure_count = 0
    for figure in soup.find_all("figure", id=True):
        figure_id = figure.get("id")
        if figure_id:
            figcaption = figure.find("figcaption")
            if figcaption:
                caption_text = figcaption.get_text().strip()
                section_info[figure_id] = caption_text
                figure_count += 1

    # Also check figcaption elements with IDs (bikeshed puts ID on figcaption, not figure)
    for figcaption in soup.find_all("figcaption", id=True):
        figcaption_id = figcaption.get("id")
        if figcaption_id and figcaption_id not in section_info:
            caption_text = figcaption.get_text().strip()
            section_info[figcaption_id] = caption_text
            figure_count += 1

    if figure_count > 0:
        logging.info(f"Extracted {figure_count} figure captions from HTML")

    return section_info


# ---------------------------------------------------------------------------
# TOC structure manipulation (flatten, placeholders, page-number update)
# ---------------------------------------------------------------------------


def flatten_toc_structure(toc_nav: Tag, soup: BeautifulSoup) -> int:
    """
    Flatten nested TOC list structure into a single-level list with explicit level markers.

    Args:
        toc_nav: The <nav id="toc"> element
        soup: BeautifulSoup object

    Returns:
        Number of entries processed
    """
    # Find the top-level TOC list
    top_ol = toc_nav.find("ol", class_="toc")
    if not top_ol:
        logging.warning("No top-level TOC list found")
        return 0

    # Collect all entries with their levels.
    # We cannot use recursive=False on <li> elements because bikeshed emits
    # unclosed <li> tags, which BeautifulSoup nests all under the first one.
    # Instead walk all <a> tags directly and infer level from section number.
    entries = []

    for link in toc_nav.find_all("a", href=lambda x: x and x.startswith("#")):
        secno = link.find("span", class_="secno")
        secno_text = secno.get_text(strip=True).rstrip(".") if secno else ""
        if secno_text:
            level = len(secno_text.split("."))
        else:
            # Unnumbered entries: infer level from DOM nesting depth
            # (count ancestor <ol> elements within the TOC nav)
            depth = sum(1 for p in link.parents if p.name == "ol" and p is not toc_nav)
            level = max(1, depth)
        entries.append({"level": level, "link": link})

    logging.info(
        f"Collected {len(entries)} TOC entries across {max((e['level'] for e in entries), default=0)} levels"
    )

    # Create new flat list
    new_ol = soup.new_tag("ol", **{"class": "toc", "role": "directory"})

    for entry in entries:
        level = entry["level"]
        link = entry["link"]

        # Create new list item with level marker
        new_li = soup.new_tag("li")
        new_li["data-level"] = str(level)

        # Create new link
        new_link = soup.new_tag("a", href=link.get("href"))

        # Add indent span at the beginning
        indent_span = soup.new_tag("span", **{"class": "toc-indent", "data-level": str(level)})
        new_link.append(indent_span)

        # Copy existing spans (secno, content)
        for child in link.children:
            if child.name == "span" and child.get("class"):
                classes = child.get("class")
                if "secno" in classes or "content" in classes:
                    new_link.append(child.__copy__())

        new_li.append(new_link)
        new_ol.append(new_li)

    # Replace the old nested structure with the new flat structure
    top_ol.replace_with(new_ol)

    return len(entries)


def add_placeholder_page_numbers(html_path: Path) -> None:
    """
    Add placeholder page numbers to all TOC entries.

    This ensures the temp PDF has the same TOC size as the final PDF,
    so page numbers will be accurate.
    """
    with open(html_path, encoding="utf-8") as f:
        html = f.read()

    soup = BeautifulSoup(html, "html.parser")

    # Find TOC
    toc = soup.find("nav", id="toc")
    if not toc:
        logging.warning("No TOC found in HTML")
        return

    # Flatten the TOC structure
    flatten_toc_structure(toc, soup)

    # Add placeholder page numbers to all TOC links
    links = toc.find_all("a", href=True)
    added_count = 0

    for link in links:
        href = link.get("href", "")
        if not href or not href.startswith("#"):
            continue

        # Remove existing leader dots and page number if present
        existing_leader = link.find("span", class_="toc-leader")
        if existing_leader:
            existing_leader.extract()
        existing_span = link.find("span", class_="toc-page-number")
        if existing_span:
            existing_span.extract()

        # Add leader dots span
        leader_span = soup.new_tag("span", **{"class": "toc-leader"})
        link.append(leader_span)

        # Add placeholder page number (3-digit to account for max page width)
        page_span = soup.new_tag("span", **{"class": "toc-page-number"})
        page_span.string = PAGE_NUMBER_PLACEHOLDER
        link.append(page_span)
        added_count += 1

    # Add CSS for TOC styling
    add_toc_page_number_css(soup)

    # Write back updated HTML
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(str(soup))

    logging.info(f"Added {added_count} placeholder page numbers to TOC")


def update_page_numbers_in_html(html_path: Path, page_map: dict[str, int]) -> None:
    """
    Update placeholder page numbers with actual values from page_map.

    Args:
        html_path: Path to HTML file
        page_map: Dictionary mapping section IDs to page numbers
    """
    with open(html_path, encoding="utf-8") as f:
        html = f.read()

    soup = BeautifulSoup(html, "html.parser")

    # Find TOC
    toc = soup.find("nav", id="toc")
    if not toc:
        logging.warning("No TOC found in HTML")
        return

    # Update page numbers in all TOC links
    links = toc.find_all("a", href=True)
    updated_count = 0
    missing_sections = []

    for link in links:
        href = link.get("href", "")
        if not href or not href.startswith("#"):
            continue

        # Get anchor ID (remove #)
        anchor_id = href[1:]

        # Find the placeholder page number span
        page_span = link.find("span", class_="toc-page-number")
        if not page_span:
            continue

        # Look up actual page number
        if anchor_id in page_map:
            page_num = page_map[anchor_id]
            page_span.string = str(page_num)
            updated_count += 1
        else:
            # Section not found - check for similar IDs
            section_text = link.get_text().strip()[:40]
            similar_ids = [
                k
                for k in page_map.keys()
                if k.lower().replace("-", "_") == anchor_id.lower().replace("-", "_")
            ]
            if similar_ids:
                logging.debug(f"Found similar ID for {anchor_id}: {similar_ids[0]}")
                page_num = page_map[similar_ids[0]]
                page_span.string = str(page_num)
                updated_count += 1
            else:
                missing_sections.append(f"{anchor_id}: {section_text}")
                # Leave placeholder as is

    # Report missing sections
    if missing_sections:
        logging.warning(f"Could not find page numbers for {len(missing_sections)} TOC entries:")
        for i, missing in enumerate(missing_sections[:10], 1):
            logging.warning(f"  {i}. {missing}")
        if len(missing_sections) > 10:
            logging.warning(f"  ... and {len(missing_sections) - 10} more")

    # Write back updated HTML
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(str(soup))

    logging.info(f"Updated {updated_count} TOC entries with actual page numbers")


# ---------------------------------------------------------------------------
# CSS injection for TOC styling
# ---------------------------------------------------------------------------


def add_toc_page_number_css(soup: BeautifulSoup) -> None:
    """
    Add CSS styling for TOC page numbers to ensure proper right alignment.

    Injects a ``<style>`` block into the document ``<head>`` that styles the
    flattened TOC list with flexbox layout, leader dots via ``::after``,
    and right-aligned page numbers.

    Args:
        soup: Parsed HTML document to modify in place.
    """
    t = THEME
    head = soup.find("head")
    if not head:
        logging.warning("No <head> found in HTML")
        return

    # Create style tag for TOC page number styling
    style_tag = soup.new_tag("style", id="toc-page-numbers-chrome")

    # CSS for proper TOC layout with right-aligned page numbers
    css_content = f"""
/* TOC Page Numbers for Chrome Headless PDF - FLATTENED + FLEXBOX */

/* Bikeshed uses @supports(display:grid) to make #toc a CSS grid with
   #toc li/a set to display:contents. This breaks our flexbox page-number
   layout.  Force #toc back to block so li elements flow normally.
   Also force a page break before the TOC — Chrome does not reliably
   honour the named-page ("page: front-matter") transition alone. */
#toc {{
  display: block !important;
  break-before: page !important;
  page-break-before: always !important;
}}

/* Center the Table of Contents title */
#toc h2#contents {{
  text-align: center !important;
}}

/* TOC list items - NO nesting, all at same level */
#toc li {{
  display: block !important;
  margin: 0.3em 0;
  line-height: 1.4;
  padding-left: 0 !important;  /* No padding on li */
  list-style: none;
}}

/* TOC links - flexbox layout (ORIGINAL DESIGN) */
#toc li a {{
  display: flex !important;
  align-items: baseline !important;  /* Baseline alignment */
  text-decoration: none !important;
  line-height: 1.4 !important;
  overflow: hidden !important;  /* Prevent overflow */
  white-space: nowrap !important;  /* No wrapping */
}}

/* Indent span - fixed width, doesn't shrink */
#toc li a .toc-indent {{
  flex: 0 0 auto;
}}

.toc-indent[data-level="1"] {{
  width: 0;
}}

.toc-indent[data-level="2"] {{
  width: 1em;
}}

.toc-indent[data-level="3"] {{
  width: 2em;
}}

.toc-indent[data-level="4"] {{
  width: 3em;
}}

.toc-indent[data-level="5"] {{
  width: 4em;
}}

/* Section number - fixed, no wrap */
#toc li a .secno {{
  flex: 0 0 auto;
  margin-right: 0.5em;
  white-space: nowrap;
}}

/* Content - no wrapping */
#toc li a .content {{
  flex: 0 0 auto;  /* Fixed size, no shrinking */
  white-space: nowrap;  /* Never wrap */
}}

/* Leader dots - fills remaining space naturally */
#toc li a .toc-leader {{
  flex: 1 1 auto;  /* Grows to fill space, can shrink if needed */
  overflow: hidden;
  white-space: nowrap;
  margin: 0 0.5em;
  /* No min-width - let it shrink naturally to fit content */
}}

#toc li a .toc-leader::after {{
  /* Repeated dot pattern — overflow:hidden clips excess beyond the available width */
  content: ' . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . ';
  color: {t.color_muted};
  font-weight: normal;
}}

/* Page numbers - right aligned */
#toc li a .toc-page-number {{
  flex: 0 0 auto !important;
  text-align: right !important;
  min-width: 3em !important;
  font-weight: normal !important;
}}

/* TOC level font weights — primary sections bold, sub-levels normal */
#toc li[data-level="1"] {{
  font-weight: bold;
}}

#toc li:not([data-level="1"]) {{
  font-weight: normal;
}}
"""

    style_tag.string = css_content
    head.append(style_tag)
    logging.info("Added CSS for TOC page number styling (flattened + flexbox)")


def convert_toc_to_table_format(html_path: Path, page_map: dict[str, int]) -> None:
    """
    Convert TOC from list format to table format with page numbers.

    This is used when toc_leaders="table" is specified.
    Converts the TOC list to a two-column table for perfect alignment.

    Args:
        html_path: Path to HTML file
        page_map: Dictionary mapping section IDs to page numbers
    """
    with open(html_path, encoding="utf-8") as f:
        html = f.read()

    soup = BeautifulSoup(html, "html.parser")

    # Find TOC
    toc_nav = soup.find("nav", id="toc")
    if not toc_nav:
        logging.warning("No TOC found in HTML")
        return

    # Find the TOC list
    toc_list = toc_nav.find("ol", class_="toc")
    if not toc_list:
        logging.warning("No TOC list found in HTML")
        return

    # Create table structure
    table = soup.new_tag("table", **{"class": "toc-table"})

    # Add colgroup to explicitly define column widths
    colgroup = soup.new_tag("colgroup")
    col1 = soup.new_tag("col", style="width: 465pt;")  # Section + dots column
    col2 = soup.new_tag("col", style="width: 75pt;")  # Page numbers column
    colgroup.append(col1)
    colgroup.append(col2)
    table.append(colgroup)

    tbody = soup.new_tag("tbody")
    table.append(tbody)

    # Get all links in the TOC
    all_links = toc_list.find_all("a", href=lambda x: x and x.startswith("#"))

    for link in all_links:
        anchor_id = link.get("href", "").lstrip("#")
        if anchor_id not in page_map:
            continue

        # Extract section number and title
        secno_span = link.find("span", class_="secno")
        content_span = link.find("span", class_="content")

        secno_text = secno_span.get_text(strip=True) if secno_span else ""
        content_text = content_span.get_text(strip=True) if content_span else ""
        page_num = page_map[anchor_id]

        # Determine level from section number
        level = 1
        if secno_text:
            level = secno_text.count(".") + 1
            level = min(level, 3)

        # Create table row
        tr = soup.new_tag("tr", **{"class": f"toc-level-{level}"})

        # First column: section info + leader dots
        td1 = soup.new_tag("td", **{"class": "toc-section"})
        section_link = soup.new_tag("a", href=link.get("href"))

        if secno_text:
            secno_new = soup.new_tag("span", **{"class": "secno"})
            secno_new.string = secno_text
            section_link.append(secno_new)
            section_link.append(" ")

        content_new = soup.new_tag("span", **{"class": "content"})
        content_new.string = content_text
        section_link.append(content_new)

        # Add leader dots span
        dots_span = soup.new_tag("span", **{"class": "toc-leaders"})
        dots_span.string = " ." * 100  # Lots of dots, overflow:hidden will clip excess
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

    # Add table-specific CSS
    add_toc_table_css(soup)

    # Write back to file
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(str(soup))

    logging.info(f"Converted TOC to table format with {len(all_links)} entries")


def add_toc_table_css(soup: BeautifulSoup) -> None:
    """
    Add CSS for the table-based TOC layout.

    Injects a ``<style>`` block that styles the two-column TOC table
    (section text + leader dots | page number).

    Args:
        soup: Parsed HTML document to modify in place.
    """
    t = THEME
    head = soup.find("head")
    if not head:
        return

    style_tag = soup.new_tag("style", id="toc-table-chrome")

    css_content = f"""
/* TOC Table Format for Chrome Headless PDF */

#toc {{
    border: none !important;
    outline: none !important;
    box-shadow: none !important;
}}

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

table.toc-table tr {{
    page-break-inside: avoid;
    border: none !important;
}}

table.toc-table td {{
    padding: 3pt 0;
    vertical-align: top;
    border: none !important;
}}

table.toc-table td.toc-section {{
    width: 86% !important;  /* 465/540 = 86% */
    padding-right: 5pt;  /* Less padding to keep dots closer */
    overflow: hidden;
    white-space: nowrap;
}}

table.toc-table td.toc-section a {{
    color: {t.color_accent};
    text-decoration: none;
    display: block;
    overflow: hidden;
    white-space: nowrap;
    text-overflow: ellipsis;
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

table.toc-table td.toc-page {{
    width: 14% !important;  /* 75/540 = 14% */
    min-width: 70pt !important;
    max-width: 80pt !important;
    text-align: right;
    white-space: nowrap;
    padding-left: 0;
    padding-right: 0.5em;
    position: relative;
    left: -10pt;  /* Pull entire column left closer to dots */
}}

table.toc-table td.toc-page a {{
    color: {t.color_text};
    text-decoration: none;
    font-weight: normal;
    display: inline-block;
}}

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
    font-size: {t.table_font_size}pt;
}}
"""

    style_tag.string = css_content
    head.append(style_tag)
    logging.info("Added CSS for TOC table format")


# ---------------------------------------------------------------------------
# "Back to TOC" link injection
# ---------------------------------------------------------------------------


def inject_back_to_toc_links(html_path: Path) -> None:
    """
    Inject "Back to TOC" links at the end of major sections.
    Only adds links to numbered sections (h2 with class="heading settled").
    Skips non-content sections like abstract, references, index.

    Args:
        html_path: Path to HTML file to modify
    """
    with open(html_path, encoding="utf-8") as f:
        html_content = f.read()

    matches = list(re.finditer(H2_SECTION_PATTERN, html_content))

    modified_html = html_content
    links_added = 0

    for match in reversed(matches):
        section_id = match.group(3)
        section_level = match.group(2)

        if section_id in SKIP_BACK_TO_TOC_SECTIONS:
            continue

        # Skip adding link before the very first content section (level 1)
        if section_level == "1":
            continue

        start_pos = match.start()

        # Check if a "Back to TOC" link already exists before this section
        check_start = max(0, start_pos - BACK_TO_TOC_LOOKBACK_CHARS)
        preceding_text = modified_html[check_start:start_pos]

        if "back-to-toc" in preceding_text.lower() or "Back to Table of Contents" in preceding_text:
            # Link already exists, skip
            continue

        back_link = '<p class="back-to-toc-wrapper"><a href="#toc" class="back-to-toc">Back to Table of Contents</a></p>\n\n'

        modified_html = modified_html[:start_pos] + back_link + modified_html[start_pos:]
        links_added += 1

    # Write back modified HTML
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(modified_html)

    if links_added > 0:
        logging.info(f"Added {links_added} 'Back to TOC' links")


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------


def add_toc_page_numbers_chrome(
    html_path: Path, chrome_path: str, toc_leaders: str = "css"
) -> None:
    """
    Add page numbers to TOC for Chrome headless using two-pass approach.

    Strategy to ensure accuracy:
    1. Add placeholder page numbers to HTML first (to match final TOC size)
    2. Generate temp PDF with markers (with placeholders in place)
    3. Extract page numbers from temp PDF
    4. Update placeholders with actual page numbers
    5. Final PDF will have correct page numbers

    Args:
        html_path: Path to HTML file
        chrome_path: Path to Chrome executable
        toc_leaders: TOC leader style ("none", "css", or "table")
    """
    logging.debug("=" * 60)
    logging.debug("Adding TOC page numbers for Chrome headless (two-pass)")
    logging.debug("=" * 60)

    # Different workflow for table format vs list format
    if toc_leaders == "table":
        # Table format: don't add placeholders, generate temp PDF, convert to table with page numbers
        logging.info("Using table format for TOC...")

        # Step 1: Generate temporary PDF without modifications (list format)
        temp_pdf = html_path.parent / f"{html_path.stem}_temp.pdf"
        success = generate_temp_pdf_with_markers(html_path, chrome_path, temp_pdf)

        if not success:
            logging.error("Failed to generate temporary PDF")
            return

        # Step 2: Extract page numbers from PDF
        page_map = extract_page_numbers_from_pdf(temp_pdf)

        if not page_map:
            logging.warning("No page numbers extracted from PDF")
            if temp_pdf.exists():
                temp_pdf.unlink()
            return

        # Clean up temp PDF
        if temp_pdf.exists():
            temp_pdf.unlink()
            logging.info("Cleaned up temporary PDF")

        # Step 3: Convert TOC to table format with page numbers
        convert_toc_to_table_format(html_path, page_map)
    else:
        # List format (css or none): use existing approach with placeholders
        logging.info(f"Using list format for TOC (toc_leaders={toc_leaders})...")

        # Step 0: Pre-process HTML to add placeholder page numbers
        # This ensures the temp PDF has the same TOC size as the final PDF
        logging.info("Step 1: Adding placeholder page numbers to TOC...")
        add_placeholder_page_numbers(html_path)

        # Step 1: Generate temporary PDF with markers (now with placeholders in place)
        temp_pdf = html_path.parent / f"{html_path.stem}_temp.pdf"
        success = generate_temp_pdf_with_markers(html_path, chrome_path, temp_pdf)

        if not success:
            logging.error("Failed to generate temporary PDF")
            return

        # Step 2: Extract page numbers from PDF
        page_map = extract_page_numbers_from_pdf(temp_pdf)

        if not page_map:
            logging.warning("No page numbers extracted from PDF")
            # Clean up temp PDF
            if temp_pdf.exists():
                temp_pdf.unlink()
            return

        # Clean up temp PDF
        if temp_pdf.exists():
            temp_pdf.unlink()
            logging.info("Cleaned up temporary PDF")

        # Step 3: Update placeholders with actual page numbers
        update_page_numbers_in_html(html_path, page_map)

    # Step 4: Add "Back to TOC" links at the end of each section
    logging.debug("Adding 'Back to TOC' links...")
    inject_back_to_toc_links(html_path)

    logging.debug("=" * 60)
    logging.info("TOC page numbers updated successfully")
    logging.debug("=" * 60)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Add page numbers to TOC for Chrome headless PDF")
    parser.add_argument("html_file", type=Path, help="Path to HTML file")
    parser.add_argument("chrome_path", type=str, help="Path to Chrome executable")
    parser.add_argument(
        "--toc-leaders",
        choices=["none", "css", "table"],
        default="css",
        help="TOC leader style: none (no dots), css (CSS ::after), table (table format)",
    )

    args = parser.parse_args()

    if not args.html_file.exists():
        logging.error(f"HTML file not found: {args.html_file}")
        sys.exit(1)

    add_toc_page_numbers_chrome(args.html_file, args.chrome_path, args.toc_leaders)
