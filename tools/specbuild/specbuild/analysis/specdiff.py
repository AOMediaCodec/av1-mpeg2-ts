"""Spec version comparison dashboard.

Generates a visual HTML dashboard comparing two specification builds,
combining structural regression data, compliance matrix differences,
and spec metrics into a single report.

Usage::

    dashboard = generate_spec_comparison(current_path, baseline_path)
    html = render_comparison_dashboard(dashboard)
"""

from __future__ import annotations

import html as _html
import logging
from pathlib import Path

from specbuild.utils import get_bs4, read_html


def find_broken_links_after_diff(
    old_ids: set[str], new_ids: set[str], new_soup: object
) -> list[dict]:
    """Detect anchor links that targeted IDs removed or renamed between versions.

    Collects all ``<a href="#...">`` in *new_soup* and checks whether each
    target fragment was present in *old_ids* but is now absent from *new_ids*
    (i.e. the anchor was removed or renamed without updating the link).

    Args:
        old_ids: Set of element IDs present in the baseline document.
        new_ids: Set of element IDs present in the current document.
        new_soup: BeautifulSoup of the current document (used to find links).

    Returns:
        List of dicts with keys:

        - ``href``: the fragment href (``"#old-id"``)
        - ``was_present``: ``True`` — indicates it existed in the old build
        - ``context``: nearest heading text near the broken link
    """
    from specbuild.utils import find_nearest_heading

    broken: list[dict] = []
    seen: set[str] = set()

    for a in new_soup.find_all("a", href=True):
        href: str = a["href"]
        if not href.startswith("#"):
            continue
        fragment = href[1:]
        if not fragment or fragment in seen:
            continue
        seen.add(fragment)
        # Broken if it was in old doc but is NOT in new doc
        if fragment in old_ids and fragment not in new_ids:
            broken.append(
                {
                    "href": href,
                    "was_present": True,
                    "context": find_nearest_heading(a),
                }
            )

    if broken:
        logging.warning(f"Spec diff: {len(broken)} potentially broken anchor link(s) after diff")
    return broken


def _collect_ids(soup: object) -> set[str]:
    """Return the set of all element IDs in *soup*."""
    return {elem["id"] for elem in soup.find_all(id=True)}


def generate_spec_comparison(current_path: Path, baseline_path: Path) -> dict:
    """Compare two spec builds comprehensively.

    Args:
        current_path: Path to the current build HTML.
        baseline_path: Path to the baseline build HTML.

    Returns:
        Dict with ``regression``, ``metrics``, ``compliance``, ``metadata``,
        and ``broken_links_after_diff``.
    """
    try:
        get_bs4()
    except ImportError:
        logging.warning("BeautifulSoup not available, skipping spec comparison")
        return {}

    from specbuild.analysis.compliance import generate_compliance_matrix_soup
    from specbuild.analysis.regression import compare_builds_soup
    from specbuild.analysis.specmetrics import collect_metrics_soup

    current_soup = read_html(current_path)
    baseline_soup = read_html(baseline_path)

    # Regression comparison
    regression = compare_builds_soup(current_soup, baseline_soup)

    # Metrics for both
    cur_metrics = collect_metrics_soup(current_soup)
    base_metrics = collect_metrics_soup(baseline_soup)

    # Compliance matrices for both
    cur_compliance = generate_compliance_matrix_soup(current_soup)
    base_compliance = generate_compliance_matrix_soup(baseline_soup)

    # Broken link detection after diff
    old_ids = _collect_ids(baseline_soup)
    new_ids = _collect_ids(current_soup)
    broken_links = find_broken_links_after_diff(old_ids, new_ids, current_soup)

    return {
        "regression": regression,
        "metrics": {
            "current": cur_metrics,
            "baseline": base_metrics,
        },
        "compliance": {
            "current": cur_compliance,
            "baseline": base_compliance,
        },
        "metadata": {
            "current_path": str(current_path),
            "baseline_path": str(baseline_path),
        },
        "broken_links_after_diff": broken_links,
    }


