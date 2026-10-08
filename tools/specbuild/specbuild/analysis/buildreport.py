"""Build report generation: HTML and JSON summaries of the build.

Collects data from all build phases — compilation, enhancements, quality
checks, timing — and produces a structured report suitable for review,
archiving, or CI integration.

The report includes:

- Build metadata (branch, SHA, date, flags)
- Section statistics (count, word counts per section)
- Quality check results (broken refs, broken images, SDL issues, terminology)
- Enhancement summary (which passes ran and what they did)
- Timing breakdown (when ``--timing`` is active)
- Warning/error log summary
"""

from __future__ import annotations

import html as _html
import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from specbuild.theme import THEME

# ---------------------------------------------------------------------------
# Report data model
# ---------------------------------------------------------------------------


@dataclass
class BuildReportData:
    """Accumulates data from all build phases for the final report.

    Modules append their results via the ``add_*`` methods.  The report
    generator reads the accumulated data to produce HTML or JSON output.
    """

    # Build identity
    branch: str = ""
    sha: str = ""
    date: str = ""
    spec_title: str = ""

    # Timing
    start_time: float = field(default_factory=time.monotonic)
    steps: list[dict] = field(default_factory=list)

    # Section statistics (populated by analyze_sections)
    sections: list[dict] = field(default_factory=list)
    total_words: int = 0

    # Quality check results
    broken_refs: list[dict] = field(default_factory=list)
    broken_images: list[dict] = field(default_factory=list)
    sdl_issues: list[dict] = field(default_factory=list)
    terminology_issues: list[dict] = field(default_factory=list)
    orphan_refs: dict = field(default_factory=dict)
    accessibility_issues: list[dict] = field(default_factory=list)
    dfn_issues: dict = field(default_factory=dict)
    link_check_issues: list[dict] = field(default_factory=list)
    table_issues: list[dict] = field(default_factory=list)
    spelling_issues: list[dict] = field(default_factory=list)
    sdl_syntax_errors: int = 0  # total syntax errors from --check-sdl-syntax

    # RFC 2119, duplicate, and requirements data
    rfc2119_issues: list[dict] = field(default_factory=list)
    duplicate_issues: list[dict] = field(default_factory=list)
    requirement_count: int = 0

    # Enhancement summary
    enhancements_run: list[str] = field(default_factory=list)

    # Log messages captured during the build
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    # CLI flags snapshot
    cli_flags: dict[str, Any] = field(default_factory=dict)

    def add_step(self, name: str, elapsed: float) -> None:
        """Record a timed build step."""
        self.steps.append({"name": name, "elapsed_s": round(elapsed, 3)})

    def add_enhancement(self, name: str) -> None:
        """Record that an enhancement pass was executed."""
        self.enhancements_run.append(name)

    def add_warning(self, message: str) -> None:
        """Record a warning message."""
        self.warnings.append(message)

    def add_error(self, message: str) -> None:
        """Record an error message."""
        self.errors.append(message)

    @property
    def total_elapsed(self) -> float:
        """Total wall-clock time since the report was created."""
        return round(time.monotonic() - self.start_time, 3)


# ---------------------------------------------------------------------------
# Section analysis
# ---------------------------------------------------------------------------

_HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
_SECNUM_RE = re.compile(r"^([\d]+(?:\.[\d]+)*)")


def analyze_sections_soup(soup: Any) -> tuple[list[dict], int]:
    """Extract section statistics from the parsed HTML.

    Walks h2–h6 headings and counts words in the prose content between
    each heading pair.

    Args:
        soup: BeautifulSoup document.

    Returns:
        Tuple of (section_list, total_word_count).  Each section dict
        contains ``id``, ``number``, ``title``, ``level``, ``word_count``.
    """
    heading_tags = {"h2", "h3", "h4", "h5", "h6"}
    headings = soup.find_all(heading_tags)

    sections: list[dict] = []
    total_words = 0

    for i, heading in enumerate(headings):
        heading_id = heading.get("id", "")
        title = heading.get_text(strip=True)
        level = int(heading.name[1])

        match = _SECNUM_RE.match(title)
        number = match.group(1) if match else ""

        # Count words between this heading and the next one
        words = _count_words_until_next_heading(
            heading, headings[i + 1] if i + 1 < len(headings) else None
        )
        total_words += words

        sections.append(
            {
                "id": heading_id,
                "number": number,
                "title": title,
                "level": level,
                "word_count": words,
            }
        )

    return sections, total_words


