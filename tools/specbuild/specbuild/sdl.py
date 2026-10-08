"""SDL syntax-to-HTML-table converter and symbol resolution.

This module converts SDL (Syntax Description Language) code blocks found in
Bikeshed ``.bs`` source files into styled HTML tables suitable for
specification rendering.  The conversion pipeline is:

1. Load descriptor definitions (function names like ``f``, ``uvlc`` and
   keyword names like ``derived``, ``reserved``) from ``config/sdl_descriptors.cfg``.
2. Optionally load symbol constants (e.g. ``DELTA_DCQUANT_BITS = 5``) from
   the spec source so that descriptors can display resolved numeric values.
3. Parse each SDL code block line-by-line, identify the descriptor and the
   variable/expression, and emit a two-column HTML table (syntax | descriptor).
"""

from __future__ import annotations

import ast
import html
import logging
import re
from pathlib import Path

from specbuild import PROJECT_ROOT
from specbuild.config import CONFIG

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

# Global symbols map for resolving constants in SDL descriptors.
# Populated by :func:`load_symbols_from_spec`.
SYMBOLS_MAP: dict[str, object] = {}

# Descriptor lists loaded from config/sdl_descriptors.cfg.
# Populated by :func:`load_descriptors`.
_DESCRIPTOR_FUNCTIONS: list[str] = []
_DESCRIPTOR_KEYWORDS: list[str] = []
_DESCRIPTORS_LOADED: bool = False

# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

# Matches symbol/value pairs in an HTML table: <td>`SYMBOL`</td> <td ...>`value`</td>
_SYMBOL_TABLE_PATTERN = re.compile(r"<td>`([A-Z_0-9]+)`</td>\s*<td[^>]*>`([^`]+)`</td>")

# Matches upper-case constant names like MAX_SEGMENTS, NUM_REF_FRAMES
_UPPER_CONST_PATTERN = re.compile(r"\b([A-Z_][A-Z0-9_]+)\b")

# Matches C-style comments (block and line)
_COMMENT_PATTERN = re.compile(r"(/\*.*?\*/|//.*)")

# Matches a function-style header line, e.g. "my_func( ) {"
_FUNC_HEADER_PATTERN = re.compile(r"(\w+\s*\([^)]*\)\s*\{?)")

# Maximum iterations when resolving symbol cross-references
_MAX_SYMBOL_RESOLVE_ITERATIONS = 10

# Indentation unit: 1 SDL indent level = 4 spaces = 1 em in HTML.
# Overridden at runtime by CONFIG.sdl_indent_spaces and CONFIG.sdl_indent_em.
_INDENT_SPACES_PER_LEVEL = 4
_INDENT_EM_PER_LEVEL = 1.0


# ---------------------------------------------------------------------------
# Safe arithmetic evaluator (replaces eval() to prevent sandbox escapes)
# ---------------------------------------------------------------------------

_SAFE_BINOPS = {
    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b,
    ast.FloorDiv: lambda a, b: a // b,
    ast.Mod: lambda a, b: a % b,
    ast.LShift: lambda a, b: a << b,
    ast.RShift: lambda a, b: a >> b,
    ast.BitOr: lambda a, b: a | b,
    ast.BitAnd: lambda a, b: a & b,
    ast.BitXor: lambda a, b: a ^ b,
}
_SAFE_UNOPS = {
    ast.USub: lambda a: -a,
    ast.UAdd: lambda a: a,
    ast.Invert: lambda a: ~a,
}