def render_comparison_dashboard(data: dict) -> str:
    """Render the comparison dashboard as a standalone HTML page.

    Args:
        data: Dict from :func:`generate_spec_comparison`.

    Returns:
        Complete HTML string.
    """
    if not data:
        return "<html><body><p>No comparison data available.</p></body></html>"

    regression = data.get("regression", {})
    metrics = data.get("metrics", {})
    compliance = data.get("compliance", {})
    metadata = data.get("metadata", {})
    broken_links = data.get("broken_links_after_diff", [])

    from specbuild.analysis.regression import render_regression_summary

    reg_summary = render_regression_summary(regression)

    # Regression badge
    if regression.get("has_regressions"):
        badge = '<span class="badge badge-fail">REGRESSIONS</span>'
    else:
        badge = '<span class="badge badge-pass">PASS</span>'

    # --- Metrics comparison table ---
    cur_m = metrics.get("current", {})
    base_m = metrics.get("baseline", {})
    metric_labels = {
        "words": "Words",
        "sections": "Sections",
        "tables": "Tables",
        "figures": "Figures",
        "equations": "Equations",
        "definitions": "Definitions",
        "images": "Images",
        "links_internal": "Internal Links",
        "links_external": "External Links",
    }
    metrics_rows = ""
    for key, label in metric_labels.items():
        c = cur_m.get(key, 0)
        b = base_m.get(key, 0)
        delta = c - b
        if delta > 0:
            delta_str = f'<span class="delta-pos">+{delta:,}</span>'
        elif delta < 0:
            delta_str = f'<span class="delta-neg">{delta:,}</span>'
        else:
            delta_str = '<span class="delta-zero">0</span>'
        metrics_rows += (
            f"<tr><td>{_html.escape(label)}</td>"
            f'<td class="num">{b:,}</td>'
            f'<td class="num">{c:,}</td>'
            f'<td class="num">{delta_str}</td></tr>\n'
        )

    # --- Section changes ---
    section_rows = ""
    for sec in regression.get("sections_added", []):
        section_rows += (
            f'<tr><td class="change-added">Added</td>'
            f"<td><code>{_html.escape(sec.get('id', ''))}</code></td>"
            f"<td>{_html.escape(sec.get('title', ''))}</td>"
            f"<td>H{sec.get('level', '?')}</td></tr>\n"
        )
    for sec in regression.get("sections_removed", []):
        section_rows += (
            f'<tr><td class="change-removed">Removed</td>'
            f"<td><code>{_html.escape(sec.get('id', ''))}</code></td>"
            f"<td>{_html.escape(sec.get('title', ''))}</td>"
            f"<td>H{sec.get('level', '?')}</td></tr>\n"
        )
    for sec in regression.get("sections_renamed", []):
        section_rows += (
            f'<tr><td class="change-renamed">Renamed</td>'
            f"<td><code>{_html.escape(sec.get('id', ''))}</code></td>"
            f"<td>{_html.escape(sec.get('old_title', ''))} &rarr; "
            f"{_html.escape(sec.get('new_title', ''))}</td>"
            f"<td></td></tr>\n"
        )

    section_block = ""
    if section_rows:
        section_block = f"""
<h2>Section Changes</h2>
<table>
<thead><tr><th>Change</th><th>ID</th><th>Title</th><th>Level</th></tr></thead>
<tbody>{section_rows}</tbody>
</table>"""
    else:
        section_block = (
            '<h2>Section Changes</h2>\n<p class="muted">No section changes detected.</p>'
        )

    # --- Compliance comparison ---
    cur_comp = compliance.get("current", {})
    base_comp = compliance.get("baseline", {})
    compliance_rows = ""
    for strength in ("mandatory", "recommended", "optional"):
        c = cur_comp.get(strength, 0)
        b = base_comp.get(strength, 0)
        delta = c - b
        if delta > 0:
            delta_str = f'<span class="delta-pos">+{delta}</span>'
        elif delta < 0:
            delta_str = f'<span class="delta-neg">{delta}</span>'
        else:
            delta_str = '<span class="delta-zero">0</span>'
        compliance_rows += (
            f"<tr><td>{strength.title()}</td>"
            f'<td class="num">{b}</td>'
            f'<td class="num">{c}</td>'
            f'<td class="num">{delta_str}</td></tr>\n'
        )
    # Total row
    ct = cur_comp.get("total", 0)
    bt = base_comp.get("total", 0)
    dt = ct - bt
    if dt > 0:
        dt_str = f'<span class="delta-pos">+{dt}</span>'
    elif dt < 0:
        dt_str = f'<span class="delta-neg">{dt}</span>'
    else:
        dt_str = '<span class="delta-zero">0</span>'
    compliance_rows += (
        f'<tr class="total-row"><td><strong>Total</strong></td>'
        f'<td class="num"><strong>{bt}</strong></td>'
        f'<td class="num"><strong>{ct}</strong></td>'
        f'<td class="num"><strong>{dt_str}</strong></td></tr>\n'
    )

    # --- Broken links after diff ---
    broken_links_block = ""
    if broken_links:
        bl_rows = ""
        for lnk in broken_links:
            bl_rows += (
                f"<tr><td><code>{_html.escape(lnk.get('href', ''))}</code></td>"
                f"<td>{_html.escape(lnk.get('context', ''))}</td></tr>\n"
            )
        broken_links_block = f"""
<h2>Broken Anchor Links After Diff ({len(broken_links)})</h2>
<p class="muted">These links target IDs that existed in the baseline but were removed or renamed.</p>
<table>
<thead><tr><th>Href</th><th>Near Section</th></tr></thead>
<tbody>{bl_rows}</tbody>
</table>"""
    else:
        broken_links_block = (
            "<h2>Broken Anchor Links After Diff</h2>\n"
            '<p class="muted">No broken anchor links detected.</p>'
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Spec Version Comparison Dashboard</title>
<style>
body {{ font-family: system-ui, sans-serif; max-width: 1000px; margin: 2em auto;
       padding: 0 1em; line-height: 1.5; }}
h1 {{ font-size: 1.4em; margin-bottom: 0.3em; }}
h2 {{ font-size: 1.15em; margin-top: 2em; border-bottom: 1px solid #e5e7eb;
      padding-bottom: 0.3em; }}
.subtitle {{ color: #666; font-size: 0.88em; margin-top: 0; }}
.muted {{ color: #888; font-size: 0.9em; }}
.badge {{ padding: 3px 12px; border-radius: 4px; font-weight: 600;
          font-size: 0.85em; vertical-align: middle; }}
.badge-pass {{ background: #d1fae5; color: #065f46; }}
.badge-fail {{ background: #fee2e2; color: #991b1b; }}
table {{ border-collapse: collapse; width: 100%; font-size: 0.88em; margin: 1em 0; }}
th, td {{ padding: 6px 10px; border: 1px solid #ddd; text-align: left; }}
th {{ background: #f5f5f5; font-weight: 600; }}
td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
.total-row {{ background: #fafafa; }}
.delta-pos {{ color: #059669; font-weight: 600; }}
.delta-neg {{ color: #dc2626; font-weight: 600; }}
.delta-zero {{ color: #888; }}
.change-added {{ color: #059669; font-weight: 600; }}
.change-removed {{ color: #dc2626; font-weight: 600; }}
.change-renamed {{ color: #d97706; font-weight: 600; }}
.grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 2em; }}
@media (max-width: 700px) {{ .grid {{ grid-template-columns: 1fr; }} }}
</style>
</head>
<body>
<h1>Spec Version Comparison {badge}</h1>
<p class="subtitle">{_html.escape(reg_summary)}</p>
<p class="muted">Current: <code>{_html.escape(metadata.get("current_path", ""))}</code><br>
Baseline: <code>{_html.escape(metadata.get("baseline_path", ""))}</code></p>

<div class="grid">
<div>
<h2>Structural Metrics</h2>
<table>
<thead><tr><th>Metric</th><th style="text-align:right">Baseline</th>
<th style="text-align:right">Current</th><th style="text-align:right">Delta</th></tr></thead>
<tbody>{metrics_rows}</tbody>
</table>
</div>

<div>
<h2>Normative Statements</h2>
<table>
<thead><tr><th>Strength</th><th style="text-align:right">Baseline</th>
<th style="text-align:right">Current</th><th style="text-align:right">Delta</th></tr></thead>
<tbody>{compliance_rows}</tbody>
</table>
</div>
</div>

{section_block}

{broken_links_block}

</body>
</html>"""
