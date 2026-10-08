"""Cross-reference report: map internal links between spec sections.

Generates a structured report of which sections reference which other
sections, producing:

- Per-section incoming/outgoing reference counts
- An adjacency list suitable for graph rendering
- An HTML report with an interactive matrix or list view
"""

from __future__ import annotations

import html as _html
import json
import logging
from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING

from specbuild.context import resolve_lookup_maps
from specbuild.utils import HEADING_TAGS, get_bs4, read_html

if TYPE_CHECKING:
    from specbuild.context import BuildContext


def generate_xref_report(html_path: Path) -> dict:
    """File-based wrapper around :func:`generate_xref_report_soup`.

    Args:
        html_path: Path to the compiled HTML file.

    Returns:
        Cross-reference report dict, or empty dict on failure.
    """
    try:
        get_bs4()
    except ImportError:
        logging.warning("BeautifulSoup not available, skipping xref report")
        return {}

    try:
        soup = read_html(html_path)
    except (FileNotFoundError, OSError) as exc:
        logging.error(f"XRef report: cannot read {html_path}: {exc}")
        return {}
    return generate_xref_report_soup(soup)


def generate_xref_report_soup(soup: object, ctx: BuildContext | None = None) -> dict:
    """Build a cross-reference map from the parsed HTML.

    Args:
        soup: BeautifulSoup document (read-only).
        ctx: Optional :class:`BuildContext` carrying prebuilt
             ``ids_by_id`` / ``links_by_href`` maps in ``ctx.precomputed``.

    Returns:
        Dict with ``sections`` (list of section info dicts),
        ``edges`` (list of {from, to} dicts), and ``matrix``
        (adjacency counts).
    """
    ids_by_id, links_by_href = resolve_lookup_maps(soup, ctx)

    # Build section index: id -> section info
    sections: dict[str, dict] = {}
    for heading in soup.find_all(list(HEADING_TAGS)):
        sec_id = heading.get("id", "")
        if not sec_id:
            parent = heading.find_parent(["section", "div"])
            if parent:
                sec_id = parent.get("id", "")
        if not sec_id:
            continue

        title = heading.get_text(strip=True)
        level = int(heading.name[1])
        sections[sec_id] = {
            "id": sec_id,
            "title": title,
            "level": level,
            "outgoing": 0,
            "incoming": 0,
        }

    # Build all anchor id -> section id mapping
    id_to_section: dict[str, str] = {}
    for sec_id in sections:
        id_to_section[sec_id] = sec_id

    # Map all elements with ids to their containing section (uses prebuilt map)
    for elem_id, elem in ids_by_id.items():
        if elem_id in id_to_section:
            continue
        # Find containing section
        for parent in elem.parents:
            if parent is None:
                break
            pid = parent.get("id", "")
            if pid in sections:
                id_to_section[elem_id] = pid
                break

    # Collect edges from internal links
    edges: list[dict] = []
    edge_counts: dict[tuple[str, str], int] = defaultdict(int)

    for href, link_list in links_by_href.items():
        if not href.startswith("#"):
            continue
        target_id = href[1:]
        if not target_id:
            continue

        target_section = id_to_section.get(target_id)
        if not target_section:
            continue

        for link in link_list:
            # Find source section
            source_section = None
            for parent in link.parents:
                if parent is None:
                    break
                pid = parent.get("id", "")
                if pid in sections:
                    source_section = pid
                    break

            if not source_section or source_section == target_section:
                continue

            key = (source_section, target_section)
            edge_counts[key] += 1

    for (src, tgt), count in edge_counts.items():
        edges.append({"from": src, "to": tgt, "count": count})
        if src in sections:
            sections[src]["outgoing"] += count
        if tgt in sections:
            sections[tgt]["incoming"] += count

    section_list = sorted(sections.values(), key=lambda s: s["id"])

    # --- Broken ref + unused figure/table detection ---
    all_ids = set(ids_by_id.keys())

    broken_refs: list[dict] = []
    referenced_ids: set[str] = set()

    for href, link_list in links_by_href.items():
        if not href.startswith("#"):
            continue
        target_id = href[1:]
        if not target_id:
            continue
        referenced_ids.add(target_id)
        if target_id not in all_ids:
            broken_refs.append(
                {
                    "href": href,
                    "text": link_list[0].get_text(strip=True),
                    "target_id": target_id,
                }
            )

    # Figures and tables with IDs that are never referenced by any <a href>
    unused_figures: list[dict] = []
    for fig in soup.find_all(["figure", "table"]):
        fig_id = fig.get("id", "")
        if not fig_id:
            continue
        caption = fig.find(["figcaption", "caption"])
        caption_text = caption.get_text(strip=True) if caption else ""
        if fig_id not in referenced_ids:
            unused_figures.append(
                {
                    "id": fig_id,
                    "tag": fig.name,
                    "caption": caption_text,
                }
            )

    return {
        "sections": section_list,
        "edges": edges,
        "total_sections": len(section_list),
        "total_edges": len(edges),
        "broken_refs": broken_refs,
        "unused_figures": unused_figures,
    }