def _safe_eval_int(expr: str) -> int:
    """Evaluate a pure-integer arithmetic expression without using eval().

    Supports: integer literals, +, -, *, //, %, <<, >>, |, &, ^, unary -, ~.
    Raises ``ValueError`` for any other construct (strings, attribute access,
    function calls, etc.) so malicious spec content cannot escape the sandbox.
    """

    def _eval(node: ast.AST) -> int:
        if isinstance(node, ast.Constant) and isinstance(node.value, int):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in _SAFE_BINOPS:
            return _SAFE_BINOPS[type(node.op)](_eval(node.left), _eval(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in _SAFE_UNOPS:
            return _SAFE_UNOPS[type(node.op)](_eval(node.operand))
        if isinstance(node, ast.Expression):
            return _eval(node.body)
        raise ValueError(f"Unsupported expression node: {ast.dump(node)}")

    try:
        tree = ast.parse(expr.strip(), mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"Invalid arithmetic expression: {expr!r}") from exc
    return _eval(tree)


# ---------------------------------------------------------------------------
# Descriptor loading
# ---------------------------------------------------------------------------


def load_descriptors(config_path: Path | None = None) -> None:
    """Load SDL descriptor definitions from a configuration file.

    The file has two sections, ``[functions]`` and ``[keywords]``.
    Lines starting with ``#`` are comments.  See ``config/sdl_descriptors.cfg``
    for the format.

    Args:
        config_path: Path to the config file.  Defaults to
            ``<project_root>/config/sdl_descriptors.cfg``.
    """
    global _DESCRIPTOR_FUNCTIONS, _DESCRIPTOR_KEYWORDS, _DESCRIPTORS_LOADED

    if config_path is None:
        config_path = PROJECT_ROOT / "config" / "sdl_descriptors.cfg"

    if not config_path.exists():
        logging.warning(
            f"SDL descriptors config not found: {config_path}. Using built-in defaults."
        )
        _DESCRIPTOR_FUNCTIONS = [
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
        ]
        _DESCRIPTOR_KEYWORDS = [
            "derived",
            "required",
            "optional",
            "computed",
            "reserved",
        ]
        _DESCRIPTORS_LOADED = True
        return

    functions = []
    keywords = []
    current_section = None

    with config_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("[") and line.endswith("]"):
                current_section = line[1:-1].strip().lower()
                continue
            if current_section == "functions":
                functions.append(line)
            elif current_section == "keywords":
                keywords.append(line)

    _DESCRIPTOR_FUNCTIONS = functions
    _DESCRIPTOR_KEYWORDS = keywords
    _DESCRIPTORS_LOADED = True

    logging.debug(
        f"Loaded SDL descriptors from {config_path}: "
        f"{len(functions)} functions, {len(keywords)} keywords"
    )

    # Pick up indentation config from SpecConfig
    global _INDENT_SPACES_PER_LEVEL, _INDENT_EM_PER_LEVEL
    try:
        from specbuild.config import CONFIG

        _INDENT_SPACES_PER_LEVEL = CONFIG.sdl_indent_spaces
        _INDENT_EM_PER_LEVEL = CONFIG.sdl_indent_em
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Symbol loading
# ---------------------------------------------------------------------------


def load_symbols_from_spec(bikeshed_dir: Path) -> dict[str, object]:
    """Load symbol definitions from the symbols/abbreviated-terms source file.

    Parses the HTML table to extract symbol-to-value mappings and resolves
    expressions that reference other symbols.

    Args:
        bikeshed_dir (Path): Path to the bikeshed directory containing source files.

    Returns:
        dict: Mapping of symbol names to their resolved numeric values.
    """
    global SYMBOLS_MAP

    if not CONFIG.symbols_file:
        # Spec didn't configure a symbols file — quietly skip.
        logging.debug("No symbols_file configured; skipping symbol load.")
        return {}

    symbols_file = bikeshed_dir / CONFIG.symbols_file

    if not symbols_file.exists():
        logging.warning(f"Symbols file not found: {symbols_file}")
        return {}

    logging.debug(f"Loading symbols from {symbols_file}")

    try:
        with symbols_file.open("r", encoding="utf8") as f:
            content = f.read()
    except (OSError, UnicodeDecodeError) as exc:
        logging.error(f"Failed to read symbols file {symbols_file}: {exc}")
        return {}

    symbols = {}

    matches = _SYMBOL_TABLE_PATTERN.finditer(content)

    for match in matches:
        symbol_name = match.group(1)
        value_str = match.group(2).strip()
        symbols[symbol_name] = value_str

    # Resolve expressions iteratively — symbols may reference other symbols,
    # so we loop until all are resolved or we hit the iteration cap.
    for _ in range(_MAX_SYMBOL_RESOLVE_ITERATIONS):
        unresolved_count = 0

        for symbol_name, value_str in list(symbols.items()):
            if isinstance(value_str, int):
                continue

            try:
                eval_str = value_str
                for other_symbol, other_value in symbols.items():
                    if other_symbol != symbol_name and isinstance(other_value, int):
                        eval_str = re.sub(
                            r"\b" + re.escape(other_symbol) + r"\b",
                            str(other_value),
                            eval_str,
                        )

                result = _safe_eval_int(eval_str)
                symbols[symbol_name] = result
            except Exception:
                unresolved_count += 1

        if unresolved_count == 0:
            break

    # Warn once per symbol that could not be resolved after all iterations.
    # (Warnings inside the loop would fire once per iteration — noisy for
    # symbols that depend on other undefined symbols.)
    for symbol_name, value_str in symbols.items():
        if not isinstance(value_str, int):
            logging.warning(
                f"Could not resolve symbol '{symbol_name}' = '{value_str}': "
                "referenced symbol(s) not defined in the symbols table"
            )

    resolved_count = sum(1 for v in symbols.values() if isinstance(v, int))
    logging.debug(f"Loaded {len(symbols)} symbols, resolved {resolved_count} to numeric values")

    SYMBOLS_MAP = symbols
    return symbols


# ---------------------------------------------------------------------------
# Symbol resolution helpers
# ---------------------------------------------------------------------------


def resolve_constants_in_descriptor(descriptor: str) -> str:
    """Resolve constant variable names in a descriptor to their numeric values.

    For example, ``"f(DELTA_DCQUANT_BITS)"`` becomes ``"f(5)"`` if
    ``DELTA_DCQUANT_BITS=5``.

    Args:
        descriptor (str): The descriptor string.

    Returns:
        str: Descriptor with constants resolved to their numeric values.
    """
    if not SYMBOLS_MAP:
        return descriptor

    def replace_symbol(match: re.Match) -> str:
        symbol_name = match.group(1)
        if symbol_name in SYMBOLS_MAP:
            value = SYMBOLS_MAP[symbol_name]
            if isinstance(value, int):
                return str(value)
        return symbol_name

    return _UPPER_CONST_PATTERN.sub(replace_symbol, descriptor)


# ---------------------------------------------------------------------------
# SDL-to-HTML conversion
# ---------------------------------------------------------------------------


def _find_matching_paren(text: str, start_pos: int) -> int:
    """Find the position just past the closing parenthesis matching an opener.

    Args:
        text: The string to scan.
        start_pos: Index immediately *after* the opening ``(``.

    Returns:
        Index one past the matching ``)``, or ``-1`` if unbalanced.
    """
    depth = 1
    pos = start_pos
    while pos < len(text) and depth > 0:
        if text[pos] == "(":
            depth += 1
        elif text[pos] == ")":
            depth -= 1
        pos += 1
    return pos if depth == 0 else -1


def _find_descriptor(line: str) -> tuple[str | None, str]:
    """Identify an SDL descriptor in *line* and split it from the remainder.

    Checks three patterns in priority order:

    1. **Leading function descriptor** — e.g. ``f(1) var_name``
    2. **Trailing function descriptor** — e.g. ``var_name  range(420, 620)``
    3. **Bare keyword descriptor** — e.g. ``var_name  derived``

    Args:
        line: A single stripped SDL source line.

    Returns:
        A ``(descriptor, remainder)`` tuple.  *descriptor* is ``None`` when
        no descriptor is found; *remainder* is the rest of the line.
    """
    if not _DESCRIPTORS_LOADED:
        load_descriptors()

    # 1) Descriptor at the START of line (AV2 style: "f(1) var_name")
    for desc_name in _DESCRIPTOR_FUNCTIONS:
        if line.startswith(desc_name + "("):
            start_paren = len(desc_name)
            end_paren = _find_matching_paren(line, start_paren + 1)
            if end_paren > 0:
                return line[:end_paren], line[end_paren:]

    # 2) Descriptor at the END of line (trailing style: "var_name  range(420, 620)")
    for desc_name in _DESCRIPTOR_FUNCTIONS:
        pattern = r"\s+(" + re.escape(desc_name) + r"\()"
        match = re.search(pattern, line)
        if match:
            desc_start = match.start(1)
            paren_pos = desc_start + len(desc_name)
            end_paren = _find_matching_paren(line, paren_pos + 1)
            if end_paren > 0:
                var_part = line[: match.start()].rstrip()
                desc_part = line[desc_start:end_paren]
                return desc_part, " " + var_part

    # 3) Bare keyword descriptors at the END of line (case-insensitive)
    for keyword in _DESCRIPTOR_KEYWORDS:
        pattern = r"\s+(" + re.escape(keyword) + r")\s*;?\s*$"
        match = re.search(pattern, line, re.IGNORECASE)
        if match:
            var_part = line[: match.start()].rstrip()
            return match.group(1), " " + var_part

    return None, line


def _escape_and_format(text: str) -> str:
    """HTML-escape *text* and neutralise square brackets for Bikeshed.

    Square brackets are replaced with their HTML entities so Bikeshed does
    not interpret them as cross-reference links.

    Args:
        text: Raw text fragment.

    Returns:
        Escaped string safe for embedding in HTML.
    """
    return html.escape(text).replace("[", "&lsqb;").replace("]", "&rsqb;")


def _format_with_comments(text: str) -> str:
    """Escape *text* while wrapping C-style comments in ``<span>`` tags.

    Args:
        text: A line (or fragment) that may contain ``/* */`` or ``//`` comments.

    Returns:
        HTML string with comments wrapped in ``<span class="sdl-comment">``.
    """
    parts = _COMMENT_PATTERN.split(text)
    result: list[str] = []
    for part in parts:
        if part.startswith("/*") or part.startswith("//"):
            result.append(f'<span class="sdl-comment">{_escape_and_format(part)}</span>')
        else:
            result.append(_escape_and_format(part))
    return "".join(result)


def _build_table_row(stripped_line: str, indent_em: float) -> str:
    """Build a single ``<tr>`` for an SDL line.

    If the line contains a recognised descriptor, the row has two populated
    cells (variable | descriptor); otherwise the whole line goes into the
    first cell and the descriptor cell is left empty.

    Args:
        stripped_line: The SDL line with leading/trailing whitespace removed.
        indent_em: Indentation depth in ``em`` units for the first cell.

    Returns:
        An HTML ``<tr>...</tr>`` string.
    """
    descriptor, after_descriptor = _find_descriptor(stripped_line)

    if descriptor:
        var_name = after_descriptor.strip().rstrip(";").strip()
        var_name_escaped = _format_with_comments(var_name)
        descriptor_resolved = resolve_constants_in_descriptor(descriptor)
        descriptor_escaped = _escape_and_format(descriptor_resolved)

        var_cell_content = f'<span style="padding-left: {indent_em}em;">{var_name_escaped}</span>'
        var_cell = f'<td class="sdl-var-with-descriptor">{var_cell_content}</td>'
        desc_cell = f'<td class="sdl-descriptor">{descriptor_escaped}</td>'
        return f"<tr>{var_cell}{desc_cell}</tr>"
    else:
        escaped_line = _format_with_comments(stripped_line)
        code_content = f'<span style="padding-left: {indent_em}em;">{escaped_line}</span>'
        code_cell = f'<td class="sdl-code">{code_content}</td>'
        empty_desc_cell = '<td class="sdl-descriptor"></td>'
        return f"<tr>{code_cell}{empty_desc_cell}</tr>"


def convert_sdl_to_html_table(code_block: str) -> str:
    """Convert an SDL syntax code block to an HTML table.

    The first non-empty line is treated as the function header (table caption).
    Subsequent lines are each converted to a table row via :func:`_build_table_row`.

    Args:
        code_block: The SDL code block content (without the
            ````` ```cpp ````` markers).

    Returns:
        HTML table representation of the syntax, or the original *code_block*
        unchanged if no rows were produced.
    """
    # Normalize multi-line /* ... */ comments to single lines
    code_block = re.sub(
        r"/\*.*?\*/",
        lambda m: re.sub(r"\s+", " ", m.group(0)),
        code_block,
        flags=re.DOTALL,
    )

    lines = code_block.split("\n")
    table_rows: list[str] = []
    table_header: str | None = None

    # Brace-depth mode: when sdl_indent_spaces == 0, compute indentation from
    # the running brace/bracket depth rather than from leading whitespace.
    # This handles specs like HEVC whose SDL blocks have no leading whitespace.
    use_depth_mode = _INDENT_SPACES_PER_LEVEL == 0
    brace_depth = 0  # tracked across lines in depth mode

    # Tokens that open a new depth level (must be at end of line after stripping)
    _OPEN_RE = re.compile(r"[{\[]$")
    # Tokens that close a depth level (line starts with closing bracket/brace)
    _CLOSE_RE = re.compile(r"^[}\]]")
    # Implicit single-statement control: if/else if/else/for/while without trailing {
    # The NEXT line is one level deeper (no brace needed in HEVC spec notation).
    _IMPLICIT_OPEN_RE = re.compile(
        r"^(?:if\s*\(.*\)|else\s+if\s*\(.*\)|else\b|for\s*\(.*\)|while\s*\(.*\))$"
    )

    implicit_indent_pending = 0  # extra depth for next line due to braceless control

    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue

        if use_depth_mode:
            # Decrease depth BEFORE rendering closing-bracket lines
            if _CLOSE_RE.search(stripped):
                brace_depth = max(0, brace_depth - 1)
                implicit_indent_pending = 0  # closing brace cancels any pending indent
            indent_em = (brace_depth + implicit_indent_pending) * _INDENT_EM_PER_LEVEL
        else:
            indent_level = len(line) - len(line.lstrip())
            indent_em = (indent_level / _INDENT_SPACES_PER_LEVEL) * _INDENT_EM_PER_LEVEL

        # The first non-empty line becomes the table header
        if table_header is None:
            func_match = _FUNC_HEADER_PATTERN.match(stripped)
            if func_match:
                table_header = func_match.group(1)
            if use_depth_mode and _OPEN_RE.search(stripped):
                brace_depth += 1
            continue

        table_rows.append(_build_table_row(stripped, indent_em))

        # Update depth AFTER rendering the current line
        if use_depth_mode:
            if _OPEN_RE.search(stripped):
                # Explicit block open: { or [
                brace_depth += 1
                implicit_indent_pending = 0  # explicit brace takes over
            elif _IMPLICIT_OPEN_RE.match(stripped):
                # Braceless control statement: indent next line implicitly
                implicit_indent_pending = 1
            else:
                # Regular statement: consume any pending implicit indent
                implicit_indent_pending = 0

    if table_rows:
        header_text = html.escape(table_header) if table_header else "Syntax Structure"
        original_code_escaped = html.escape(code_block)

        table_html = (
            f'<table class="sdl-syntax-table" data-original-syntax="{original_code_escaped}">\n'
        )
        table_html += f'<thead><tr><th class="sdl-syntax-name">{header_text}</th><th class="sdl-descriptor-header">Descriptor</th></tr></thead>\n'
        table_html += "<tbody>\n"
        table_html += "\n".join(table_rows)
        table_html += "\n</tbody>\n</table>"
        return table_html
    else:
        return code_block
