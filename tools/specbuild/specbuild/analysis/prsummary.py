"""PR summary generator: produce structured PR descriptions from spec changes.

Analyses the git diff between the current branch and a baseline (typically
``main``) to build a PR-ready summary covering:

- Commit list and file-level changes
- Section heading additions/removals
- Normative keyword (RFC 2119) changes
- Definition (``<dfn>``) additions/removals
- Overall insertion/deletion statistics

Output is available as a structured dict, Markdown text, or a standalone
HTML page.
"""

from __future__ import annotations

import html as _html
import logging
import re
from pathlib import Path

from specbuild.config import CONFIG
from specbuild.git import run_git

# ---------------------------------------------------------------------------
# Diff-analysis patterns
# ---------------------------------------------------------------------------

_HEADING_RE = re.compile(r"^#{1,6}\s+(.+)$", re.MULTILINE)
_HTML_HEADING_RE = re.compile(r"<h[1-6][^>]*>\s*(.+?)\s*</h[1-6]>", re.IGNORECASE)
_DFN_RE = re.compile(r"<dfn[^>]*>\s*(.+?)\s*</dfn>", re.IGNORECASE)
_NORMATIVE_RE = re.compile(
    r"\b(MUST(?:\s+NOT)?|SHALL(?:\s+NOT)?|SHOULD(?:\s+NOT)?"
    r"|MAY|REQUIRED|RECOMMENDED|OPTIONAL)\b"
)

_STATUS_MAP = {"M": "Modified", "A": "Added", "D": "Deleted", "R": "Renamed"}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_pr_summary(
    base_branch: str = None,
    *,
    html_path: Path | None = None,
) -> dict:
    """Generate a structured PR summary for the current branch.

    Args:
        base_branch: Git ref to compare against.  Defaults to
            ``CONFIG.main_branch``.
        html_path: If provided, the standalone HTML report is written to
            this path as a side effect.

    Returns:
        Dict with PR summary data (see module docstring for schema).
    """
    if base_branch is None:
        base_branch = CONFIG.main_branch

    result: dict = {
        "base_branch": base_branch,
        "current_branch": "",
        "commit_count": 0,
        "commits": [],
        "files_changed": [],
        "sections_changed": [],
        "normative_changes": {"added": 0, "removed": 0},
        "definition_changes": {"added": [], "removed": []},
        "stats": {"insertions": 0, "deletions": 0, "files": 0},
    }

    # Current branch name
    current = run_git("rev-parse", "--abbrev-ref", "HEAD")
    if current is None:
        logging.warning("Could not determine current branch")
        return result
    result["current_branch"] = current.strip()

    # Same branch guard
    if result["current_branch"] == base_branch:
        logging.info("Current branch is the same as base branch; nothing to summarise")
        return result

    # Commit count
    count_str = run_git("rev-list", "--count", f"{base_branch}..HEAD")
    if count_str is not None:
        try:
            result["commit_count"] = int(count_str.strip())
        except ValueError:
            pass

    # File-level changes
    file_status = run_git(
        "diff",
        "--name-status",
        base_branch,
        "--",
        CONFIG.bikeshed_dir,
    )
    if file_status:
        result["files_changed"] = _parse_file_status(file_status)
        result["stats"]["files"] = len(result["files_changed"])

    # Combined diff for content analysis
    diff_text = run_git("diff", "-U0", base_branch, "--", CONFIG.bikeshed_dir)
    if diff_text:
        analysis = _analyze_diff(diff_text)
        result["stats"]["insertions"] = analysis["insertions"]
        result["stats"]["deletions"] = analysis["deletions"]
        result["sections_changed"] = analysis["sections"]
        result["normative_changes"] = analysis["normative"]
        result["definition_changes"] = analysis["definitions"]

    # Commit messages
    log_output = run_git("log", "--oneline", f"{base_branch}..HEAD")
    if log_output:
        result["commits"] = [line for line in log_output.strip().splitlines() if line.strip()]

    logging.info(
        f"PR summary: {result['commit_count']} commit(s), "
        f"{result['stats']['files']} file(s) changed, "
        f"+{result['stats']['insertions']}/-{result['stats']['deletions']}"
    )

    # Optional HTML side-effect
    if html_path is not None:
        html_path.write_text(render_pr_summary_html(result), encoding="utf-8")
        logging.info(f"PR summary HTML written to {html_path}")

    return result


