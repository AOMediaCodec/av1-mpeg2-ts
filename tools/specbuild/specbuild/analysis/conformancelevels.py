"""Conformance level compliance matrix generation.

Extends the basic RFC 2119 compliance matrix with support for multiple
conformance levels (profiles, tiers, levels) as used in video codec
standards (H.264 Main Profile, H.265 High Tier, etc.).
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING

from specbuild.analysis.compliance import RFC2119_RE
from specbuild.utils import HEADING_RE

if TYPE_CHECKING:
    from bs4 import BeautifulSoup


def generate_conformance_level_matrix(
    soup: BeautifulSoup | None,
    levels: list[str],
    output_path: Path,
) -> Path | None:
    """Generate a conformance level compliance matrix.

    Scans the document for normative statements and maps them against
    the specified conformance levels.  Each requirement gets a row;
    each level gets a column indicating applicability.

    Args:
        soup: Parsed HTML document.
        levels: List of conformance level names (e.g. ["Main", "Main 10", "High Tier"]).
        output_path: Destination HTML file path.

    Returns:
        Path to the generated matrix HTML, or None on failure.
    """
    if soup is None or not levels:
        return None

    requirements = _extract_requirements(soup)
    if not requirements:
        logging.info("No conformance requirements found for level matrix")
        return None

    html = _render_matrix_html(requirements, levels)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    logging.info(
        f"Conformance level matrix: {len(requirements)} requirements x "
        f"{len(levels)} levels -> {output_path}"
    )
    return output_path


def _extract_requirements(soup: BeautifulSoup) -> list[dict[str, str]]:
    """Extract normative requirement statements from the document."""
    requirements = []

    for p in soup.find_all("p"):
        text = p.get_text()
        match = RFC2119_RE.search(text)
        if not match:
            continue

        if p.find_parent(class_="note") or p.find_parent(class_="example"):
            continue

        req_id = p.get("data-req-id", p.get("id", ""))
        section = _get_section_context(p)
        keyword = match.group(1)

        short_text = text[:120].strip()
        if len(text) > 120:
            short_text += "..."

        requirements.append(
            {
                "id": req_id,
                "section": section,
                "keyword": keyword,
                "text": short_text,
                "level_hints": _detect_level_hints(text),
            }
        )

    return requirements


def _get_section_context(tag) -> str:
    """Get the section heading text for a tag."""
    for parent in tag.parents:
        if parent.name == "section":
            heading = parent.find(HEADING_RE)
            if heading:
                return heading.get_text(strip=True)
    return ""


def _detect_level_hints(text: str) -> list[str]:
    """Detect explicit level/profile mentions in requirement text.

    Looks for patterns like "for Main profile", "in High Tier",
    "when Level 5.1 is used", etc.
    """
    hints = []
    profile_re = re.compile(
        r"(?:for|in|when|if)\s+(?:the\s+)?"
        r"([\w\s]+?)\s+(?:profile|tier|level|conformance\s+point)",
        re.IGNORECASE,
    )
    for m in profile_re.finditer(text):
        hint = m.group(1).strip()
        if hint and len(hint) < 40:
            hints.append(hint)
    return hints


def _render_matrix_html(
    requirements: list[dict[str, str]],
    levels: list[str],
) -> str:
    """Render the conformance level matrix as an HTML document."""
    level_headers = "".join(f"<th>{level}</th>" for level in levels)

    rows = []
    for req in requirements:
        level_cells = []
        for level in levels:
            applicable = _is_applicable(req, level)
            if applicable == "yes":
                cell = '<td class="applicable">&#10003;</td>'
            elif applicable == "explicit":
                cell = '<td class="applicable explicit">&#10003;*</td>'
            elif applicable == "recommended":
                cell = '<td class="applicable recommended">(&#10003;)</td>'
            elif applicable == "optional":
                cell = '<td class="applicable optional">opt</td>'
            elif applicable == "no":
                cell = '<td class="not-applicable">&mdash;</td>'
            else:
                cell = '<td class="unknown">?</td>'
            level_cells.append(cell)

        keyword_class = _keyword_css_class(req["keyword"])
        row = (
            f"<tr>"
            f'<td class="req-id">{req["id"]}</td>'
            f'<td class="req-section">{req["section"]}</td>'
            f'<td class="req-keyword {keyword_class}">{req["keyword"]}</td>'
            f'<td class="req-text">{req["text"]}</td>'
            f"{''.join(level_cells)}"
            f"</tr>"
        )
        rows.append(row)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Conformance Level Compliance Matrix</title>
<style>
body {{ font-family: system-ui, -apple-system, sans-serif; margin: 2em; }}
h1 {{ border-bottom: 2px solid #333; padding-bottom: 0.3em; }}
table {{ border-collapse: collapse; width: 100%; font-size: 0.9em; }}
th, td {{ border: 1px solid #ddd; padding: 0.4em 0.6em; text-align: left; }}
th {{ background: #f5f5f5; font-weight: 600; position: sticky; top: 0; }}
tr:nth-child(even) {{ background: #fafafa; }}
.req-id {{ font-family: monospace; font-size: 0.85em; white-space: nowrap; }}
.req-section {{ white-space: nowrap; max-width: 200px; overflow: hidden; text-overflow: ellipsis; }}
.req-text {{ max-width: 400px; }}
.kw-mandatory {{ color: #c00; font-weight: bold; }}
.kw-recommended {{ color: #960; }}
.kw-optional {{ color: #069; }}
.applicable {{ text-align: center; color: #155724; background: #d4edda; }}
.explicit {{ font-weight: bold; }}
.recommended {{ color: #664d03; background: #fff3cd; }}
.optional {{ color: #0a3855; background: #cfe2ff; font-size: 0.8em; }}
.not-applicable {{ text-align: center; color: #999; }}
.unknown {{ text-align: center; color: #856404; background: #fff3cd; }}
.summary {{ margin: 1em 0; }}
.legend {{ margin: 1em 0; font-size: 0.9em; color: #666; }}
</style>
</head>
<body>
<h1>Conformance Level Compliance Matrix</h1>
<p class="summary">{len(requirements)} requirements across {len(levels)} conformance levels</p>
<p class="legend">&#10003; = mandatory (MUST), &#10003;* = explicitly mentioned, (&#10003;) = recommended (SHOULD), opt = optional (MAY), &mdash; = not applicable, ? = undetermined</p>
<table>
<thead>
<tr>
<th>ID</th><th>Section</th><th>Keyword</th><th>Requirement</th>
{level_headers}
</tr>
</thead>
<tbody>
{"".join(rows)}
</tbody>
</table>
</body>
</html>
"""


