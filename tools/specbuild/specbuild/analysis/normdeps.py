"""Normative dependency graph: cross-section requirement references.

Analyzes normative statements (RFC 2119 keywords) and identifies
cross-references to other sections within those statements, building
a directed dependency graph.

Usage::

    graph = build_normative_graph(html_path)
    html = render_normative_graph_html(graph)
"""

from __future__ import annotations

import html as _html
import logging
from collections import defaultdict
from pathlib import Path

from specbuild.analysis.compliance import RFC2119_RE
from specbuild.analysis.regression import extract_headings
from specbuild.utils import PROSE_TAGS, find_nearest_section, get_bs4, read_html


def build_normative_graph(html_path: Path) -> dict:
    """File-based wrapper around :func:`build_normative_graph_soup`.

    Args:
        html_path: Path to the compiled HTML.

    Returns:
        Normative dependency graph dict, or empty dict on failure.
    """
    try:
        get_bs4()
    except ImportError:
        logging.warning("BeautifulSoup not available, skipping normative deps")
        return {}

    soup = read_html(html_path)
    return build_normative_graph_soup(soup)


def build_normative_graph_soup(soup: object) -> dict:
    """Build a normative dependency graph from parsed HTML.

    For each section, finds normative statements and identifies which
    other sections they reference via internal links.

    Args:
        soup: BeautifulSoup document (read-only).

    Returns:
        Dict with:
        - ``nodes``: list of section dicts (``id``, ``title``, ``level``)
        - ``edges``: list of edge dicts (``source``, ``target``, ``keywords``, ``count``)
        - ``stats``: summary statistics
    """
    _PROSE_SET = set(PROSE_TAGS)

    # Collect all section IDs from headings via shared extractor
    headings = extract_headings(soup)
    section_ids: set[str] = set()
    section_titles: dict[str, str] = {}
    section_levels: dict[str, int] = {}
    for h in headings:
        sid = h["id"]
        if sid:
            section_ids.add(sid)
            section_titles[sid] = h["title"]
            section_levels[sid] = h["level"]

    # Build edges: for each normative statement, find cross-refs
    edges: dict[tuple[str, str], list[str]] = defaultdict(list)
    sections_with_normative: set[str] = set()

    for elem in soup.find_all(list(_PROSE_SET)):
        text = elem.get_text()
        if not RFC2119_RE.search(text):
            continue

        # Find which section this element belongs to
        source_id, _source_title = find_nearest_section(elem)
        if not source_id or source_id not in section_ids:
            continue

        sections_with_normative.add(source_id)

        # Find keywords in this element
        keywords = [m.group(1) for m in RFC2119_RE.finditer(text)]

        # Find cross-reference links via DOM instead of string serialization
        for a_tag in elem.find_all("a"):
            href = a_tag.get("href", "")
            if href.startswith("#"):
                target_id = href[1:]
                if target_id in section_ids and target_id != source_id:
                    edges[(source_id, target_id)].extend(keywords)

    # Build structured output
    node_list = []
    involved_ids = set()
    for src, tgt in edges:
        involved_ids.add(src)
        involved_ids.add(tgt)

    for sid in sorted(involved_ids):
        node_list.append(
            {
                "id": sid,
                "title": section_titles.get(sid, sid),
                "level": section_levels.get(sid, 0),
            }
        )

    edge_list = []
    for (src, tgt), kws in sorted(edges.items()):
        edge_list.append(
            {
                "source": src,
                "target": tgt,
                "keywords": sorted(set(kws)),
                "count": len(kws),
            }
        )

    # Stats
    in_degree: dict[str, int] = defaultdict(int)
    out_degree: dict[str, int] = defaultdict(int)
    for edge in edge_list:
        out_degree[edge["source"]] += 1
        in_degree[edge["target"]] += 1

    most_deps = max(out_degree.items(), key=lambda x: x[1]) if out_degree else ("", 0)
    most_depended = max(in_degree.items(), key=lambda x: x[1]) if in_degree else ("", 0)

    return {
        "nodes": node_list,
        "edges": edge_list,
        "stats": {
            "total_sections": len(section_ids),
            "sections_with_normative": len(sections_with_normative),
            "sections_in_graph": len(involved_ids),
            "total_edges": len(edge_list),
            "most_dependencies": {
                "id": most_deps[0],
                "title": section_titles.get(most_deps[0], ""),
                "count": most_deps[1],
            },
            "most_depended_on": {
                "id": most_depended[0],
                "title": section_titles.get(most_depended[0], ""),
                "count": most_depended[1],
            },
        },
    }