def _count_words_until_next_heading(heading: Any, next_heading: Any) -> int:
    """Count words in elements between two headings.

    Walks siblings after *heading* until *next_heading* (or end of parent),
    collecting text from leaf prose elements only to avoid double-counting.
    """
    _HEADING_TAGS_SET = {"h1", "h2", "h3", "h4", "h5", "h6"}
    _PROSE_TAGS = {"p", "li", "dd", "dt", "td", "th", "figcaption"}

    word_count = 0
    for elem in heading.find_all_next():
        if next_heading is not None and elem is next_heading:
            break
        if elem.name in _HEADING_TAGS_SET:
            break
        # Only count leaf prose elements (no nested prose children)
        if elem.name in _PROSE_TAGS and not elem.find(_PROSE_TAGS):
            text = elem.get_text(strip=True)
            if text:
                word_count += len(text.split())

    return word_count


# ---------------------------------------------------------------------------
# Report logging handler
# ---------------------------------------------------------------------------


class ReportLogHandler(logging.Handler):
    """Logging handler that captures warnings and errors into a report."""

    def __init__(self, report: BuildReportData):
        super().__init__(level=logging.WARNING)
        self._report = report

    def emit(self, record: logging.LogRecord) -> None:
        msg = self.format(record)
        if record.levelno >= logging.ERROR:
            self._report.add_error(msg)
        elif record.levelno >= logging.WARNING:
            self._report.add_warning(msg)


# ---------------------------------------------------------------------------
# JSON output
# ---------------------------------------------------------------------------


def generate_json_report(report: BuildReportData) -> dict:
    """Convert a BuildReportData into a JSON-serializable dict.

    Args:
        report: The accumulated build report data.

    Returns:
        A dict ready for ``json.dumps()``.
    """
    return {
        "build": {
            "branch": report.branch,
            "sha": report.sha,
            "date": report.date,
            "spec_title": report.spec_title,
            "total_elapsed_s": report.total_elapsed,
        },
        "sections": {
            "total": len(report.sections),
            "total_words": report.total_words,
            "details": report.sections,
        },
        "quality": {
            "broken_refs": report.broken_refs,
            "broken_images": report.broken_images,
            "sdl_issues": report.sdl_issues,
            "sdl_syntax_errors": report.sdl_syntax_errors,
            "terminology_issues": report.terminology_issues,
            "orphan_refs": report.orphan_refs,
            "accessibility_issues": report.accessibility_issues,
            "dfn_issues": report.dfn_issues,
            "link_check_issues": report.link_check_issues,
            "table_issues": report.table_issues,
            "spelling_issues": report.spelling_issues,
            "rfc2119_issues": report.rfc2119_issues,
            "duplicate_issues": report.duplicate_issues,
            "requirement_count": report.requirement_count,
        },
        "enhancements": report.enhancements_run,
        "timing": report.steps,
        "messages": {
            "warnings": report.warnings,
            "errors": report.errors,
        },
        "cli_flags": report.cli_flags,
    }


def write_json_report(report: BuildReportData, output_path: Path) -> None:
    """Write the build report as a JSON file.

    Args:
        report: The accumulated build report data.
        output_path: Destination file path.
    """
    data = generate_json_report(report)
    output_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    logging.info(f"Build report (JSON) written to {output_path}")


# ---------------------------------------------------------------------------
# HTML output
# ---------------------------------------------------------------------------


def write_html_report(report: BuildReportData, output_path: Path) -> None:
    """Write the build report as a standalone HTML file.

    Args:
        report: The accumulated build report data.
        output_path: Destination file path.
    """
    html = _render_html_report(report)
    output_path.write_text(html, encoding="utf-8")
    logging.info(f"Build report (HTML) written to {output_path}")


