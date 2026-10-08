"""PDF fallback converter using pypdf.

This provides a lower-fidelity import path for when only a PDF is
available (no Word source).  Heuristics detect headings, tables, and
images, but the results require significantly more manual review than
the DOCX path.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from specbuild.input.report import ConversionReport, generate_report_html, generate_report_text
from specbuild.input.utils import make_html_id as _clean_heading_id
from specbuild.input.utils import sanitize_filename as _sanitize_filename

#: Matches numbered heading patterns: "5.1.2 Heading text", "A.3 Annex heading"
_HEADING_NUM_RE = re.compile(r"^(\d+(?:\.\d+)*|[A-Z](?:\.\d+(?:\.\d+)*)?)[\.\s]+([A-Z][A-Za-z].*)")

#: Matches ALL CAPS lines (potential headings).
_ALL_CAPS_RE = re.compile(r"^[A-Z][A-Z\s\-\d\.]{4,}$")

#: Matches table-like lines with multiple columns separated by whitespace.
_TABLE_ROW_RE = re.compile(r"^\s*\S+(?:\s{2,}\S+){2,}\s*$")


def _is_likely_heading(line: str) -> bool:
    """Heuristically detect if a line is a heading."""
    stripped = line.strip()
    if not stripped:
        return False
    if _HEADING_NUM_RE.match(stripped):
        return True
    if _ALL_CAPS_RE.match(stripped) and len(stripped) < 80:
        return True
    return False


def _heading_level_from_text(text: str) -> int:
    """Guess heading level from numbering depth."""
    m = _HEADING_NUM_RE.match(text.strip())
    if m:
        number_part = m.group(1)
        dots = number_part.count(".")
        return min(dots + 1, 6)
    return 1


# ---------------------------------------------------------------------------
# PDF text extraction
# ---------------------------------------------------------------------------


def _extract_pdf_text(pdf_path: Path) -> list[dict]:
    """Extract text from each page of a PDF.

    Returns:
        List of dicts with keys: ``page_num``, ``text``.
    """
    try:
        from pypdf import PdfReader
    except ImportError:
        logging.error("pypdf is required for PDF import. Install it: pip install pypdf")
        raise SystemExit(1)

    reader = PdfReader(str(pdf_path))
    pages: list[dict] = []

    for i, page in enumerate(reader.pages):
        text = page.extract_text() or ""
        pages.append({"page_num": i + 1, "text": text})

    return pages


def _extract_pdf_images(pdf_path: Path, output_dir: Path) -> int:
    """Extract images from a PDF (best-effort).

    Returns the number of images extracted.
    """
    try:
        from pypdf import PdfReader
    except ImportError:
        return 0

    images_dir = output_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    reader = PdfReader(str(pdf_path))
    count = 0

    for page_idx, page in enumerate(reader.pages):
        for img_idx, image in enumerate(page.images):
            try:
                fname = f"page{page_idx + 1}_img{img_idx + 1}_{image.name}"
                dest = images_dir / fname
                dest.write_bytes(image.data)
                count += 1
            except Exception as exc:
                logging.debug(f"Failed to extract image from page {page_idx + 1}: {exc}")

    if count:
        logging.info(f"Extracted {count} images from PDF")
    return count


# ---------------------------------------------------------------------------
# Section detection and splitting
# ---------------------------------------------------------------------------


def _split_text_into_sections(
    pages: list[dict],
    split_level: int,
    report: ConversionReport,
) -> list[dict]:
    """Split PDF text into sections based on detected headings.

    Returns:
        List of section dicts with keys: ``heading_text``, ``heading_id``,
        ``heading_level``, ``lines``.
    """
    sections: list[dict] = []
    current: dict | None = None

    for page_data in pages:
        for line in page_data["text"].splitlines():
            stripped = line.strip()
            if not stripped:
                if current is not None:
                    current["lines"].append("")
                continue

            report.total_paragraphs += 1

            if _is_likely_heading(stripped):
                level = _heading_level_from_text(stripped)
                if level <= split_level:
                    current = {
                        "heading_text": stripped,
                        "heading_id": _clean_heading_id(stripped),
                        "heading_level": level,
                        "lines": [],
                    }
                    sections.append(current)
                    report.sections_generated += 1
                    continue
                # Sub-heading (below split level): store as a tagged tuple so
                # _render_pdf_section can emit it exactly once without re-classifying.
                if current is None:
                    current = {
                        "heading_text": "Preamble",
                        "heading_id": "preamble",
                        "heading_level": 0,
                        "lines": [],
                    }
                    sections.append(current)
                current["lines"].append(("heading", stripped, level))
                continue

            if current is None:
                current = {
                    "heading_text": "Preamble",
                    "heading_id": "preamble",
                    "heading_level": 0,
                    "lines": [],
                }
                sections.append(current)

            current["lines"].append(stripped)

    return sections


def _render_pdf_section(section: dict, report: ConversionReport) -> str:
    """Render a PDF section to Bikeshed source text."""
    lines: list[str] = []
    heading = section["heading_text"]
    level = section["heading_level"]

    if level > 0:
        h_tag = "#" * level
        lines.append(f"{h_tag} {heading} {{#{section['heading_id']}}}")
        lines.append("")

    in_table = False
    table_lines: list[str] = []

    for line in section["lines"]:
        # Handle tagged sub-heading tuples inserted by _split_text_into_sections
        if isinstance(line, tuple) and line[0] == "heading":
            _, sub_text, sub_level = line
            if in_table:
                lines.append(_table_lines_to_html(table_lines))
                table_lines = []
                in_table = False
                report.total_tables += 1
            h_tag = "#" * sub_level
            h_id = _clean_heading_id(sub_text)
            lines.append(f"{h_tag} {sub_text} {{#{h_id}}}")
            lines.append("")
            continue

        if not line:
            if in_table:
                # End of table block
                lines.append(_table_lines_to_html(table_lines))
                table_lines = []
                in_table = False
                report.total_tables += 1
            lines.append("")
            continue

        # Detect table-like rows
        if _TABLE_ROW_RE.match(line):
            if not in_table:
                in_table = True
            table_lines.append(line)
            continue

        if in_table:
            # Non-table line while in table — close table
            lines.append(_table_lines_to_html(table_lines))
            table_lines = []
            in_table = False
            report.total_tables += 1

        lines.append(line)
        lines.append("")

    if in_table and table_lines:
        lines.append(_table_lines_to_html(table_lines))
        report.total_tables += 1

    return "\n".join(lines)


def _table_lines_to_html(table_lines: list[str]) -> str:
    """Convert whitespace-aligned text lines to an HTML table."""
    if not table_lines:
        return ""

    lines = ["<!-- MANUAL REVIEW: table detected heuristically from PDF -->", "<table>"]

    for i, row_text in enumerate(table_lines):
        cells = re.split(r"\s{2,}", row_text.strip())
        tag = "th" if i == 0 else "td"
        lines.append("  <tr>")
        for cell in cells:
            lines.append(f"    <{tag}>{cell}</{tag}>")
        lines.append("  </tr>")

    lines.append("</table>")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def convert_pdf(
    pdf_path: Path,
    output_dir: Path,
    *,
    split_level: int = 1,
    flavor: str = "",
) -> dict:
    """Convert a PDF to Bikeshed source files (lower fidelity).

    Args:
        pdf_path:    Path to the ``.pdf`` file.
        output_dir:  Directory to write generated ``.bs`` files.
        split_level: Split at Heading N level (default: 1).
        flavor:      Standards flavor hint.

    Returns:
        Dict with keys: ``bs_files``, ``manifest_path``, ``report``.
    """
    logging.info(f"Importing PDF: {pdf_path}")
    report = ConversionReport()

    # Extract text
    pages = _extract_pdf_text(pdf_path)
    logging.info(f"PDF has {len(pages)} pages")

    # Extract images (best-effort)
    output_dir.mkdir(parents=True, exist_ok=True)
    img_count = _extract_pdf_images(pdf_path, output_dir)
    report.images_extracted = img_count

    # Split into sections
    sections = _split_text_into_sections(pages, split_level, report)
    logging.info(f"Detected {len(sections)} sections")

    # Render sections
    bs_files: list[Path] = []
    manifest_entries: list[str] = []

    # Header
    header_lines = [
        "<pre class='metadata'>",
        f"Title: {pdf_path.stem}",
        "Status: WD",
        "Work Status: exploring",
        f"Shortname: {_clean_heading_id(pdf_path.stem)}",
        "Level: 1",
        "URL: https://example.com/spec",
        "Editor: TBD",
        "Abstract: This specification was imported from a PDF document. "
        "Manual review is strongly recommended.",
        "Markup Shorthands: markdown yes",
        "</pre>",
        "",
    ]
    header_path = output_dir / "header.bs"
    header_path.write_text("\n".join(header_lines), encoding="utf-8")
    bs_files.append(header_path)
    manifest_entries.append("header.bs")
    report.add_bs_file("header.bs")

    for idx, section in enumerate(sections):
        heading = section["heading_text"]
        filename = f"{idx:03d}_{_sanitize_filename(heading)}.bs"

        content = _render_pdf_section(section, report)

        file_path = output_dir / filename
        file_path.write_text(content, encoding="utf-8")
        bs_files.append(file_path)
        manifest_entries.append(filename)
        report.add_bs_file(filename)

    # Add review notice
    report.add_review_item(
        "PDF import is heuristic — all headings, tables, and structure should be manually verified."
    )

    # Manifest
    manifest_path = output_dir / "manifest.txt"
    manifest_path.write_text("\n".join(manifest_entries) + "\n", encoding="utf-8")

    # Report
    report_text = generate_report_text(report)
    logging.info("\n" + report_text)

    report_html_path = output_dir / "conversion_report.html"
    generate_report_html(report, report_html_path)

    return {
        "bs_files": [str(p) for p in bs_files],
        "manifest_path": str(manifest_path),
        "report": report,
    }
