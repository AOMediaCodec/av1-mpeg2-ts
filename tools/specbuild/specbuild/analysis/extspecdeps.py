"""External specification dependency tracking.

Scans the compiled HTML for references to external specifications
(bibliography entries and inline citations) and maps which internal
sections depend on each external spec.  Generates an impact-analysis
report for tracking cross-spec dependencies.
"""

from __future__ import annotations

import html as _html
import logging
import re
from pathlib import Path

from specbuild.utils import PROSE_TAGS, find_nearest_section, get_bs4, read_html, write_json

# Pattern matching inline normative citations like "Section 5.2 of [AV1]"
# or "as defined in [ISO/IEC 23008-12]" or "per clause 8.3 of [H.264]".
_INLINE_CITE_RE = re.compile(
    r"(?:(?:section|clause|annex|table|figure)\s+[\w.]+\s+of\s+)?"
    r"\[([A-Z][A-Za-z0-9_./-]+)\]",
    re.IGNORECASE,
)

# Known spec families for classification
_SPEC_FAMILIES = {
    "AV1": "Alliance for Open Media",
    "AV2": "Alliance for Open Media",
    "VP9": "Alliance for Open Media",
    "H.264": "ITU-T / ISO/IEC",
    "H.265": "ITU-T / ISO/IEC",
    "H.266": "ITU-T / ISO/IEC",
    "HEVC": "ITU-T / ISO/IEC",
    "VVC": "ITU-T / ISO/IEC",
    "RFC": "IETF",
}


def generate_ext_spec_deps(html_path: Path) -> dict:
    """File-based wrapper around :func:`generate_ext_spec_deps_soup`.

    Args:
        html_path: Path to the compiled HTML file.

    Returns:
        External spec dependencies dict, or empty dict on failure.
    """
    try:
        get_bs4()
    except ImportError:
        logging.warning("BeautifulSoup not available, skipping ext spec deps")
        return {}

    soup = read_html(html_path)
    return generate_ext_spec_deps_soup(soup)


def generate_ext_spec_deps_soup(soup: object) -> dict:
    """Extract external spec references and map to internal sections.

    Args:
        soup: BeautifulSoup document (read-only).

    Returns:
        Dict with ``specs`` (external spec → internal sections),
        ``sections`` (internal section → external specs), ``bibliography``
        (bibliography entries found), and ``summary``.
    """
    specs: dict[str, dict] = {}
    sections: dict[str, set[str]] = {}
    bibliography: dict[str, dict] = {}

    # First, extract bibliography entries
    for dt in soup.find_all("dt"):
        bib_id = dt.get("id", "")
        if bib_id.startswith("biblio-"):
            ref_name = bib_id[len("biblio-") :].upper()
            dd = dt.find_next_sibling("dd")
            bib_text = dd.get_text().strip() if dd else ""
            bibliography[ref_name] = {
                "id": ref_name,
                "text": bib_text[:200],
                "type": _classify_reference(ref_name, bib_text),
            }

    # Scan prose for inline citations
    for elem in soup.find_all(PROSE_TAGS):
        text = elem.get_text()
        matches = list(_INLINE_CITE_RE.finditer(text))
        if not matches:
            continue

        section_id, section_title = find_nearest_section(elem)

        for match in matches:
            ref_name = match.group(1).upper()

            # Skip self-references and purely numeric refs
            if ref_name.isdigit():
                continue

            if ref_name not in specs:
                bib_entry = bibliography.get(ref_name, {})
                specs[ref_name] = {
                    "name": ref_name,
                    "family": _get_spec_family(ref_name),
                    "type": bib_entry.get("type", "unknown"),
                    "sections": set(),
                    "count": 0,
                }
            specs[ref_name]["sections"].add(section_id)
            specs[ref_name]["count"] += 1

            if section_id not in sections:
                sections[section_id] = set()
            sections[section_id].add(ref_name)

    # Convert sets to sorted lists for JSON serialization
    for spec_data in specs.values():
        spec_data["sections"] = sorted(spec_data["sections"])
    sorted_sections = {k: sorted(v) for k, v in sections.items()}

    # Sort specs by reference count (most-referenced first)
    sorted_specs = dict(sorted(specs.items(), key=lambda x: x[1]["count"], reverse=True))

    return {
        "specs": sorted_specs,
        "sections": sorted_sections,
        "bibliography": bibliography,
        "summary": {
            "total_external_specs": len(specs),
            "total_references": sum(s["count"] for s in specs.values()),
            "total_sections_with_refs": len(sections),
            "total_bibliography": len(bibliography),
        },
    }


def _classify_reference(ref_name: str, bib_text: str) -> str:
    """Classify a bibliography reference as normative or informative."""
    text_lower = bib_text.lower()
    if any(kw in text_lower for kw in ("normative", "shall", "must", "required")):
        return "normative"
    if any(kw in text_lower for kw in ("informative", "for information", "optional")):
        return "informative"
    return "unknown"


def _get_spec_family(ref_name: str) -> str:
    """Determine the standards family for a reference."""
    for prefix, family in _SPEC_FAMILIES.items():
        if ref_name.startswith(prefix):
            return family
    if ref_name.startswith("ISO"):
        return "ISO/IEC"
    if ref_name.startswith("ITU"):
        return "ITU-T"
    return "other"


def write_ext_spec_deps_json(data: dict, output_path: Path) -> None:
    """Write external spec dependencies as JSON."""
    write_json(data, output_path, label="External spec dependencies")


def render_ext_spec_deps_html(data: dict) -> str:
    """Render external spec dependencies as an HTML report."""
    specs = data.get("specs", {})
    summary = data.get("summary", {})

    spec_rows = ""
    for name, info in specs.items():
        secs = ", ".join(info.get("sections", []))
        family = _html.escape(info.get("family", ""))
        ref_type = _html.escape(info.get("type", ""))
        spec_rows += (
            f"<tr>"
            f"<td><strong>{_html.escape(name)}</strong></td>"
            f"<td>{family}</td>"
            f"<td>{ref_type}</td>"
            f"<td>{info.get('count', 0)}</td>"
            f"<td>{_html.escape(secs)}</td>"
            f"</tr>\n"
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>External Spec Dependencies</title>
<style>
body {{ font-family: system-ui, sans-serif; max-width: 1100px; margin: 2em auto; }}
h1 {{ font-size: 1.4em; }}
.summary {{ color: #666; }}
table {{ border-collapse: collapse; width: 100%; font-size: 0.88em; margin: 1em 0; }}
th, td {{ padding: 6px 10px; border: 1px solid #ddd; text-align: left; }}
th {{ background: #f5f5f5; font-weight: 600; }}
</style>
</head>
<body>
<h1>External Specification Dependencies</h1>
<p class="summary">{summary.get("total_external_specs", 0)} external specs referenced
{summary.get("total_references", 0)} times across
{summary.get("total_sections_with_refs", 0)} sections</p>

<table>
<thead><tr>
<th>Spec</th><th>Family</th><th>Type</th><th>References</th><th>Dependent Sections</th>
</tr></thead>
<tbody>{spec_rows}</tbody>
</table>
</body>
</html>"""