def _is_applicable(req: dict[str, str], level: str) -> str:
    """Determine if a requirement applies to a given conformance level.

    Returns "explicit", "yes" (mandatory), "recommended", "optional", or "no".
    """
    hints = req.get("level_hints", [])

    if hints:
        for hint in hints:
            if level.lower() in hint.lower() or hint.lower() in level.lower():
                return "explicit"
        return "no"

    # No explicit level hints — use RFC 2119 keyword strength.
    keyword = req.get("keyword", "").upper().rstrip(".")
    if keyword in ("MUST", "MUST NOT", "SHALL", "SHALL NOT", "REQUIRED"):
        return "yes"
    if keyword in ("SHOULD", "SHOULD NOT", "RECOMMENDED", "NOT RECOMMENDED"):
        return "recommended"
    if keyword in ("MAY", "OPTIONAL", "NEED NOT"):
        return "optional"
    return "unknown"


def extract_conformance_profiles(soup: object) -> dict[str, list[str]]:
    """Extract named conformance profiles from the document.

    Profiles are declared via elements with ``data-conformance-profile``
    attribute, or ``<section class="conformance-profile" data-profile-name="...">``.

    Returns a dict mapping profile_name -> list of req IDs in that profile.
    """
    profiles: dict[str, list[str]] = {}

    # Method 1: explicit data-conformance-profile on requirement elements
    for el in soup.find_all(attrs={"data-conformance-profile": True}):
        profile_names = el.get("data-conformance-profile", "").split()
        req_id = el.get("data-req-id", el.get("id", ""))
        for name in profile_names:
            if req_id:
                profiles.setdefault(name, []).append(req_id)
            else:
                logging.warning(f"Conformance profile '{name}': element missing data-req-id and id")
                profiles.setdefault(name, [])

    # Method 2: <section class="conformance-profile" data-profile-name="...">
    for section in soup.find_all("section", class_="conformance-profile"):
        name = section.get("data-profile-name", "")
        if not name:
            continue
        profiles.setdefault(name, [])
        for el in section.find_all(attrs={"data-req-id": True}):
            profiles[name].append(el["data-req-id"])

    return profiles


def generate_conformance_matrix(soup: object) -> list[dict]:
    """Generate a table of all structured requirements with key metadata columns.

    Each row contains: req_id, req_type, clause, subject, verification,
    and a ``profiles`` field listing profile names the requirement belongs to.

    Uses ``data-req-id`` elements (produced by the structured-requirements
    enhancement) when available, falling back to normative-statement
    paragraphs detected by RFC 2119 keywords.

    Returns a list of dicts (one per requirement).
    """
    profiles = extract_conformance_profiles(soup)

    # Build a reverse map: req_id -> [profile names]
    req_to_profiles: dict[str, list[str]] = {}
    for profile_name, req_ids in profiles.items():
        for rid in req_ids:
            req_to_profiles.setdefault(rid, []).append(profile_name)

    matrix: list[dict] = []

    # Prefer structured requirement blocks (data-req-id attributes)
    structured_blocks = soup.find_all(attrs={"data-req-id": True})
    if structured_blocks:
        for block in structured_blocks:
            req_id = block.get("data-req-id", "")
            matrix.append(
                {
                    "req_id": req_id,
                    "req_type": block.get("data-req-type", ""),
                    "clause": block.get("data-req-clause", ""),
                    "subject": block.get("data-req-subject", ""),
                    "verification": block.get("data-req-verification", ""),
                    "profiles": req_to_profiles.get(req_id, []),
                }
            )
    else:
        # Fallback: scan paragraphs for RFC 2119 normative statements
        for p in soup.find_all("p"):
            text = p.get_text()
            match = RFC2119_RE.search(text)
            if not match:
                continue
            if p.find_parent(class_="note") or p.find_parent(class_="example"):
                continue
            req_id = p.get("data-req-id", p.get("id", ""))
            matrix.append(
                {
                    "req_id": req_id,
                    "req_type": match.group(1),
                    "clause": _get_section_context(p),
                    "subject": "",
                    "verification": "",
                    "profiles": req_to_profiles.get(req_id, []),
                }
            )

    return matrix


def _keyword_css_class(keyword: str) -> str:
    """Map an RFC 2119 keyword to a CSS class."""
    upper = keyword.upper().split()[0]
    if upper in ("SHALL", "MUST", "REQUIRED"):
        return "kw-mandatory"
    if upper in ("SHOULD", "RECOMMENDED"):
        return "kw-recommended"
    return "kw-optional"
