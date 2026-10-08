"""Bikeshed compilation and code-block post-processing."""

from __future__ import annotations

import logging
import re
import subprocess
from collections.abc import Callable
from pathlib import Path

from specbuild.config import CONFIG
from specbuild.merge import prepare_bikeshed_files

# Regex to strip HTML tags for brace-depth analysis.
_HTML_TAG_RE = re.compile(r"<[^>]+>")

# Number of spaces per indentation level for auto-indent.
_INDENT_SPACES = 4

# Compiled regex matching C/C++ code blocks produced by Bikeshed.
_CODE_BLOCK_RE = re.compile(
    r'(<pre\s+class="[^"]*(?:language-c|language-cpp)[^"]*highlight[^"]*"\s*>)'
    r"(.*?)"
    r"(</pre>)",
    re.DOTALL,
)


# ---------------------------------------------------------------------------
# Shared code-block transform helpers
# ---------------------------------------------------------------------------


def _read_html(html_file: Path) -> str:
    """Read an HTML file, raising IOError on failure."""
    try:
        with open(html_file, encoding="utf8") as f:
            return f.read()
    except OSError as e:
        logging.error(f"Failed to read {html_file}: {e}")
        raise


def _write_html(html_file: Path, content: str) -> None:
    """Write content to an HTML file, raising IOError on failure."""
    try:
        with open(html_file, "w", encoding="utf8") as f:
            f.write(content)
    except OSError as e:
        logging.error(f"Failed to write {html_file}: {e}")
        raise


def _transform_code_blocks(
    html_content: str,
    transform: Callable[[re.Match], str],
) -> tuple[str, int]:
    """Apply *transform* to every C/C++ code block in *html_content*.

    Returns:
        Tuple of (transformed HTML, number of blocks matched).
    """
    count = 0

    def _counted(match: re.Match) -> str:
        nonlocal count
        count += 1
        return transform(match)

    result = _CODE_BLOCK_RE.sub(_counted, html_content)
    return result, count


# ---------------------------------------------------------------------------
# Code-block to striped table conversion
# ---------------------------------------------------------------------------


def _code_block_to_table(match: re.Match) -> str:
    """Convert a single ``<pre>`` code block match into an HTML table."""
    inner_html = match.group(2)
    lines = inner_html.split("\n")
    table_html = '<table class="code-table"><tbody>\n'
    for line in lines:
        if not line:
            continue
        table_html += f"<tr><td>{line}</td></tr>\n"
    table_html += "</tbody></table>"
    return table_html


def convert_code_blocks_to_tables(html_file: Path) -> None:
    """Post-process HTML to convert code blocks to tables with alternating row colors.

    Finds ``<pre class="language-c highlight">`` blocks and converts them to
    tables where each line is a table row.

    Args:
        html_file (Path): Path to the HTML file to process.
    """
    logging.info(f"Converting code blocks to tables in {html_file}")
    html_content = _read_html(html_file)
    html_content, _ = _transform_code_blocks(html_content, _code_block_to_table)
    _write_html(html_file, html_content)
    logging.info("Converted code blocks to tables")


# ---------------------------------------------------------------------------
# Auto-indent by brace depth
# ---------------------------------------------------------------------------


def _indent_code_line(line: str, depth: int) -> str:
    """Strip existing leading whitespace and re-indent to *depth* levels."""
    stripped = line.lstrip()
    if not stripped:
        return ""
    return " " * (_INDENT_SPACES * depth) + stripped


def _auto_indent_block(inner_html: str) -> str:
    """Re-indent a code block based on C-style brace depth.

    Scans each line for ``{`` and ``}`` in the plain-text content (HTML tags
    stripped) and adjusts the leading whitespace accordingly.
    """
    lines = inner_html.split("\n")
    result: list[str] = []
    depth = 0

    for line in lines:
        plain = _HTML_TAG_RE.sub("", line).strip()
        if not plain:
            result.append("")
            continue

        # A line that starts with '}' decreases depth *before* indenting.
        if plain.startswith("}"):
            depth = max(0, depth - 1)

        result.append(_indent_code_line(line, depth))

        # A line that ends with '{' increases depth for subsequent lines.
        if plain.endswith("{"):
            depth += 1

    return "\n".join(result)


def _reindent_code_block(match: re.Match) -> str:
    """Re-indent a single code block match."""
    return match.group(1) + _auto_indent_block(match.group(2)) + match.group(3)


def auto_indent_code_blocks(html_file: Path) -> None:
    """Re-indent ``<pre class="language-c/cpp highlight">`` blocks using
    C-style brace counting.

    Args:
        html_file: Path to the HTML file to process in place.
    """
    logging.info(f"Auto-indenting code blocks in {html_file}")
    html_content = _read_html(html_file)
    html_content, count = _transform_code_blocks(html_content, _reindent_code_block)
    _write_html(html_file, html_content)
    logging.info(f"Auto-indented {count} code blocks")


# ---------------------------------------------------------------------------
# Combined transform (avoids double file I/O)
# ---------------------------------------------------------------------------


def process_code_blocks(
    html_file: Path,
    *,
    auto_indent: bool = False,
    striped_tables: bool = False,
) -> None:
    """Apply code-block transforms in a single read/write pass.

    Args:
        html_file: Path to the HTML file to process in place.
        auto_indent: Re-indent blocks by brace depth.
        striped_tables: Convert blocks to striped HTML tables.
    """
    if not auto_indent and not striped_tables:
        return

    html_content = _read_html(html_file)

    if auto_indent:
        logging.info(f"Auto-indenting code blocks in {html_file}")
        html_content, indent_count = _transform_code_blocks(html_content, _reindent_code_block)
        logging.info(f"Auto-indented {indent_count} code blocks")

    if striped_tables:
        logging.info(f"Converting code blocks to tables in {html_file}")
        html_content, _ = _transform_code_blocks(html_content, _code_block_to_table)
        logging.info("Converted code blocks to tables")

    _write_html(html_file, html_content)


