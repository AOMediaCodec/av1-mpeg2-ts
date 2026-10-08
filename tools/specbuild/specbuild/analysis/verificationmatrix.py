"""Conformance verification matrix linking requirements to verification methods.

Scans the compiled HTML for structured requirement blocks (processed by
:mod:`specbuild.enhancements.requirements`) and renders a traceability matrix
showing each requirement alongside its assigned verification method.

This matches Metanorma's requirements traceability feature.
"""

from __future__ import annotations

import html as _html
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from specbuild.utils import get_bs4, inject_css

if TYPE_CHECKING:
    from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class VerificationEntry:
    """One row in the conformance verification matrix."""

    req_id: str
    req_type: str  # "requirement", "permission", "recommendation"
    clause: str  # e.g. "7.3.2"
    subject: str  # what is governed
    text_summary: str  # first 100 chars of requirement text
    verification: str  # "test", "inspection", "demonstration", "analysis", ""
    href: str  # "#req-id-anchor"


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------


def extract_verification_entries(soup: BeautifulSoup) -> list[VerificationEntry]:
    """Scan all elements with ``data-req-id`` and build :class:`VerificationEntry` objects.

    Args:
        soup: A BeautifulSoup document previously processed by
            :func:`~specbuild.enhancements.requirements.process_requirement_blocks_soup`.

    Returns:
        List of :class:`VerificationEntry`, one per requirement block.
    """
    entries: list[VerificationEntry] = []

    for elem in soup.find_all(attrs={"data-req-id": True}):
        req_id = elem.get("data-req-id", "")
        req_type = elem.get("data-req-type", "requirement")
        clause = elem.get("data-req-clause", "")
        subject = elem.get("data-req-subject", "")
        verification = elem.get("data-req-verification", "")

        # Derive anchor href — prefer explicit id attribute, fall back to req_id
        anchor = elem.get("id") or req_id
        href = f"#{anchor}" if anchor else ""

        # text_summary: first 100 chars of element text content, stripped
        raw_text = elem.get_text(separator=" ", strip=True)
        text_summary = raw_text[:100]

        entries.append(
            VerificationEntry(
                req_id=req_id,
                req_type=req_type,
                clause=clause,
                subject=subject,
                text_summary=text_summary,
                verification=verification,
                href=href,
            )
        )

    return entries


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

# Colour tokens for type badges
_TYPE_COLORS: dict[str, str] = {
    "requirement": "#1d4ed8",  # blue
    "permission": "#15803d",  # green
    "recommendation": "#c2410c",  # orange
}

# Colour tokens for verification method badges
_VERIF_COLORS: dict[str, str] = {
    "test": "#15803d",  # green
    "inspection": "#1d4ed8",  # blue
    "demonstration": "#7c3aed",  # purple
    "analysis": "#c2410c",  # orange
}


def _type_badge(req_type: str) -> str:
    color = _TYPE_COLORS.get(req_type, "#555")
    label = _html.escape(req_type.title() if req_type else "—")
    return f'<span style="color:{color};font-weight:600;white-space:nowrap">{label}</span>'


def _verif_badge(verification: str) -> str:
    if not verification:
        return '<span style="color:#9ca3af;font-style:italic">—</span>'
    color = _VERIF_COLORS.get(verification.lower(), "#555")
    label = _html.escape(verification.title())
    return f'<span style="color:{color};font-weight:600;white-space:nowrap">{label}</span>'


def _build_rows_html(entries: list[VerificationEntry]) -> str:
    rows = ""
    for entry in entries:
        safe_id = _html.escape(entry.req_id)
        safe_href = _html.escape(entry.href)
        safe_clause = _html.escape(entry.clause)
        safe_subject = _html.escape(entry.subject)
        safe_summary = _html.escape(entry.text_summary)
        rows += (
            "<tr>"
            f'<td><a href="{safe_href}"><code>{safe_id}</code></a></td>'
            f"<td>{_type_badge(entry.req_type)}</td>"
            f"<td>{safe_clause}</td>"
            f"<td>{safe_subject}</td>"
            f'<td class="vm-summary">{safe_summary}</td>'
            f"<td>{_verif_badge(entry.verification)}</td>"
            "</tr>\n"
        )
    return rows


def render_verification_matrix_html(
    entries: list[VerificationEntry],
    title: str = "Conformance Requirements",
) -> str:
    """Produce a self-contained HTML page with the verification matrix table.

    Args:
        entries: List of :class:`VerificationEntry` objects to render.
        title: Page/section title string.

    Returns:
        Complete HTML document string.
    """
    total = len(entries)
    assigned = sum(1 for e in entries if e.verification)
    pct = round(assigned / total * 100) if total else 0

    rows_html = _build_rows_html(entries)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{_html.escape(title)} — Verification Matrix</title>