def render_pr_summary_markdown(data: dict) -> str:
    """Render PR summary data as Markdown suitable for a PR description.

    Args:
        data: Dict returned by :func:`generate_pr_summary`.

    Returns:
        Markdown string.
    """
    lines: list[str] = []

    current = data.get("current_branch", "?")
    base = data.get("base_branch", "?")
    commits = data.get("commit_count", 0)
    stats = data.get("stats", {})
    files = stats.get("files", 0)

    # Summary
    lines.append("## Summary")
    lines.append(f"{current} \u2192 {base} | {commits} commits | {files} files changed")
    lines.append("")

    # Changes overview
    sections = data.get("sections_changed", [])
    sec_added = sum(1 for s in sections if s["change"] == "added")
    sec_removed = sum(1 for s in sections if s["change"] == "removed")
    normative = data.get("normative_changes", {})
    norm_added = normative.get("added", 0)
    norm_removed = normative.get("removed", 0)
    dfn = data.get("definition_changes", {})
    dfn_added = dfn.get("added", [])
    dfn_removed = dfn.get("removed", [])
    insertions = stats.get("insertions", 0)
    deletions = stats.get("deletions", 0)

    lines.append("## Changes")
    lines.append(f"- **Sections**: {sec_added} added, {sec_removed} removed")
    lines.append(f"- **Normative statements**: +{norm_added} added, -{norm_removed} removed")
    lines.append(f"- **Definitions**: {len(dfn_added)} new, {len(dfn_removed)} removed")
    lines.append(f"- **Lines**: +{insertions} / -{deletions}")
    lines.append("")

    # Section changes
    if sections:
        lines.append("## Section Changes")
        for sec in sections:
            marker = "+" if sec["change"] == "added" else "-"
            lines.append(f"- [{marker}] {sec['heading']}")
        lines.append("")

    # Definition changes
    if dfn_added or dfn_removed:
        lines.append("## Definition Changes")
        if dfn_added:
            bold = ", ".join(f"**{t}**" for t in dfn_added)
            lines.append(f"- Added: {bold}")
        if dfn_removed:
            bold = ", ".join(f"**{t}**" for t in dfn_removed)
            lines.append(f"- Removed: {bold}")
        lines.append("")

    # Commits
    if data.get("commits"):
        lines.append("## Commits")
        for c in data["commits"]:
            lines.append(f"- {c}")
        lines.append("")

    # Files changed
    if data.get("files_changed"):
        lines.append("## Files Changed")
        for f in data["files_changed"]:
            label = _STATUS_MAP.get(f.get("status", "M"), f.get("status", "?"))
            lines.append(f"- `{f['path']}` ({label})")
        lines.append("")

    return "\n".join(lines)


