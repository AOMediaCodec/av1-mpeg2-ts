"""Definition cross-reference index: map every ``<dfn>`` to its references.

Builds a navigable glossary that pairs each defined term with every
``<a>`` reference pointing back to it, grouped by section.  Unlike
:mod:`dfnconsistency` (which only validates), this module produces a full
cross-reference index suitable for JSON export or HTML rendering.
"""

from __future__ import annotations

import html as _html
import json
import logging
from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING

from specbuild.context import resolve_lookup_maps
from specbuild.utils import find_nearest_section, get_bs4, read_html

if TYPE_CHECKING:
    from specbuild.context import BuildContext


def generate_dfn_index(html_path: Path) -> dict:
    """File-based wrapper around :func:`generate_dfn_index_soup`.

    Args:
        html_path: Path to the compiled HTML file.

    Returns:
        Definition index dict, or empty dict on failure.
    """
    try:
        get_bs4()
    except ImportError:
        logging.warning("BeautifulSoup not available, skipping dfn index generation")
        return {}

    logging.info(f"Generating definition index from {html_path.name}")
    soup = read_html(html_path)
    return generate_dfn_index_soup(soup)


def generate_dfn_index_soup(soup: object, ctx: BuildContext | None = None) -> dict:
    """Build a definition cross-reference index from parsed HTML.

    Args:
        soup: BeautifulSoup document (read-only).
        ctx: Optional :class:`BuildContext` carrying prebuilt
             ``links_by_href`` map in ``ctx.precomputed``.

    Returns:
        Dict with ``definitions``, ``undefined_refs``, and ``stats`` keys.
        See module docstring for the full schema.
    """
    # --- 1. Collect all <dfn> elements ---
    dfn_map: dict[str, dict] = {}  # dfn id -> info dict

    for dfn in soup.find_all("dfn"):
        dfn_id = dfn.get("id", "")
        term = dfn.get_text(strip=True)
        if not term or not dfn_id:
            continue
        sec_id, sec_title = find_nearest_section(dfn)
        dfn_map[dfn_id] = {
            "term": term,
            "id": dfn_id,
            "section_id": sec_id,
            "section_title": sec_title,
        }

    # --- 2. Collect all internal <a href="#..."> links via prebuilt map ---
    # target_id -> list of source section info
    ref_by_target: dict[str, list[tuple[str, str]]] = defaultdict(list)
    all_link_targets: list[dict] = []

    _, links_by_href = resolve_lookup_maps(soup, ctx)
    for href, link_list in links_by_href.items():
        if not href.startswith("#"):
            continue
        target_id = href[1:]
        if not target_id:
            continue
        for link in link_list:
            src_sec_id, src_sec_title = find_nearest_section(link)
            ref_by_target[target_id].append((src_sec_id, src_sec_title))

            # Keep track for undefined-reference detection
            all_link_targets.append(
                {
                    "target_id": target_id,
                    "term": link.get_text(strip=True),
                    "section": src_sec_title,
                }
            )

    # --- 3. For each dfn, gather references and aggregate by section ---
    total_references = 0
    definitions: list[dict] = []

    for dfn_id, info in dfn_map.items():
        sources = ref_by_target.get(dfn_id, [])
        total_references += len(sources)

        # Count references per source section
        sec_counts: dict[tuple[str, str], dict] = {}
        for src_id, src_title in sources:
            key = (src_id, src_title)
            if key not in sec_counts:
                sec_counts[key] = {
                    "section_id": src_id,
                    "section_title": src_title,
                    "count": 0,
                }
            sec_counts[key]["count"] += 1

        ref_list = sorted(sec_counts.values(), key=lambda r: r["count"], reverse=True)

        definitions.append(
            {
                "term": info["term"],
                "id": info["id"],
                "section_id": info["section_id"],
                "section_title": info["section_title"],
                "references": ref_list,
                "ref_count": len(sources),
            }
        )

    # Sort alphabetically by term (case-insensitive)
    definitions.sort(key=lambda d: d["term"].lower())

    # --- 4. Identify undefined references ---
    dfn_ids = set(dfn_map.keys())
    seen_undefined: set[str] = set()
    undefined_refs: list[dict] = []

    for entry in all_link_targets:
        target = entry["target_id"]
        if target.startswith("dfn-") and target not in dfn_ids:
            if target not in seen_undefined:
                seen_undefined.add(target)
                undefined_refs.append(
                    {
                        "term": entry["term"],
                        "href": f"#{target}",
                        "section": entry["section"],
                    }
                )

    # --- 5. Compute stats ---
    unused_count = sum(1 for d in definitions if d["ref_count"] == 0)

    stats = {
        "total_definitions": len(definitions),
        "total_references": total_references,
        "unused_definitions": unused_count,
        "undefined_references": len(undefined_refs),
    }

    logging.info(
        f"Definition index: {stats['total_definitions']} definitions, "
        f"{stats['total_references']} references, "
        f"{stats['unused_definitions']} unused, "
        f"{stats['undefined_references']} undefined"
    )

    return {
        "definitions": definitions,
        "undefined_refs": undefined_refs,
        "stats": stats,
    }