def _render_html_report(report: BuildReportData) -> str:
    """Render the build report as a complete HTML page."""
    t = THEME

    # Summary counts
    n_warnings = len(report.warnings)
    n_errors = len(report.errors)
    n_broken_refs = len(report.broken_refs)
    n_broken_images = len(report.broken_images)
    n_sdl_issues = len(report.sdl_issues)
    n_sdl_syntax_errors = report.sdl_syntax_errors
    n_rfc2119_issues = len(report.rfc2119_issues)
    n_duplicate_issues = len(report.duplicate_issues)

    # Status badge
    if n_errors > 0:
        status_class = "status-error"
        status_text = "ERRORS"
    elif n_warnings > 0 or n_broken_refs > 0 or n_broken_images > 0 or n_sdl_syntax_errors > 0:
        status_class = "status-warning"
        status_text = "WARNINGS"
    else:
        status_class = "status-ok"
        status_text = "CLEAN"

    # Timing rows
    timing_rows = ""
    total_step_time = sum(s["elapsed_s"] for s in report.steps)
    for step in report.steps:
        pct = (step["elapsed_s"] / total_step_time * 100) if total_step_time > 0 else 0
        bar_width = max(1, int(pct * 2))
        timing_rows += (
            f"<tr><td>{_esc(step['name'])}</td>"
            f'<td class="num">{step["elapsed_s"]:.2f}s</td>'
            f'<td class="num">{pct:.1f}%</td>'
            f'<td><div class="bar" style="width:{bar_width}px"></div></td></tr>\n'
        )

    # Section rows (top-level only for summary, full for details)
    section_summary_rows = ""
    for sec in report.sections:
        if sec["level"] <= 3:
            indent = "  " * max(0, sec["level"] - 2)
            section_summary_rows += (
                f"<tr><td>{indent}{_esc(sec['title'])}</td>"
                f'<td class="num">{sec["word_count"]:,}</td></tr>\n'
            )

    # Quality issue rows
    ref_rows = ""
    for ref in report.broken_refs[:50]:
        ref_rows += (
            f"<tr><td><code>{_esc(ref.get('href', ''))}</code></td>"
            f"<td>{_esc(ref.get('text', ''))}</td>"
            f"<td>{_esc(ref.get('context', ''))}</td></tr>\n"
        )

    image_rows = ""
    for img in report.broken_images[:50]:
        image_rows += (
            f"<tr><td><code>{_esc(img.get('src', ''))}</code></td>"
            f"<td>&lt;{_esc(img.get('tag', ''))}&gt;</td>"
            f"<td>{_esc(img.get('context', ''))}</td></tr>\n"
        )

    sdl_rows = ""
    for issue in report.sdl_issues[:50]:
        sdl_rows += (
            f"<tr><td><code>{_esc(issue.get('name', ''))}</code></td>"
            f"<td><code>{_esc(issue.get('table', ''))}</code></td>"
            f"<td>{_esc(issue.get('context', ''))}</td></tr>\n"
        )

    rfc2119_rows = ""
    for issue in report.rfc2119_issues[:50]:
        rfc2119_rows += (
            f"<tr><td>{_esc(issue.get('type', ''))}</td>"
            f"<td><code>{_esc(issue.get('keyword', ''))}</code></td>"
            f"<td>{_esc(issue.get('context', ''))}</td>"
            f"<td>{_esc(issue.get('detail', ''))}</td></tr>\n"
        )

    duplicate_rows = ""
    for issue in report.duplicate_issues[:50]:
        duplicate_rows += (
            f"<tr><td><code>{_esc(issue.get('hash', ''))}</code></td>"
            f"<td>{_esc(issue.get('context', ''))}</td></tr>\n"
        )

    # Enhancement list
    enh_list = ""
    for enh in report.enhancements_run:
        enh_list += f"<li>{_esc(enh)}</li>\n"

    # Warning/error list
    msg_rows = ""
    for err in report.errors:
        msg_rows += f'<tr class="msg-error"><td>ERROR</td><td>{_esc(err)}</td></tr>\n'
    for warn in report.warnings[:100]:
        msg_rows += f'<tr class="msg-warning"><td>WARNING</td><td>{_esc(warn)}</td></tr>\n'

    # CLI flags
    flags_rows = ""
    for key, value in sorted(report.cli_flags.items()):
        if value not in (None, False, "INFO"):
            flags_rows += (
                f"<tr><td><code>--{_esc(key)}</code></td><td>{_esc(str(value))}</td></tr>\n"
            )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Build Report — {_esc(report.spec_title or "Specification")}</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{
    font-family: {t.font_sans};
    line-height: 1.6;
    color: #1a1a1a;
    max-width: 1100px;
    margin: 0 auto;
    padding: 2em;
    background: #fafafa;
}}
h1 {{ font-size: 1.6em; margin-bottom: 0.3em; }}
h2 {{
    font-size: 1.15em;
    margin: 1.5em 0 0.5em;
    padding-bottom: 0.3em;
    border-bottom: 2px solid {t.color_border};
}}
.header {{
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    margin-bottom: 1.5em;
    padding-bottom: 1em;
    border-bottom: 3px solid #2d3748;
}}
.header-left {{ flex: 1; }}
.meta {{ color: {t.color_muted}; font-size: 0.9em; }}
.meta code {{ background: #eee; padding: 2px 6px; border-radius: 3px; }}
.status {{
    display: inline-block;
    padding: 6px 16px;
    border-radius: 4px;
    font-weight: 600;
    font-size: 0.85em;
    letter-spacing: 0.5px;
}}
.status-ok {{ background: #c6f6d5; color: #276749; }}
.status-warning {{ background: #fefcbf; color: #975a16; }}
.status-error {{ background: #fed7d7; color: #9b2c2c; }}

/* Summary cards */
.cards {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
    gap: 12px;
    margin: 1em 0;
}}
.card {{
    background: white;
    border: 1px solid {t.color_border_light};
    border-radius: 6px;
    padding: 12px 16px;
    text-align: center;
}}
.card .value {{
    font-size: 1.8em;
    font-weight: 700;
    color: #2d3748;
}}
.card .label {{
    font-size: 0.8em;
    color: {t.color_muted};
    text-transform: uppercase;
    letter-spacing: 0.5px;
}}
.card.warn .value {{ color: #975a16; }}
.card.error .value {{ color: #9b2c2c; }}

/* Tables */
table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 0.88em;
    margin: 0.5em 0 1em;
    background: white;
}}
th, td {{
    padding: 6px 10px;
    border: 1px solid {t.color_border_light};
    text-align: left;
}}
th {{
    background: {t.color_bg_muted};
    font-weight: 600;
    font-size: 0.85em;
    text-transform: uppercase;
    letter-spacing: 0.3px;
}}
td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
tr:nth-child(even) td {{ background: {t.color_bg_subtle}; }}

/* Timing bar */
.bar {{
    height: 14px;
    background: #4299e1;
    border-radius: 2px;
    min-width: 2px;
}}

/* Messages */
.msg-error td:first-child {{ color: #9b2c2c; font-weight: 600; }}
.msg-warning td:first-child {{ color: #975a16; font-weight: 600; }}

/* Collapsible sections */
details {{ margin: 0.5em 0; }}
details summary {{
    cursor: pointer;
    font-weight: 600;
    padding: 4px 0;
    color: #2d3748;
}}
details summary:hover {{ color: {t.color_accent}; }}

.empty {{ color: {t.color_muted}; font-style: italic; padding: 1em; }}
code {{ font-family: {t.font_mono}; font-size: 0.9em; }}
</style>
</head>
<body>

<div class="header">
    <div class="header-left">
        <h1>Build Report</h1>
        <div class="meta">
            {_esc(report.spec_title) + " &mdash; " if report.spec_title else ""}
            <code>{_esc(report.branch)}@{_esc(report.sha[:8] if report.sha else "?")}</code>
            &middot; {_esc(report.date)}
            &middot; {report.total_elapsed:.1f}s total
        </div>
    </div>
    <span class="status {status_class}">{status_text}</span>
</div>

<!-- Summary cards -->
<div class="cards">
    <div class="card"><div class="value">{len(report.sections)}</div><div class="label">Sections</div></div>
    <div class="card"><div class="value">{report.total_words:,}</div><div class="label">Words</div></div>
    <div class="card"><div class="value">{len(report.enhancements_run)}</div><div class="label">Enhancements</div></div>
    <div class="card{" warn" if n_broken_refs else ""}"><div class="value">{n_broken_refs}</div><div class="label">Broken Refs</div></div>
    <div class="card{" warn" if n_broken_images else ""}"><div class="value">{n_broken_images}</div><div class="label">Broken Images</div></div>
    <div class="card{" warn" if n_sdl_issues else ""}"><div class="value">{n_sdl_issues}</div><div class="label">SDL Ref Issues</div></div>
    <div class="card{" warn" if n_sdl_syntax_errors else ""}"><div class="value">{n_sdl_syntax_errors}</div><div class="label">SDL Syntax Errors</div></div>
    <div class="card{" warn" if n_rfc2119_issues else ""}"><div class="value">{n_rfc2119_issues}</div><div class="label">RFC 2119 Issues</div></div>
    <div class="card{" warn" if n_duplicate_issues else ""}"><div class="value">{n_duplicate_issues}</div><div class="label">Duplicates</div></div>
    <div class="card"><div class="value">{report.requirement_count}</div><div class="label">Requirements</div></div>
    <div class="card{" warn" if n_warnings else ""}"><div class="value">{n_warnings}</div><div class="label">Warnings</div></div>
    <div class="card{" error" if n_errors else ""}"><div class="value">{n_errors}</div><div class="label">Errors</div></div>
</div>

<!-- Timing -->
{"<h2>Timing</h2>" + _timing_table(timing_rows) if report.steps else ""}

<!-- Sections -->
<h2>Section Statistics</h2>
{_sections_table(section_summary_rows) if section_summary_rows else '<p class="empty">No section data collected.</p>'}

<!-- Quality checks -->
<h2>Quality Checks</h2>
{_quality_section("Broken Cross-References", "href", "Link Text", "Near Section", ref_rows, n_broken_refs)}
{_quality_section("Broken Images", "Source", "Tag", "Near Section", image_rows, n_broken_images)}
{_quality_section("SDL Reference Issues", "Unresolved Function", "Referenced In", "Section", sdl_rows, n_sdl_issues)}
{_sdl_syntax_section(n_sdl_syntax_errors)}
{_terminology_section(report.terminology_issues)}
{_rfc2119_section(rfc2119_rows, n_rfc2119_issues)}
{_duplicate_section(duplicate_rows, n_duplicate_issues)}
{_requirements_summary_section(report.requirement_count, report.rfc2119_issues)}

<!-- Enhancements -->
<h2>Enhancements</h2>
{("<ul>" + enh_list + "</ul>") if enh_list else '<p class="empty">No enhancements were run.</p>'}

<!-- Messages -->
{"<h2>Messages (" + str(n_errors + n_warnings) + ")</h2>" + '<table><thead><tr><th style="width:80px">Level</th><th>Message</th></tr></thead><tbody>' + msg_rows + "</tbody></table>" if msg_rows else ""}

<!-- CLI Flags -->
<details>
<summary>CLI Flags</summary>
{("<table><thead><tr><th>Flag</th><th>Value</th></tr></thead><tbody>" + flags_rows + "</tbody></table>") if flags_rows else '<p class="empty">No flags recorded.</p>'}
</details>

</body>
</html>"""


def _esc(text: str) -> str:
    """HTML-escape a string."""
    return _html.escape(text, quote=True)


def _timing_table(rows: str) -> str:
    if not rows:
        return ""
    return (
        "<table><thead><tr><th>Step</th><th>Duration</th>"
        "<th>%</th><th>Bar</th></tr></thead><tbody>" + rows + "</tbody></table>"
    )


def _sections_table(rows: str) -> str:
    return (
        "<table><thead><tr><th>Section</th>"
        '<th style="width:100px">Words</th></tr></thead><tbody>' + rows + "</tbody></table>"
    )


def _sdl_syntax_section(error_count: int) -> str:
    """Render the SDL syntax check summary for the build report."""
    if error_count == 0:
        return '<p><strong>SDL Syntax:</strong> <span style="color:#276749">All blocks valid</span></p>'
    if error_count < 0:
        # -1 means the check was skipped (Node/npm not available)
        return '<p><strong>SDL Syntax:</strong> <span style="color:#888">Check skipped (Node.js or @mpeggroup/mpeg-sdl-parser not installed)</span></p>'
    return (
        f'<p><strong>SDL Syntax:</strong> <span style="color:#c0392b">'
        f"{error_count} error(s) found — run with <code>--check-sdl-syntax</code> "
        f"and check the build log for details.</span></p>"
    )


def _quality_section(title: str, col1: str, col2: str, col3: str, rows: str, count: int) -> str:
    if count == 0:
        return (
            f'<p><strong>{_esc(title)}:</strong> <span style="color:#276749">None found</span></p>'
        )
    return (
        f"<details open><summary>{_esc(title)} ({count})</summary>"
        f"<table><thead><tr><th>{_esc(col1)}</th><th>{_esc(col2)}</th>"
        f"<th>{_esc(col3)}</th></tr></thead><tbody>" + rows + "</tbody></table></details>"
    )


def _terminology_section(issues: list[dict]) -> str:
    if not issues:
        return '<p><strong>Terminology Issues:</strong> <span style="color:#276749">None found</span></p>'
    rows = ""
    for issue in issues[:50]:
        rows += (
            f"<tr><td>{_esc(issue.get('canonical', ''))}</td>"
            f"<td>{_esc(issue.get('variant', ''))}</td>"
            f'<td class="num">{issue.get("canonical_count", 0)}</td>'
            f'<td class="num">{issue.get("variant_count", 0)}</td></tr>\n'
        )
    return (
        f"<details open><summary>Terminology Issues ({len(issues)})</summary>"
        "<table><thead><tr><th>Canonical</th><th>Variant</th>"
        "<th>Canonical Count</th><th>Variant Count</th></tr></thead><tbody>"
        + rows
        + "</tbody></table></details>"
    )


def _rfc2119_section(rows: str, count: int) -> str:
    """Render the RFC 2119 consistency section."""
    if count == 0:
        return '<p><strong>RFC 2119 Consistency:</strong> <span style="color:#276749">No issues found</span></p>'
    return (
        f"<details open><summary>RFC 2119 Consistency Issues ({count})</summary>"
        "<table><thead><tr>"
        "<th>Type</th><th>Keyword</th><th>Context</th><th>Detail</th>"
        "</tr></thead><tbody>" + rows + "</tbody></table></details>"
    )


def _duplicate_section(rows: str, count: int) -> str:
    """Render the duplicate content section."""
    if count == 0:
        return '<p><strong>Duplicate Content:</strong> <span style="color:#276749">None found</span></p>'
    return (
        f"<details open><summary>Duplicate Paragraphs ({count})</summary>"
        "<table><thead><tr>"
        "<th>Hash</th><th>Context</th>"
        "</tr></thead><tbody>" + rows + "</tbody></table></details>"
    )


def _requirements_summary_section(total: int, rfc2119_issues: list[dict]) -> str:
    """Render the requirements summary section."""
    if total == 0:
        return '<p><strong>Requirements:</strong> <span style="color:#666">No requirements found</span></p>'

    # Count by keyword type from rfc2119_issues if available
    keyword_counts: dict[str, int] = {}
    for issue in rfc2119_issues:
        kw = issue.get("keyword", "").upper()
        if kw:
            keyword_counts[kw] = keyword_counts.get(kw, 0) + 1

    breakdown = ""
    if keyword_counts:
        for kw, cnt in sorted(keyword_counts.items()):
            breakdown += f"<tr><td>{_esc(kw)}</td><td class='num'>{cnt}</td></tr>\n"
        breakdown_table = (
            "<table><thead><tr><th>Keyword</th><th>Count</th></tr></thead><tbody>"
            + breakdown
            + "</tbody></table>"
        )
    else:
        breakdown_table = ""

    return (
        f"<details><summary>Requirements Summary ({total} total)</summary>"
        f"<p>Total requirements tracked: <strong>{total}</strong></p>"
        + breakdown_table
        + "</details>"
    )
