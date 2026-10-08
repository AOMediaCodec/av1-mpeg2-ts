"""Baseline snapshot for build regression checking.

Saves a structural fingerprint of a build to JSON so that future builds
can be compared without keeping the full baseline HTML around.

Usage::

    # Save baseline after a known-good build
    save_baseline(html_path)

    # Compare current build against saved baseline
    data = compare_with_baseline(html_path)
    from specbuild.analysis.regression import report_regression
    report_regression(data)
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from specbuild.git import run_git

#: Default baseline file name (in project root).
DEFAULT_BASELINE = ".specbuild_baseline.json"


def _empty_regression_result() -> dict:
    """Return an empty regression comparison result."""
    return {
        "sections_added": [],
        "sections_removed": [],
        "sections_renamed": [],
        "counts": {},
        "has_regressions": False,
    }


def save_baseline(
    html_path: Path,
    output_path: Path | None = None,
) -> Path:
    """Save a structural baseline snapshot of *html_path* to JSON.

    Args:
        html_path: Path to the compiled HTML file.
        output_path: Where to write the JSON.  Defaults to
            :data:`DEFAULT_BASELINE` in the current directory.

    Returns:
        The path the baseline was written to.
    """
    from specbuild.analysis.regression import count_elements, extract_headings
    from specbuild.utils import get_bs4, read_html

    try:
        get_bs4()
    except ImportError:
        logging.error("BeautifulSoup required for baseline snapshots")
        raise SystemExit(1)

    soup = read_html(html_path)
    headings = extract_headings(soup)
    counts = count_elements(soup)

    # Git metadata
    branch = (run_git("rev-parse", "--abbrev-ref", "HEAD") or "").strip()
    sha = (run_git("rev-parse", "--short", "HEAD") or "").strip()

    data = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "branch": branch,
        "sha": sha,
        "source": str(html_path),
        "headings": headings,
        "counts": counts,
    }

    if output_path is None:
        output_path = Path(DEFAULT_BASELINE)

    output_path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    logging.info(
        f"Baseline saved to {output_path} ({branch}@{sha}, {counts.get('words', 0):,} words)"
    )
    return output_path


def load_baseline(path: Path | None = None) -> dict | None:
    """Load a previously saved baseline snapshot.

    Args:
        path: Path to the JSON file.  Defaults to :data:`DEFAULT_BASELINE`.

    Returns:
        Parsed baseline dict, or ``None`` if the file does not exist.
    """
    if path is None:
        path = Path(DEFAULT_BASELINE)

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        logging.warning(f"Baseline file not found: {path}")
        return None

    logging.info(
        f"Loaded baseline from {path} "
        f"({data.get('branch', '?')}@{data.get('sha', '?')}, "
        f"saved {data.get('timestamp', '?')})"
    )
    return data


def compare_with_baseline(
    html_path: Path,
    baseline_path: Path | None = None,
) -> dict:
    """Compare the current build against a saved baseline snapshot.

    Args:
        html_path: Path to the current build HTML.
        baseline_path: Path to the baseline JSON.  Defaults to
            :data:`DEFAULT_BASELINE`.

    Returns:
        Dict compatible with :func:`specbuild.regression.compare_builds_soup`
        (``sections_added``, ``sections_removed``, ``sections_renamed``,
        ``counts``, ``has_regressions``).
    """
    from specbuild.analysis.regression import count_elements, extract_headings
    from specbuild.utils import get_bs4, read_html

    baseline = load_baseline(baseline_path)
    if baseline is None:
        logging.warning("No baseline available — skipping regression check")
        return _empty_regression_result()

    try:
        get_bs4()
    except ImportError:
        logging.warning("BeautifulSoup not available — skipping regression check")
        return _empty_regression_result()

    soup = read_html(html_path)
    cur_headings = extract_headings(soup)
    cur_counts = count_elements(soup)

    base_headings = baseline.get("headings", [])
    base_counts = baseline.get("counts", {})

    # --- Heading comparison ---
    cur_by_id: dict[str, dict] = {}
    for h in cur_headings:
        if h.get("id"):
            cur_by_id[h["id"]] = h

    base_by_id: dict[str, dict] = {}
    for h in base_headings:
        if h.get("id"):
            base_by_id[h["id"]] = h

    cur_ids = set(cur_by_id.keys())
    base_ids = set(base_by_id.keys())

    sections_added = [cur_by_id[hid] for hid in cur_ids - base_ids]
    sections_removed = [base_by_id[hid] for hid in base_ids - cur_ids]

    sections_renamed: list[dict] = []
    for sid in cur_ids & base_ids:
        cur_title = cur_by_id[sid]["title"]
        base_title = base_by_id[sid].get("title", "")
        if cur_title != base_title:
            sections_renamed.append(
                {
                    "id": sid,
                    "old_title": base_title,
                    "new_title": cur_title,
                }
            )

    # --- Element counts ---
    count_keys = ("tables", "figures", "definitions", "images", "words")
    counts: dict[str, dict[str, int]] = {}
    for key in count_keys:
        c = cur_counts.get(key, 0)
        b = base_counts.get(key, 0)
        counts[key] = {"current": c, "baseline": b, "delta": c - b}

    # --- Regression flag ---
    has_regressions = len(sections_removed) > 0 or counts.get("definitions", {}).get("delta", 0) < 0

    return {
        "sections_added": sections_added,
        "sections_removed": sections_removed,
        "sections_renamed": sections_renamed,
        "counts": counts,
        "has_regressions": has_regressions,
    }
