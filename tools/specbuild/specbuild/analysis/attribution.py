"""Contributor attribution: annotate sections with git blame data.

Uses ``git blame`` to determine which contributors authored each section
and how recently each section was modified.  Produces a per-section
attribution table with primary authors and change frequency.

:func:`generate_section_attribution` extends the file-level analysis with
clause-level granularity by mapping source line numbers from Bikeshed
``data-bs-line`` attributes back to git blame output.
"""

from __future__ import annotations

import json
import logging
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from specbuild.git import run_git


def generate_attribution(
    *,
    source_dir: str = "bikeshed",
    max_authors: int = 3,
) -> dict:
    """Generate contributor attribution data from git blame.

    Args:
        source_dir: Directory containing ``.bs`` source files.
        max_authors: Maximum number of authors to list per file.

    Returns:
        Dict with ``files`` (per-file attribution), ``authors``
        (global author stats), and ``summary``.
    """
    # Get list of .bs files
    file_list = run_git("ls-files", "--", f"{source_dir}/*.bs")
    if not file_list:
        logging.info("No .bs files found for attribution")
        return {"files": [], "authors": {}, "summary": {}}

    files = [f.strip() for f in file_list.strip().splitlines() if f.strip()]

    file_data: list[dict] = []
    global_authors: Counter = Counter()

    def _blame_file(filepath: str) -> tuple[str, str]:
        return filepath, run_git("blame", "--line-porcelain", filepath, timeout=60)

    with ThreadPoolExecutor(max_workers=min(len(files), 8)) as executor:
        futures = {executor.submit(_blame_file, f): f for f in files}
        for future in as_completed(futures):
            try:
                filepath, blame_output = future.result()
            except Exception as exc:
                logging.warning(f"git blame failed for {futures[future]}: {exc}")
                continue
            if not blame_output:
                continue

            authors, dates = _parse_blame(blame_output)
            if not authors:
                continue

            author_counts = Counter(authors)
            global_authors.update(author_counts)
            total_lines = len(authors)

            top_authors = [
                {"name": name, "lines": count, "pct": round(count / total_lines * 100, 1)}
                for name, count in author_counts.most_common(max_authors)
            ]

            last_modified = max(dates) if dates else ""

            file_data.append(
                {
                    "file": filepath,
                    "total_lines": total_lines,
                    "authors": top_authors,
                    "unique_authors": len(author_counts),
                    "last_modified": last_modified,
                }
            )

    # Sort by file path to give deterministic output order
    file_data.sort(key=lambda d: d["file"])

    author_summary = {name: count for name, count in global_authors.most_common()}

    return {
        "files": file_data,
        "authors": author_summary,
        "summary": {
            "total_files": len(file_data),
            "total_authors": len(global_authors),
            "total_lines": sum(f["total_lines"] for f in file_data),
        },
    }


def generate_section_attribution(
    soup: object,
    *,
    source_dir: str = "bikeshed",
    max_authors: int = 3,
) -> list[dict]:
    """Generate section-level contributor attribution from compiled HTML.

    Uses ``data-bs-line`` attributes (Bikeshed source line annotations on
    headings and blocks) to map each heading back to its source file and line
    number, then resolves authorship via ``git blame``.

    Args:
        soup: BeautifulSoup document with ``data-bs-line`` annotations.
        source_dir: Directory containing ``.bs`` source files.
        max_authors: Maximum number of authors to list per section.

    Returns:
        List of dicts with ``section_id``, ``heading``, ``file``, ``line``,
        ``authors`` (top contributors), and ``last_modified``.
    """
    # Build a per-file blame cache (line→author, line→date)
    blame_cache: dict[str, tuple[list[str], list[str]]] = {}

    def _get_blame(filepath: str) -> tuple[list[str], list[str]]:
        if filepath not in blame_cache:
            out = run_git("blame", "--line-porcelain", filepath, timeout=60)
            blame_cache[filepath] = _parse_blame(out) if out else ([], [])
        return blame_cache[filepath]

    sections: list[dict] = []
    heading_re = re.compile(r"^h[2-6]$")

    for heading in soup.find_all(heading_re):
        hid = heading.get("id", "")
        heading_text = heading.get_text(" ", strip=True)

        # Walk the heading and its parent elements looking for data-bs-line
        bs_line_raw = ""
        for candidate in [heading, *heading.parents]:
            val = getattr(candidate, "get", lambda _: None)("data-bs-line")
            if val:
                bs_line_raw = val
                break

        if not bs_line_raw:
            sections.append(
                {
                    "section_id": hid,
                    "heading": heading_text,
                    "file": "",
                    "line": 0,
                    "authors": [],
                    "last_modified": "",
                }
            )
            continue

        # Format: "filename.bs:NN" or just "NN"
        if ":" in bs_line_raw:
            file_part, line_part = bs_line_raw.rsplit(":", 1)
            filepath = file_part if "/" in file_part else f"{source_dir}/{file_part}"
        else:
            line_part = bs_line_raw
            filepath = ""

        try:
            line_num = int(line_part) - 1  # blame is 0-indexed in list
        except ValueError:
            line_num = 0

        if not filepath:
            sections.append(
                {
                    "section_id": hid,
                    "heading": heading_text,
                    "file": "",
                    "line": line_num + 1,
                    "authors": [],
                    "last_modified": "",
                }
            )
            continue

        authors_list, dates_list = _get_blame(filepath)
        # Collect authors for a window of ±5 lines around the heading line
        start = max(0, line_num - 5)
        end = min(len(authors_list), line_num + 6)
        window_authors = authors_list[start:end]
        window_dates = dates_list[start:end]

        if not window_authors:
            sections.append(
                {
                    "section_id": hid,
                    "heading": heading_text,
                    "file": filepath,
                    "line": line_num + 1,
                    "authors": [],
                    "last_modified": "",
                }
            )
            continue

        author_counts = Counter(window_authors)
        total = len(window_authors)
        top = [
            {"name": name, "lines": cnt, "pct": round(cnt / total * 100, 1)}
            for name, cnt in author_counts.most_common(max_authors)
        ]
        last_mod = max(window_dates) if window_dates else ""

        sections.append(
            {
                "section_id": hid,
                "heading": heading_text,
                "file": filepath,
                "line": line_num + 1,
                "authors": top,
                "last_modified": last_mod,
            }
        )

    logging.info(f"Section attribution: analysed {len(sections)} heading(s)")
    return sections


