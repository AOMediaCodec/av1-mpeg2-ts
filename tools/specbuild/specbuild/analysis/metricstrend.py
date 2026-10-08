"""Spec metrics trend analysis.

Compares current build metrics against the saved baseline to detect
significant growth, shrinkage, or complexity changes.  Generates a
health report with per-section deltas and warnings for sections that
are growing disproportionately.
"""

from __future__ import annotations

import html as _html
import logging
from pathlib import Path

from specbuild.analysis.specmetrics import collect_metrics_soup
from specbuild.utils import HEADING_TAGS, get_bs4, read_html, write_json

# Threshold (fraction) above which a section is flagged as "fast-growing".
_GROWTH_WARNING_THRESHOLD = 0.20  # 20%

# Minimum word count for a section to be eligible for growth warnings.
_MIN_WORDS_FOR_WARNING = 50


def generate_metrics_trend(
    html_path: Path, baseline_path: Path | None = None, *, soup: object = None
) -> dict:
    """Compare current metrics against baseline.

    If *baseline_path* is provided, reads section-level metrics from that
    HTML file and computes deltas.  If no baseline is available, returns
    only the current metrics with empty deltas.

    Args:
        html_path: Path to the current build's HTML.
        baseline_path: Path to a previous build's HTML (optional).

    Returns:
        Dict with ``current``, ``baseline`` (if available),
        ``section_deltas``, and ``warnings``.
    """
    try:
        get_bs4()
    except ImportError:
        logging.warning("BeautifulSoup not available, skipping metrics trend")
        return {}

    current_soup = soup if soup is not None else read_html(html_path)
    current_metrics = collect_metrics_soup(current_soup)
    current_sections = _collect_section_metrics(current_soup)

    baseline_metrics: dict = {}
    baseline_sections: dict[str, dict] = {}
    if baseline_path:
        try:
            baseline_soup = read_html(baseline_path)
            baseline_metrics = collect_metrics_soup(baseline_soup)
            baseline_sections = _collect_section_metrics(baseline_soup)
        except FileNotFoundError:
            logging.warning(f"Baseline file not found: {baseline_path}")
        except OSError as exc:
            logging.warning(f"Could not read baseline {baseline_path}: {exc}")
        except Exception as exc:
            logging.warning(
                f"Could not parse baseline {baseline_path}: {type(exc).__name__}: {exc}"
            )

    # Compute section-level deltas
    section_deltas = _compute_section_deltas(current_sections, baseline_sections)

    # Generate warnings
    warnings = _generate_warnings(section_deltas, current_metrics, baseline_metrics)

    return {
        "current": current_metrics,
        "baseline": baseline_metrics,
        "current_sections": current_sections,
        "baseline_sections": baseline_sections,
        "section_deltas": section_deltas,
        "warnings": warnings,
        "has_baseline": bool(baseline_metrics),
    }


def _collect_section_metrics(soup: object) -> dict[str, dict]:
    """Collect per-section word counts and element counts.

    Args:
        soup: BeautifulSoup document.

    Returns:
        Dict mapping section ID → {title, words, tables, figures, definitions}.
    """
    sections: dict[str, dict] = {}

    for heading in soup.find_all(list(HEADING_TAGS - {"h1"})):
        section_id = heading.get("id", "")
        if not section_id:
            continue

        title = heading.get_text().strip()
        words = 0
        tables = 0
        figures = 0
        definitions = 0

        # Walk siblings until the next heading of same or higher level.
        # Stop at ANY heading to give EXCLUSIVE per-section counts: only the
        # text directly under this heading, not text from sub-sections.
        # Previously `sib_level <= level` continued through sub-headings,
        # causing h3 text to be counted in both h2's and h3's totals.
        level = int(heading.name[1])
        for sibling in heading.find_next_siblings():
            if sibling.name and sibling.name in HEADING_TAGS:
                sib_level = int(sibling.name[1])
                if sib_level <= level:
                    break
                # Deeper heading: stop counting for this section (exclusive).
                break

            if hasattr(sibling, "get_text"):
                words += len(sibling.get_text().split())
            if sibling.name == "table":
                tables += 1
            elif sibling.name == "figure":
                figures += 1
            if hasattr(sibling, "find_all"):
                definitions += len(sibling.find_all("dfn"))

        sections[section_id] = {
            "title": title,
            "words": words,
            "tables": tables,
            "figures": figures,
            "definitions": definitions,
        }

    return sections


