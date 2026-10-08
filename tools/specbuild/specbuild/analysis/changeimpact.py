"""Change impact analysis for spec builds.

Compares two HTML builds of a spec and classifies which sections changed,
labelling each as normative, definition, conformance, or informative.
"""

from __future__ import annotations

import difflib
import html
import json
import logging
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from specbuild.utils import read_html

#: Keywords that identify normative content.
_NORMATIVE_RE = re.compile(
    r"\b(shall|shall not|must|must not|required to|is required)\b", re.IGNORECASE
)

#: Patterns that identify conformance sections.
_CONFORMANCE_RE = re.compile(r"\bconformance\b", re.IGNORECASE)


@dataclass
class ImpactItem:
    section_id: str
    heading: str
    impact_class: str
    added_lines: int
    removed_lines: int
    change_summary: str = ""


def _extract_sections(soup) -> dict[str, dict]:
    """Extract text content of each named section from *soup*.

    Returns a mapping from section id to ``{"heading": str, "text": str, "html": str}``.
    """
    sections: dict[str, dict] = {}

    for elem in soup.find_all(id=True):
        tag = getattr(elem, "name", "")
        if tag not in ("section", "div", "h1", "h2", "h3", "h4", "h5", "h6"):
            continue
        sec_id = elem.get("id", "")
        if not sec_id:
            continue

        # Find heading text
        heading_el = elem.find(re.compile(r"^h[1-6]$"))
        heading = heading_el.get_text(strip=True)[:120] if heading_el else sec_id

        text = elem.get_text(" ", strip=True)
        sections[sec_id] = {
            "heading": heading,
            "text": text,
            "html": str(elem),
        }

    return sections


def _classify_section(text: str, section_id: str) -> str:
    """Return an impact class for a section based on its content."""
    if _CONFORMANCE_RE.search(section_id) or _CONFORMANCE_RE.search(text[:200]):
        return "conformance"
    if _NORMATIVE_RE.search(text):
        return "normative"
    return "informative"


def compare_html(
    old_html: Path,
    new_html: Path,
    *,
    new_soup: object = None,
) -> list[ImpactItem]:
    """Compare two HTML builds and return per-section impact items.

    Args:
        old_html: Path to the baseline HTML file.
        new_html: Path to the current HTML file.
        new_soup: Pre-parsed soup for *new_html* (avoids re-parsing).

    Returns:
        List of :class:`ImpactItem` for sections that changed.
    """
    old_soup = read_html(old_html)
    actual_new_soup = new_soup if new_soup is not None else read_html(new_html)

    old_sections = _extract_sections(old_soup)
    new_sections = _extract_sections(actual_new_soup)

    all_ids = set(old_sections) | set(new_sections)
    items: list[ImpactItem] = []

    for sec_id in sorted(all_ids):
        old_text = old_sections.get(sec_id, {}).get("text", "")
        new_text = new_sections.get(sec_id, {}).get("text", "")

        if old_text == new_text:
            continue

        old_lines = old_text.splitlines()
        new_lines = new_text.splitlines()
        diff = list(difflib.unified_diff(old_lines, new_lines, lineterm=""))
        added = sum(1 for ln in diff if ln.startswith("+") and not ln.startswith("+++"))
        removed = sum(1 for ln in diff if ln.startswith("-") and not ln.startswith("---"))

        heading = new_sections.get(sec_id, old_sections.get(sec_id, {})).get("heading", sec_id)
        impact_class = _classify_section(new_text or old_text, sec_id)

        status = "added" if not old_text else "removed" if not new_text else "changed"
        summary = f"{status}: +{added}/-{removed} lines"
        if status == "added":
            summary = f"new section (+{added} lines)"
        elif status == "removed":
            summary = f"section removed (-{removed} lines)"

        items.append(
            ImpactItem(
                section_id=sec_id,
                heading=heading,
                impact_class=impact_class,
                added_lines=added,
                removed_lines=removed,
                change_summary=summary,
            )
        )

    logging.info(
        f"Impact analysis: {len(items)} changed section(s) "
        f"({sum(1 for i in items if i.impact_class == 'normative')} normative, "
        f"{sum(1 for i in items if i.impact_class == 'conformance')} conformance)"
    )
    return items


def find_base_html(current_html: Path, base_path: str | None) -> Path | None:
    """Locate the baseline HTML to compare against.

    Checks (in order): explicit *base_path*, ``baseline/index.html``, the
    second-newest output directory sibling.
    """
    if base_path:
        p = Path(base_path)
        return p if p.exists() else None

    # Check saved baseline
    baseline = current_html.parent.parent / "baseline" / current_html.name
    if baseline.exists():
        return baseline

    # Scan sibling output dirs (named YYYYMMDD_sha_SpecName_...)
    parent = current_html.parent.parent
    candidates = sorted(
        [
            d / current_html.name
            for d in parent.iterdir()
            if d.is_dir() and d != current_html.parent and (d / current_html.name).exists()
        ],
        reverse=True,
    )
    return candidates[0] if candidates else None


def write_impact_report(items: list[ImpactItem], output_path: Path) -> None:
    """Write an HTML impact report to *output_path*."""
    class_color = {
        "normative": "#dc3545",
        "conformance": "#fd7e14",
        "definition": "#6f42c1",
        "informative": "#0d6efd",
    }

    rows = []
    for item in sorted(items, key=lambda i: (i.impact_class, i.section_id)):
        color = class_color.get(item.impact_class, "#6c757d")
        sec_id = html.escape(str(item.section_id))
        heading = html.escape(str(item.heading))
        impact = html.escape(str(item.impact_class))
        summary = html.escape(str(item.change_summary))
        rows.append(
            f"<tr>"
            f'<td><a href="#{sec_id}">{sec_id}</a></td>'
            f"<td>{heading}</td>"
            f'<td style="color:{color};font-weight:bold">{impact}</td>'
            f"<td>+{item.added_lines} / -{item.removed_lines}</td>"
            f"<td>{summary}</td>"
            f"</tr>"
        )

    table = "\n".join(rows) if rows else "<tr><td colspan='5'>No changes detected.</td></tr>"

    counts = {}
    for item in items:
        counts[item.impact_class] = counts.get(item.impact_class, 0) + 1
    summary = ", ".join(f"{v} {k}" for k, v in sorted(counts.items()))

    html_doc = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>Change Impact Report</title>
<style>body{{font-family:sans-serif;margin:2rem}}
table{{border-collapse:collapse;width:100%}}
th,td{{border:1px solid #dee2e6;padding:.5rem .75rem;text-align:left}}
th{{background:#e9ecef}}</style></head>
<body>
<h1>Change Impact Report</h1>
<p>{len(items)} section(s) changed: {summary}</p>
<table><thead><tr>
<th>Section ID</th><th>Heading</th><th>Impact Class</th>
<th>Lines +/-</th><th>Summary</th>
</tr></thead>
<tbody>{table}</tbody></table>
</body></html>"""
    output_path.write_text(html_doc, encoding="utf-8")
    logging.info(f"Impact report: {output_path}")


def write_impact_json(items: list[ImpactItem], output_path: Path) -> None:
    """Write impact data as JSON for downstream tooling."""
    data = [asdict(item) for item in items]
    output_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