def _parse_blame(blame_output: str) -> tuple[list[str], list[str]]:
    """Parse git blame --line-porcelain output.

    Returns:
        Tuple of (author_names, dates) lists, one entry per line.
    """
    authors: list[str] = []
    dates: list[str] = []
    current_author = ""
    current_date = ""

    for line in blame_output.splitlines():
        if line.startswith("author "):
            current_author = line[7:]
        elif line.startswith("author-time "):
            # Unix timestamp — just store as-is for comparison
            current_date = line[12:]
        elif line.startswith("\t"):
            # This is a content line — commit the current entry
            if current_author:
                authors.append(current_author)
                dates.append(current_date)

    return authors, dates


def write_attribution(data: dict, output_path: Path) -> None:
    """Write attribution data as JSON.

    Args:
        data: Attribution dict from :func:`generate_attribution`.
        output_path: Destination file path.
    """
    output_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    logging.info(f"Attribution data written to {output_path}")


def render_attribution_html(data: dict) -> str:
    """Render attribution data as an HTML page.

    Args:
        data: Attribution dict from :func:`generate_attribution`.

    Returns:
        Complete HTML string.
    """
    import html as _html

    summary = data.get("summary", {})
    files = data.get("files", [])
    authors = data.get("authors", {})

    # Author ranking rows
    author_rows = ""
    for name, lines in sorted(authors.items(), key=lambda x: -x[1]):
        author_rows += f'<tr><td>{_html.escape(name)}</td><td class="num">{lines:,}</td></tr>\n'

    # File rows
    file_rows = ""
    for f in files:
        author_str = ", ".join(f"{a['name']} ({a['pct']}%)" for a in f["authors"])
        file_rows += (
            f"<tr><td><code>{_html.escape(f['file'])}</code></td>"
            f'<td class="num">{f["total_lines"]:,}</td>'
            f'<td class="num">{f["unique_authors"]}</td>'
            f"<td>{_html.escape(author_str)}</td></tr>\n"
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Contributor Attribution</title>
<style>
body {{ font-family: system-ui, sans-serif; max-width: 1000px; margin: 2em auto; }}
h1 {{ font-size: 1.4em; }}
h2 {{ font-size: 1.15em; margin-top: 1.5em; }}
.summary {{ color: #666; }}
table {{ border-collapse: collapse; width: 100%; font-size: 0.88em; margin: 0.5em 0; }}
th, td {{ padding: 6px 10px; border: 1px solid #ddd; text-align: left; }}
th {{ background: #f5f5f5; font-weight: 600; }}
td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
</style>
</head>
<body>
<h1>Contributor Attribution</h1>
<p class="summary">{summary.get("total_files", 0)} files,
{summary.get("total_authors", 0)} contributors,
{summary.get("total_lines", 0):,} total lines</p>

<h2>Contributors</h2>
<table>
<thead><tr><th>Author</th><th>Lines</th></tr></thead>
<tbody>{author_rows}</tbody>
</table>

<h2>Files</h2>
<table>
<thead><tr><th>File</th><th>Lines</th><th>Authors</th><th>Top Contributors</th></tr></thead>
<tbody>{file_rows}</tbody>
</table>
</body>
</html>"""