def _compute_section_deltas(
    current: dict[str, dict],
    baseline: dict[str, dict],
) -> list[dict]:
    """Compute per-section metric deltas between current and baseline."""
    deltas = []
    all_ids = sorted(set(current.keys()) | set(baseline.keys()))

    for sid in all_ids:
        cur = current.get(sid)
        base = baseline.get(sid)

        if cur and not base:
            deltas.append(
                {
                    "id": sid,
                    "title": cur["title"],
                    "status": "new",
                    "words_current": cur["words"],
                    "words_baseline": 0,
                    "words_delta": cur["words"],
                    "words_pct": None,
                }
            )
        elif base and not cur:
            deltas.append(
                {
                    "id": sid,
                    "title": base["title"],
                    "status": "removed",
                    "words_current": 0,
                    "words_baseline": base["words"],
                    "words_delta": -base["words"],
                    "words_pct": None,
                }
            )
        elif cur and base:
            delta = cur["words"] - base["words"]
            pct = (delta / base["words"] * 100) if base["words"] > 0 else None
            deltas.append(
                {
                    "id": sid,
                    "title": cur["title"],
                    "status": "changed" if delta != 0 else "unchanged",
                    "words_current": cur["words"],
                    "words_baseline": base["words"],
                    "words_delta": delta,
                    "words_pct": round(pct, 1) if pct is not None else None,
                }
            )

    return deltas


def _generate_warnings(
    section_deltas: list[dict],
    current_metrics: dict,
    baseline_metrics: dict,
) -> list[dict]:
    """Generate health warnings based on metric deltas."""
    warnings: list[dict] = []

    # Overall word count change
    cur_words = current_metrics.get("words", 0)
    base_words = baseline_metrics.get("words", 0)
    if base_words > 0:
        overall_pct = (cur_words - base_words) / base_words
        if overall_pct > _GROWTH_WARNING_THRESHOLD:
            warnings.append(
                {
                    "level": "warning",
                    "message": (
                        f"Overall spec grew {overall_pct:.0%} "
                        f"({base_words:,} → {cur_words:,} words)"
                    ),
                }
            )

    # Per-section growth warnings
    for delta in section_deltas:
        if delta["status"] == "new":
            if delta["words_current"] > _MIN_WORDS_FOR_WARNING:
                warnings.append(
                    {
                        "level": "info",
                        "section": delta["id"],
                        "message": f"New section: {delta['title']} ({delta['words_current']:,} words)",
                    }
                )
        elif delta["words_pct"] is not None and delta["words_baseline"] >= _MIN_WORDS_FOR_WARNING:
            if delta["words_pct"] > _GROWTH_WARNING_THRESHOLD * 100:
                warnings.append(
                    {
                        "level": "warning",
                        "section": delta["id"],
                        "message": (
                            f"Section '{delta['title']}' grew {delta['words_pct']:.0f}% "
                            f"({delta['words_baseline']:,} → {delta['words_current']:,} words)"
                        ),
                    }
                )

    return warnings


def write_metrics_trend_json(data: dict, output_path: Path) -> None:
    """Write metrics trend data as JSON."""
    write_json(data, output_path, label="Metrics trend")


