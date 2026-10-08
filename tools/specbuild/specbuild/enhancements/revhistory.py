"""Revision history table auto-generated from git tags and commits.

Reads version information from the local git repository (annotated tags or,
as a fallback, recent commits) and injects an HTML revision-history table
into the compiled specification.  The table is inserted immediately after
the abstract or header section so it appears near the front of the document.

Public API
----------
* :func:`inject_revision_history` -- file-based entry point (read/mutate/write).
* :func:`inject_revision_history_soup` -- operate on a pre-parsed BeautifulSoup tree.
* :func:`get_revision_entries` -- retrieve raw revision data without touching HTML.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Any

from specbuild.theme import THEME
from specbuild.utils import get_bs4, inject_css, read_html, write_html

# ---------------------------------------------------------------------------
# Column layout for the revision-history table
# ---------------------------------------------------------------------------

_TABLE_COLUMNS = ("Version", "Date", "Description")

# Width allocated to the Version and Date columns (CSS percentage).
_VERSION_COL_WIDTH = "15%"
_DATE_COL_WIDTH = "15%"

# Placeholder shown when a revision entry has no description.
_NO_DESCRIPTION = "\u2014"  # em-dash

# ---------------------------------------------------------------------------
# Git data retrieval
# ---------------------------------------------------------------------------

# git-tag --format placeholders (tab-separated):
#   %(refname:short)       -> tag name without refs/tags/ prefix
#   %(creatordate:short)   -> YYYY-MM-DD creation date
#   %(subject)             -> annotated-tag message (first line)
#   %(objectname:short)    -> abbreviated SHA of the tag object
_TAG_FORMAT = "%(refname:short)\t%(creatordate:short)\t%(subject)\t%(objectname:short)"

# git-log --format placeholders (tab-separated):
#   %h  -> abbreviated commit SHA
#   %cs -> committer date (YYYY-MM-DD, short format)
#   %s  -> subject line
_COMMIT_FORMAT = "%h\t%cs\t%s"


def _get_git_tags() -> list[dict[str, str]]:
    """Return git tags with dates and messages, sorted newest-first.

    Each tag is represented as a dict with the keys ``tag``, ``date``,
    ``message``, and ``sha``.

    Returns:
        List of tag dicts, or an empty list on failure.
    """
    try:
        result = subprocess.run(
            ["git", "tag", "-l", "--sort=-creatordate", f"--format={_TAG_FORMAT}"],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        logging.warning(f"git tag failed: {exc}")
        return []

    tags: list[dict[str, str]] = []
    for line in result.stdout.strip().split("\n"):
        if not line.strip():
            continue
        # Split on tab with a max of 4 fields (tag, date, message, sha)
        parts = line.split("\t", 3)
        if len(parts) >= 2:
            tags.append(
                {
                    "tag": parts[0],
                    "date": parts[1],
                    "message": parts[2] if len(parts) > 2 else "",
                    "sha": parts[3] if len(parts) > 3 else "",
                }
            )
    return tags


def _get_recent_commits(limit: int = 10) -> list[dict[str, str]]:
    """Return the most recent commits as a fallback when no tags exist.

    Args:
        limit: Maximum number of commits to retrieve.

    Returns:
        List of commit dicts with keys ``sha``, ``date``, ``message``,
        or an empty list on failure.
    """
    try:
        result = subprocess.run(
            ["git", "log", f"-{limit}", f"--format={_COMMIT_FORMAT}"],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        logging.warning(f"git log failed: {exc}")
        return []

    commits: list[dict[str, str]] = []
    for line in result.stdout.strip().split("\n"):
        if not line.strip():
            continue
        # Split on tab with a max of 3 fields (sha, date, message)
        parts = line.split("\t", 2)
        if len(parts) >= 3:
            commits.append(
                {
                    "sha": parts[0],
                    "date": parts[1],
                    "message": parts[2],
                }
            )
    return commits


# ---------------------------------------------------------------------------
# Public data retrieval
# ---------------------------------------------------------------------------


def get_revision_entries(max_entries: int = 20) -> tuple[list[dict[str, str]], bool]:
    """Collect revision entries from git tags or recent commits.

    Tags are preferred; commits are used only when the repository has no
    tags at all.

    Args:
        max_entries: Maximum number of entries to return.

    Returns:
        A ``(entries, used_tags)`` tuple.  *entries* is a list of dicts
        whose keys are ``tag``/``sha``, ``date``, and ``message``.
        *used_tags* is ``True`` when entries came from git tags, ``False``
        when they fell back to recent commits.
    """
    tags = _get_git_tags()
    if tags:
        return tags[:max_entries], True
    logging.info("No git tags found, using recent commits for revision history")
    return _get_recent_commits(max_entries), False


# ---------------------------------------------------------------------------
# HTML injection -- file-level entry point
# ---------------------------------------------------------------------------


def inject_revision_history(html_path: Path, *, max_entries: int = 20) -> int:
    """Insert a revision-history table after the document abstract/header.

    This is the file-based wrapper around
    :func:`inject_revision_history_soup`: it reads *html_path*, mutates
    the parsed tree, and writes the result back.

    Args:
        html_path: Path to the compiled HTML file.
        max_entries: Maximum number of revision entries to include.

    Returns:
        Number of revision entries added (0 if nothing was inserted).
    """
    try:
        get_bs4()
    except ImportError:
        logging.warning("BeautifulSoup not available, skipping revision history")
        return 0

    logging.info(f"Generating revision history for {html_path.name}")

    entries, used_tags = get_revision_entries(max_entries)

    if not entries:
        logging.warning("No revision entries found (no tags or commits)")
        return 0

    soup = read_html(html_path)
    count = inject_revision_history_soup(soup, entries, use_tags=used_tags)
    write_html(html_path, soup)
    return count


# ---------------------------------------------------------------------------
# HTML injection -- soup-level entry point
# ---------------------------------------------------------------------------


def inject_revision_history_soup(
    soup: Any, entries: list[dict[str, str]], *, use_tags: bool = True
) -> int:
    """Insert a revision-history table into a pre-parsed BeautifulSoup tree.

    The table is placed immediately after the abstract (``<div id="abstract">``)
    or the document header (``<div class="head">``).  If neither is found,
    it falls back to inserting before the first ``<h2>`` inside ``<main>``.

    Args:
        soup: BeautifulSoup document (mutated in place).
        entries: Revision dicts -- see :func:`get_revision_entries`.
        use_tags: ``True`` when *entries* represent git tags; ``False``
            for commit-based entries.

    Returns:
        Number of revision entries added (0 if no insertion point found).
    """
    rev_div = _build_revision_table(soup, entries, use_tags)

    if not _insert_revision_div(soup, rev_div):
        return 0

    _inject_revision_history_css(soup)

    source_kind = "tags" if use_tags else "commits"
    logging.info(f"Inserted revision history with {len(entries)} entries ({source_kind})")
    return len(entries)


# ---------------------------------------------------------------------------
# Table construction helpers
# ---------------------------------------------------------------------------


def _build_revision_table(soup: Any, entries: list[dict[str, str]], use_tags: bool) -> Any:
    """Build the ``<div class="revision-history">`` element and its table.

    Args:
        soup: BeautifulSoup document used as a tag factory.
        entries: Revision dicts to populate table rows.
        use_tags: Whether entries are tags (True) or commits (False).

    Returns:
        The constructed ``<div>`` element (not yet inserted into *soup*).
    """
    rev_div = soup.new_tag("div", id="revision-history", **{"class": "revision-history"})

    heading = soup.new_tag("h2")
    heading.string = "Revision History"
    rev_div.append(heading)

    table = soup.new_tag("table", **{"class": "revision-history-table"})
    table.append(_build_table_header(soup))
    table.append(_build_table_body(soup, entries, use_tags))
    rev_div.append(table)

    return rev_div


def _build_table_header(soup: Any) -> Any:
    """Create a ``<thead>`` with the column headings.

    Args:
        soup: BeautifulSoup document used as a tag factory.

    Returns:
        A ``<thead>`` element.
    """
    thead = soup.new_tag("thead")
    header_row = soup.new_tag("tr")
    for col_name in _TABLE_COLUMNS:
        th = soup.new_tag("th")
        th.string = col_name
        header_row.append(th)
    thead.append(header_row)
    return thead


def _build_table_body(soup: Any, entries: list[dict[str, str]], use_tags: bool) -> Any:
    """Create a ``<tbody>`` populated with one row per revision entry.

    Args:
        soup: BeautifulSoup document used as a tag factory.
        entries: Revision dicts to populate table rows.
        use_tags: Whether entries are tags (True) or commits (False).

    Returns:
        A ``<tbody>`` element.
    """
    tbody = soup.new_tag("tbody")
    for entry in entries:
        row = soup.new_tag("tr")

        # Version column -- tag name (plain text) or commit SHA (<code>)
        td_version = soup.new_tag("td")
        if use_tags:
            td_version.string = entry["tag"]
        else:
            code = soup.new_tag("code")
            code.string = entry["sha"]
            td_version.append(code)
        row.append(td_version)

        # Date column
        td_date = soup.new_tag("td")
        td_date.string = entry["date"]
        row.append(td_date)

        # Description column
        td_desc = soup.new_tag("td")
        td_desc.string = entry.get("message", "") or _NO_DESCRIPTION
        row.append(td_desc)

        tbody.append(row)
    return tbody


# ---------------------------------------------------------------------------
# Insertion-point detection
# ---------------------------------------------------------------------------


def _insert_revision_div(soup: Any, rev_div: Any) -> bool:
    """Find the best insertion point and place *rev_div* into *soup*.

    Insertion strategy (first match wins):
      1. After ``<div id="abstract">``
      2. After ``<div class="head">``
      3. Before the first ``<h2>`` inside ``<main>``
      4. At the top of ``<main>``

    Args:
        soup: BeautifulSoup document to insert into.
        rev_div: The revision-history ``<div>`` to insert.

    Returns:
        ``True`` if insertion succeeded, ``False`` otherwise.
    """
    anchor = soup.find("div", id="abstract")
    if not anchor:
        anchor = soup.find("div", class_="head")

    if anchor:
        anchor.insert_after(rev_div)
        return True

    # Fallback: insert before the first <h2> in <main>
    main = soup.find("main")
    if main:
        first_h2 = main.find("h2")
        if first_h2:
            first_h2.insert_before(rev_div)
        else:
            main.insert(0, rev_div)
        return True

    logging.warning("Cannot find insertion point for revision history")
    return False


# ---------------------------------------------------------------------------
# CSS injection
# ---------------------------------------------------------------------------


def _inject_revision_history_css(soup: Any) -> None:
    """Inject scoped CSS for the revision-history table.

    All values that depend on the active colour theme are interpolated from
    :data:`specbuild.theme.THEME`.

    Args:
        soup: BeautifulSoup document to inject the ``<style>`` block into.
    """
    t = THEME
    css = f"""
