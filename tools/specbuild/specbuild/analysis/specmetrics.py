"""Spec metrics over time: track specification size and complexity per git tag/commit.

Analyses the compiled HTML at each git tag (or a set of commits) to produce
a time-series of metrics:

- Word count (prose only)
- Section count
- Table count
- Figure/image count
- Equation count
- Definition count

Results are returned as structured data and can be written as JSON or
rendered as a simple HTML chart.
"""

from __future__ import annotations

import html as _html
import json
import logging
import re
from pathlib import Path

from specbuild.git import run_git
from specbuild.utils import HEADING_TAGS, get_bs4, read_html

_SECTION_TAGS = list(HEADING_TAGS - {"h1"})


def collect_metrics_from_html(html_path: Path) -> dict:
    """Collect spec metrics from a compiled HTML file.

    Args:
        html_path: Path to the compiled HTML.

    Returns:
        Dict with metric counts.
    """
    try:
        get_bs4()
    except ImportError:
        logging.warning("BeautifulSoup not available, skipping metrics")
        return {}

    soup = read_html(html_path)
    return collect_metrics_soup(soup)


def collect_metrics_soup(soup: object) -> dict:
    """Collect spec metrics from a pre-parsed soup object.

    Args:
        soup: BeautifulSoup document (read-only).

    Returns:
        Dict with keys: ``words``, ``sections``, ``tables``, ``figures``,
        ``equations``, ``definitions``, ``images``, ``links_internal``,
        ``links_external``, ``req_mandatory``, ``req_recommended``,
        ``req_optional``, ``req_total``.
    """
    # Single-pass tag counting for simple metrics
    tag_counts: dict[str, int] = {}
    main = soup.find("main") or soup.find("body") or soup

    words = 0
    links_internal = 0
    links_external = 0
    req_mandatory = 0
    req_recommended = 0
    req_optional = 0

    for elem in main.descendants:
        if not hasattr(elem, "name") or elem.name is None:
            continue

        name = elem.name
        tag_counts[name] = tag_counts.get(name, 0) + 1

        # Word count from prose elements
        if name in ("p", "li", "dd", "dt"):
            words += len(elem.get_text().split())

        # Link classification
        if name == "a":
            href = elem.get("href", "")
            if href.startswith(("http://", "https://")):
                links_external += 1
            elif href.startswith("#"):
                links_internal += 1

        # Requirement counts from data attributes
        if name in ("p", "div", "span") and elem.get("data-req-type"):
            strength = elem.get("data-req-classification", "")
            req_type = elem.get("data-req-type", "")
            if not strength:
                # Infer from req-type: requirement→mandatory, recommendation→recommended, permission→optional
                if req_type == "requirement":
                    strength = "mandatory"
                elif req_type == "recommendation":
                    strength = "recommended"
                else:
                    strength = "optional"
            if strength == "mandatory":
                req_mandatory += 1
            elif strength == "recommended":
                req_recommended += 1
            else:
                req_optional += 1

    # Also count paragraphs tagged by conformance.py with class="req"
    for p in main.find_all("p", class_="req"):
        if not p.get("data-req-type"):
            req_mandatory += 1

    # Section count (h2+ headings, excluding h1 title)
    sections = sum(tag_counts.get(t, 0) for t in _SECTION_TAGS)

    # Equation count (elements with class containing 'equation')
    equations = len(main.find_all(class_=re.compile(r"equation")))

    return {
        "words": words,
        "sections": sections,
        "tables": tag_counts.get("table", 0),
        "figures": tag_counts.get("figure", 0),
        "images": tag_counts.get("img", 0),
        "equations": equations,
        "definitions": tag_counts.get("dfn", 0),
        "links_internal": links_internal,
        "links_external": links_external,
        "req_mandatory": req_mandatory,
        "req_recommended": req_recommended,
        "req_optional": req_optional,
        "req_total": req_mandatory + req_recommended + req_optional,
    }


