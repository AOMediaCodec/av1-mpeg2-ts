"""Requirement ID numbering for conformance traceability.

Scans the compiled HTML for RFC 2119 normative statements and assigns
stable requirement IDs in the format ``REQ-<section>-<keyword>-<n>``.
Outputs a structured requirements list as JSON and an HTML report for
test suite developers.
"""

from __future__ import annotations

import html as _html
import logging
import re
from collections import Counter
from pathlib import Path

from specbuild.analysis.compliance import KEYWORD_STRENGTH, RFC2119_RE
from specbuild.utils import PROSE_TAGS, find_nearest_section, get_bs4, read_html, write_json


def generate_requirement_ids(html_path: Path) -> dict:
    """File-based wrapper around :func:`generate_requirement_ids_soup`.

    Args:
        html_path: Path to the compiled HTML file.

    Returns:
        Requirements dict, or empty dict on failure.
    """
    try:
        get_bs4()
    except ImportError:
        logging.warning("BeautifulSoup not available, skipping requirement IDs")
        return {}

    soup = read_html(html_path)
    return generate_requirement_ids_soup(soup)


def generate_requirement_ids_soup(soup: object, inject_attrs: bool = False) -> dict:
    """Extract normative statements and assign stable requirement IDs.

    Each RFC 2119 keyword occurrence gets a unique ID based on its
    containing section and ordinal position within that section.  The
    format is ``REQ-<section_number>-<NNN>`` where NNN is zero-padded.
    A global sequential ID ``REQ-<NNNN>`` is also assigned.

    Args:
        soup: BeautifulSoup document (mutated in place when *inject_attrs* is True).
        inject_attrs: If True, set ``data-req-id`` and ``data-req-global`` attributes
            on matched HTML elements for downstream STS XML export.

    Returns:
        Dict with ``requirements`` (list), ``by_section`` (grouped),
        and ``summary`` (counts by strength).
    """
    requirements: list[dict] = []
    by_section: dict[str, list[dict]] = {}
    section_counters: dict[str, int] = {}
    global_counter = 0

    for elem in soup.find_all(PROSE_TAGS):
        text = elem.get_text()
        matches = list(RFC2119_RE.finditer(text))
        if not matches:
            continue

        section_id, section_title = find_nearest_section(elem)

        # Derive a short section label for the ID (e.g., "5.2.1" from "section-5.2.1")
        section_label = _extract_section_number(section_id, section_title)

        # Use the first match per element to determine the primary ID for attribute injection
        first_req_id = None

        for match in matches:
            keyword = match.group(1)
            strength = KEYWORD_STRENGTH.get(keyword, "unknown")

            # Increment per-section counter
            section_counters[section_label] = section_counters.get(section_label, 0) + 1
            seq = section_counters[section_label]
            global_counter += 1

            req_id = f"REQ-{section_label}-{seq:03d}"
            global_id = f"REQ-{global_counter:04d}"

            if first_req_id is None:
                first_req_id = req_id

            # Extract sentence context (wider than compliance matrix)
            start = max(0, match.start() - 120)
            end = min(len(text), match.end() + 120)
            context = text[start:end].strip()
            if start > 0:
                context = "..." + context
            if end < len(text):
                context = context + "..."

            req = {
                "id": req_id,
                "global_id": global_id,
                "keyword": keyword,
                "strength": strength,
                "section_id": section_id,
                "section_title": section_title,
                "section_label": section_label,
                "context": context,
                "subject": _nearest_req_attr(elem, "data-req-subject"),
                "classification": _nearest_req_attr(elem, "data-req-classification"),
                "verification": _nearest_req_attr(elem, "data-req-verification"),
            }
            requirements.append(req)

            if section_label not in by_section:
                by_section[section_label] = []
            by_section[section_label].append(req)

        # Inject data attributes on the HTML element for STS XML consumption
        if inject_attrs and first_req_id and hasattr(elem, "__setitem__"):
            elem["data-req-id"] = first_req_id
            # Store global ID of first match for this element
            elem["data-req-global"] = f"REQ-{global_counter - len(matches) + 1:04d}"

    strength_counts = Counter(r["strength"] for r in requirements)
    summary = {
        "total": len(requirements),
        "mandatory": strength_counts.get("mandatory", 0),
        "recommended": strength_counts.get("recommended", 0),
        "optional": strength_counts.get("optional", 0),
        "sections": len(by_section),
    }

    return {
        "requirements": requirements,
        "by_section": by_section,
        "summary": summary,
    }


