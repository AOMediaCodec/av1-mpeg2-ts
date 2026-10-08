"""Detect and reconstruct SDL syntax tables from Word documents.

Two kinds of syntax are supported:

* **Video-coding syntax tables** (H.265/HEVC style) — two-column Word tables
  where column 1 holds variable names / control-flow and column 2 holds
  descriptors like ``u(8)``, ``se(v)``, ``f(1)``, etc.

* **ISOBMFF SDL code** (CMAF / ISO 14496-12 style) — verbatim code paragraphs
  whose text begins with ``aligned(8) class ...`` or similar ISOBMFF box
  definition syntax.  These arrive as ``Code (-)`` style paragraphs, not as
  tables.

The :func:`detect_table_syntax` function dispatches to the right detector
based on the ``flavor`` hint.  Pass ``flavor="h265"`` for video-coding specs,
``flavor="cmaf"`` for ISO publication files, or ``flavor="auto"`` to try both.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from docx.table import Table

# ---------------------------------------------------------------------------
# Patterns — video-coding SDL (H.265 style)
# ---------------------------------------------------------------------------

#: Matches SDL descriptor calls: u(8), ue(v), se(v), f(1), b(8), ae(v), etc.
SDL_DESCRIPTOR_RE = re.compile(
    r"\b(?:u|ue|se|f|b|ae|st|tu|ce|me|ns|leb128|uvlc)\s*\(\s*(?:v|\d+)\s*\)"
)

#: Matches a function-style opening: ``name( ) {`` or ``name() {``
_FUNC_OPEN_RE = re.compile(r"^(\w[\w\s]*?)\s*\([^)]*\)\s*\{?\s*$")

_CONTROL_FLOW_KEYWORDS = frozenset(
    {"if", "else", "else if", "for", "while", "do", "switch", "case", "default", "break", "return"}
)

# ---------------------------------------------------------------------------
# Patterns — ISOBMFF SDL code (CMAF style)
# ---------------------------------------------------------------------------

#: Matches ISOBMFF box class declarations: ``aligned(8) class FooBox ...``
ISOBMFF_CLASS_RE = re.compile(r"^\s*aligned\s*\(\s*8\s*\)\s+class\s+\w", re.IGNORECASE)

#: Matches ISO 14496-12 bit-field declarations: ``bit(N)`` / ``unsigned int(N)``
ISOBMFF_FIELD_RE = re.compile(r"\b(?:unsigned\s+)?(?:int|bit)\s*\(\s*\d+\s*\)", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _cell_text(cell) -> str:
    return cell.text.strip()


def _col_count(table: Table) -> int:
    if not table.rows:
        return 0
    return len(table.rows[0].cells)


# ---------------------------------------------------------------------------
# Detection — video-coding syntax tables
# ---------------------------------------------------------------------------


def is_sdl_table(table: Table) -> bool:
    """Check if *table* is an H.265-style two-column SDL syntax table."""
    if _col_count(table) != 2:
        return False
    rows = table.rows
    if len(rows) < 3:
        return False

    first_col1 = _cell_text(rows[0].cells[0])
    first_col2 = _cell_text(rows[0].cells[1])

    descriptor_hits = 0
    any_col2_nonempty = False
    for row in rows:
        col2_text = _cell_text(row.cells[1])
        if col2_text:
            any_col2_nonempty = True
        if SDL_DESCRIPTOR_RE.search(col2_text):
            descriptor_hits += 1
            if descriptor_hits >= 2:
                return True

    if "Descriptor" in first_col2 and descriptor_hits >= 1:
        return True
    if first_col1.rstrip().endswith("{") and any_col2_nonempty:
        return True
    if descriptor_hits >= 1 and _FUNC_OPEN_RE.match(first_col1):
        return True
    return False


# ---------------------------------------------------------------------------
# Detection — ISOBMFF SDL code paragraphs
# ---------------------------------------------------------------------------


def is_isobmff_code(text: str) -> bool:
    """Return ``True`` if *text* looks like an ISOBMFF box class definition.

    Matches ``aligned(8) class FooBox ...`` declarations typical in ISO
    14496-12 (ISOBMFF) and documents derived from it such as CMAF.
    """
    return bool(ISOBMFF_CLASS_RE.match(text))


# ---------------------------------------------------------------------------
# Flavor-aware dispatch
# ---------------------------------------------------------------------------


def detect_table_syntax(
    table: Table,
    flavor: str = "auto",
    custom_descriptor_re: re.Pattern | None = None,
) -> str | None:
    """Check whether *table* is a syntax table and return its kind.

    Args:
        table:               A python-docx ``Table``.
        flavor:              ``"h265"``, ``"cmaf"``, ``"iso"``, ``"itu-t"``,
                             or ``"auto"``.
        custom_descriptor_re: Override the descriptor detection regex.
                             When supplied, replaces :data:`SDL_DESCRIPTOR_RE`
                             for the video-coding check.

    Returns:
        ``"video_syntax"`` for H.265-style two-column SDL tables,
        ``"isobmff"`` for tables containing ISOBMFF box fields,
        or ``None`` if the table is a plain data table.
    """
    # CMAF: tables are always data tables.  ISOBMFF SDL lives in Code (-)
    # paragraphs, not in Word tables.
    if flavor == "cmaf":
        return None

    # All other flavors — including ``iso`` (e.g. ISO/IEC 23008-2 HEVC FDIS)
    # and ``itu-t`` (e.g. ITU-T H.265 publication) — use the H.265-style
    # video-coding descriptor detection.  Both organizations publish the
    # same standard as parallel text with identical 2-column syntax tables
    # ("syntax body | Descriptor" with descriptors like ``u(8)``, ``ue(v)``).
    check_re = custom_descriptor_re or SDL_DESCRIPTOR_RE
    # Temporarily patch SDL_DESCRIPTOR_RE if a custom pattern is supplied
    if custom_descriptor_re is not None:
        # We can't rebind the module-level const, so check inline
        if _col_count(table) == 2 and len(table.rows) >= 3:
            rows = table.rows
            first_col1 = _cell_text(rows[0].cells[0])
            first_col2 = _cell_text(rows[0].cells[1])
            hits = sum(1 for row in rows if check_re.search(_cell_text(row.cells[1])))
            any_col2 = any(_cell_text(r.cells[1]) for r in rows)
            if hits >= 2:
                return "video_syntax"
            if "Descriptor" in first_col2 and hits >= 1:
                return "video_syntax"
            if first_col1.rstrip().endswith("{") and any_col2:
                return "video_syntax"
            if hits >= 1 and _FUNC_OPEN_RE.match(first_col1):
                return "video_syntax"
    elif is_sdl_table(table):
        return "video_syntax"

    return None


# ---------------------------------------------------------------------------
# Reconstruction — video-coding SDL
# ---------------------------------------------------------------------------


def _extract_func_name(first_row_text: str) -> str:
    m = _FUNC_OPEN_RE.match(first_row_text.strip())
    if m:
        return m.group(0).rstrip()
    return first_row_text.strip().rstrip("{").strip()


def _preserve_indentation(text: str) -> str:
    return text.replace("\u00a0", " ")


def reconstruct_sdl(table: Table) -> str:
    """Convert an H.265-style syntax table to a fenced SDL code block."""
    rows = table.rows
    if not rows:
        return ""

    lines: list[str] = []
    func_header = _extract_func_name(_cell_text(rows[0].cells[0]))
    if not func_header.rstrip().endswith("{"):
        func_header += " {"
    lines.append(func_header)

    for row in rows[1:]:
        col1 = _preserve_indentation(_cell_text(row.cells[0]))
        col2 = _cell_text(row.cells[1])
        if not col1 and not col2:
            continue
        if col1.strip() == "}" and not col2:
            lines.append("}")
            continue
        if col2:
            padding = max(2, 50 - len(col1))
            lines.append(f"{col1}{' ' * padding}{col2}")
        else:
            lines.append(col1)

    if lines and lines[-1].strip() != "}":
        lines.append("}")

    return "```sdl\n" + "\n".join(lines) + "\n```"


def _raw_cell_text(cell) -> str:
    return cell.text.replace("\u00a0", " ")


def reconstruct_syntax_table(table: Table) -> str:
    """Convert an H.265-style syntax table to a styled HTML ``<table>``."""
    import html as html_mod

    rows = table.rows
    if not rows:
        return ""

    lines: list[str] = ['<table class="sdl-syntax-table">']
    for i, row in enumerate(rows):
        raw_col1 = _raw_cell_text(row.cells[0])
        col1 = raw_col1.strip()
        col2 = _cell_text(row.cells[1]) if len(row.cells) > 1 else ""

        if not col1 and not col2:
            continue

        col1_esc = html_mod.escape(col1)
        col2_esc = html_mod.escape(col2)
        indent_px = (len(raw_col1) - len(raw_col1.lstrip())) * 8
        style = f' style="padding-left: {indent_px}px"' if indent_px else ""

        if i == 0 and ("Descriptor" in col2 or "{" in col1):
            lines.append(
                f'  <tr><th class="sdl-syntax-name"{style}>'
                f"<code>{col1_esc}</code></th>"
                f'<th class="sdl-descriptor-header">{col2_esc}</th></tr>'
            )
        elif col2 and SDL_DESCRIPTOR_RE.search(col2):
            lines.append(
                f'  <tr><td class="sdl-var-with-descriptor"{style}>'
                f"<code>{col1_esc}</code></td>"
                f'<td class="sdl-descriptor">{col2_esc}</td></tr>'
            )
        else:
            lines.append(
                f'  <tr><td class="sdl-code"{style}><code>{col1_esc}</code></td><td></td></tr>'
            )

    lines.append("</table>")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Bulk extraction
# ---------------------------------------------------------------------------


def extract_sdl_descriptors(tables: list[Table]) -> set[str]:
    """Extract all unique descriptor types found across SDL tables."""
    descriptors: set[str] = set()
    for table in tables:
        if not is_sdl_table(table):
            continue
        if _col_count(table) < 2:
            continue
        for row in table.rows:
            col2_text = _cell_text(row.cells[1])
            for m in SDL_DESCRIPTOR_RE.finditer(col2_text):
                descriptors.add(m.group())
    if descriptors:
        logging.debug(f"SDL descriptors found: {sorted(descriptors)}")
    return descriptors
