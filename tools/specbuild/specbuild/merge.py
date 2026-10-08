"""Merge ``.bs`` source files, manifest parsing, and editor-note removal.

This module handles the assembly of individually-authored Bikeshed source
files into a single ``index.bs`` ready for Bikeshed compilation.  Along the
way it can optionally update header metadata, convert SDL syntax blocks to
HTML tables, extract tables into compact attachment files, and strip editor
notes.
"""

from __future__ import annotations

import fnmatch
import logging
import re
import shutil
from pathlib import Path

from specbuild.analysis.tables import create_combined_header, extract_tables_from_section9
from specbuild.config import CONFIG
from specbuild.enhancements.symbolstable import sort_symbols_table
from specbuild.git import get_branch_info
from specbuild.sdl import convert_sdl_to_html_table, load_descriptors, load_symbols_from_spec

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Pattern matching filenames that start with a digit (e.g. "01_Scope.bs").
# Used both in manifest parsing and in the fallback glob to enforce a
# consistent ordering convention.
_NUMBERED_FILENAME_RE = re.compile(r"^\d+")

# Matches an editor note: a paragraph whose first line starts with
# "Note: TODO" followed by any continuation lines (non-blank).
_EDITOR_NOTE_RE = re.compile(
    r"Note:\s*TODO[^\n]*(?:\n(?!\n)[^\n]*)*",
    re.MULTILINE,
)

# Matches runs of three or more consecutive newlines (used to collapse
# whitespace left behind after removing editor notes).
_EXCESS_BLANK_LINES_RE = re.compile(r"\n\n\n+")

# Matches the ``Date: YYYY-MM-DD`` metadata line in the Bikeshed header.
_HEADER_DATE_RE = re.compile(r"Date:\s*\d{4}-\d{2}-\d{2}")

# Matches fenced SDL code blocks: ```sdl or ```cpp (both used by different specs).
_SDL_CODE_BLOCK_RE = re.compile(r"```(?:sdl|cpp)\n(.*?)```", re.DOTALL)


# ---------------------------------------------------------------------------
# Editor-note removal
# ---------------------------------------------------------------------------


def remove_editor_notes(content: str, filename: str) -> tuple[str, int]:
    """Remove editor notes (paragraphs starting with "Note: TODO") from content.

    Args:
        content: The file content to process.
        filename: Name of the file being processed (for logging).

    Returns:
        Tuple of (modified_content, count_of_removed_notes).
    """
    modified_content, count = _EDITOR_NOTE_RE.subn("", content)

    if count > 0:
        modified_content = _EXCESS_BLANK_LINES_RE.sub("\n\n", modified_content)
        logging.info(f"  Removed {count} editor note(s) from {filename}")
        return modified_content, count

    return content, 0


# ---------------------------------------------------------------------------
# Manifest parsing
# ---------------------------------------------------------------------------


