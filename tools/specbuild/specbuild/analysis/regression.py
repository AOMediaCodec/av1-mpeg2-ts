"""Build regression checker: compare two HTML builds structurally.

Compares the current build output against a baseline HTML file, reporting
structural differences (sections, tables, figures, definitions, word count)
without performing a visual or textual diff.

Typical usage::

    data = compare_builds(current_path, baseline_path)
    report_regression(data)
    html = render_regression_html(data)
"""

from __future__ import annotations

import html as _html
import logging
from pathlib import Path

from specbuild.utils import HEADING_TAGS, get_bs4, read_html

# ---------------------------------------------------------------------------
# Heading extraction helper
# ---------------------------------------------------------------------------


def extract_headings(soup: object) -> list[dict]:
    """Extract all headings from *soup* in document order.

    Returns:
        List of dicts with ``id``, ``title``, ``level`` keys.
    """
    headings: list[dict] = []
    for elem in soup.find_all(list(HEADING_TAGS)):
        level = int(elem.name[1])
        headings.append(
            {
                "id": elem.get("id", ""),
                "title": elem.get_text(strip=True),
                "level": level,
            }
        )
    return headings


# ---------------------------------------------------------------------------
# Element / word counting
# ---------------------------------------------------------------------------


def count_elements(soup: object) -> dict[str, int]:
    """Count structural elements and words in *soup*.

    Returns:
        Dict with ``tables``, ``figures``, ``definitions``, ``images``,
        ``words``.
    """
    main = soup.find("main") or soup.find("body") or soup

    words = 0
    tables = 0
    figures = 0
    definitions = 0
    images = 0

    for elem in main.descendants:
        if not hasattr(elem, "name") or elem.name is None:
            continue

        name = elem.name
        if name == "table":
            tables += 1
        elif name == "figure":
            figures += 1
        elif name == "dfn":
            definitions += 1
        elif name == "img":
            images += 1

        if name in ("p", "li", "dd", "dt"):
            words += len(elem.get_text().split())

    return {
        "tables": tables,
        "figures": figures,
        "definitions": definitions,
        "images": images,
        "words": words,
    }


# ---------------------------------------------------------------------------
# Core comparison (soup-based)
# ---------------------------------------------------------------------------


def compare_builds_soup(current_soup: object, baseline_soup: object) -> dict:
    """Compare two parsed HTML documents structurally.

    Args:
        current_soup: BeautifulSoup document for the current build.
        baseline_soup: BeautifulSoup document for the baseline build.

    Returns:
        Dict with ``sections_added``, ``sections_removed``,
        ``sections_renamed``, ``counts``, and ``has_regressions``.
    """
    # --- Headings ---
    cur_headings = extract_headings(current_soup)
    base_headings = extract_headings(baseline_soup)

    cur_by_id: dict[str, dict] = {}
    for h in cur_headings:
        if h["id"]:
            cur_by_id[h["id"]] = h

    base_by_id: dict[str, dict] = {}
    for h in base_headings:
        if h["id"]:
            base_by_id[h["id"]] = h

    cur_ids = set(cur_by_id.keys())
    base_ids = set(base_by_id.keys())

    sections_added = [
        cur_by_id[h["id"]] for h in cur_headings if h["id"] and h["id"] in (cur_ids - base_ids)
    ]
    sections_removed = [
        base_by_id[h["id"]] for h in base_headings if h["id"] and h["id"] in (base_ids - cur_ids)
    ]

    sections_renamed: list[dict] = []
    for sid in cur_ids & base_ids:
        cur_title = cur_by_id[sid]["title"]
        base_title = base_by_id[sid]["title"]
        if cur_title != base_title:
            sections_renamed.append(
                {
                    "id": sid,
                    "old_title": base_title,
                    "new_title": cur_title,
                }
            )

    # --- Element counts ---
    cur_counts = count_elements(current_soup)
    base_counts = count_elements(baseline_soup)

    counts: dict[str, dict[str, int]] = {}
    for key in ("tables", "figures", "definitions", "images", "words"):
        c = cur_counts[key]
        b = base_counts[key]
        counts[key] = {"current": c, "baseline": b, "delta": c - b}

    # --- Regression flag ---
    has_regressions = len(sections_removed) > 0 or counts["definitions"]["delta"] < 0

    return {
        "sections_added": sections_added,
        "sections_removed": sections_removed,
        "sections_renamed": sections_renamed,
        "counts": counts,
        "has_regressions": has_regressions,
    }


