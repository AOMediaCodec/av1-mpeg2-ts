"""Compliance matrix: extract normative statements from the specification.

Scans prose text for RFC 2119 keywords (SHALL, MUST, SHOULD, MAY, etc.)
and organizes them into a structured table by section.  The output is
useful for conformance testing and specification review.
"""

from __future__ import annotations

import html as _html
import json
import logging
import re
from pathlib import Path

from specbuild.utils import PROSE_TAGS, find_nearest_section, get_bs4, read_html

# RFC 2119 keywords (case-sensitive per the RFC)
_RFC2119_KEYWORDS = (
    "MUST",
    "MUST NOT",
    "SHALL",
    "SHALL NOT",
    "SHOULD",
    "SHOULD NOT",
    "NEED NOT",
    "MAY",
    "REQUIRED",
    "RECOMMENDED",
    "NOT RECOMMENDED",
    "OPTIONAL",
)

RFC2119_RE = re.compile(
    r"\b("
    + "|".join(re.escape(k) for k in sorted(_RFC2119_KEYWORDS, key=len, reverse=True))
    + r")\b"
)

# Classify keywords by strength
KEYWORD_STRENGTH: dict[str, str] = {
    "MUST": "mandatory",
    "MUST NOT": "mandatory",
    "SHALL": "mandatory",
    "SHALL NOT": "mandatory",
    "REQUIRED": "mandatory",
    "SHOULD": "recommended",
    "SHOULD NOT": "recommended",
    "RECOMMENDED": "recommended",
    "NOT RECOMMENDED": "recommended",
    "MAY": "optional",
    "NEED NOT": "optional",
    "OPTIONAL": "optional",
}


def generate_compliance_matrix(html_path: Path) -> dict:
    """File-based wrapper around :func:`generate_compliance_matrix_soup`.

    Args:
        html_path: Path to the compiled HTML file.

    Returns:
        Compliance matrix dict, or empty dict on failure.
    """
    try:
        get_bs4()
    except ImportError:
        logging.warning("BeautifulSoup not available, skipping compliance matrix")
        return {}

    soup = read_html(html_path)
    return generate_compliance_matrix_soup(soup)


def generate_compliance_matrix_soup(soup: object) -> dict:
    """Extract normative statements from the parsed HTML.

    Args:
        soup: BeautifulSoup document (read-only).

    Returns:
        Dict with ``statements`` (list), ``summary`` (keyword counts),
        and ``by_section`` (grouped statements).
    """
    statements: list[dict] = []
    summary: dict[str, int] = {k: 0 for k in _RFC2119_KEYWORDS}
    by_section: dict[str, list[dict]] = {}

    prose_set = frozenset(PROSE_TAGS)
    for elem in soup.find_all(prose_set):
        if any(p.name in prose_set for p in elem.parents):
            continue
        text = elem.get_text()
        matches = list(RFC2119_RE.finditer(text))
        if not matches:
            continue

        # Determine containing section
        section_id, section_title = find_nearest_section(elem)

        for match in matches:
            keyword = match.group(1)
            # Extract surrounding sentence context
            start = max(0, match.start() - 80)
            end = min(len(text), match.end() + 80)
            context = text[start:end].strip()
            if start > 0:
                context = "..." + context
            if end < len(text):
                context = context + "..."

            stmt = {
                "keyword": keyword,
                "strength": KEYWORD_STRENGTH.get(keyword, "unknown"),
                "context": context,
                "section_id": section_id,
                "section_title": section_title,
            }
            statements.append(stmt)
            summary[keyword] = summary.get(keyword, 0) + 1

            if section_id not in by_section:
                by_section[section_id] = []
            by_section[section_id].append(stmt)

    return {
        "statements": statements,
        "summary": summary,
        "by_section": by_section,
        "total": len(statements),
        "mandatory": sum(1 for s in statements if s["strength"] == "mandatory"),
        "recommended": sum(1 for s in statements if s["strength"] == "recommended"),
        "optional": sum(1 for s in statements if s["strength"] == "optional"),
    }