def hack_bs_for_diff(main_bs_file: str, hacked_bs_file: str) -> None:
    """Modify a ``.bs`` file for HTML diff by removing line numbers and syntax highlighting."""
    logging.info(f"Creating hacked .bs file: {main_bs_file} -> {hacked_bs_file}")

    with open(main_bs_file, encoding="utf8") as infile:
        main_bs = infile.read()

    main_bs = "\n".join(line for line in main_bs.splitlines() if "Line Numbers: yes" not in line)
    main_bs = main_bs.replace("```cpp", "```").replace("```c", "```")

    with open(hacked_bs_file, "w", encoding="utf8") as outfile:
        outfile.write(main_bs)


def compile_spec(
    build_dir: str | None = None,
    *,
    diff_hack: bool = False,
    update_header: bool = True,
    convert_sdl: bool = False,
    compact: bool = False,
    remove_editor_notes_flag: bool = False,
    override_date: str | None = None,
    striped_code_blocks: bool = False,
    auto_indent_code: bool = False,
    manifest_path: Path | None = None,
    bikeshed_die_on: str = "nothing",
    include_sections: str | None = None,
    exclude_sections: str | None = None,
) -> None:
    """Compile the specification using Bikeshed.

    Args:
        build_dir: The directory where the spec files are located.
            If None, uses the current directory.
        diff_hack: Whether to use a hacked version for HTML diff.
        update_header: If True, update the header with git info.
        convert_sdl: If True, convert SDL syntax blocks to HTML tables.
        compact: If True, extract Section 9 tables to .h files.
        remove_editor_notes_flag: If True, remove "Note: TODO" paragraphs.
        override_date: Date in YYYY-MM-DD to use instead of commit date.
        striped_code_blocks: If True, convert code blocks to striped tables.
        auto_indent_code: If True, auto-indent C/C++ code blocks by brace depth.
        manifest_path: Path to a manifest file controlling file order.
        bikeshed_die_on: Bikeshed error level that causes a build failure.
            "nothing" (default) suppresses all errors; "warning" fails on
            warnings; "fatal" fails only on fatal errors.
        include_sections: Comma-separated glob patterns for sections to include.
        exclude_sections: Comma-separated glob patterns for sections to exclude.
    """
    logging.debug(
        f"Compile spec in '{build_dir if build_dir else './'}'  "
        f"diff_hack={diff_hack} convert_sdl={convert_sdl} compact={compact} "
        f"remove_editor_notes={remove_editor_notes_flag} "
        f"striped_code_blocks={striped_code_blocks}"
    )

    build_path = Path(build_dir) if build_dir else Path(".")
    root_bs_dir = build_path / CONFIG.bikeshed_dir
    main_bs_file = build_path / CONFIG.main_bs_file
    attachments_dir = build_path / "attachments" if compact else None

    prepare_bikeshed_files(
        directory=root_bs_dir,
        output_file=main_bs_file,
        update_header=update_header,
        convert_sdl=convert_sdl,
        compact=compact,
        attachments_dir=attachments_dir,
        remove_editor_notes_flag=remove_editor_notes_flag,
        override_date=override_date,
        manifest_path=manifest_path,
        include_sections=include_sections,
        exclude_sections=exclude_sections,
    )
    try:
        if diff_hack:
            main_bs_file_hacked = build_path / CONFIG.diff_bs_file
            hack_bs_for_diff(str(main_bs_file), str(main_bs_file_hacked))
            main_index_hacked = main_bs_file_hacked.with_suffix(".html")

            logging.info(f"Run: 'bikeshed spec {main_bs_file_hacked} {main_index_hacked}'")
            subprocess.run(
                [
                    "bikeshed",
                    f"--die-on={bikeshed_die_on}",
                    "spec",
                    str(main_bs_file_hacked),
                    str(main_index_hacked),
                ],
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=300,
            )

            process_code_blocks(
                main_index_hacked, auto_indent=auto_indent_code, striped_tables=striped_code_blocks
            )
        else:
            # Always pass explicit input/output so `main_bs_file` is not
            # constrained to Bikeshed's default `index.bs`.  This lets
            # single-file projects use a working merge target while still
            # producing the canonical `index.html`.
            input_bs = main_bs_file.name
            output_html = "index.html"
            logging.debug(f"Run 'bikeshed spec {input_bs} {output_html}' inside '{build_path}'")
            subprocess.run(
                ["bikeshed", f"--die-on={bikeshed_die_on}", "spec", input_bs, output_html],
                cwd=str(build_path),
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=300,
            )

            index_html = build_path / "index.html"
            if not index_html.exists():
                logging.error(f"Expected Bikeshed output not found: {index_html}")
                # let the rest of the pipeline handle the missing file naturally
            else:
                process_code_blocks(
                    index_html,
                    auto_indent=auto_indent_code,
                    striped_tables=striped_code_blocks,
                )

    except subprocess.CalledProcessError as e:
        logging.error(f"Failed to compile the spec: {e}")
        if hasattr(e, "stderr") and e.stderr:
            for line in e.stderr.strip().splitlines()[-20:]:
                logging.error(f"  bikeshed: {line}")
        raise
