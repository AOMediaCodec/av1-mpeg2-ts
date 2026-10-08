"""Spec completeness checker.

Scans the built HTML for incomplete content markers: TODO/FIXME/TBD text,
empty sections, unfilled editor notes, and leftover issue markers.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

from specbuild.utils import read_html

#: Patterns that flag incomplete content.
_INCOMPLETE_RE = re.compile(
    r"\b(TODO|FIXME|TBD|@@)\b|"
    r"\[EDITOR[:\s]|\[ISSUE\]|\[INSERT\]",
    re.IGNORECASE,
)

#: Heading tag names in document order.
_HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}


@dataclass
class CompletenessIssue:
    issue_type: str
    section_heading: str
    text_context: str
    severity: str = "warning"


def check_completeness(html_path: Path) -> list[CompletenessIssue]:
    """Run completeness check on a built HTML file."""
    soup = read_html(html_path)
    return check_completeness_soup(soup)


def check_completeness_soup(soup: object) -> list[CompletenessIssue]:
    """Scan *soup* for completeness issues and return a list of findings.

    Args:
        soup: A BeautifulSoup object of the built spec HTML.

    Returns:
        List of :class:`CompletenessIssue` items, sorted by severity then location.
    """
    issues: list[CompletenessIssue] = []

    def _nearest_heading(elem) -> str:
        """Walk parents to find the enclosing section heading."""
        for parent in elem.parents:
            heading = parent.find(list(_HEADING_TAGS))
            if heading:
                return heading.get_text(strip=True)[:120]
        return "(unknown section)"

    # --- Marker scan ---
    for text_node in soup.find_all(string=_INCOMPLETE_RE):
        parent = text_node.parent
        if parent and parent.name in ("script", "style", "code", "pre"):
            continue
        raw = text_node.strip()
        m = _INCOMPLETE_RE.search(raw)
        marker = m.group(0) if m else raw[:20]
        context = raw[:100].replace("\n", " ")
        issues.append(
            CompletenessIssue(
                issue_type=f"marker:{marker.upper()}",
                section_heading=_nearest_heading(text_node),
                text_context=context,
                severity="error" if marker.upper() in ("TODO", "FIXME") else "warning",
            )
        )

    # --- Editor's note divs ---
    for div in soup.find_all("div", class_=re.compile(r"\b(?:note|issue|advisement)\b", re.I)):
        text = div.get_text(" ", strip=True)
        if re.search(r"\b(editor|TODO|FIXME|TBD)\b", text, re.IGNORECASE):
            issues.append(
                CompletenessIssue(
                    issue_type="editor-note",
                    section_heading=_nearest_heading(div),
                    text_context=text[:120],
                    severity="warning",
                )
            )

    # --- Empty sections (heading with no body text before the next heading) ---
    for tag in _HEADING_TAGS:
        for heading in soup.find_all(tag):
            siblings = list(heading.next_siblings)
            text_content = ""
            for sib in siblings:
                sib_name = getattr(sib, "name", None)
                if sib_name in _HEADING_TAGS:
                    break
                sib_text = (
                    sib.get_text(strip=True) if hasattr(sib, "get_text") else str(sib).strip()
                )
                text_content += sib_text
            if not text_content:
                issues.append(
                    CompletenessIssue(
                        issue_type="empty-section",
                        section_heading=heading.get_text(strip=True)[:120],
                        text_context="(no body text before next heading)",
                        severity="info",
                    )
                )

    # Deduplicate (same type + heading)
    seen: set[tuple[str, str]] = set()
    unique: list[CompletenessIssue] = []
    for issue in issues:
        key = (issue.issue_type, issue.section_heading)
        if key not in seen:
            seen.add(key)
            unique.append(issue)

    severity_order = {"error": 0, "warning": 1, "info": 2}
    unique.sort(key=lambda i: severity_order.get(i.severity, 3))
    return unique


def report_completeness(
    issues: list[CompletenessIssue],
    strict: bool = False,
) -> None:
    """Log a summary of completeness issues.

    Args:
        issues: From :func:`check_completeness_soup`.
        strict: If True, raises ``SystemExit(1)`` when error-severity items exist.
    """
    if not issues:
        logging.info("Completeness check: no issues found.")
        return

    errors = [i for i in issues if i.severity == "error"]
    warnings = [i for i in issues if i.severity == "warning"]
    infos = [i for i in issues if i.severity == "info"]

    logging.warning(
        f"Completeness: {len(errors)} error(s), {len(warnings)} warning(s), "
        f"{len(infos)} info(s) — {len(issues)} total"
    )
    for issue in issues:
        level = logging.ERROR if issue.severity == "error" else logging.WARNING
        logging.log(
            level,
            f"  [{issue.severity.upper()}] {issue.issue_type} in "
            f"'{issue.section_heading}': {issue.text_context!r}",
        )

    if strict and errors:
        raise SystemExit(1)


def write_completeness_report(
    issues: list[CompletenessIssue],
    output_path: Path,
) -> None:
    """Write an HTML completeness report to *output_path*."""
    severity_color = {"error": "#dc3545", "warning": "#ffc107", "info": "#17a2b8"}
    rows = []
    for issue in issues:
        color = severity_color.get(issue.severity, "#6c757d")
        rows.append(
            f"<tr>"
            f'<td style="color:{color};font-weight:bold">{issue.severity.upper()}</td>'
            f"<td>{issue.issue_type}</td>"
            f"<td>{issue.section_heading}</td>"
            f"<td><code>{issue.text_context}</code></td>"
            f"</tr>"
        )

    table = "\n".join(rows) if rows else "<tr><td colspan='4'>No issues found.</td></tr>"
    html = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>Completeness Report</title>
<style>body{{font-family:sans-serif;margin:2rem}}
table{{border-collapse:collapse;width:100%}}
th,td{{border:1px solid #dee2e6;padding:.5rem .75rem;text-align:left}}
th{{background:#e9ecef}}</style></head>
<body>
<h1>Spec Completeness Report</h1>
<p>{len(issues)} issue(s) found.</p>
<table><thead><tr><th>Severity</th><th>Type</th><th>Section</th><th>Context</th></tr></thead>
<tbody>{table}</tbody></table>
</body></html>"""
    output_path.write_text(html, encoding="utf-8")
    logging.info(f"Completeness report: {output_path}")
