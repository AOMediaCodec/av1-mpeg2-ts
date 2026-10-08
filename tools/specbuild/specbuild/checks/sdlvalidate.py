"""SDL cross-reference validation for compiled HTML specifications.

Validates that function calls within SDL syntax tables reference
defined SDL elements elsewhere in the specification.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from specbuild.utils import HEADING_TAGS, find_nearest_heading, get_bs4, read_html

# C language constructs that are not SDL element references
_C_BUILTINS = frozenset(
    {
        "if",
        "else",
        "for",
        "while",
        "do",
        "return",
        "switch",
        "case",
        "break",
        "continue",
        "sizeof",
        "typedef",
        "struct",
        "enum",
        "union",
        "goto",
        "default",
        "static",
        "const",
        "void",
        "int",
        "unsigned",
        "signed",
        "char",
        "short",
        "long",
        "float",
        "double",
    }
)

# SDL descriptor functions -- not cross-references
_DESCRIPTOR_FUNCTIONS = frozenset(
    {
        "f",
        "uvlc",
        "svlc",
        "le",
        "leb128",
        "su",
        "ns",
        "rg",
        "tu",
        "L",
        "S",
        "NS",
        "range",
    }
)

# Combined ignore set
_IGNORE_NAMES = _C_BUILTINS | _DESCRIPTOR_FUNCTIONS

# Regex to extract function calls: identifier followed by parenthesised args.
# Captures just the function name (group 1).
_FUNC_CALL_RE = re.compile(r"\b([A-Za-z_]\w*)\s*\(")

# Regex to extract function name from a header like "install_component(part) {"
_FUNC_DEF_RE = re.compile(r"^([A-Za-z_]\w*)\s*\(")

# Pattern matching valid SDL descriptor syntax in table cells.
# Covers: f(n), f(n,m), u(n), i(n), b(n), ae(v), se(n), ue(n), leb128(n),
# uvlc(n), ns(n), su(n), delta_*(n), fixed(n), variable(n), golomb(n).
_VALID_DESCRIPTOR_PATTERN = re.compile(
    r"^(?:f|u|i|b|ae|se|ue|le|leb128|uvlc|svlc|ns|su|rg|tu|delta_\w+)\(\d+(?:,\d+)?\)$"
    r"|^(?:fixed|variable|golomb)\(\d+\)$"
)


def validate_sdl_references(html_path: Path) -> list[dict]:
    """Validate SDL cross-references in a compiled HTML file.

    File-based wrapper around :func:`validate_sdl_references_soup`.

    Args:
        html_path: Path to the compiled HTML specification.

    Returns:
        A list of dicts describing unresolved SDL function references,
        each with keys ``name``, ``table``, and ``context``.
    """
    try:
        get_bs4()
    except ImportError:
        logging.warning("BeautifulSoup not available, skipping SDL reference validation")
        return []

    logging.info(f"Validating SDL cross-references in {html_path.name}")
    soup = read_html(html_path)
    return validate_sdl_references_soup(soup)


def validate_sdl_references_soup(soup: object) -> list[dict]:
    """Validate SDL cross-references in the parsed HTML.

    Collects defined function names from six sources: SDL syntax table
    headers, ``<dfn>`` elements, section headings, ``<pre>`` pseudo-code
    blocks, inline ``<code>`` elements, and ``<strong>``/``<b>`` prose
    definitions.  Then scans SDL table body cells for function calls and
    reports any reference that does not match a defined name (and is not
    in the ignore list).

    Args:
        soup: BeautifulSoup document (read-only).

    Returns:
        A list of dicts with keys:

        - ``name``: the unresolved function name
        - ``table``: the SDL table header where it was referenced
        - ``context``: nearest heading for user context
    """
    tables = soup.find_all("table", class_="sdl-syntax-table")
    if not tables:
        logging.info("No SDL syntax tables found in the document")
        return []

    logging.info(f"Found {len(tables)} SDL syntax table(s)")

    # ------------------------------------------------------------------
    # Pass 1: collect all defined SDL function names
    # ------------------------------------------------------------------
    defined: set[str] = set()

    # 1a. SDL table headers (primary source)
    for table in tables:
        header_th = table.find("th", class_="sdl-syntax-name")
        if header_th is None:
            continue
        name = _extract_def_name(header_th.get_text(strip=True))
        if name:
            defined.add(name)

    sdl_count = len(defined)
    logging.info(f"Collected {sdl_count} defined SDL function name(s) from table headers")

    # 1b. <dfn> elements that look like function definitions
    for dfn in soup.find_all("dfn"):
        text = dfn.get_text(strip=True)
        name = _extract_def_name(text, allow_bare=False)
        if name and name not in _IGNORE_NAMES:
            defined.add(name)

    dfn_count = len(defined) - sdl_count
    logging.info(f"Collected {dfn_count} additional name(s) from <dfn> elements")

    # 1c. Section headings that define functions (e.g. "4.11.8. ns(n)")
    prev_total = len(defined)
    for heading in soup.find_all(HEADING_TAGS):
        text = heading.get_text(strip=True)
        # Strip leading section numbers like "4.11.8." or "Annex A:"
        stripped = re.sub(r"^[\d.]+\s*", "", text)
        name = _extract_def_name(stripped, allow_bare=False)
        if name and name not in _IGNORE_NAMES:
            defined.add(name)

    heading_count = len(defined) - prev_total
    logging.info(f"Collected {heading_count} additional name(s) from section headings")

    # 1d. <pre> pseudo-code blocks whose first line defines a function
    prev_total = len(defined)
    for pre in soup.find_all("pre"):
        if _in_sdl_table(pre):
            continue
        first_line = pre.get_text().strip().split("\n")[0].strip()
        name = _extract_def_name(first_line, allow_bare=False)
        if name and name not in _IGNORE_NAMES:
            defined.add(name)

    pre_count = len(defined) - prev_total
    logging.info(f"Collected {pre_count} additional name(s) from <pre> blocks")

    # 1e. Inline <code> elements with function signatures in prose
    #     e.g. "<code>Clip3(x, y, z)</code>" — requires name(...) pattern
    prev_total = len(defined)
    for code in soup.find_all("code"):
        if _in_sdl_table(code):
            continue
        if code.find_parent("pre"):
            continue
        text = code.get_text(strip=True)
        name = _extract_def_name(text, allow_bare=False)
        if name and name not in _IGNORE_NAMES:
            defined.add(name)

    code_count = len(defined) - prev_total
    logging.info(f"Collected {code_count} additional name(s) from inline <code> elements")

    # 1f. <strong> / <b> elements with function signatures in prose
    #     e.g. "<strong>get_position( )</strong>: Return the value of..."
    prev_total = len(defined)
    for tag in soup.find_all(("strong", "b")):
        if _in_sdl_table(tag):
            continue
        text = tag.get_text(strip=True)
        name = _extract_def_name(text, allow_bare=False)
        if name and name not in _IGNORE_NAMES:
            defined.add(name)

    strong_count = len(defined) - prev_total
    logging.info(f"Collected {strong_count} additional name(s) from <strong>/<b> elements")
    logging.info(f"Total defined names: {len(defined)}")

    # ------------------------------------------------------------------
    # Pass 2: collect referenced function calls and cross-check
    # ------------------------------------------------------------------
    issues: list[dict] = []

    for table in tables:
        # Determine the defining function name for reporting
        header_th = table.find("th", class_="sdl-syntax-name")
        raw_header = header_th.get_text(strip=True) if header_th else ""
        table_header = _extract_def_name(raw_header) or raw_header or "(unknown)"

        # Nearest heading for user context
        context = find_nearest_heading(table)

        tbody = table.find("tbody")
        if tbody is None:
            continue

        # Gather all body cells that may contain references
        ref_cells = tbody.find_all(
            "td", class_=lambda c: c and c in ("sdl-code", "sdl-var-with-descriptor")
        )

        # Track names already reported for this table to avoid duplicates
        reported_in_table: set[str] = set()

        for cell in ref_cells:
            text = cell.get_text()
            if not text or not text.strip():
                continue

            for match in _FUNC_CALL_RE.finditer(text):
                fname = match.group(1)
                if fname in _IGNORE_NAMES:
                    continue
                if fname in defined:
                    continue
                if fname in reported_in_table:
                    continue
                reported_in_table.add(fname)
                issues.append(
                    {
                        "name": fname,
                        "table": table_header,
                        "context": context,
                    }
                )

        # Validate SDL descriptor syntax in this table
        descriptor_issues = validate_sdl_descriptor_syntax(table)
        for desc_issue in descriptor_issues:
            issues.append(
                {
                    "name": desc_issue["descriptor"],
                    "table": table_header,
                    "context": f"row {desc_issue['row']}: {desc_issue['detail']}",
                }
            )

    logging.info(f"SDL cross-reference check complete: {len(issues)} unresolved reference(s)")
    return issues


def validate_sdl_descriptor_syntax(table_el: object) -> list[dict]:
    """Validate SDL descriptor syntax in a table element.

    Checks that descriptor column values (2nd or 3rd column) match known
    SDL descriptor types.  Only cells that contain ``(`` are checked —
    plain identifier cells are skipped to avoid false positives.

    Args:
        table_el: A BeautifulSoup ``<table>`` element.

    Returns:
        List of issue dicts with keys ``row``, ``descriptor``, and ``detail``.
    """
    issues: list[dict] = []
    rows = table_el.find_all("tr")
    for row_idx, row in enumerate(rows):
        cells = row.find_all(["td", "th"])
        if len(cells) < 2:
            continue
        # Descriptor is typically in the 2nd or 3rd column (0-indexed: 1 or 2)
        for col_idx in (1, 2):
            if col_idx >= len(cells):
                continue
            cell_text = cells[col_idx].get_text(strip=True)
            if not cell_text:
                continue
            # Only validate cells that look like descriptor expressions
            if "(" not in cell_text:
                continue
            if not _VALID_DESCRIPTOR_PATTERN.match(cell_text):
                issues.append(
                    {
                        "row": row_idx + 1,
                        "descriptor": cell_text,
                        "detail": "Unrecognized SDL descriptor syntax",
                    }
                )
    return issues


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _in_sdl_table(element: object) -> bool:
    """Return True if *element* is inside an SDL syntax table."""
    return element.find_parent("table", class_="sdl-syntax-table") is not None


def _extract_def_name(header_text: str, *, allow_bare: bool = True) -> str | None:
    """Extract a function/element name from text.

    Handles forms like ``install_component(part) {`` by stripping
    trailing braces and extracting the identifier before the ``(``.

    Args:
        header_text: Text that may contain a function definition.
        allow_bare: If ``True`` (default), fall back to extracting a bare
            identifier when no parenthesised form is found.  Set to
            ``False`` to require the ``name(...)`` pattern.

    Returns:
        The function name, or ``None`` if extraction fails.
    """
    text = header_text.strip().rstrip("{").strip()
    m = _FUNC_DEF_RE.match(text)
    if m:
        return m.group(1)
    if not allow_bare:
        return None
    # Fallback: header might be just a name with no parens
    # e.g. "some_table {" — take the first identifier
    ident = re.match(r"^([A-Za-z_]\w*)", text)
    return ident.group(1) if ident else None


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def report_sdl_refs(issues: list[dict], html_path: Path, *, strict: bool = False) -> None:
    """Log SDL cross-reference issues.

    Args:
        issues: List of unresolved reference dicts from
            :func:`validate_sdl_references`.
        html_path: Path shown in log messages.
        strict: If ``True``, exit with error code when issues are found.
    """
    if not issues:
        logging.info("All SDL cross-references are valid")
        return

    logging.warning(f"Found {len(issues)} unresolved SDL cross-reference(s) in {html_path.name}:")
    for ref in issues:
        logging.warning(f'  {ref["name"]}() referenced in "{ref["table"]}" near: {ref["context"]}')

    if strict:
        raise SystemExit(1)