def render_normative_graph_html(graph: dict) -> str:
    """Render the normative dependency graph as a standalone HTML page.

    Args:
        graph: Dict from :func:`build_normative_graph_soup`.

    Returns:
        Complete HTML string with an interactive adjacency-matrix style view.
    """
    if not graph:
        return "<html><body><p>No normative dependency data available.</p></body></html>"

    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])
    stats = graph.get("stats", {})

    # Stats section
    stats_html = (
        f'<div class="stats">'
        f'<div class="stat"><div class="value">{stats.get("total_sections", 0)}</div>'
        f'<div class="label">Total Sections</div></div>'
        f'<div class="stat"><div class="value">{stats.get("sections_with_normative", 0)}</div>'
        f'<div class="label">With Normative</div></div>'
        f'<div class="stat"><div class="value">{stats.get("sections_in_graph", 0)}</div>'
        f'<div class="label">In Dep Graph</div></div>'
        f'<div class="stat"><div class="value">{stats.get("total_edges", 0)}</div>'
        f'<div class="label">Dependencies</div></div>'
        f"</div>"
    )

    # Key findings
    most_deps = stats.get("most_dependencies", {})
    most_depended = stats.get("most_depended_on", {})
    findings = ""
    if most_deps.get("id"):
        findings += (
            f"<p><strong>Most dependencies:</strong> "
            f"<code>{_html.escape(most_deps['id'])}</code> "
            f"({_html.escape(most_deps.get('title', ''))}) "
            f"&mdash; references {most_deps['count']} other sections normatively</p>"
        )
    if most_depended.get("id"):
        findings += (
            f"<p><strong>Most depended on:</strong> "
            f"<code>{_html.escape(most_depended['id'])}</code> "
            f"({_html.escape(most_depended.get('title', ''))}) "
            f"&mdash; referenced by {most_depended['count']} other sections</p>"
        )

    # Edge table (sorted by count descending)
    sorted_edges = sorted(edges, key=lambda e: e["count"], reverse=True)
    node_map = {n["id"]: n for n in nodes}
    edge_rows = ""
    for edge in sorted_edges[:200]:  # Cap for large specs
        kw_badges = " ".join(f'<span class="kw">{_html.escape(k)}</span>' for k in edge["keywords"])
        src_title = node_map.get(edge["source"], {}).get("title", "")
        tgt_title = node_map.get(edge["target"], {}).get("title", "")

        edge_rows += (
            f"<tr>"
            f"<td><code>{_html.escape(edge['source'])}</code>"
            f'<br><span class="sec-title">{_html.escape(src_title)}</span></td>'
            f"<td><code>{_html.escape(edge['target'])}</code>"
            f'<br><span class="sec-title">{_html.escape(tgt_title)}</span></td>'
            f'<td class="num">{edge["count"]}</td>'
            f"<td>{kw_badges}</td>"
            f"</tr>\n"
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Normative Dependency Graph</title>
<style>
body {{ font-family: system-ui, sans-serif; max-width: 1100px; margin: 2em auto;
       padding: 0 1em; line-height: 1.5; }}
h1 {{ font-size: 1.4em; }}
h2 {{ font-size: 1.15em; margin-top: 2em; border-bottom: 1px solid #e5e7eb;
      padding-bottom: 0.3em; }}
.stats {{ display: flex; gap: 1em; flex-wrap: wrap; margin: 1.5em 0; }}
.stat {{ background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px;
         padding: 12px 20px; text-align: center; min-width: 120px; }}
.stat .value {{ font-size: 1.6em; font-weight: 700; color: #1e293b; }}
.stat .label {{ font-size: 0.75em; color: #64748b; text-transform: uppercase;
               letter-spacing: 0.05em; }}
table {{ border-collapse: collapse; width: 100%; font-size: 0.88em; margin: 1em 0; }}
th, td {{ padding: 6px 10px; border: 1px solid #ddd; text-align: left; }}
th {{ background: #f5f5f5; font-weight: 600; }}
td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
.sec-title {{ font-size: 0.8em; color: #666; }}
.kw {{ display: inline-block; background: #fef3c7; color: #92400e;
       padding: 1px 6px; border-radius: 3px; font-size: 0.8em;
       font-weight: 600; margin: 1px; }}
</style>
</head>
<body>
<h1>Normative Dependency Graph</h1>
<p class="muted">Cross-section normative requirement references — which sections'
RFC 2119 statements reference other sections.</p>

{stats_html}

{findings}

<h2>Dependency Edges</h2>
<p class="muted">Sorted by number of normative references (descending).</p>
<table>
<thead><tr><th>Source Section</th><th>Target Section</th>
<th style="text-align:right">Count</th><th>Keywords</th></tr></thead>
<tbody>{edge_rows}</tbody>
</table>
</body>
</html>"""