def render_metrics_trend_html(data: dict) -> str:
    """Render metrics trend as an HTML health report."""
    current = data.get("current", {})
    baseline = data.get("baseline", {})
    warnings = data.get("warnings", [])
    deltas = data.get("section_deltas", [])
    has_baseline = data.get("has_baseline", False)

    # Warnings section
    warning_html = ""
    if warnings:
        for w in warnings:
            level = w.get("level", "info")
            icon = "!!" if level == "warning" else "i"
            warning_html += (
                f'<div class="alert alert-{level}">'
                f"<strong>[{icon}]</strong> {_html.escape(w['message'])}"
                f"</div>\n"
            )
    else:
        warning_html = '<div class="alert alert-ok"><strong>[OK]</strong> No warnings</div>'

    # Overall metrics comparison
    metrics_html = ""
    if has_baseline:
        for key in ("words", "sections", "tables", "figures", "definitions"):
            cur_val = current.get(key, 0)
            base_val = baseline.get(key, 0)
            delta = cur_val - base_val
            sign = "+" if delta > 0 else ""
            cls = "delta-pos" if delta > 0 else "delta-neg" if delta < 0 else ""
            metrics_html += (
                f"<tr><td>{key.title()}</td>"
                f"<td>{base_val:,}</td>"
                f"<td>{cur_val:,}</td>"
                f'<td class="{cls}">{sign}{delta:,}</td></tr>\n'
            )

    # Section deltas table (changed sections only, sorted by absolute delta)
    changed = [d for d in deltas if d["status"] != "unchanged"]
    changed.sort(key=lambda d: abs(d["words_delta"]), reverse=True)

    section_rows = ""
    for d in changed[:50]:
        status_cls = f"status-{d['status']}"
        pct = f"{d['words_pct']:+.0f}%" if d["words_pct"] is not None else "—"
        delta_sign = "+" if d["words_delta"] > 0 else ""
        section_rows += (
            f'<tr class="{status_cls}">'
            f"<td>{_html.escape(d['title'][:60])}</td>"
            f"<td>{d['status']}</td>"
            f"<td>{d['words_baseline']:,}</td>"
            f"<td>{d['words_current']:,}</td>"
            f"<td>{delta_sign}{d['words_delta']:,}</td>"
            f"<td>{pct}</td>"
            f"</tr>\n"
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Spec Health Report</title>
<style>
body {{ font-family: system-ui, sans-serif; max-width: 1000px; margin: 2em auto; }}
h1 {{ font-size: 1.4em; }}
h2 {{ font-size: 1.15em; margin-top: 1.5em; }}
.alert {{ padding: 8px 14px; border-radius: 6px; margin: 4px 0; }}
.alert-warning {{ background: #fef3c7; border: 1px solid #fcd34d; }}
.alert-info {{ background: #dbeafe; border: 1px solid #93c5fd; }}
.alert-ok {{ background: #d1fae5; border: 1px solid #6ee7b7; }}
table {{ border-collapse: collapse; width: 100%; font-size: 0.88em; margin: 1em 0; }}
th, td {{ padding: 6px 10px; border: 1px solid #ddd; text-align: left; }}
th {{ background: #f5f5f5; font-weight: 600; }}
.delta-pos {{ color: #dc2626; }}
.delta-neg {{ color: #059669; }}
.status-new td:nth-child(2) {{ color: #2563eb; font-weight: 600; }}
.status-removed td:nth-child(2) {{ color: #dc2626; font-weight: 600; }}
</style>
</head>
<body>
<h1>Specification Health Report</h1>

<h2>Warnings</h2>
{warning_html}

{"<h2>Overall Metrics</h2>" if has_baseline else "<p><em>No baseline available for comparison.</em></p>"}
{"<table><thead><tr><th>Metric</th><th>Baseline</th><th>Current</th><th>Delta</th></tr></thead><tbody>" + metrics_html + "</tbody></table>" if has_baseline else ""}

<h2>Section Changes</h2>
{"<table><thead><tr><th>Section</th><th>Status</th><th>Baseline</th><th>Current</th><th>Delta</th><th>%</th></tr></thead><tbody>" + section_rows + "</tbody></table>" if section_rows else "<p>No section-level changes detected.</p>"}
</body>
</html>"""
