#!/usr/bin/env python3
"""Scan Bikeshed source files for tables/figures that are not referenceable.

A *referenceable* table has ``<caption id="...">`` so it can be numbered and
cross-referenced.  A *referenceable* figure has ``id="..."`` on the
``<figure>`` tag and a ``<figcaption>`` child.

Usage::

    # Report issues in all .bs files under bikeshed/
    python scripts/check_referenceable_sources.py bikeshed/

    # Report issues in specific files
    python scripts/check_referenceable_sources.py bikeshed/symbols.bs bikeshed/frame_geometry.bs

    # Exclude tables with specific classes (e.g. inline definition tables)
    python scripts/check_referenceable_sources.py bikeshed/ --exclude-class table-nohead

    # Apply automatic fixes (adds placeholder caption/id)
    python scripts/check_referenceable_sources.py bikeshed/ --fix
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
from pathlib import Path

# Route logging through the shared colored formatter when this script is
# invoked as a subprocess of compile.py.
_repo_root = str(Path(__file__).resolve().parent.parent)
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)
from specbuild.logsetup import setup_logging  # noqa: E402

setup_logging("INFO")

# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------

# Match <table ...> opening tag (possibly multiline attributes)
TABLE_OPEN_RE = re.compile(
    r"^(\s*)<table\b([^>]*)>",
    re.IGNORECASE,
)

# Match <caption ...> tag with or without id
CAPTION_RE = re.compile(
    r"<caption\b([^>]*)>",
    re.IGNORECASE,
)

# Match id="..." in an attribute string
ID_ATTR_RE = re.compile(r'id\s*=\s*["\']([^"\']*)["\']', re.IGNORECASE)

# Match class="..." in an attribute string
CLASS_ATTR_RE = re.compile(r'class\s*=\s*["\']([^"\']*)["\']', re.IGNORECASE)

# Match <figure ...> opening tag
FIGURE_OPEN_RE = re.compile(
    r"^(\s*)<figure\b([^>]*)>",
    re.IGNORECASE,
)

# Match <figcaption ...> tag
FIGCAPTION_RE = re.compile(r"<figcaption\b", re.IGNORECASE)

# Match </figure>
FIGURE_CLOSE_RE = re.compile(r"</figure>", re.IGNORECASE)

# Match </table>
TABLE_CLOSE_RE = re.compile(r"</table>", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Issue dataclass
# ---------------------------------------------------------------------------


class Issue:
    """A single referenceable-format issue found in a source file."""

    __slots__ = ("file", "line", "rule", "element", "detail", "suggestion", "fix_line", "fix_text")

    def __init__(
        self,
        file: Path,
        line: int,
        rule: str,
        element: str,
        detail: str,
        suggestion: str,
        fix_line: int | None = None,
        fix_text: str | None = None,
    ):
        self.file = file
        self.line = line
        self.rule = rule
        self.element = element
        self.detail = detail
        self.suggestion = suggestion
        self.fix_line = fix_line  # line number to insert fix at
        self.fix_text = fix_text  # text to insert

    def __str__(self) -> str:
        return f"{self.file}:{self.line}: [{self.rule}] {self.detail}"


# ---------------------------------------------------------------------------
# Scanner
# ---------------------------------------------------------------------------


def _slug_from_context(lines: list[str], start: int) -> str:
    """Try to derive a slug from surrounding heading or content.

    Looks backwards from *start* for the nearest heading (``## ...`` or
    ``<h2>``) and derives a kebab-case slug from it.  Falls back to using
    the line number.
    """
    for i in range(start - 1, max(start - 30, -1), -1):
        line = lines[i].strip()
        # Bikeshed markdown heading
        m = re.match(r"^#{1,6}\s+(.+)", line)
        if m:
            text = m.group(1).strip()
            slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
            if slug:
                return slug[:40]
        # HTML heading
        m = re.match(r"<h[1-6][^>]*>(.+?)</h[1-6]>", line, re.IGNORECASE)
        if m:
            text = re.sub(r"<[^>]+>", "", m.group(1)).strip()
            slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
            if slug:
                return slug[:40]
    return f"line-{start + 1}"


def scan_file(
    filepath: Path,
    exclude_classes: set[str] | None = None,
) -> list[Issue]:
    """Scan a single .bs file for unreferenceable tables and figures.

    Args:
        filepath: Path to the .bs file.
        exclude_classes: Set of CSS class names to skip (e.g. ``{"table-nohead"}``).

    Returns:
        List of :class:`Issue` instances.
    """
    issues: list[Issue] = []
    exclude_classes = exclude_classes or set()

    lines = filepath.read_text(encoding="utf-8").splitlines()
    used_slugs: dict[str, int] = {}  # slug -> count, for deduplication

    def _unique_slug(prefix: str) -> str:
        """Return a unique slug by appending a numeric suffix if needed."""
        base = _slug_from_context(lines, i)
        slug = f"{prefix}-{base}"
        if slug in used_slugs:
            used_slugs[slug] += 1
            slug = f"{slug}-{used_slugs[slug]}"
            used_slugs[slug] = (
                1  # Also track the new suffixed form so a third collision won't reuse it
            )
        else:
            used_slugs[slug] = 1
        return slug

    i = 0
    while i < len(lines):
        line = lines[i]

        # --- Tables ---
        m_table = TABLE_OPEN_RE.match(line)
        if m_table:
            indent = m_table.group(1)
            attrs = m_table.group(2)
            table_line = i + 1  # 1-based

            # Check for excluded classes
            cls_match = CLASS_ATTR_RE.search(attrs)
            if cls_match:
                classes = set(cls_match.group(1).split())
                if classes & exclude_classes:
                    # Skip to </table>
                    while i < len(lines) and not TABLE_CLOSE_RE.search(lines[i]):
                        i += 1
                    i += 1
                    continue

            # Look for <caption> in the next few lines (within the table)
            has_caption = False
            caption_has_id = False
            caption_line = None

            for j in range(i + 1, min(i + 5, len(lines))):
                m_cap = CAPTION_RE.search(lines[j])
                if m_cap:
                    has_caption = True
                    caption_line = j + 1
                    cap_attrs = m_cap.group(1)
                    if ID_ATTR_RE.search(cap_attrs):
                        caption_has_id = True
                    break
                # Stop looking if we hit a <tr>, <thead>, or <tbody>
                if re.search(r"<(tr|thead|tbody)\b", lines[j], re.IGNORECASE):
                    break

            if not has_caption:
                slug = _unique_slug("table")
                fix_text = f'{indent}  <caption id="{slug}">TODO: add caption</caption>\n'
                # Insert after the <table> line
                issues.append(
                    Issue(
                        file=filepath,
                        line=table_line,
                        rule="table-no-caption",
                        element="table",
                        detail="Table has no <caption> — cannot be numbered or cross-referenced",
                        suggestion=f'Add: <caption id="{slug}">Description</caption>',
                        fix_line=i + 1,
                        fix_text=fix_text,
                    )
                )
            elif not caption_has_id:
                slug = _unique_slug("table")
                issues.append(
                    Issue(
                        file=filepath,
                        line=caption_line,
                        rule="table-caption-no-id",
                        element="table",
                        detail="Table caption has no id — cannot be cross-referenced",
                        suggestion=f'Add id to caption: <caption id="{slug}">...',
                        fix_line=None,
                        fix_text=None,
                    )
                )

        # --- Figures ---
        m_fig = FIGURE_OPEN_RE.match(line)
        if m_fig:
            attrs = m_fig.group(2)
            fig_line = i + 1  # 1-based
            fig_has_id = bool(ID_ATTR_RE.search(attrs))

            # Scan until </figure> for <figcaption>
            has_figcaption = False
            fig_end = i
            for j in range(i + 1, min(i + 30, len(lines))):
                if FIGCAPTION_RE.search(lines[j]):
                    has_figcaption = True
                if FIGURE_CLOSE_RE.search(lines[j]):
                    fig_end = j
                    break

            if not fig_has_id or not has_figcaption:
                slug = _unique_slug("fig")

                if not fig_has_id and not has_figcaption:
                    issues.append(
                        Issue(
                            file=filepath,
                            line=fig_line,
                            rule="figure-not-referenceable",
                            element="figure",
                            detail="Figure has no id and no <figcaption>",
                            suggestion=f'Add id="{slug}" to <figure> and add <figcaption>',
                            fix_line=None,
                            fix_text=None,
                        )
                    )
                elif not fig_has_id:
                    issues.append(
                        Issue(
                            file=filepath,
                            line=fig_line,
                            rule="figure-no-id",
                            element="figure",
                            detail="Figure has no id — cannot be cross-referenced",
                            suggestion=f'Add id="{slug}" to the <figure> tag',
                            fix_line=None,
                            fix_text=None,
                        )
                    )
                elif not has_figcaption:
                    indent_fig = m_fig.group(1)
                    fix_text = f"{indent_fig}  <figcaption>TODO: add caption</figcaption>\n"
                    issues.append(
                        Issue(
                            file=filepath,
                            line=fig_line,
                            rule="figure-no-figcaption",
                            element="figure",
                            detail="Figure has no <figcaption> — will not appear in List of Figures",
                            suggestion="Add <figcaption>Description</figcaption> inside the <figure>",
                            fix_line=fig_end,
                            fix_text=fix_text,
                        )
                    )

        i += 1

    return issues


# ---------------------------------------------------------------------------
# Auto-fix
# ---------------------------------------------------------------------------


def apply_fixes(issues: list[Issue]) -> dict[Path, int]:
    """Apply automatic fixes for issues that have fix data.

    Only issues with ``fix_line`` and ``fix_text`` set are fixable.
    For tables missing captions, inserts a placeholder ``<caption>`` line.
    For figures missing ``<figcaption>``, inserts a placeholder.

    Issues without fix data (e.g. caption-no-id, figure-no-id) require
    manual editing and are skipped.

    Args:
        issues: List of :class:`Issue` instances.

    Returns:
        Dict mapping file paths to the number of fixes applied.
    """
    # Group fixable issues by file, sorted by line descending (so inserts
    # don't shift subsequent line numbers)
    from collections import defaultdict

    by_file: dict[Path, list[Issue]] = defaultdict(list)
    for issue in issues:
        if issue.fix_line is not None and issue.fix_text is not None:
            by_file[issue.file].append(issue)

    stats: dict[Path, int] = {}

    for filepath, file_issues in by_file.items():
        lines = filepath.read_text(encoding="utf-8").splitlines(keepends=True)

        # Sort by fix_line descending so we insert from bottom up
        file_issues.sort(key=lambda i: i.fix_line, reverse=True)

        for issue in file_issues:
            lines.insert(issue.fix_line, issue.fix_text)
            logging.info(
                "  Fixed %s:%d — inserted %s", filepath.name, issue.fix_line + 1, issue.rule
            )

        filepath.write_text("".join(lines), encoding="utf-8")
        stats[filepath] = len(file_issues)

    return stats


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def report_issues(issues: list[Issue]) -> None:
    """Print a formatted report of all issues found."""
    if not issues:
        logging.info("All tables and figures are referenceable.")
        return

    tables = [i for i in issues if i.element == "table"]
    figures = [i for i in issues if i.element == "figure"]
    fixable = [i for i in issues if i.fix_line is not None]

    logging.warning(
        "Found %d issue(s): %d table(s), %d figure(s)  [%d auto-fixable]",
        len(issues),
        len(tables),
        len(figures),
        len(fixable),
    )
    print()

    current_file = None
    for issue in issues:
        if issue.file != current_file:
            current_file = issue.file
            print(f"  {current_file}:")

        marker = " [fixable]" if issue.fix_line is not None else " [manual]"
        print(f"    line {issue.line}: [{issue.rule}]{marker} {issue.detail}")
        print(f"      → {issue.suggestion}")

    if fixable:
        print(f"\n  Run with --fix to auto-fix {len(fixable)} issue(s).")
        print("  Issues marked [manual] require hand-editing.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Check .bs source files for unreferenceable tables and figures.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "paths",
        nargs="+",
        type=Path,
        help="Paths to .bs files or directories containing .bs files.",
    )
    parser.add_argument(
        "--exclude-class",
        action="append",
        default=[],
        dest="exclude_classes",
        metavar="CLASS",
        help="Skip tables with this CSS class (can be repeated).",
    )
    parser.add_argument(
        "--fix",
        action="store_true",
        help="Auto-fix issues where possible (inserts placeholder captions).",
    )
    args = parser.parse_args()

    # Collect .bs files
    bs_files: list[Path] = []
    for path in args.paths:
        if path.is_dir():
            bs_files.extend(sorted(path.glob("*.bs")))
        elif path.is_file() and path.suffix == ".bs":
            bs_files.append(path)
        else:
            logging.warning("Skipping %s (not a .bs file or directory)", path)

    if not bs_files:
        logging.error("No .bs files found")
        sys.exit(1)

    exclude = set(args.exclude_classes)
    logging.info("Scanning %d .bs file(s) for referenceable issues...", len(bs_files))

    all_issues: list[Issue] = []
    for bs_file in bs_files:
        file_issues = scan_file(bs_file, exclude_classes=exclude)
        all_issues.extend(file_issues)

    report_issues(all_issues)

    if args.fix and all_issues:
        fixable = [i for i in all_issues if i.fix_line is not None]
        if fixable:
            logging.info("Applying %d auto-fix(es)...", len(fixable))
            stats = apply_fixes(all_issues)
            for filepath, count in stats.items():
                logging.info("  %s: %d fix(es) applied", filepath.name, count)
            logging.info("Done. Review the inserted TODO placeholders and update them.")
        else:
            logging.info("No auto-fixable issues found. All issues require manual editing.")
    elif args.fix:
        logging.info("Nothing to fix.")

    if all_issues and not args.fix:
        sys.exit(1)


if __name__ == "__main__":
    main()
