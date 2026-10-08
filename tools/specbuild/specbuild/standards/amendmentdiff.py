"""Amendment-diff integration.

Connects the amendment formatting system with git-based change detection,
so amendment documents can automatically identify which sections changed
rather than requiring manual specification.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bs4 import BeautifulSoup


def detect_changed_sections_from_git(
    baseline_ref: str = "main",
) -> list[str]:
    """Detect which spec sections changed using git diff.

    Compares the current bikeshed/ sources against *baseline_ref*
    and returns a list of section identifiers (heading text patterns)
    that had content changes.
    """
    import subprocess

    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", f"{baseline_ref}...HEAD", "--", "bikeshed/"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            logging.warning(f"git diff failed: {result.stderr.strip()}")
            return []

        changed_files = [f.strip() for f in result.stdout.strip().split("\n") if f.strip()]
    except (FileNotFoundError, subprocess.TimeoutExpired):
        logging.warning("Could not run git diff for amendment change detection")
        return []

    if not changed_files:
        return []

    section_patterns = _files_to_section_patterns(changed_files)
    logging.info(
        f"Amendment: {len(changed_files)} file(s) changed, "
        f"mapped to {len(section_patterns)} section pattern(s)"
    )
    return section_patterns


def _files_to_section_patterns(changed_files: list[str]) -> list[str]:
    """Map changed .bs filenames to section heading patterns.

    Bikeshed files are typically named like:
    - 01_scope.bs -> "Scope"
    - 05_coding_tools.bs -> "Coding tools"
    - annex_a_assembly.bs -> "Annex A"
    """
    patterns = []
    for filepath in changed_files:
        if not filepath.endswith(".bs"):
            continue

        filename = filepath.rsplit("/", 1)[-1]
        name = filename.removesuffix(".bs")

        name = re.sub(r"^(\d+_)+", "", name)

        if name.startswith("annex_"):
            letter_match = re.match(r"annex_([a-z])", name)
            if letter_match:
                letter = letter_match.group(1).upper()
                patterns.append(rf"(?i)^(?:Annex|Appendix)\s+{letter}\b")
            continue

        if name in ("header", "index", "manifest"):
            continue

        heading = name.replace("_", " ").strip()
        if heading:
            escaped = re.escape(heading)
            patterns.append(rf"(?i)^(?:\d+(?:\.\d+)*\s+)?{escaped}")

    return patterns


def apply_amendment_changes_from_git(
    soup: BeautifulSoup,
    baseline_ref: str = "main",
) -> int:
    """Mark sections as changed based on git diff analysis.

    Returns the number of sections marked as changed.
    """
    from specbuild.output.amendment import mark_changed_sections_soup

    patterns = detect_changed_sections_from_git(baseline_ref)
    if not patterns:
        return 0

    return mark_changed_sections_soup(soup, changed_sections=patterns)