def write_compliance_matrix(matrix: dict, output_path: Path) -> None:
    """Write the compliance matrix as JSON.

    Args:
        matrix: Matrix dict from :func:`generate_compliance_matrix`.
        output_path: Destination file path.
    """
    output_path.write_text(json.dumps(matrix, indent=2), encoding="utf-8")
    logging.info(f"Compliance matrix written to {output_path}")


def render_compliance_html(matrix: dict) -> str:
    """Render the compliance matrix as an HTML page.

    Args:
        matrix: Matrix dict from :func:`generate_compliance_matrix`.

    Returns:
        Complete HTML string.
    """
    summary = matrix.get("summary", {})
    statements = matrix.get("statements", [])

    # Summary cards
    cards = ""
    for keyword in _RFC2119_KEYWORDS:
        count = summary.get(keyword, 0)
        if count > 0:
            strength = KEYWORD_STRENGTH.get(keyword, "")
            cls = f"card-{strength}"
            cards += (
                f'<div class="card {cls}">'
                f'<div class="value">{count}</div>'
                f'<div class="label">{_html.escape(keyword)}</div>'
                f"</div>\n"
            )

    # Statement rows
    rows = ""
    for stmt in statements[:500]:  # Cap for large specs
        strength_cls = f"strength-{stmt['strength']}"
        rows += (
            f'<tr class="{strength_cls}">'
            f"<td><code>{_html.escape(stmt['keyword'])}</code></td>"
            f"<td>{_html.escape(stmt['strength'])}</td>"
            f"<td>{_html.escape(stmt['section_title'])}</td>"
            f'<td class="context">{_html.escape(stmt["context"])}</td>'
            f"</tr>\n"
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Compliance Matrix</title>
<style>
body {{ font-family: system-ui, sans-serif; max-width: 1100px; margin: 2em auto; }}
h1 {{ font-size: 1.4em; }}
h2 {{ font-size: 1.15em; margin-top: 1.5em; }}
.summary {{ color: #666; margin-bottom: 1em; }}
.cards {{ display: flex; flex-wrap: wrap; gap: 8px; margin: 1em 0; }}
.card {{ padding: 8px 14px; border-radius: 6px; text-align: center;
         border: 1px solid #ddd; min-width: 80px; }}
.card .value {{ font-size: 1.4em; font-weight: 700; }}
.card .label {{ font-size: 0.75em; text-transform: uppercase; color: #666; }}
.card-mandatory {{ background: #fee2e2; border-color: #fca5a5; }}
.card-recommended {{ background: #fef3c7; border-color: #fcd34d; }}
.card-optional {{ background: #d1fae5; border-color: #6ee7b7; }}
table {{ border-collapse: collapse; width: 100%; font-size: 0.88em; }}
th, td {{ padding: 6px 10px; border: 1px solid #ddd; text-align: left; }}
th {{ background: #f5f5f5; font-weight: 600; }}
.context {{ max-width: 500px; font-size: 0.85em; color: #444; }}
.strength-mandatory td:first-child {{ color: #dc2626; }}
.strength-recommended td:first-child {{ color: #d97706; }}
.strength-optional td:first-child {{ color: #059669; }}
</style>
</head>
<body>
<h1>Specification Compliance Matrix</h1>
<p class="summary">{matrix.get("total", 0)} normative statements:
{matrix.get("mandatory", 0)} mandatory,
{matrix.get("recommended", 0)} recommended,
{matrix.get("optional", 0)} optional</p>

<h2>Keyword Summary</h2>
<div class="cards">{cards}</div>

<h2>Normative Statements</h2>
<table>
<thead><tr><th>Keyword</th><th>Strength</th><th>Section</th><th>Context</th></tr></thead>
<tbody>{rows}</tbody>
</table>
</body>
</html>"""
