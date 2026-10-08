"""Conversion quality report for Word/PDF to Bikeshed imports.

Tracks statistics about extracted content (paragraphs, tables, equations,
figures, etc.) and flags items that need manual review.  Generates both
HTML and plain-text summaries.
"""

from __future__ import annotations

import html
import logging
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Report data
# ---------------------------------------------------------------------------


@dataclass
class ConversionReport:
    """Accumulated statistics and warnings from a DOCX/PDF import."""

    total_paragraphs: int = 0
    total_tables: int = 0
    total_figures: int = 0
    sdl_tables_detected: int = 0
    equations_extracted: int = 0
    terms_extracted: int = 0
    bibliography_entries: int = 0
    images_extracted: int = 0
    xrefs_resolved: int = 0
    xrefs_unresolved: int = 0
    sections_generated: int = 0
    manual_review_items: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    bs_files_generated: list[str] = field(default_factory=list)

    def add_warning(self, message: str) -> None:
        """Record a warning."""
        self.warnings.append(message)
        logging.warning(f"Import: {message}")

    def add_review_item(self, message: str) -> None:
        """Record an item that needs manual review."""
        self.manual_review_items.append(message)

    def add_bs_file(self, filename: str) -> None:
        """Record a generated .bs file."""
        self.bs_files_generated.append(filename)


# ---------------------------------------------------------------------------
# Text report
# ---------------------------------------------------------------------------


def generate_report_text(report: ConversionReport) -> str:
    """Generate a plain-text summary for console output.

    Args:
        report: The conversion report data.

    Returns:
        Multi-line text summary.
    """
    lines: list[str] = [
        "=" * 60,
        "  DOCX/PDF to Bikeshed Conversion Report",
        "=" * 60,
        "",
        f"  Paragraphs processed:   {report.total_paragraphs}",
        f"  Tables found:           {report.total_tables}",
        f"  SDL tables detected:    {report.sdl_tables_detected}",
        f"  Equations extracted:    {report.equations_extracted}",
        f"  Figures found:          {report.total_figures}",
        f"  Images extracted:       {report.images_extracted}",
        f"  Terms extracted:        {report.terms_extracted}",
        f"  Bibliography entries:   {report.bibliography_entries}",
        f"  Cross-refs resolved:    {report.xrefs_resolved}",
        f"  Cross-refs unresolved:  {report.xrefs_unresolved}",
        f"  Sections generated:     {report.sections_generated}",
        f"  .bs files generated:    {len(report.bs_files_generated)}",
        "",
    ]

    if report.bs_files_generated:
        lines.append("  Generated files:")
        for f in report.bs_files_generated:
            lines.append(f"    - {f}")
        lines.append("")

    if report.warnings:
        lines.append(f"  Warnings ({len(report.warnings)}):")
        for w in report.warnings:
            lines.append(f"    ! {w}")
        lines.append("")

    if report.manual_review_items:
        lines.append(f"  Items needing manual review ({len(report.manual_review_items)}):")
        for item in report.manual_review_items:
            lines.append(f"    * {item}")
        lines.append("")

    lines.append("=" * 60)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# HTML report
# ---------------------------------------------------------------------------


def generate_report_html(report: ConversionReport, output_path: Path) -> Path:
    """Generate an HTML conversion report.

    Args:
        report:      The conversion report data.
        output_path: Where to write the HTML file.

    Returns:
        The path to the written HTML file.
    """
    h = html.escape

    rows = [
        ("Paragraphs processed", report.total_paragraphs),
        ("Tables found", report.total_tables),
        ("SDL tables detected", report.sdl_tables_detected),
        ("Equations extracted", report.equations_extracted),
        ("Figures found", report.total_figures),
        ("Images extracted", report.images_extracted),
        ("Terms extracted", report.terms_extracted),
        ("Bibliography entries", report.bibliography_entries),
        ("Cross-refs resolved", report.xrefs_resolved),
        ("Cross-refs unresolved", report.xrefs_unresolved),
        ("Sections generated", report.sections_generated),
        (".bs files generated", len(report.bs_files_generated)),
    ]

    table_rows = "\n".join(f"<tr><td>{h(label)}</td><td>{value}</td></tr>" for label, value in rows)

    files_list = ""
    if report.bs_files_generated:
        items = "\n".join(f"<li><code>{h(f)}</code></li>" for f in report.bs_files_generated)
        files_list = f"<h2>Generated Files</h2>\n<ul>{items}</ul>"

    warnings_section = ""
    if report.warnings:
        items = "\n".join(f"<li>{h(w)}</li>" for w in report.warnings)
        warnings_section = (
            f'<h2>Warnings ({len(report.warnings)})</h2>\n<ul class="warnings">{items}</ul>'
        )

    review_section = ""
    if report.manual_review_items:
        items = "\n".join(f"<li>{h(item)}</li>" for item in report.manual_review_items)
        review_section = (
            f"<h2>Manual Review Items ({len(report.manual_review_items)})</h2>\n"
            f'<ul class="review">{items}</ul>'
        )

    content = f"""\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>DOCX/PDF to Bikeshed Conversion Report</title>
<style>
body {{ font-family: system-ui, sans-serif; max-width: 800px; margin: 2em auto; padding: 0 1em; }}
h1 {{ border-bottom: 2px solid #333; padding-bottom: 0.3em; }}
table {{ border-collapse: collapse; width: 100%; margin: 1em 0; }}
th, td {{ border: 1px solid #ccc; padding: 0.5em 1em; text-align: left; }}
th {{ background: #f5f5f5; }}
td:last-child {{ text-align: right; font-weight: bold; }}
.warnings li {{ color: #b45309; }}
.review li {{ color: #dc2626; }}
code {{ background: #f0f0f0; padding: 0.1em 0.3em; border-radius: 3px; }}
</style>
</head>
<body>
<h1>Conversion Report</h1>
<h2>Statistics</h2>
<table>
<tr><th>Metric</th><th>Count</th></tr>
{table_rows}
</table>
{files_list}
{warnings_section}
{review_section}
</body>
</html>"""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")
    logging.info(f"Conversion report written to {output_path}")
    return output_path
