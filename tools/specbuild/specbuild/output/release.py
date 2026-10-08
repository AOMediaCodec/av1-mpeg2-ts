"""Release automation: tag, baseline, changelog, and packaging.

Automates the release workflow for spec builds:

1. Validate the working tree is clean
2. Run a full build (delegated to the caller)
3. Save a structural baseline snapshot
4. Generate a changelog from git history between tags
5. Create a git tag
6. Package outputs into a ZIP

Usage::

    from specbuild.output.release import prepare_release, generate_changelog

    # In compile.py, after a successful build:
    prepare_release(tag, html_path, target_dir)
"""

from __future__ import annotations

import logging
from pathlib import Path

from specbuild.git import run_git


def validate_clean_tree() -> bool:
    """Check that the git working tree has no uncommitted changes.

    Returns:
        True if the tree is clean, False otherwise.
    """
    status = run_git("status", "--porcelain")
    if status is None:
        logging.warning("Could not check git status")
        return False
    # Filter out untracked files (lines starting with ??) for cleanliness check
    dirty = [line for line in status.strip().splitlines() if line and not line.startswith("??")]
    if dirty:
        logging.error(
            f"Working tree has {len(dirty)} uncommitted change(s). "
            "Commit or stash before releasing."
        )
        for line in dirty[:10]:
            logging.error(f"  {line}")
        return False
    return True


def get_latest_tag() -> str | None:
    """Get the most recent git tag.

    Returns:
        Tag name string, or None if no tags exist.
    """
    result = run_git("describe", "--tags", "--abbrev=0")
    if result is None:
        return None
    return result.strip()


def generate_changelog(since_ref: str | None = None) -> str:
    """Generate a changelog from git log between *since_ref* and HEAD.

    Args:
        since_ref: Git ref (tag or commit) to start from.  If None,
            uses the latest tag; if no tags exist, includes all history.

    Returns:
        Markdown-formatted changelog string.
    """
    if since_ref is None:
        since_ref = get_latest_tag()

    if since_ref:
        log_range = f"{since_ref}..HEAD"
        header = f"## Changes since {since_ref}\n\n"
    else:
        log_range = "HEAD"
        header = "## Full History\n\n"

    raw = run_git("log", log_range, "--pretty=format:%h %s", "--no-merges")
    if raw is None or not raw.strip():
        return header + "_No changes._\n"

    lines: list[str] = []
    for line in raw.strip().splitlines():
        line = line.strip()
        if line:
            # Format as markdown bullet: - sha message
            parts = line.split(" ", 1)
            sha = parts[0]
            msg = parts[1] if len(parts) > 1 else ""
            lines.append(f"- `{sha}` {msg}")

    return header + "\n".join(lines) + "\n"


def create_tag(tag: str, message: str | None = None) -> bool:
    """Create an annotated git tag.

    Args:
        tag: Tag name (e.g. ``'v1.0'``).
        message: Tag message.  Defaults to ``'Release <tag>'``.

    Returns:
        True on success, False on failure.
    """
    if message is None:
        message = f"Release {tag}"

    result = run_git("tag", "-a", tag, "-m", message)
    if result is None:
        logging.error(f"Failed to create tag '{tag}'")
        return False

    logging.info(f"Created tag: {tag}")
    return True


def prepare_release(
    tag: str,
    html_path: Path,
    target_dir: Path,
    *,
    skip_clean_check: bool = False,
) -> dict:
    """Run the full release workflow after a successful build.

    This should be called after the build completes successfully.
    It does NOT run the build itself.

    Args:
        tag: Version tag to create (e.g. ``'v1.0'``).
        html_path: Path to the compiled HTML file.
        target_dir: Build output directory.
        skip_clean_check: Skip the clean-tree validation.

    Returns:
        Dict with release metadata: ``tag``, ``changelog_path``,
        ``baseline_path``, ``success``.
    """
    result = {
        "tag": tag,
        "changelog_path": None,
        "baseline_path": None,
        "success": False,
    }

    # 1. Validate clean tree
    if not skip_clean_check:
        if not validate_clean_tree():
            return result

    # 2. Save baseline
    from specbuild.analysis.baseline import save_baseline

    baseline_path = target_dir / ".specbuild_baseline.json"
    try:
        save_baseline(html_path, baseline_path)
        result["baseline_path"] = str(baseline_path)
        logging.info(f"Baseline saved: {baseline_path}")
    except Exception as exc:
        logging.warning(f"Failed to save baseline: {exc}")

    # 3. Generate changelog
    previous_tag = get_latest_tag()
    changelog = generate_changelog(previous_tag)
    changelog_path = target_dir / "CHANGELOG.md"
    try:
        changelog_path.write_text(changelog, encoding="utf-8")
        result["changelog_path"] = str(changelog_path)
        logging.info(f"Changelog written: {changelog_path}")
    except OSError as exc:
        logging.warning(f"Failed to write changelog to {changelog_path}: {exc}")

    # 4. Create tag
    tag_ok = create_tag(tag, message=f"Release {tag}")
    if not tag_ok:
        logging.error("Tag creation failed — release incomplete")
        return result

    result["success"] = True
    logging.info(f"Release {tag} prepared successfully")
    return result