def write_dfn_index(data: dict, output_path: Path) -> None:
    """Write the definition index as JSON.

    Args:
        data: Index dict from :func:`generate_dfn_index`.
        output_path: Destination file path.
    """
    output_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    logging.info(f"Definition index written to {output_path}")


def render_dfn_index_html(data: dict) -> str:
    """Render the definition index as a standalone HTML page.

    Args:
        data: Index dict from :func:`generate_dfn_index`.

    Returns:
        Complete HTML string.
    """
    definitions = data.get("definitions", [])
    undefined_refs = data.get("undefined_refs", [])
    stats = data.get("stats", {})

    # --- Group definitions by first letter ---
    groups: dict[str, list[dict]] = defaultdict(list)
    for dfn in definitions:
        letter = dfn["term"][0].upper() if dfn["term"] else "#"
        if not letter.isalpha():
            letter = "#"
        groups[letter].append(dfn)

    letters = sorted(groups.keys())

    # --- Letter navigation ---
    nav_links = " ".join(
        f'<a href="#letter-{_html.escape(ch)}">{_html.escape(ch)}</a>' for ch in letters
    )

    # --- Build definition tables per letter group ---
    letter_sections = ""
    for ch in letters:
        rows = ""
        for dfn in groups[ch]:
            ref_sections = (
                ", ".join(
                    f"{_html.escape(r['section_title'])} ({r['count']})" for r in dfn["references"]
                )
                if dfn["references"]
                else "<em>none</em>"
            )

            rows += (
                f"<tr>"
                f"<td><code>{_html.escape(dfn['id'])}</code><br>"
                f"<strong>{_html.escape(dfn['term'])}</strong></td>"
                f"<td>{_html.escape(dfn['section_title'])}</td>"
                f'<td class="num">{dfn["ref_count"]}</td>'
                f'<td class="refs">{ref_sections}</td>'
                f"</tr>\n"
            )

        letter_sections += (
            f'<h2 id="letter-{_html.escape(ch)}">{_html.escape(ch)}</h2>\n'
            f"<table>\n"
            f"<thead><tr>"
            f"<th>Term</th>"
            f"<th>Defined In</th>"
            f"<th>Refs</th>"
            f"<th>Referenced From</th>"
            f"</tr></thead>\n"
            f"<tbody>{rows}</tbody>\n"
            f"</table>\n"
        )

    # --- Undefined references section ---
    undefined_section = ""
    if undefined_refs:
        undef_rows = ""
        for ref in undefined_refs:
            undef_rows += (
                f"<tr>"
                f"<td>{_html.escape(ref['term'])}</td>"
                f"<td><code>{_html.escape(ref['href'])}</code></td>"
                f"<td>{_html.escape(ref['section'])}</td>"
                f"</tr>\n"
            )
        undefined_section = (
            f'<h2 id="undefined-refs">Undefined References</h2>\n'
            f"<p>{len(undefined_refs)} link(s) target <code>dfn-*</code> IDs "
            f"with no matching definition.</p>\n"
            f"<table>\n"
            f"<thead><tr><th>Term</th><th>Target</th><th>Source Section</th>"
            f"</tr></thead>\n"
            f"<tbody>{undef_rows}</tbody>\n"
            f"</table>\n"
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Definition Cross-Reference Index</title>
<style>
body {{ font-family: system-ui, sans-serif; max-width: 1100px; margin: 2em auto; }}
table {{ border-collapse: collapse; width: 100%; margin: 1em 0; }}
th, td {{ padding: 6px 10px; border: 1px solid #ddd; text-align: left; }}
th {{ background: #f5f5f5; font-weight: 600; }}
td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
td.refs {{ font-size: 0.9em; color: #555; }}
h1 {{ font-size: 1.4em; }}
h2 {{ font-size: 1.15em; margin-top: 1.5em; }}
.summary {{ color: #666; }}
.nav {{ margin: 1em 0; line-height: 2; }}
.nav a {{ display: inline-block; min-width: 1.5em; text-align: center;
          padding: 2px 6px; margin: 2px; border: 1px solid #ccc;
          border-radius: 3px; text-decoration: none; color: #333; }}
.nav a:hover {{ background: #eef; }}
.unused {{ color: #c33; }}
</style>
</head>
<body>
<h1>Definition Cross-Reference Index</h1>
<p class="summary">
{stats.get("total_definitions", 0)} definitions,
{stats.get("total_references", 0)} references,
{stats.get("unused_definitions", 0)} unused,
{stats.get("undefined_references", 0)} undefined
</p>

<div class="nav">{nav_links}</div>

{letter_sections}
{undefined_section}
</body>
</html>"""