/* Revision History Table */
.revision-history {{
  margin: 2em 0;
  page-break-before: always;
}}
.revision-history h2 {{
  text-align: center;
  font-size: {t.rev_heading_font_size};
  margin-bottom: 1em;
}}
.revision-history-table {{
  width: 100%;
  border-collapse: collapse;
  font-size: {t.rev_table_font_size};
}}
.revision-history-table th {{
  background-color: {t.rev_table_header_bg};
  border: {t.rev_table_header_border};
  padding: 6px 10px;
  text-align: left;
  font-weight: bold;
}}
.revision-history-table td {{
  border: {t.rev_table_cell_border};
  padding: 4px 10px;
  vertical-align: top;
}}
.revision-history-table td:first-child {{
  white-space: nowrap;
  font-weight: bold;
  width: {_VERSION_COL_WIDTH};
}}
.revision-history-table td:nth-child(2) {{
  white-space: nowrap;
  width: {_DATE_COL_WIDTH};
}}
.revision-history-table tr:nth-child(even) {{
  background-color: {t.rev_table_alt_row_bg};
}}
@media print {{
  .revision-history {{
    page-break-before: always;
    page-break-after: always;
  }}
  .revision-history-table {{
    font-size: {t.footer_font_size}pt;
  }}
}}
"""
    inject_css(soup, "revision-history-css", css)