<style>
body {{ font-family: system-ui, sans-serif; max-width: 1300px; margin: 2em auto; padding: 0 1em; }}
h1 {{ font-size: 1.4em; margin-bottom: 0.25em; }}
.vm-stats {{ color: #555; font-size: 0.9em; margin-bottom: 1.2em; }}
table {{ border-collapse: collapse; width: 100%; font-size: 0.85em; }}
th, td {{ padding: 6px 10px; border: 1px solid #e5e7eb; text-align: left; vertical-align: top; }}
th {{ background: #f9fafb; font-weight: 600; position: sticky; top: 0; z-index: 1; }}
tr:hover {{ background: #f9fafb; }}
.vm-summary {{ max-width: 360px; color: #374151; }}
code {{ background: #f3f4f6; padding: 1px 4px; border-radius: 3px; font-size: 0.9em; }}
a {{ color: inherit; text-decoration: none; }}
a:hover {{ text-decoration: underline; }}
</style>
</head>
<body>
<h1>Conformance Requirements Matrix</h1>
<p class="vm-stats">
  <strong>{total}</strong> total requirement(s) &mdash;
  <strong>{assigned}</strong> with verification assigned
  ({pct}%)
</p>
<table>
<thead>
<tr>
  <th>Req ID</th>
  <th>Type</th>
  <th>Clause</th>
  <th>Subject</th>
  <th>Summary</th>
  <th>Verification</th>
</tr>
</thead>
<tbody>
{rows_html}
</tbody>
</table>
</body>
</html>"""


# ---------------------------------------------------------------------------
# File-based entry point
# ---------------------------------------------------------------------------


def generate_verification_matrix(soup: BeautifulSoup, output_path: Path) -> Path | None:
    """Extract entries, render HTML, and write to *output_path*.

    Args:
        soup: Parsed BeautifulSoup document.
        output_path: Destination ``.html`` file path.

    Returns:
        The resolved *output_path* on success, or ``None`` if no entries were found.
    """
    entries = extract_verification_entries(soup)
    if not entries:
        log.info("No requirement blocks found; skipping verification matrix.")
        return None

    html_content = render_verification_matrix_html(entries)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html_content, encoding="utf-8")
    log.info("Verification matrix written to %s (%d entries)", output_path.name, len(entries))
    return output_path


# ---------------------------------------------------------------------------
# Inline injection
# ---------------------------------------------------------------------------

_INLINE_CSS = """\
/* Inline verification matrix section */
#verification-matrix { margin: 2em 0; }
#verification-matrix h2 { font-size: 1.1em; }
#verification-matrix table { border-collapse: collapse; width: 100%; font-size: 0.85em; }
#verification-matrix th,
#verification-matrix td { padding: 5px 9px; border: 1px solid #e5e7eb; text-align: left; }
#verification-matrix th { background: #f9fafb; font-weight: 600; }
#verification-matrix .vm-summary { max-width: 340px; color: #374151; }
"""

_INLINE_CSS_ID = "verification-matrix-inline-css"


def render_verification_matrix_inline_soup(soup: BeautifulSoup) -> bool:
    """Inject the verification matrix as a ``<section id="verification-matrix">``
    block directly into the document body.

    The section is inserted after the bibliography (``<section id="bibliography">``)
    when present; otherwise before the first Annex heading, or at the end of
    ``<body>``.

    Args:
        soup: A BeautifulSoup document (mutated in place).

    Returns:
        ``True`` if the matrix was injected; ``False`` if no requirement blocks
        were found.
    """
    BS = get_bs4()

    entries = extract_verification_entries(soup)
    if not entries:
        return False

    rows_html = _build_rows_html(entries)
    total = len(entries)
    assigned = sum(1 for e in entries if e.verification)
    pct = round(assigned / total * 100) if total else 0

    section_html = (
        '<section id="verification-matrix">'
        "<h2>Conformance Requirements Matrix</h2>"
        f"<p>{total} requirement(s) — {assigned} with verification ({pct}%)</p>"
        '<table class="vm-table">'
        "<thead><tr>"
        "<th>Req ID</th><th>Type</th><th>Clause</th>"
        "<th>Subject</th><th>Summary</th><th>Verification</th>"
        "</tr></thead>"
        f"<tbody>{rows_html}</tbody>"
        "</table>"
        "</section>"
    )

    section_tag = BS(section_html, "html.parser")

    # Insertion point logic
    body = soup.find("body")
    if not body:
        return False

    inserted = False

    # 1. After bibliography section
    bib = soup.find("section", id="bibliography")
    if bib:
        bib.insert_after(section_tag)
        inserted = True

    # 2. Before first Annex heading (h2 with "Annex" text)
    if not inserted:
        for heading in body.find_all(["h2", "h3"]):
            if re.search(r"\bannex\b", heading.get_text(), re.IGNORECASE):
                parent = heading.parent
                if parent.name == "body":
                    heading.insert_before(section_tag)
                else:
                    parent.insert_before(section_tag)
                inserted = True
                break

    # 3. Append to body
    if not inserted:
        body.append(section_tag)

    # Inject CSS
    if not soup.find("style", id=_INLINE_CSS_ID):
        inject_css(soup, _INLINE_CSS_ID, _INLINE_CSS)

    log.info("Injected inline verification matrix (%d entries)", total)
    return True