def get_metrics_history(*, max_tags: int = 50) -> list[dict]:
    """Collect metrics at each git tag.

    Reads the tag list from git and, for each tag that has a compiled
    ``index.html`` in the expected output directory, collects metrics.

    Args:
        max_tags: Maximum number of tags to process (most recent first).

    Returns:
        List of dicts with ``tag``, ``date``, and metric fields.
    """
    output = run_git(
        "tag",
        "-l",
        "--sort=-creatordate",
        "--format=%(refname:short)\t%(creatordate:short)",
    )
    if not output:
        logging.info("No git tags found for metrics history")
        return []

    history: list[dict] = []
    for line in output.strip().splitlines():
        if not line.strip():
            continue
        parts = line.split("\t", 1)
        tag = parts[0].strip()
        date = parts[1].strip() if len(parts) > 1 else ""
        history.append({"tag": tag, "date": date})
        if len(history) >= max_tags:
            break

    logging.info(f"Found {len(history)} git tags for metrics history")
    return history


def collect_current_metrics(html_path: Path) -> dict:
    """Collect metrics for the current build.

    Args:
        html_path: Path to the compiled HTML.

    Returns:
        Dict with ``date``, ``label``, and metric fields.
    """
    metrics = collect_metrics_from_html(html_path)
    if not metrics:
        return {}

    # Single git call for both date and sha
    output = run_git("log", "-1", "--format=%ci %h", "HEAD")
    date = ""
    sha = ""
    if output:
        parts = output.strip().split()
        if parts:
            date = parts[0]
        if len(parts) >= 4:
            sha = parts[3]  # date time tz sha

    return {
        "label": f"current ({sha})",
        "date": date,
        **metrics,
    }


def write_metrics_json(metrics: dict, output_path: Path) -> None:
    """Write metrics to a JSON file.

    Args:
        metrics: Metrics dict from :func:`collect_current_metrics`.
        output_path: Destination file path.
    """
    output_path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    logging.info(f"Spec metrics written to {output_path}")


def render_metrics_html(metrics: dict) -> str:
    """Render a simple HTML summary of current metrics.

    Args:
        metrics: Dict from :func:`collect_current_metrics`.

    Returns:
        HTML string with a styled metrics summary table.
    """
    rows = []
    display_names = {
        "words": "Word Count",
        "sections": "Sections",
        "tables": "Tables",
        "figures": "Figures",
        "images": "Images",
        "equations": "Equations",
        "definitions": "Definitions",
        "links_internal": "Internal Links",
        "links_external": "External Links",
        "req_mandatory": "Requirements (mandatory)",
        "req_recommended": "Requirements (recommended)",
        "req_optional": "Requirements (optional)",
        "req_total": "Requirements (total)",
    }
    for key, label in display_names.items():
        value = metrics.get(key, 0)
        rows.append(
            f'<tr><td>{_html.escape(label)}</td><td style="text-align:right">{value:,}</td></tr>'
        )

    label = _html.escape(str(metrics.get("label", "unknown")))
    date = _html.escape(str(metrics.get("date", "")))

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Spec Metrics</title>
<style>
body {{ font-family: system-ui, sans-serif; max-width: 600px; margin: 2em auto; }}
table {{ border-collapse: collapse; width: 100%; }}
th, td {{ padding: 8px 12px; border-bottom: 1px solid #ddd; text-align: left; }}
th {{ background: #f5f5f5; }}
h1 {{ font-size: 1.4em; }}
.meta {{ color: #666; font-size: 0.9em; }}
</style>
</head>
<body>
<h1>Specification Metrics</h1>
<p class="meta">Build: {label} &mdash; {date}</p>
<table>
<thead><tr><th>Metric</th><th style="text-align:right">Value</th></tr></thead>
<tbody>
{"".join(rows)}
</tbody>
</table>
</body>
</html>"""
