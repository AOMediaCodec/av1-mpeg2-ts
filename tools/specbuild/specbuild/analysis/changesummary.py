"""Spec change summary generator: produce human-readable summaries of what changed.

Given a commit range or baseline reference, analyses the specification source
files to identify:

- New, modified, and deleted sections
- Changed definitions (``<dfn>`` additions/removals)
- Modified syntax tables
- Changed equations

The output is a structured summary suitable for contribution reviews, meeting
prep, and build reports.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from specbuild.config import CONFIG
from specbuild.git import run_git


def generate_change_summary(
    baseline: str | None = None,
    *,
    manifest_path: Path | None = None,
) -> dict:
    """Generate a human-readable summary of specification changes.

    Args:
        baseline: Git ref to compare against (branch, tag, or SHA).
            Defaults to ``CONFIG.main_branch``.
        manifest_path: Path to the manifest file.  Defaults to
            ``CONFIG.bikeshed_dir / "manifest.txt"``.

    Returns:
        Dict with keys:

        - ``baseline``: the resolved baseline ref
        - ``files``: list of dicts with per-file change info
        - ``sections``: list of new/modified/deleted section headings
        - ``definitions``: list of added/removed ``<dfn>`` terms
        - ``equations``: count of changed equation blocks
        - ``syntax_tables``: count of changed SDL/syntax blocks
        - ``stats``: dict with ``insertions``, ``deletions``, ``files_changed``
        - ``summary_text``: formatted multi-line summary string
    """
    if baseline is None:
        baseline = CONFIG.main_branch

    bikeshed_dir = Path(CONFIG.bikeshed_dir)
    if manifest_path is None:
        manifest_path = bikeshed_dir / "manifest.txt"

    result: dict = {
        "baseline": baseline,
        "files": [],
        "sections": [],
        "definitions": [],
        "equations": 0,
        "syntax_tables": 0,
        "stats": {"insertions": 0, "deletions": 0, "files_changed": 0},
        "summary_text": "",
    }

    # Get list of changed .bs files
    changed_files = _get_changed_files(baseline, bikeshed_dir)
    if not changed_files:
        result["summary_text"] = f"No specification changes since {baseline}."
        logging.info(result["summary_text"])
        return result

    result["stats"]["files_changed"] = len(changed_files)
    result["files"] = changed_files

    # Get combined diff for all changed files in a single subprocess call
    combined_diff = run_git("diff", "-U3", baseline, "--", str(bikeshed_dir))
    if combined_diff:
        # Single-pass analysis of the combined diff
        analysis = _analyze_diff(combined_diff)
        result["stats"]["insertions"] = analysis["insertions"]
        result["stats"]["deletions"] = analysis["deletions"]
        result["sections"] = analysis["sections"]
        result["definitions"] = analysis["definitions"]
        result["equations"] = analysis["equations"]
        result["syntax_tables"] = analysis["syntax_tables"]

    # Generate formatted summary
    result["summary_text"] = _format_summary(result)
    logging.info(
        f"Change summary: {len(changed_files)} files, "
        f"{result['stats']['insertions']} insertions, "
        f"{result['stats']['deletions']} deletions"
    )
    return result


def format_change_summary_markdown(summary: dict) -> str:
    """Format a change summary dict as Markdown text.

    Args:
        summary: Dict from :func:`generate_change_summary`.

    Returns:
        Markdown-formatted summary string.
    """
    lines = [f"# Specification Changes (vs {summary['baseline']})", ""]

    stats = summary["stats"]
    lines.append(
        f"**{stats['files_changed']}** file(s) changed, "
        f"**+{stats['insertions']}** insertions, "
        f"**-{stats['deletions']}** deletions"
    )
    lines.append("")

    if summary["sections"]:
        lines.append("## Section Changes")
        for sec in summary["sections"]:
            marker = {"added": "+", "removed": "-", "modified": "~"}
            lines.append(f"- [{marker.get(sec['change'], '?')}] {sec['heading']}")
        lines.append("")

    if summary["definitions"]:
        lines.append("## Definition Changes")
        for dfn in summary["definitions"]:
            prefix = "Added" if dfn["change"] == "added" else "Removed"
            lines.append(f"- {prefix}: **{dfn['term']}**")
        lines.append("")

    if summary["equations"]:
        lines.append(f"## Equations: {summary['equations']} block(s) changed")
        lines.append("")

    if summary["syntax_tables"]:
        lines.append(f"## Syntax Tables: {summary['syntax_tables']} block(s) changed")
        lines.append("")

    if summary["files"]:
        lines.append("## Changed Files")
        for f in summary["files"]:
            status_map = {"M": "Modified", "A": "Added", "D": "Deleted", "R": "Renamed"}
            status = status_map.get(f.get("status", "M"), f.get("status", "?"))
            lines.append(f"- `{f['path']}` ({status})")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Git operations
# ---------------------------------------------------------------------------


def _get_changed_files(baseline: str, bikeshed_dir: Path) -> list[dict]:
    """Get list of .bs files changed since baseline."""
    output = run_git("diff", "--name-status", baseline, "--", str(bikeshed_dir))
    if not output:
        return []

    files = []
    for line in output.strip().splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        status = parts[0]
        path = parts[-1]  # for renames, use the new path (last field)
        if path.endswith(".bs"):
            files.append({"status": status[0], "path": path})
    return files


# ---------------------------------------------------------------------------
# Diff analysis (single-pass)
# ---------------------------------------------------------------------------

# Bikeshed heading pattern: lines like "## Section Title" or "### Subsection"
_HEADING_RE = re.compile(r"^#{1,6}\s+(.+)$", re.MULTILINE)
# HTML-style headings in .bs files
_HTML_HEADING_RE = re.compile(r"<h[1-6][^>]*>\s*(.+?)\s*</h[1-6]>", re.IGNORECASE)
# Definition elements
_DFN_RE = re.compile(r"<dfn[^>]*>\s*(.+?)\s*</dfn>", re.IGNORECASE)
# Pre-compiled patterns for equation and syntax table detection
_EQUATION_RE = re.compile(r"\\begin\{equation\}|^\s*\$\$|\\\(")
_SYNTAX_TABLE_RE = re.compile(r"^```cpp|^```c\b")


def _analyze_diff(diff_text: str) -> dict:
    """Single-pass analysis of a unified diff.

    Returns:
        Dict with insertions, deletions, sections, definitions,
        equations, and syntax_tables.
    """
    insertions = 0
    deletions = 0
    sections: list[dict] = []
    definitions: list[dict] = []
    equations = 0
    syntax_tables = 0
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

        # Check for heading changes
        for pattern in (_HEADING_RE, _HTML_HEADING_RE):
            m = pattern.search(content)
            if m:
                heading = m.group(1).strip()
                key = (heading, change)
                if key not in seen_sections:
                    seen_sections.add(key)
                    sections.append({"heading": heading, "change": change})

        # Check for definition changes
        for m in _DFN_RE.finditer(content):
            term = m.group(1).strip()
            key = (term, change)
            if key not in seen_dfns:
                seen_dfns.add(key)
                definitions.append({"term": term, "change": change})

        # Check for equation and syntax table changes
        if _EQUATION_RE.search(content):
            equations += 1
        if _SYNTAX_TABLE_RE.search(content):
            syntax_tables += 1

    return {
        "insertions": insertions,
        "deletions": deletions,
        "sections": sections,
        "definitions": definitions,
        "equations": equations,
        "syntax_tables": syntax_tables,
    }


# Keep individual functions available for direct testing
def _count_diff_lines(diff_text: str) -> tuple[int, int]:
    """Count insertion and deletion lines in a unified diff."""
    result = _analyze_diff(diff_text)
    return result["insertions"], result["deletions"]


def _extract_section_changes(diff_text: str) -> list[dict]:
    """Extract section heading additions and removals from a diff."""
    return _analyze_diff(diff_text)["sections"]


def _extract_definition_changes(diff_text: str) -> list[dict]:
    """Extract <dfn> additions and removals from a diff."""
    return _analyze_diff(diff_text)["definitions"]


def _count_pattern_changes(diff_text: str, pattern: str) -> int:
    """Count lines matching a regex pattern in diff added/removed lines."""
    compiled = re.compile(pattern)
    count = 0
    for line in diff_text.splitlines():
        if (
            (line.startswith("+") or line.startswith("-"))
            and not line.startswith("+++")
            and not line.startswith("---")
        ):
            if compiled.search(line[1:]):
                count += 1
    return count


def _format_summary(result: dict) -> str:
    """Format a concise summary string."""
    parts = []
    stats = result["stats"]
    parts.append(
        f"{stats['files_changed']} file(s) changed (+{stats['insertions']}/-{stats['deletions']})"
    )

    if result["sections"]:
        added = sum(1 for s in result["sections"] if s["change"] == "added")
        removed = sum(1 for s in result["sections"] if s["change"] == "removed")
        parts.append(f"{added} section(s) added, {removed} removed")

    if result["definitions"]:
        added = sum(1 for d in result["definitions"] if d["change"] == "added")
        removed = sum(1 for d in result["definitions"] if d["change"] == "removed")
        parts.append(f"{added} definition(s) added, {removed} removed")

    if result["equations"]:
        parts.append(f"{result['equations']} equation block(s) changed")

    if result["syntax_tables"]:
        parts.append(f"{result['syntax_tables']} syntax table(s) changed")

    return "; ".join(parts)