def render_pr_summary_html(data: dict) -> str:
    """Render PR summary data as a standalone HTML page.

    Args:
        data: Dict returned by :func:`generate_pr_summary`.

    Returns:
        Complete HTML document string.
    """
    e = _html.escape  # convenience alias

    current = e(data.get("current_branch", "?"))
    base = e(data.get("base_branch", "?"))
    commits = data.get("commit_count", 0)
    stats = data.get("stats", {})
    files = stats.get("files", 0)
    insertions = stats.get("insertions", 0)
    deletions = stats.get("deletions", 0)

    sections = data.get("sections_changed", [])
    sec_added = sum(1 for s in sections if s["change"] == "added")
    sec_removed = sum(1 for s in sections if s["change"] == "removed")
    normative = data.get("normative_changes", {})
    norm_added = normative.get("added", 0)
    norm_removed = normative.get("removed", 0)
    dfn = data.get("definition_changes", {})
    dfn_added = dfn.get("added", [])
    dfn_removed = dfn.get("removed", [])

    # Build HTML fragments
    section_rows = ""
    for sec in sections:
        cls = "added" if sec["change"] == "added" else "removed"
        marker = "+" if sec["change"] == "added" else "\u2212"
        section_rows += f'<tr class="{cls}"><td>{marker}</td><td>{e(sec["heading"])}</td></tr>\n'

    dfn_added_html = ", ".join(f"<strong>{e(t)}</strong>" for t in dfn_added)
    dfn_removed_html = ", ".join(f"<strong>{e(t)}</strong>" for t in dfn_removed)

    commit_rows = ""
    for c in data.get("commits", []):
        commit_rows += f"<li>{e(c)}</li>\n"

    file_rows = ""
    for f in data.get("files_changed", []):
        label = _STATUS_MAP.get(f.get("status", "M"), f.get("status", "?"))
        file_rows += f"<tr><td><code>{e(f['path'])}</code></td><td>{e(label)}</td></tr>\n"

    return f"""\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PR Summary: {current} &rarr; {base}</title>
<style>
  :root {{
    --bg: #fff; --fg: #1a1a1a; --accent: #0057b7;
    --green: #22863a; --red: #cb2431; --border: #d0d7de;
    --subtle-bg: #f6f8fa;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{
      --bg: #0d1117; --fg: #c9d1d9; --accent: #58a6ff;
      --green: #3fb950; --red: #f85149; --border: #30363d;
      --subtle-bg: #161b22;
    }}
  }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica,
      Arial, sans-serif;
    background: var(--bg); color: var(--fg);
    line-height: 1.6; max-width: 52em; margin: 2em auto; padding: 0 1em;
  }}
  h1 {{ font-size: 1.5em; margin-bottom: .3em; }}
  h2 {{ font-size: 1.15em; margin: 1.2em 0 .4em; border-bottom: 1px solid var(--border); padding-bottom: .2em; }}
  .banner {{
    background: var(--subtle-bg); border: 1px solid var(--border);
    border-radius: 6px; padding: .8em 1em; margin-bottom: 1em;
  }}
  .banner .meta {{ color: var(--accent); font-weight: 600; }}
  table {{ width: 100%; border-collapse: collapse; margin: .4em 0; }}
  th, td {{ text-align: left; padding: .35em .6em; border-bottom: 1px solid var(--border); }}
  th {{ background: var(--subtle-bg); font-size: .85em; text-transform: uppercase; letter-spacing: .04em; }}
  tr.added td:first-child {{ color: var(--green); font-weight: 700; }}
  tr.removed td:first-child {{ color: var(--red); font-weight: 700; }}
  code {{ background: var(--subtle-bg); padding: .15em .35em; border-radius: 3px; font-size: .9em; }}
  ul {{ list-style: disc; padding-left: 1.5em; }}
  li {{ margin: .15em 0; }}
  .stat {{ display: inline-block; margin-right: 1.2em; }}
  .stat .label {{ font-size: .85em; color: var(--fg); opacity: .7; }}
  .stat .value {{ font-weight: 700; }}
  .plus {{ color: var(--green); }}
  .minus {{ color: var(--red); }}
</style>
</head>
<body>

<h1>PR Summary</h1>

<div class="banner">
  <span class="meta">{current} &rarr; {base}</span> &mdash;
  {commits} commit(s) | {files} file(s) changed
</div>

<h2>Overview</h2>
<div>
  <span class="stat"><span class="label">Sections</span> <span class="value">{sec_added} added, {sec_removed} removed</span></span>
  <span class="stat"><span class="label">Normative</span> <span class="value"><span class="plus">+{norm_added}</span> / <span class="minus">&minus;{norm_removed}</span></span></span>
  <span class="stat"><span class="label">Definitions</span> <span class="value">{len(dfn_added)} new, {len(dfn_removed)} removed</span></span>
  <span class="stat"><span class="label">Lines</span> <span class="value"><span class="plus">+{insertions}</span> / <span class="minus">&minus;{deletions}</span></span></span>
</div>

{"<h2>Section Changes</h2><table><tr><th></th><th>Heading</th></tr>" + section_rows + "</table>" if section_rows else ""}

{"<h2>Definition Changes</h2>" + ("<p>Added: " + dfn_added_html + "</p>" if dfn_added_html else "") + ("<p>Removed: " + dfn_removed_html + "</p>" if dfn_removed_html else "") if dfn_added_html or dfn_removed_html else ""}

{"<h2>Commits</h2><ul>" + commit_rows + "</ul>" if commit_rows else ""}

{"<h2>Files Changed</h2><table><tr><th>File</th><th>Status</th></tr>" + file_rows + "</table>" if file_rows else ""}

</body>
</html>"""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _parse_file_status(output: str) -> list[dict]:
    """Parse ``git diff --name-status`` output into a list of dicts."""
    files = []
    for line in output.strip().splitlines():
        parts = line.split("\t", 1)
        if len(parts) < 2 or not parts[0]:
            continue
        status, path = parts[0][0], parts[1]
        files.append({"status": status, "path": path})
    return files


def _analyze_diff(diff_text: str) -> dict:
    """Single-pass analysis of a unified diff for PR summary metrics.

    Returns:
        Dict with insertions, deletions, sections, normative counts,
        and definition lists.
    """
    insertions = 0
    deletions = 0
    sections: list[dict] = []
    norm_added = 0
    norm_removed = 0
    dfn_added: list[str] = []
    dfn_removed: list[str] = []
    seen_sections: set[tuple[str, str]] = set()
    seen_dfns: set[tuple[str, str]] = set()

    for line in diff_text.splitlines():
        if line.startswith("+++") or line.startswith("---"):
            continue

        if line.startswith("+"):
            insertions += 1
            change = "added"
        elif line.startswith("-"):
            deletions += 1
            change = "removed"
        else:
            continue

        content = line[1:]

        # Heading changes
        for pattern in (_HEADING_RE, _HTML_HEADING_RE):
            m = pattern.search(content)
            if m:
                heading = m.group(1).strip()
                key = (heading, change)
                if key not in seen_sections:
                    seen_sections.add(key)
                    sections.append({"heading": heading, "change": change})

        # Normative keyword changes
        norm_count = len(_NORMATIVE_RE.findall(content))
        if norm_count:
            if change == "added":
                norm_added += norm_count
            else:
                norm_removed += norm_count

        # Definition changes
        for m in _DFN_RE.finditer(content):
            term = m.group(1).strip()
            key = (term, change)
            if key not in seen_dfns:
                seen_dfns.add(key)
                if change == "added":
                    dfn_added.append(term)
                else:
                    dfn_removed.append(term)

    return {
        "insertions": insertions,
        "deletions": deletions,
        "sections": sections,
        "normative": {"added": norm_added, "removed": norm_removed},
        "definitions": {"added": dfn_added, "removed": dfn_removed},
    }