# ---------------------------------------------------------------------------
# File-based wrapper
# ---------------------------------------------------------------------------


def compare_builds(current_path: Path, baseline_path: Path) -> dict:
    """Compare two HTML build files structurally.

    Args:
        current_path: Path to the current build HTML.
        baseline_path: Path to the baseline HTML.

    Returns:
        Dict from :func:`compare_builds_soup`.
    """
    try:
        get_bs4()
    except ImportError:
        logging.warning("BeautifulSoup not available, skipping regression check")
        return {
            "sections_added": [],
            "sections_removed": [],
            "sections_renamed": [],
            "counts": {},
            "has_regressions": False,
        }

    logging.info(f"Comparing builds: {current_path.name} vs {baseline_path.name}")
    try:
        current_soup = read_html(current_path)
        baseline_soup = read_html(baseline_path)
    except (FileNotFoundError, OSError) as exc:
        logging.error(f"Regression check failed: {exc}")
        return {
            "sections_added": [],
            "sections_removed": [],
            "sections_renamed": [],
            "counts": {},
            "has_regressions": False,
        }
    return compare_builds_soup(current_soup, baseline_soup)


# ---------------------------------------------------------------------------
# Summary renderer (one-line)
# ---------------------------------------------------------------------------


def render_regression_summary(data: dict) -> str:
    """Render a single-line summary of regression results.

    Args:
        data: Dict from :func:`compare_builds_soup`.

    Returns:
        Human-readable one-line summary string.
    """
    parts: list[str] = []

    n_added = len(data.get("sections_added", []))
    n_removed = len(data.get("sections_removed", []))
    n_renamed = len(data.get("sections_renamed", []))

    if n_added:
        parts.append(f"{n_added} section{'s' if n_added != 1 else ''} added")
    if n_removed:
        parts.append(f"{n_removed} removed")
    if n_renamed:
        parts.append(f"{n_renamed} renamed")

    counts = data.get("counts", {})
    for key in ("tables", "figures", "definitions", "images", "words"):
        delta = counts.get(key, {}).get("delta", 0)
        if delta != 0:
            sign = "+" if delta > 0 else ""
            parts.append(f"{sign}{delta:,} {key}")

    return ", ".join(parts) if parts else "no structural changes"


# ---------------------------------------------------------------------------
# Report logger
# ---------------------------------------------------------------------------


def report_regression(data: dict, *, strict: bool = False) -> None:
    """Log regression findings; exit with error in strict mode if regressions found.

    Args:
        data: Dict from :func:`compare_builds_soup`.
        strict: If True, raise :class:`SystemExit` when regressions are detected.
    """
    summary = render_regression_summary(data)

    if data.get("has_regressions"):
        logging.warning(f"Build regression detected: {summary}")
        for sec in data.get("sections_removed", []):
            logging.warning(f"  Section removed: [{sec['id']}] {sec['title']}")
        defn_delta = data.get("counts", {}).get("definitions", {}).get("delta", 0)
        if defn_delta < 0:
            logging.warning(f"  Definitions decreased by {abs(defn_delta)}")
        if strict:
            raise SystemExit(1)
    else:
        logging.info(f"Regression check passed: {summary}")

    for sec in data.get("sections_added", []):
        logging.info(f"  Section added: [{sec['id']}] {sec['title']}")
    for sec in data.get("sections_renamed", []):
        logging.info(
            f'  Section renamed: [{sec["id"]}] "{sec["old_title"]}" -> "{sec["new_title"]}"'
        )


# ---------------------------------------------------------------------------
# HTML renderer
# ---------------------------------------------------------------------------