def _nearest_req_attr(elem: object, attr: str) -> str:
    """Walk element ancestors to find the nearest structured-block metadata attribute.

    Returns the attribute value as a string, or ``""`` if not found.
    """
    node = getattr(elem, "parent", None)
    while node is not None:
        val = None
        try:
            val = node.get(attr)
        except AttributeError:
            pass
        if val:
            return str(val)
        node = getattr(node, "parent", None)
    return ""


def write_requirements_manifest(data: dict, output_path: Path) -> None:
    """Write a stable requirements manifest for build-to-build diffing."""
    manifest = {
        "requirements": [
            {
                "id": r["id"],
                "global_id": r.get("global_id", ""),
                "section_label": r["section_label"],
                "keyword": r["keyword"],
                "strength": r["strength"],
                "subject": r.get("subject", ""),
                "classification": r.get("classification", ""),
                "verification": r.get("verification", ""),
            }
            for r in data.get("requirements", [])
        ]
    }
    write_json(manifest, output_path, label="Requirements manifest")


def _extract_section_number(section_id: str, section_title: str) -> str:
    """Derive a short numeric section label from the ID or title.

    Tries to find a pattern like "5.2.1" in the section title first,
    then falls back to the section ID with common prefixes stripped.
    """
    # Try to extract "5.2.1" style number from the title
    m = re.match(r"^(\d+(?:\.\d+)*)", section_title.strip())
    if m:
        return m.group(1)

    # Try to extract from the id (e.g., "section-5.2.1" or "5.2.1")
    m = re.search(r"(\d+(?:\.\d+)*)", section_id)
    if m:
        return m.group(1)

    # Fallback: use the id itself, cleaned up
    return section_id.replace(" ", "_")[:20] if section_id else "unknown"


def write_requirements_json(data: dict, output_path: Path) -> None:
    """Write the requirements list as JSON."""
    write_json(data, output_path, label="Requirement IDs")


def write_requirements_csv(data: dict, output_path: Path) -> None:
    """Write the requirements list as CSV for test suite import."""
    import csv
    import io

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        ["ID", "Global ID", "Keyword", "Strength", "Section", "Section Title", "Context"]
    )

    for req in data.get("requirements", []):
        writer.writerow(
            [
                req["id"],
                req.get("global_id", ""),
                req["keyword"],
                req["strength"],
                req["section_label"],
                req["section_title"],
                req["context"],
            ]
        )

    output_path.write_text(buf.getvalue(), encoding="utf-8")
    logging.info(f"Requirements CSV written to {output_path}")


def render_requirements_html(data: dict) -> str:
    """Render the requirements list as an HTML report."""
    summary = data.get("summary", {})
    requirements = data.get("requirements", [])

    rows = ""
    for req in requirements:
        strength_cls = f"strength-{req['strength']}"
        rows += (
            f'<tr class="{strength_cls}">'
            f"<td><code>{_html.escape(req['id'])}</code></td>"
            f"<td><code>{_html.escape(req.get('global_id', ''))}</code></td>"
            f"<td><code>{_html.escape(req['keyword'])}</code></td>"
            f"<td>{_html.escape(req['strength'])}</td>"
            f"<td>{_html.escape(req['section_label'])}</td>"
            f"<td>{_html.escape(req['section_title'])}</td>"
            f'<td class="context">{_html.escape(req["context"])}</td>'
            f"</tr>\n"
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Requirement Traceability</title>
<style>
body {{ font-family: system-ui, sans-serif; max-width: 1200px; margin: 2em auto; }}
h1 {{ font-size: 1.4em; }}
.summary {{ color: #666; margin-bottom: 1em; }}
table {{ border-collapse: collapse; width: 100%; font-size: 0.85em; }}
th, td {{ padding: 6px 10px; border: 1px solid #ddd; text-align: left; }}
th {{ background: #f5f5f5; font-weight: 600; position: sticky; top: 0; }}
.context {{ max-width: 400px; font-size: 0.85em; color: #444; }}
.strength-mandatory td:nth-child(2) {{ color: #dc2626; }}
.strength-recommended td:nth-child(2) {{ color: #d97706; }}
.strength-optional td:nth-child(2) {{ color: #059669; }}
code {{ background: #f3f4f6; padding: 1px 4px; border-radius: 3px; font-size: 0.9em; }}
</style>
</head>
<body>
<h1>Requirement Traceability Matrix</h1>
<p class="summary">{summary.get("total", 0)} requirements across
{summary.get("sections", 0)} sections:
{summary.get("mandatory", 0)} mandatory,
{summary.get("recommended", 0)} recommended,
{summary.get("optional", 0)} optional</p>

<table>
<thead><tr>
<th>Req ID</th><th>Global ID</th><th>Keyword</th><th>Strength</th>
<th>Section</th><th>Section Title</th><th>Context</th>
</tr></thead>
<tbody>{rows}</tbody>
</table>
</body>
</html>"""
