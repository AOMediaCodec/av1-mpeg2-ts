"""Compose and post a sticky PR comment summarizing build outputs.

Reads (when present) the artifacts produced by:

* ``--pr-summary``  -> ``pr_summary.json`` / ``pr_summary.md``
* ``--build-report`` -> ``build_report.json`` (warnings count, etc.)
* ``--regression``  -> ``regression_report.json`` (delta vs baseline)
* ``--ai-review``   -> ``ai_review.md``

Composes a single Markdown body and posts it via ``gh api`` using the
sticky-comment convention: a hidden ``<!-- specbuild-sticky -->`` HTML
marker is embedded so subsequent runs find and update the same comment
instead of creating duplicates.

Designed to run inside GitHub Actions; ``GITHUB_TOKEN``, ``GITHUB_REPOSITORY``,
and ``GITHUB_REF`` (or ``PR_NUMBER``) must be in the environment.

Usage::

    python scripts/post_pr_summary.py --target-dir 20260520_abc123_Spec/

For local testing, pass ``--dry-run`` to print the rendered body without
calling the GitHub API.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

STICKY_MARKER = "<!-- specbuild-sticky -->"


# ---------------------------------------------------------------------------
# Artifact loaders
# ---------------------------------------------------------------------------


def _read_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _read_text(path: Path) -> str | None:
    if not path.exists():
        return None
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


# ---------------------------------------------------------------------------
# Markdown composition
# ---------------------------------------------------------------------------


def _summarize_pr(pr: dict | None) -> str:
    if not pr:
        return ""
    commits = pr.get("commit_count", 0)
    files = pr.get("stats", {}).get("files", 0)
    norm = pr.get("normative_changes", {}).get("added", 0)
    return (
        "**PR Summary**\n"
        f"- Commits: {commits}\n"
        f"- Files changed: {files}\n"
        f"- Normative additions: {norm}\n"
    )


def _summarize_build(report: dict | None) -> str:
    if not report:
        return ""
    warnings = report.get("warnings_count") or report.get("warnings", 0)
    errors = report.get("errors_count") or report.get("errors", 0)
    return f"**Build Report**\n- Warnings: {warnings}\n- Errors: {errors}\n"


def _summarize_regression(report: dict | None) -> str:
    if not report:
        return ""
    delta = report.get("delta", {})
    summary_bits = ", ".join(f"{k}: {v:+}" for k, v in delta.items() if isinstance(v, int))
    if not summary_bits:
        summary_bits = "no structural changes"
    return f"**Regression**\n- {summary_bits}\n"


def _summarize_ai_review(text: str | None, max_chars: int = 1500) -> str:
    if not text:
        return ""
    snippet = text.strip()
    if len(snippet) > max_chars:
        snippet = snippet[:max_chars].rstrip() + "\n\n_(truncated)_"
    return "**AI Review**\n\n" + snippet + "\n"


def compose_comment(target_dir: Path) -> str:
    """Compose the full sticky-comment Markdown body."""
    pr = _read_json(target_dir / "pr_summary.json")
    build = _read_json(target_dir / "build_report.json")
    regression = _read_json(target_dir / "regression_report.json")
    ai_review = _read_text(target_dir / "ai_review.md")

    parts = [
        STICKY_MARKER,
        "## specbuild — PR Build Summary",
        "",
        f"_Build artifacts: `{target_dir}`_",
        "",
    ]
    sections = [
        _summarize_pr(pr),
        _summarize_build(build),
        _summarize_regression(regression),
        _summarize_ai_review(ai_review),
    ]
    sections = [s for s in sections if s]
    if not sections:
        sections = ["_No build artifacts found in target directory._"]
    parts.extend(sections)
    return "\n".join(parts) + "\n"


# ---------------------------------------------------------------------------
# GitHub API plumbing (via `gh api` CLI for simplicity)
# ---------------------------------------------------------------------------


def _gh_api(args: list[str], *, input_text: str | None = None) -> str:
    """Invoke ``gh api`` and return stdout. Raises on non-zero exit."""
    completed = subprocess.run(
        ["gh", "api", *args],
        capture_output=True,
        text=True,
        timeout=30,
        input=input_text,
        check=True,
    )
    return completed.stdout


def _resolve_pr_number(env: dict[str, str]) -> int | None:
    """Pull the PR number out of the workflow environment."""
    if env.get("PR_NUMBER"):
        try:
            return int(env["PR_NUMBER"])
        except ValueError:
            return None
    ref = env.get("GITHUB_REF", "")
    m = re.match(r"refs/pull/(\d+)/", ref)
    if m:
        return int(m.group(1))
    return None


def find_existing_sticky(repo: str, pr_number: int) -> int | None:
    """Search the PR's existing comments for the sticky marker; return the comment id."""
    # Drop --paginate: it emits multiple JSON arrays on separate lines which
    # breaks json.loads.  PR comments rarely exceed 100 per page, so one page
    # is sufficient for finding the sticky comment.
    out = _gh_api([f"repos/{repo}/issues/{pr_number}/comments"])
    try:
        comments = json.loads(out)
    except json.JSONDecodeError:
        return None
    if not isinstance(comments, list):
        return None
    for c in comments:
        body = c.get("body") or ""
        if STICKY_MARKER in body:
            return c.get("id")
    return None


def upsert_comment(
    repo: str,
    pr_number: int,
    body: str,
    *,
    comment_id: int | None = None,
) -> int:
    """Create-or-update a PR comment. Returns the resulting comment id."""
    payload = json.dumps({"body": body})
    if comment_id is not None:
        out = _gh_api(
            [
                f"repos/{repo}/issues/comments/{comment_id}",
                "--method",
                "PATCH",
                "--input",
                "-",
            ],
            input_text=payload,
        )
    else:
        out = _gh_api(
            [
                f"repos/{repo}/issues/{pr_number}/comments",
                "--method",
                "POST",
                "--input",
                "-",
            ],
            input_text=payload,
        )
    try:
        return int(json.loads(out).get("id", 0))
    except (json.JSONDecodeError, ValueError, AttributeError):
        return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--target-dir",
        type=Path,
        required=True,
        help="Build output directory containing the artifact files.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the rendered comment without posting to GitHub.",
    )
    args = parser.parse_args(argv)

    body = compose_comment(args.target_dir)
    if args.dry_run:
        sys.stdout.write(body)
        return 0

    env = os.environ.copy()
    repo = env.get("GITHUB_REPOSITORY")
    if not repo:
        print("error: GITHUB_REPOSITORY is not set", file=sys.stderr)
        return 1
    pr_number = _resolve_pr_number(env)
    if pr_number is None:
        print("error: cannot resolve PR number from environment", file=sys.stderr)
        return 1

    existing = find_existing_sticky(repo, pr_number)
    upsert_comment(repo, pr_number, body, comment_id=existing)
    return 0


if __name__ == "__main__":
    sys.exit(main())