def write_xref_report(report: dict, output_path: Path) -> None:
    """Write the cross-reference report as JSON.

    Args:
        report: Report dict from :func:`generate_xref_report`.
        output_path: Destination file path.
    """
    output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    logging.info(f"Cross-reference report written to {output_path}")


def render_xref_html(report: dict) -> str:
    """Render the cross-reference report as an HTML page.

    Args:
        report: Report dict from :func:`generate_xref_report`.

    Returns:
        Complete HTML string.
    """
    sections = report.get("sections", [])
    edges = report.get("edges", [])
    broken_refs = report.get("broken_refs", [])
    unused_figures = report.get("unused_figures", [])

    # Build rows for the section table
    section_rows = ""
    for sec in sections:
        section_rows += (
            f"<tr>"
            f"<td><code>{_html.escape(sec['id'])}</code></td>"
            f"<td>{_html.escape(sec['title'])}</td>"
            f'<td class="num">{sec["outgoing"]}</td>'
            f'<td class="num">{sec["incoming"]}</td>'
            f"</tr>\n"
        )

    # Build rows for top edges
    top_edges = sorted(edges, key=lambda e: e["count"], reverse=True)[:50]
    edge_rows = ""
    for edge in top_edges:
        edge_rows += (
            f"<tr>"
            f"<td><code>{_html.escape(edge['from'])}</code></td>"
            f"<td><code>{_html.escape(edge['to'])}</code></td>"
            f'<td class="num">{edge["count"]}</td>'
            f"</tr>\n"
        )

    # Build rows for broken refs
    broken_rows = ""
    for ref in broken_refs:
        broken_rows += (
            f"<tr>"
            f"<td><code>{_html.escape(ref['href'])}</code></td>"
            f"<td>{_html.escape(ref['text'])}</td>"
            f"</tr>\n"
        )

    # Build rows for unused figures/tables
    unused_rows = ""
    for item in unused_figures:
        unused_rows += (
            f"<tr>"
            f"<td><code>{_html.escape(item['id'])}</code></td>"
            f"<td>{_html.escape(item['tag'])}</td>"
            f"<td>{_html.escape(item['caption'])}</td>"
            f"</tr>\n"
        )

    broken_section = ""
    if broken_refs:
        broken_section = f"""
<h2>Broken Internal Links ({len(broken_refs)})</h2>
<table>
<thead><tr><th>href</th><th>Link text</th></tr></thead>
<tbody>{broken_rows}</tbody>
</table>"""

    unused_section = ""
    if unused_figures:
        unused_section = f"""
<h2>Unreferenced Figures/Tables ({len(unused_figures)})</h2>
<table>
<thead><tr><th>ID</th><th>Type</th><th>Caption</th></tr></thead>
<tbody>{unused_rows}</tbody>
</table>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Cross-Reference Report</title>
<style>
body {{ font-family: system-ui, sans-serif; max-width: 900px; margin: 2em auto; }}
table {{ border-collapse: collapse; width: 100%; margin: 1em 0; }}
th, td {{ padding: 6px 10px; border: 1px solid #ddd; text-align: left; }}
th {{ background: #f5f5f5; font-weight: 600; }}
td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
h1 {{ font-size: 1.4em; }}
h2 {{ font-size: 1.15em; margin-top: 1.5em; }}
.summary {{ color: #666; }}
</style>
</head>
<body>
<h1>Cross-Reference Report</h1>
<p class="summary">{report.get("total_sections", 0)} sections,
{report.get("total_edges", 0)} cross-reference links</p>

<h2>Sections by Reference Count</h2>
<table>
<thead><tr><th>ID</th><th>Title</th><th>Outgoing</th><th>Incoming</th></tr></thead>
<tbody>{section_rows}</tbody>
</table>

<h2>Top Cross-References</h2>
<table>
<thead><tr><th>From</th><th>To</th><th>Count</th></tr></thead>
<tbody>{edge_rows}</tbody>
</table>
{broken_section}{unused_section}
</body>
</html>"""
