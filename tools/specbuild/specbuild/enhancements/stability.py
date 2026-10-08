"""Section stability indicator: classify sections by git change frequency.

Analyzes git history to classify each section as:

- **stable**: Unchanged for a configurable number of tags/releases
- **active**: Modified in recent commits
- **new**: Added since the last tag/release

Results can be injected as visual badges in the HTML or exported as
a summary report.
"""

from __future__ import annotations

import html as _html
import json
import logging
from pathlib import Path

from specbuild.git import run_git
from specbuild.utils import HEADING_TAGS, inject_css


def analyze_stability(
    *,
    source_dir: str = "bikeshed",
    stable_threshold: int = 3,
) -> dict:
    """Analyze section stability from git history.

    Args:
        source_dir: Directory containing ``.bs`` source files.
        stable_threshold: Number of tags with no changes to be "stable".

    Returns:
        Dict with ``sections`` (list of section stability dicts)
        and ``summary``.
    """
    # Get recent tags
    tag_output = run_git(
        "tag",
        "-l",
        "--sort=-creatordate",
        "--format=%(refname:short)",
    )
    tags = []
    if tag_output:
        tags = [t.strip() for t in tag_output.strip().splitlines() if t.strip()][
            : stable_threshold + 1
        ]

    # Get the latest tag as baseline
    baseline = tags[0] if tags else "HEAD~20"

    # Get files changed since baseline
    diff_output = run_git("diff", "--name-only", f"{baseline}..HEAD", "--", f"{source_dir}/")
    changed_files = set()
    if diff_output:
        changed_files = {f.strip() for f in diff_output.strip().splitlines() if f.strip()}

    # Get files added since baseline
    diff_status = run_git("diff", "--name-status", f"{baseline}..HEAD", "--", f"{source_dir}/")
    new_files = set()
    if diff_status:
        for line in diff_status.strip().splitlines():
            parts = line.split("\t")
            if len(parts) >= 2 and parts[0].startswith("A"):
                new_files.add(parts[1])

    # Get all .bs files
    file_list = run_git("ls-files", f"{source_dir}/*.bs")
    all_files = []
    if file_list:
        all_files = [f.strip() for f in file_list.strip().splitlines() if f.strip()]

    # For stable classification, check older tags
    stable_files = set()
    if len(tags) >= stable_threshold:
        old_tag = tags[stable_threshold - 1]
        old_diff = run_git("diff", "--name-only", f"{old_tag}..HEAD", "--", f"{source_dir}/")
        if old_diff:
            recently_changed = {f.strip() for f in old_diff.strip().splitlines() if f.strip()}
        else:
            recently_changed = set()
        stable_files = set(all_files) - recently_changed

    # Build section data
    sections: list[dict] = []
    for filepath in all_files:
        if filepath in new_files:
            status = "new"
        elif filepath in stable_files:
            status = "stable"
        elif filepath in changed_files:
            status = "active"
        else:
            status = "stable"

        # Get last commit date for this file
        date_output = run_git("log", "-1", "--format=%ci", "--", filepath)
        last_modified = ""
        if date_output:
            last_modified = date_output.strip().split()[0]

        sections.append(
            {
                "file": filepath,
                "status": status,
                "last_modified": last_modified,
            }
        )

    stable_count = sum(1 for s in sections if s["status"] == "stable")
    active_count = sum(1 for s in sections if s["status"] == "active")
    new_count = sum(1 for s in sections if s["status"] == "new")

    return {
        "sections": sections,
        "baseline": baseline,
        "summary": {
            "total": len(sections),
            "stable": stable_count,
            "active": active_count,
            "new": new_count,
        },
    }


def inject_stability_badges_soup(soup: object, stability: dict) -> bool:
    """Inject visual stability badges next to section headings.

    Args:
        soup: BeautifulSoup document (modified in place).
        stability: Stability dict from :func:`analyze_stability`.

    Returns:
        True if any badges were injected.
    """
    # Build a file-stem to status mapping
    status_map: dict[str, str] = {}
    for sec in stability.get("sections", []):
        # Extract section number from filename (e.g., "bikeshed/03_Syntax.bs" -> "03")
        fname = Path(sec["file"]).stem
        parts = fname.split("_", 1)
        if parts:
            status_map[parts[0]] = sec["status"]

    badge_css = """
.stability-badge {
    display: inline-block; font-size: 0.65em; padding: 1px 6px;
    border-radius: 3px; margin-left: 8px; vertical-align: middle;
    font-weight: 600; letter-spacing: 0.3px; text-transform: uppercase;
}
.stability-new { background: #dbeafe; color: #1d4ed8; }
.stability-active { background: #fef3c7; color: #92400e; }
.stability-stable { background: #d1fae5; color: #065f46; }
"""

    injected = False
    for heading in soup.find_all(list(HEADING_TAGS - {"h1"})):
        title = heading.get_text(strip=True)
        # Try to match by section number prefix
        for prefix, status in status_map.items():
            if status == "stable":
                continue  # Don't badge stable sections
            if title.startswith(prefix.lstrip("0") + ".") or title.startswith(prefix + "."):
                badge = soup.new_tag("span")
                badge["class"] = f"stability-badge stability-{status}"
                badge.string = status
                heading.append(badge)
                injected = True
                break

    if injected:
        inject_css(soup, "stability-badges-css", badge_css)

    return injected


def write_stability(data: dict, output_path: Path) -> None:
    """Write stability data as JSON."""
    output_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    logging.info(f"Stability data written to {output_path}")


def render_stability_html(data: dict) -> str:
    """Render stability data as an HTML page."""
    summary = data.get("summary", {})
    sections = data.get("sections", [])

    rows = ""
    for sec in sections:
        cls = f"status-{sec['status']}"
        rows += (
            f'<tr class="{cls}">'
            f"<td><code>{_html.escape(sec['file'])}</code></td>"
            f'<td><span class="badge badge-{sec["status"]}">'
            f"{_html.escape(sec['status'])}</span></td>"
            f"<td>{_html.escape(sec['last_modified'])}</td>"
            f"</tr>\n"
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Section Stability</title>
<style>
body {{ font-family: system-ui, sans-serif; max-width: 800px; margin: 2em auto; }}
h1 {{ font-size: 1.4em; }}
.summary {{ color: #666; }}
table {{ border-collapse: collapse; width: 100%; font-size: 0.88em; margin: 1em 0; }}
th, td {{ padding: 6px 10px; border: 1px solid #ddd; text-align: left; }}
th {{ background: #f5f5f5; font-weight: 600; }}
.badge {{ display: inline-block; padding: 2px 8px; border-radius: 3px;
          font-size: 0.85em; font-weight: 600; }}
.badge-stable {{ background: #d1fae5; color: #065f46; }}
.badge-active {{ background: #fef3c7; color: #92400e; }}
.badge-new {{ background: #dbeafe; color: #1d4ed8; }}
</style>
</head>
<body>
<h1>Section Stability Report</h1>
<p class="summary">Baseline: <code>{_html.escape(data.get("baseline", ""))}</code> &mdash;
{summary.get("stable", 0)} stable, {summary.get("active", 0)} active,
{summary.get("new", 0)} new</p>

<table>
<thead><tr><th>File</th><th>Status</th><th>Last Modified</th></tr></thead>
<tbody>{rows}</tbody>
</table>
</body>
</html>"""