def parse_manifest(manifest_path: Path, directory: Path) -> list:
    """Parse a manifest file and return an ordered list of .bs file Paths.

    The manifest file supports:
    - ``#`` comments and blank lines (ignored)
    - ``!filename.bs`` to explicitly exclude a file (suppresses warnings)
    - ``filename.bs`` to include a file in the listed order
    - ``[front-matter]`` section (skipped here; see :func:`parse_manifest_front_matter`)

    Args:
        manifest_path (Path): Path to the manifest file.
        directory (Path): The directory containing .bs files.

    Returns:
        list: Ordered list of Path objects for included files.

    Raises:
        FileNotFoundError: If the manifest file does not exist.
        ValueError: If no files are included after parsing.
    """
    if not manifest_path.exists():
        raise FileNotFoundError(f"Manifest file not found: {manifest_path}")

    included = []
    excluded = set()
    seen = set()
    in_section = None

    with manifest_path.open("r", encoding="utf8") as f:
        for line_num, raw_line in enumerate(f, start=1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue

            if line.startswith("[") and line.endswith("]"):
                section_name = line[1:-1].strip().lower()
                # [files] or [] returns to the default file-list mode
                in_section = None if section_name in ("", "files") else section_name
                continue

            if in_section is not None:
                continue

            if line.startswith("!"):
                filename = line[1:].strip()
                if filename in seen:
                    logging.warning(
                        f"Manifest line {line_num}: duplicate entry '{filename}' (ignored)"
                    )
                    continue
                seen.add(filename)
                excluded.add(filename)
                filepath = directory / filename
                if not filepath.exists():
                    logging.warning(
                        f"Manifest line {line_num}: excluded file '{filename}' not found on disk"
                    )
                else:
                    logging.debug(f"Manifest: excluding '{filename}'")
            else:
                filename = line
                if filename in seen:
                    logging.warning(
                        f"Manifest line {line_num}: duplicate entry '{filename}' (ignored)"
                    )
                    continue
                seen.add(filename)
                filepath = directory / filename
                if not filepath.exists():
                    logging.warning(
                        f"Manifest line {line_num}: file '{filename}' not found on disk (skipped)"
                    )
                else:
                    included.append(filepath)

    on_disk = {
        f.name
        for f in directory.iterdir()
        if f.suffix == ".bs" and _NUMBERED_FILENAME_RE.match(f.name)
    }
    unmentioned = on_disk - seen
    for name in sorted(unmentioned):
        logging.warning(
            f"Manifest: file '{name}' exists on disk but is not listed in manifest (not included)"
        )

    if not included:
        raise ValueError(f"Manifest '{manifest_path}' contains no files to include")

    logging.debug(f"Manifest: {len(included)} file(s) included, {len(excluded)} excluded")
    return included


def parse_manifest_front_matter(manifest_path: Path) -> list | None:
    """Parse the ``[front-matter]`` section of a manifest file.

    Returns the ordered list of front-matter element keywords (e.g. ``toc``,
    ``lof``, ``lot``) that controls their placement order in PDF output.

    Args:
        manifest_path (Path): Path to the manifest file.

    Returns:
        list: Ordered list of front-matter keywords, or None if no
        ``[front-matter]`` section exists.
    """
    if not manifest_path.exists():
        return None

    VALID_FRONT_MATTER = {"toc", "lof", "lot"}
    order = []
    seen = set()
    in_front_matter = False

    with manifest_path.open("r", encoding="utf8") as f:
        for line_num, raw_line in enumerate(f, start=1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue

            if line.startswith("[") and line.endswith("]"):
                section = line[1:-1].strip().lower()
                in_front_matter = section == "front-matter"
                continue

            if not in_front_matter:
                continue

            keyword = line.lower()
            if keyword not in VALID_FRONT_MATTER:
                logging.warning(
                    f"Manifest line {line_num}: unknown front-matter entry '{line}' (ignored)"
                )
                continue
            if keyword in seen:
                logging.warning(
                    f"Manifest line {line_num}: duplicate front-matter entry '{keyword}' (ignored)"
                )
                continue
            seen.add(keyword)
            order.append(keyword)

    if not order:
        return None

    logging.debug(f"Manifest: front-matter order: {', '.join(order)}")
    return order


# ---------------------------------------------------------------------------
# Per-file content transforms (used during merge)
# ---------------------------------------------------------------------------


def _update_header_metadata(content: str, directory: Path, override_date: str | None) -> str:
    """Replace date and version placeholders in the Bikeshed header file.

    Args:
        content: Raw text of the header ``.bs`` file.
        directory: The ``.bs`` source directory (passed to ``get_branch_info``).
        override_date: Explicit date string (YYYY-MM-DD) or ``None`` to use
            the commit date.

    Returns:
        str: Updated header content.
    """
    branch_name, sha, spec_date = get_branch_info(directory, override_date=override_date)

    content = _HEADER_DATE_RE.sub(f"Date: {spec_date}", content)

    version_url = f"{CONFIG.repo_browse_url}{branch_name}"
    content = content.replace(CONFIG.version_url_placeholder, version_url)
    content = content.replace(CONFIG.version_text_placeholder, f"{branch_name}@{sha}")

    logging.debug(f"Update bikeshed header: commit_date={spec_date} branch={branch_name}@{sha}")
    return content


def _extract_compact_tables(content: str, filepath: Path, attachments_dir: Path) -> str:
    """Extract tables from Section 9 into attachment ``.h`` files.

    Args:
        content: Raw text of the tables ``.bs`` file.
        filepath: Path to the source file (used by the extractor).
        attachments_dir: Directory where ``.h`` files will be written.

    Returns:
        str: Content with tables replaced by include directives.
    """
    logging.info(f"Extracting tables from {filepath.name} to {attachments_dir}")
    content = extract_tables_from_section9(filepath, attachments_dir, content=content)
    create_combined_header(attachments_dir)
    return content


def _convert_sdl_blocks(content: str, filename: str) -> str:
    """Convert fenced SDL code blocks (``cpp``) to HTML table markup.

    Args:
        content: Raw text of a ``.bs`` file.
        filename: Filename for logging purposes.

    Returns:
        str: Content with SDL code blocks replaced by HTML ``<div>`` wrappers.
    """
    logging.debug(f"Converting SDL syntax blocks to HTML tables in {filename}")

    def _sdl_block_to_html(match: re.Match) -> str:
        """Replace a single fenced SDL code block with an HTML table."""
        code_content = match.group(1)
        html_table = convert_sdl_to_html_table(code_content)
        return f'<div class="sdl-syntax-wrapper">\n{html_table}\n</div>'

    return _SDL_CODE_BLOCK_RE.sub(_sdl_block_to_html, content)


# ---------------------------------------------------------------------------
# Main merge entry point
# ---------------------------------------------------------------------------


def prepare_bikeshed_files(
    directory: Path,
    output_file: Path,
    *,
    update_header: bool = False,
    convert_sdl: bool = False,
    compact: bool = False,
    attachments_dir: Path | None = None,
    remove_editor_notes_flag: bool = False,
    override_date: str | None = None,
    manifest_path: Path | None = None,
    include_sections: str | None = None,
    exclude_sections: str | None = None,
) -> None:
    """Merge all ``.bs`` files in *directory* into a single *output_file*.

    Args:
        directory: The directory containing ``.bs`` files to be merged.
        output_file: The output file path where the merged content
            will be written.
        update_header: If ``True``, updates the date and version in the header.
        convert_sdl: If ``True``, converts SDL syntax blocks to HTML tables.
        compact: If ``True``, extracts tables from Section 9 to ``.h`` files.
        attachments_dir: Directory where ``.h`` files will be written in
            compact mode.
        remove_editor_notes_flag: If ``True``, removes editor notes starting
            with ``Note: TODO``.
        override_date: Date to use instead of commit date (``YYYY-MM-DD``).
        manifest_path: Path to a manifest file controlling file order and
            inclusion.
        include_sections: Comma-separated glob patterns for sections to include.
        exclude_sections: Comma-separated glob patterns for sections to exclude.
    """
    files = _resolve_file_list(
        directory,
        manifest_path,
        include_sections=include_sections,
        exclude_sections=exclude_sections,
        output_file=output_file,
    )

    logging.debug(f"Merging {len(files)} markdown files from {directory} into {output_file}")
    if remove_editor_notes_flag:
        logging.debug(
            'Editor notes removal enabled - removing paragraphs starting with "Note: TODO"'
        )

    if convert_sdl:
        # Use spec-specific SDL descriptors config if configured, otherwise
        # fall back to the specbuild package default.
        descriptors_cfg: Path | None = None
        if CONFIG.sdl_descriptors_file:
            descriptors_cfg = Path(CONFIG.sdl_descriptors_file)
            if not descriptors_cfg.is_absolute():
                descriptors_cfg = Path(".") / descriptors_cfg
        load_descriptors(descriptors_cfg)
        load_symbols_from_spec(directory)

    with output_file.open("w", encoding="utf8") as outfile:
        for filepath in files:
            content = _process_single_file(
                filepath,
                directory,
                update_header=update_header,
                convert_sdl=convert_sdl,
                compact=compact,
                attachments_dir=attachments_dir,
                remove_editor_notes_flag=remove_editor_notes_flag,
                override_date=override_date,
            )
            outfile.write(content)

    _copy_footer(directory)


def _resolve_file_list(
    directory: Path,
    manifest_path: Path | None,
    *,
    include_sections: str | None = None,
    exclude_sections: str | None = None,
    output_file: Path | None = None,
) -> list[Path]:
    """Return the ordered list of ``.bs`` files to merge.

    Uses the manifest if provided; otherwise falls back to sorting all
    ``.bs`` files in *directory* alphabetically.  Applies include/exclude
    section filtering when specified.  When *output_file* is given, it
    is removed from the list so a previous build's merged output (or the
    single-file source-equals-output collision) does not feed back into
    the new merge.

    Args:
        directory: The ``.bs`` source directory.
        manifest_path: Optional manifest file controlling order/inclusion.
        include_sections: Comma-separated glob patterns for sections to include.
        exclude_sections: Comma-separated glob patterns for sections to exclude.
        output_file: Path the merge will write to; excluded from the
            returned list to avoid self-merging.

    Returns:
        list[Path]: Ordered file paths.
    """
    if manifest_path is not None:
        files = parse_manifest(manifest_path, directory)
    else:
        files = sorted(f for f in directory.iterdir() if f.suffix == ".bs")
        logging.debug(
            f"No manifest found in {directory}; merging {len(files)} .bs file(s) "
            f"in alphabetical order"
        )

    if output_file is not None:
        out_resolved = output_file.resolve()
        files = [f for f in files if f.resolve() != out_resolved]

    if include_sections or exclude_sections:
        files = _filter_sections(files, include_sections, exclude_sections)

    return files


def _filter_sections(
    files: list[Path],
    include_patterns: str | None,
    exclude_patterns: str | None,
) -> list[Path]:
    """Filter a file list by include/exclude glob patterns.

    Patterns are matched against the file stem (e.g. ``scope``, ``annex_a_assembly``)
    using case-insensitive shell-style globbing.  The header file is always
    included to ensure valid Bikeshed output.

    Args:
        files: Ordered list of ``.bs`` file paths.
        include_patterns: Comma-separated glob patterns (e.g. ``'header,scope,terms'``).
        exclude_patterns: Comma-separated glob patterns (e.g. ``'annex_*,bibliography'``).

    Returns:
        Filtered list preserving the original order.
    """
    header_stem = Path(CONFIG.header_file).stem.lower()

    # Pre-parse patterns once (avoid re-splitting per file)
    inc_pats = (
        [p.strip() for p in include_patterns.split(",") if p.strip()] if include_patterns else []
    )
    exc_pats = (
        [p.strip() for p in exclude_patterns.split(",") if p.strip()] if exclude_patterns else []
    )

    def _matches(stem: str, patterns: list[str]) -> bool:
        """Return True if *stem* matches any pattern in the list."""
        return any(fnmatch.fnmatch(stem.lower(), pat.lower()) for pat in patterns)

    original_count = len(files)
    result = []

    for f in files:
        stem = f.stem.lower()

        # Always include the header file
        if stem == header_stem:
            result.append(f)
            continue

        # Apply include filter: if specified, file must match at least one pattern
        if inc_pats and not _matches(f.stem, inc_pats):
            logging.debug(f"Section filter: excluding '{f.name}' (not in --include-sections)")
            continue

        # Apply exclude filter: if specified, file must not match any pattern
        if exc_pats and _matches(f.stem, exc_pats):
            logging.debug(f"Section filter: excluding '{f.name}' (matched --exclude-sections)")
            continue

        result.append(f)

    filtered_count = original_count - len(result)
    if filtered_count:
        logging.info(f"Section filter: {len(result)} files included, {filtered_count} excluded")

    return result


def _process_single_file(
    filepath: Path,
    directory: Path,
    *,
    update_header: bool,
    convert_sdl: bool,
    compact: bool,
    attachments_dir: Path | None,
    remove_editor_notes_flag: bool,
    override_date: str | None,
) -> str:
    """Read a single ``.bs`` file and apply all enabled transforms.

    Args:
        filepath: Path to the ``.bs`` file.
        directory: The parent ``.bs`` source directory.
        update_header: Replace header metadata placeholders.
        convert_sdl: Convert SDL code blocks to HTML.
        compact: Extract tables to attachment files.
        attachments_dir: Destination for extracted attachment files.
        remove_editor_notes_flag: Strip ``Note: TODO`` paragraphs.
        override_date: Explicit date override for the header.

    Returns:
        str: Transformed file content ready for writing.
    """
    logging.debug(f"Appending {filepath}")
    with filepath.open("r", encoding="utf8") as infile:
        content = infile.read()

    if update_header and filepath == directory / CONFIG.header_file:
        content = _update_header_metadata(content, directory, override_date)

    if compact and filepath.name == CONFIG.tables_file:
        if attachments_dir is None:
            logging.error("attachments_dir must be provided in compact mode")
            raise ValueError("attachments_dir is required for compact mode")
        content = _extract_compact_tables(content, filepath, attachments_dir)

    if convert_sdl and filepath.name in CONFIG.sdl_files:
        content = _convert_sdl_blocks(content, filepath.name)

    if CONFIG.sort_symbols_file and filepath.name == CONFIG.sort_symbols_file:
        content, rows_sorted = sort_symbols_table(content)
        logging.info(f"Sorted {rows_sorted} row(s) in {filepath.name} symbols table")

    if remove_editor_notes_flag:
        content, _ = remove_editor_notes(content, filepath.name)

    return content


def _copy_footer(directory: Path) -> None:
    """Copy ``footer.include`` from *directory* to the working directory if it exists.

    Args:
        directory: The ``.bs`` source directory.
    """
    footer_file = directory / "footer.include"
    if not footer_file.exists():
        # Optional file — most specs don't have one.  Quiet by default.
        logging.debug(f"No footer.include in {directory} (optional)")
        return
    try:
        shutil.copyfile(footer_file, Path("./footer.include"))
        logging.debug(f"Copied footer.include from {footer_file}")
    except OSError as exc:
        logging.error(f"Failed to copy footer.include: {exc}")