def _delta_cell(delta: int) -> str:
    """Format a delta value as a styled table cell."""
    if delta > 0:
        color = "#2a7f2a"
        text = f"+{delta:,}"
    elif delta < 0:
        color = "#c0392b"
        text = f"{delta:,}"
    else:
        color = "#888"
        text = "0"
    return f'<td style="text-align:right;color:{color};font-weight:600">{text}</td>'


def render_regression_html(data: dict) -> str:
    """Render regression comparison results as a standalone HTML page.

    Args:
        data: Dict from :func:`compare_builds_soup`.

    Returns:
        Complete HTML string.
    """
    # --- Section changes table ---
    section_rows = ""
    for sec in data.get("sections_added", []):
        section_rows += (
            f"<tr>"
            f'<td style="color:#2a7f2a;font-weight:600">Added</td>'
            f"<td>{_html.escape(sec['id'])}</td>"
            f"<td>{_html.escape(sec['title'])}</td>"
            f"<td>H{sec['level']}</td>"
            f"</tr>\n"
        )
    for sec in data.get("sections_removed", []):
        section_rows += (
            f"<tr>"
            f'<td style="color:#c0392b;font-weight:600">Removed</td>'
            f"<td>{_html.escape(sec['id'])}</td>"
            f"<td>{_html.escape(sec['title'])}</td>"
            f"<td>H{sec['level']}</td>"
            f"</tr>\n"
        )
    for sec in data.get("sections_renamed", []):
        section_rows += (
            f"<tr>"
            f'<td style="color:#d4a017;font-weight:600">Renamed</td>'
            f"<td>{_html.escape(sec['id'])}</td>"
            f"<td>{_html.escape(sec['old_title'])} &rarr; "
            f"{_html.escape(sec['new_title'])}</td>"
            f"<td></td>"
            f"</tr>\n"
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
        section_block = '<h2>Section Changes</h2>\n<p class="summary">No section changes.</p>'

    # --- Counts table ---
    display_names = {
        "tables": "Tables",
        "figures": "Figures",
        "definitions": "Definitions",
        "images": "Images",
        "words": "Words",
    }
    count_rows = ""
    counts = data.get("counts", {})
    for key, label in display_names.items():
        entry = counts.get(key, {"current": 0, "baseline": 0, "delta": 0})
        count_rows += (
            f"<tr>"
            f"<td>{_html.escape(label)}</td>"
            f'<td style="text-align:right">{entry["baseline"]:,}</td>'
            f'<td style="text-align:right">{entry["current"]:,}</td>'
            f"{_delta_cell(entry['delta'])}"
            f"</tr>\n"
        )

    # --- Regression badge ---
    if data.get("has_regressions"):
        badge = '<span style="background:#c0392b;color:#fff;padding:3px 10px;border-radius:4px;font-weight:600">REGRESSIONS DETECTED</span>'
    else:
        badge = '<span style="background:#2a7f2a;color:#fff;padding:3px 10px;border-radius:4px;font-weight:600">PASS</span>'

    summary = _html.escape(render_regression_summary(data))

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Build Regression Report</title>
<style>
body {{ font-family: system-ui, sans-serif; max-width: 900px; margin: 2em auto; }}
h1 {{ font-size: 1.4em; }}
h2 {{ font-size: 1.15em; margin-top: 1.5em; }}
.summary {{ color: #666; font-size: 0.9em; }}
table {{ border-collapse: collapse; width: 100%; font-size: 0.88em; margin: 1em 0; }}
th, td {{ padding: 6px 10px; border: 1px solid #ddd; text-align: left; }}
th {{ background: #f5f5f5; font-weight: 600; }}
.badge {{ margin-left: 1em; }}
</style>
</head>
<body>
<h1>Build Regression Report <span class="badge">{badge}</span></h1>
<p class="summary">{summary}</p>

{section_block}

<h2>Structural Element Counts</h2>
<table>
<thead><tr><th>Element</th><th style="text-align:right">Baseline</th><th style="text-align:right">Current</th><th style="text-align:right">Delta</th></tr></thead>
<tbody>{count_rows}</tbody>
</table>
</body>
</html>"""
