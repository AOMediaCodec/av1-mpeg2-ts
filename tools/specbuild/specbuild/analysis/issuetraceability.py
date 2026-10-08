"""Issue-to-requirement traceability.

Scans git commit messages for issue references (e.g. "Fixes #123",
"Resolves !456") and maps them to changed sections in the specification.
Generates a bidirectional index: issues → sections and sections → issues.
"""

from __future__ import annotations

import html as _html
import re
from pathlib import Path

from specbuild.git import run_git
from specbuild.utils import write_json


def _natural_sort_key(s: str) -> list:
    """Split string into alternating text/int chunks for natural ordering."""
    return [int(c) if c.isdigit() else c for c in re.split(r"(\d+)", s)]


# Patterns matching issue references in commit messages.
_ISSUE_PATTERNS = [
    # GitHub: Fixes #123, Closes #456, Resolves #789
    re.compile(r"(?:fix(?:es|ed)?|close[sd]?|resolve[sd]?)\s+#(\d+)", re.IGNORECASE),
    # Bare #123 references
    re.compile(r"(?<!\w)#(\d+)"),
    # GitLab MR: !456
    re.compile(r"(?<!\w)!(\d+)"),
]

# Pattern to extract changed file stems from git diff output.
_BS_FILE_RE = re.compile(r"bikeshed/(\w+)\.bs$")


def generate_issue_traceability(baseline: str = "auto") -> dict:
    """Analyze git history and map issues to changed spec sections.

    Args:
        baseline: Git ref to compare against. "auto" detects the
            main branch (origin/main or main).

    Returns:
        Dict with ``issues`` (issue → sections), ``sections``
        (section → issues), and ``commits`` (raw commit data).
    """
    if baseline == "auto":
        baseline = _detect_main_branch()

    commits = _get_commits_with_issues(baseline)

    issues: dict[str, dict] = {}
    sections: dict[str, set[str]] = {}

    for commit in commits:
        changed_sections = commit.get("changed_sections", [])

        for issue_ref in commit.get("issues", []):
            if issue_ref not in issues:
                issues[issue_ref] = {
                    "id": issue_ref,
                    "commits": [],
                    "sections": set(),
                }
            issues[issue_ref]["commits"].append(commit["sha"])
            issues[issue_ref]["sections"].update(changed_sections)

            for section in changed_sections:
                if section not in sections:
                    sections[section] = set()
                sections[section].add(issue_ref)

    # Convert sets to sorted lists for JSON serialization
    for issue_data in issues.values():
        issue_data["sections"] = sorted(issue_data["sections"], key=_natural_sort_key)
    sorted_sections = {k: sorted(v, key=_natural_sort_key) for k, v in sections.items()}

    return {
        "issues": issues,
        "sections": sorted_sections,
        "commits": commits,
        "summary": {
            "total_issues": len(issues),
            "total_commits": len(commits),
            "total_sections": len(sections),
        },
    }


def _detect_main_branch() -> str:
    """Detect the main branch reference."""
    for ref in ("origin/main", "main", "origin/master", "master"):
        result = run_git("rev-parse", "--verify", ref)
        if result is not None:
            return ref
    return "HEAD~20"  # Fallback: last 20 commits


def _get_commits_with_issues(baseline: str) -> list[dict]:
    """Get commits since baseline that reference issues."""
    # Get commit log with file changes
    log_output = run_git(
        "log",
        f"{baseline}..HEAD",
        "--format=%H%n%s%n%b%n---END---",
        "--name-only",
    )
    if not log_output:
        return []

    commits = []
    current: dict | None = None

    for line in log_output.splitlines():
        line = line.strip()

        if re.match(r"^[0-9a-f]{40}$", line):
            # New commit SHA
            if current:
                commits.append(current)
            current = {
                "sha": line[:8],
                "full_sha": line,
                "subject": "",
                "issues": [],
                "changed_sections": [],
                "files": [],
            }
        elif line == "---END---":
            continue
        elif current is not None:
            if not current["subject"]:
                current["subject"] = line
                # Extract issue refs from subject
                current["issues"].extend(_extract_issues(line))
            elif line:
                # Body lines or file names
                m = _BS_FILE_RE.search(line)
                if m:
                    current["changed_sections"].append(m.group(1))
                    current["files"].append(line)
                else:
                    # Might be commit body — also check for issue refs
                    current["issues"].extend(_extract_issues(line))

    if current:
        commits.append(current)

    # Deduplicate issue refs per commit
    for commit in commits:
        commit["issues"] = sorted(set(commit["issues"]))

    return commits


def _extract_issues(text: str) -> list[str]:
    """Extract issue references from a line of text."""
    refs = []
    for pattern in _ISSUE_PATTERNS:
        for match in pattern.finditer(text):
            # Preserve the original prefix (# for issues, ! for MRs)
            full_match = match.group(0)
            if "!" in full_match:
                ref = f"!{match.group(1)}"
            else:
                ref = f"#{match.group(1)}"
            if ref not in refs:
                refs.append(ref)
    return refs


def write_traceability_json(data: dict, output_path: Path) -> None:
    """Write the traceability data as JSON."""
    write_json(data, output_path, label="Issue traceability")


def render_traceability_html(data: dict) -> str:
    """Render the traceability data as an HTML report."""
    issues = data.get("issues", {})
    sections = data.get("sections", {})
    summary = data.get("summary", {})

    # Issues → Sections table
    issue_rows = ""
    for issue_id in sorted(
        issues.keys(), key=lambda x: int(x.lstrip("#!")) if x.lstrip("#!").isdigit() else 0
    ):
        info = issues[issue_id]
        secs = ", ".join(info.get("sections", []))
        commits = ", ".join(f"<code>{c}</code>" for c in info.get("commits", []))
        issue_rows += (
            f"<tr>"
            f"<td><strong>{_html.escape(issue_id)}</strong></td>"
            f"<td>{_html.escape(secs)}</td>"
            f"<td>{commits}</td>"
            f"</tr>\n"
        )

    # Sections → Issues table
    section_rows = ""
    for section in sorted(sections.keys()):
        issue_list = ", ".join(sections[section])
        section_rows += (
            f"<tr>"
            f"<td><strong>{_html.escape(section)}</strong></td>"
            f"<td>{_html.escape(issue_list)}</td>"
            f"</tr>\n"
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Issue Traceability</title>
<style>
body {{ font-family: system-ui, sans-serif; max-width: 900px; margin: 2em auto; }}
h1 {{ font-size: 1.4em; }}
h2 {{ font-size: 1.15em; margin-top: 1.5em; }}
.summary {{ color: #666; }}
table {{ border-collapse: collapse; width: 100%; font-size: 0.9em; margin: 1em 0; }}
th, td {{ padding: 6px 10px; border: 1px solid #ddd; text-align: left; }}
th {{ background: #f5f5f5; font-weight: 600; }}
code {{ background: #f3f4f6; padding: 1px 4px; border-radius: 3px; font-size: 0.85em; }}
</style>
</head>
<body>
<h1>Issue Traceability Report</h1>
<p class="summary">{summary.get("total_issues", 0)} issues linked to
{summary.get("total_sections", 0)} sections across
{summary.get("total_commits", 0)} commits</p>

<h2>Issues &rarr; Sections</h2>
<table>
<thead><tr><th>Issue</th><th>Changed Sections</th><th>Commits</th></tr></thead>
<tbody>{issue_rows}</tbody>
</table>

<h2>Sections &rarr; Issues</h2>
<table>
<thead><tr><th>Section</th><th>Related Issues</th></tr></thead>
<tbody>{section_rows}</tbody>
</table>
</body>
</html>"""
