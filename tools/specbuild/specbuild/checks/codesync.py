"""C++ ↔ Bikeshed SDL syntax-table sync checker.

Compares syntax-element ordering and descriptors between video-codec C++
reference code (VTM/HM/JM-style ``READ_FLAG``/``READ_UVLC``/``READ_CODE``
macros) and the SDL syntax tables in a Bikeshed-built specification.

Usage::

    cpp_funcs = extract_cpp_syntax(Path("VLCReader.cpp"))
    sdl_funcs = extract_sdl_tables(Path("index.html"))
    diffs = diff_syntax(cpp_funcs, sdl_funcs)
    write_codesync_report(diffs, Path("codesync_report.html"))

This is an MVP: regex-based, dependency-free, conservative. Anything that
isn't a recognized ``READ_*`` macro is reported as ``<unrecognized macro>``
so the user can see coverage gaps explicitly rather than silently dropping
information.
"""

from __future__ import annotations

import html
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Union

from specbuild.utils import get_bs4

# ---------------------------------------------------------------------------
# Public dataclass
# ---------------------------------------------------------------------------


@dataclass
class SyntaxField:
    """A single parsed syntax-table row.

    Attributes:
        name: The syntax-element identifier (e.g. ``pps_id``).
        descriptor: The bitstream descriptor (e.g. ``u(1)``, ``ue(v)``).
        condition: Enclosing ``if (...)`` condition, or empty string.
    """

    name: str
    descriptor: str
    condition: str = ""

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, SyntaxField):
            return NotImplemented
        return (
            self.name == other.name
            and self.descriptor == other.descriptor
            and self.condition == other.condition
        )

    def __hash__(self) -> int:
        return hash((self.name, self.descriptor, self.condition))


# ---------------------------------------------------------------------------
# C++ macro recognition
# ---------------------------------------------------------------------------

# Recognized JVET/MPEG reference-codec macros. New macros can be added here
# without changing the parser logic. Each entry maps a macro name to a
# callable that accepts the captured argument-string (the text between the
# outermost parens) and returns ``(name, descriptor)`` or ``None`` if the
# arg list cannot be parsed.


# A simple comma-splitter that respects nested parens and quoted strings.
def _split_top_level_args(args: str) -> list[str]:
    """Split *args* on top-level commas (ignore commas inside parens/quotes)."""
    parts: list[str] = []
    depth = 0
    in_str = False
    str_ch = ""
    cur: list[str] = []
    i = 0
    while i < len(args):
        ch = args[i]
        if in_str:
            cur.append(ch)
            if ch == "\\" and i + 1 < len(args):
                cur.append(args[i + 1])
                i += 2
                continue
            if ch == str_ch:
                in_str = False
        elif ch in ("'", '"'):
            in_str = True
            str_ch = ch
            cur.append(ch)
        elif ch == "(":
            depth += 1
            cur.append(ch)
        elif ch == ")":
            depth -= 1
            cur.append(ch)
        elif ch == "," and depth == 0:
            parts.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
        i += 1
    if cur:
        parts.append("".join(cur).strip())
    return parts


def _strip_quotes(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ('"', "'"):
        return s[1:-1]
    return s


def _macro_read_flag(args: str) -> tuple[str, str] | None:
    parts = _split_top_level_args(args)
    if len(parts) < 1:
        return None
    name = parts[0].strip()
    return (name, "u(1)")


def _macro_read_code(args: str) -> tuple[str, str] | None:
    parts = _split_top_level_args(args)
    if len(parts) < 2:
        return None
    width = parts[0].strip()
    name = parts[1].strip()
    return (name, f"u({width})")


def _macro_read_uvlc(args: str) -> tuple[str, str] | None:
    parts = _split_top_level_args(args)
    if len(parts) < 1:
        return None
    return (parts[0].strip(), "ue(v)")


def _macro_read_svlc(args: str) -> tuple[str, str] | None:
    parts = _split_top_level_args(args)
    if len(parts) < 1:
        return None
    return (parts[0].strip(), "se(v)")


def _macro_read_ue_limited(args: str) -> tuple[str, str] | None:
    parts = _split_top_level_args(args)
    if len(parts) < 1:
        return None
    return (parts[0].strip(), "ue(v)")


def _macro_read_svlc_limited(args: str) -> tuple[str, str] | None:
    parts = _split_top_level_args(args)
    if len(parts) < 1:
        return None
    return (parts[0].strip(), "se(v)")


# Add additional READ_* macros here as needed (e.g. READ_SCODE, READ_UV).
_MACRO_HANDLERS = {
    "READ_FLAG": _macro_read_flag,
    "READ_CODE": _macro_read_code,
    "READ_UVLC": _macro_read_uvlc,
    "READ_SVLC": _macro_read_svlc,
    "READ_UE_LIMITED": _macro_read_ue_limited,
    "READ_SVLC_LIMITED": _macro_read_svlc_limited,
}

# Sentinel descriptor for macro names we don't (yet) recognize.
_UNRECOGNIZED = "<unrecognized macro>"

# Token that looks like "MAYBE_A_MACRO(..." — we use this to flag possible
# READ_-style macros that aren't in our handler table.
_POSSIBLE_MACRO_RE = re.compile(r"\b(READ_[A-Z0-9_]+)\s*\(")

# A function header like ``void parse_pps(InputBitstream &bs) {`` — we need
# to identify the function name to group rows under it.
_FUNC_HEADER_RE = re.compile(
    r"""(?mx)
    ^[\ \t]*                            # leading indent
    (?:[A-Za-z_][\w:<>,\s\*&]*?\s+)?    # optional return type / qualifiers
    ([A-Za-z_]\w*)                      # function name (group 1)
    \s*\([^;{}]*\)                      # parameter list (no braces/semicolons inside)
    [\s\w:,&\*]*                        # const, override, etc.
    \{                                  # opening brace must follow
    """
)

# An ``if (CONDITION)`` line. Captures the condition (group 1).
_IF_RE = re.compile(r"\bif\s*\(\s*(.*?)\s*\)\s*\{?", re.DOTALL)


# ---------------------------------------------------------------------------
# C++ comment / string stripping
# ---------------------------------------------------------------------------


def _strip_cpp_comments(src: str) -> str:
    """Remove ``//`` line comments and ``/* */`` block comments.

    Preserves string literals so that macro arg strings stay intact.
    """
    out: list[str] = []
    i = 0
    n = len(src)
    while i < n:
        ch = src[i]
        nxt = src[i + 1] if i + 1 < n else ""
        if ch == "/" and nxt == "/":
            # line comment — skip to newline
            j = src.find("\n", i)
            if j == -1:
                break
            i = j
            continue
        if ch == "/" and nxt == "*":
            j = src.find("*/", i + 2)
            if j == -1:
                break
            # collapse to single space to keep token boundaries
            out.append(" ")
            i = j + 2
            continue
        if ch in ('"', "'"):
            # copy string literal verbatim
            out.append(ch)
            i += 1
            while i < n:
                out.append(src[i])
                if src[i] == "\\" and i + 1 < n:
                    out.append(src[i + 1])
                    i += 2
                    continue
                if src[i] == ch:
                    i += 1
                    break
                i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _strip_string_literals(src: str) -> str:
    """Replace the *contents* of every C/C++ string and char literal with spaces.

    The opening / closing delimiters (``"`` and ``'``) are preserved so byte
    offsets do not shift; only the inner characters are blanked.  This stops
    the per-body walker from interpreting tokens like ``READ_FLAG(...)`` that
    appear *inside* a string literal (e.g. ``printf("READ_FLAG(fake)")``) as
    real syntax fields.

    Escape sequences (``\\"``, ``\\'``, ``\\\\``) are honoured so a single
    backslash followed by a quote does not terminate the literal early.
    """
    out: list[str] = []
    i = 0
    n = len(src)
    while i < n:
        ch = src[i]
        if ch in ('"', "'"):
            quote = ch
            out.append(ch)  # preserve opening delimiter
            i += 1
            while i < n:
                c = src[i]
                if c == "\\" and i + 1 < n:
                    # Mask the backslash and the escaped char (preserve newlines).
                    out.append(" " if src[i] != "\n" else "\n")
                    out.append(" " if src[i + 1] != "\n" else "\n")
                    i += 2
                    continue
                if c == quote:
                    out.append(quote)  # preserve closing delimiter
                    i += 1
                    break
                # Mask interior char with a space (preserve newlines so
                # downstream regexes that anchor on lines still work).
                out.append("\n" if c == "\n" else " ")
                i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


# ---------------------------------------------------------------------------
# Function-body extraction
# ---------------------------------------------------------------------------


def _find_matching_brace(text: str, open_pos: int) -> int:
    """Return index *just past* the ``}`` matching the ``{`` at *open_pos*.

    Returns ``-1`` if unbalanced. Strings and comments must already be
    handled (this function only counts braces).
    """
    depth = 0
    i = open_pos
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return -1


@dataclass
class _FunctionBody:
    name: str
    body: str
    start: int = 0


def _iter_functions(src: str) -> list[_FunctionBody]:
    """Find top-level (and nested) function definitions in *src*.

    Returns a list of ``_FunctionBody`` records with the function's name and
    its body (the text *inside* the outermost braces).
    """
    funcs: list[_FunctionBody] = []
    pos = 0
    while True:
        m = _FUNC_HEADER_RE.search(src, pos)
        if not m:
            break
        # The opening ``{`` is the last char captured by the regex.
        open_brace = m.end() - 1
        if open_brace < 0 or src[open_brace] != "{":
            pos = m.end()
            continue
        close = _find_matching_brace(src, open_brace)
        if close == -1:
            break
        body = src[open_brace + 1 : close - 1]
        funcs.append(_FunctionBody(name=m.group(1), body=body, start=m.start()))
        pos = close
    return funcs


# ---------------------------------------------------------------------------
# Per-body macro extraction
# ---------------------------------------------------------------------------


def _find_balanced_paren(text: str, open_pos: int) -> int:
    """Return index just past the ``)`` matching the ``(`` at *open_pos*.

    Returns ``-1`` if unbalanced.
    """
    depth = 0
    i = open_pos
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return -1


# Match any candidate macro: a bare uppercase identifier followed by "(".
# We then check the name against ``_MACRO_HANDLERS`` and the
# ``_POSSIBLE_MACRO_RE`` predicate.
_CANDIDATE_RE = re.compile(r"\b([A-Z][A-Z0-9_]+)\s*\(")


def _join_conds(*parts: str) -> str:
    """Join non-empty condition strings with ``" && "``.

    Used to combine an outer enclosing condition with an inner one
    discovered inside a nested ``if`` (e.g. an ``if (a) if (b) X;``
    pattern yields ``"a && b"``).
    """
    return " && ".join(p for p in parts if p)


def _extract_fields_from_body(body: str, parent_cond: str = "") -> list[SyntaxField]:
    """Extract :class:`SyntaxField` rows from a function body.

    Tracks ``if (...)`` nesting so each row gets the condition of its
    enclosing ``if`` block (innermost wins for block-form ifs; conditions
    are not concatenated at the same brace level).

    For *single-statement* ``if`` bodies (no braces) the recursive call
    is given a ``parent_cond`` so the outer condition is joined with the
    inner one via ``" && "`` — without this, ``if (a) if (b) READ_FLAG(x);``
    would lose the outer ``a`` and report only ``b``.

    Anything matching ``READ_*(...)`` that we don't have a handler for
    becomes a row with descriptor ``<unrecognized macro>``.
    """
    fields: list[SyntaxField] = []
    # Stack of (condition_str, brace_depth_at_entry). When the brace depth
    # falls back to ``brace_depth_at_entry``, the condition is popped.
    cond_stack: list[tuple[str, int]] = []
    depth = 0
    i = 0
    n = len(body)

    def _current_cond(extra: str = "") -> str:
        """Innermost cond_stack entry, joined with ``parent_cond`` if any.

        ``extra`` (used for the single-statement-if recursion path) is
        appended after the cond_stack innermost.
        """
        innermost = cond_stack[-1][0] if cond_stack else ""
        return _join_conds(parent_cond, innermost, extra)

    while i < n:
        ch = body[i]
        if ch == "{":
            depth += 1
            i += 1
            continue
        if ch == "}":
            depth -= 1
            # Pop any conditions whose scope just closed.
            while cond_stack and cond_stack[-1][1] >= depth + 1:
                cond_stack.pop()
            i += 1
            continue

        # Try to match an if-statement at this position.
        m_if = _IF_RE.match(body, i)
        if m_if:
            # Find the matching ``)`` for the outer "(": _IF_RE may stop
            # mid-condition if the condition contains nested parens.
            paren_open = body.find("(", i)
            paren_close = _find_balanced_paren(body, paren_open)
            if paren_close == -1:
                i = m_if.end()
                continue
            condition = body[paren_open + 1 : paren_close - 1].strip()
            # Move past the ")" and find the next non-whitespace char.
            j = paren_close
            while j < n and body[j] in " \t\r\n":
                j += 1
            if j < n and body[j] == "{":
                # Block-form if: push and enter the brace.
                depth += 1
                cond_stack.append((condition, depth))
                i = j + 1
                continue
            # Single-statement if: apply condition just to next macro call.
            # Combine the outer (parent + cond_stack innermost) condition
            # with this inner ``if`` condition so a nested
            # ``if (a) { if (b) READ_FLAG(x); }`` produces ``"a && b"``
            # rather than just ``"b"``.
            outer = _current_cond()
            combined = _join_conds(outer, condition)
            # Find the terminating semicolon of the next statement.
            stmt_end = body.find(";", j)
            if stmt_end == -1:
                stmt_end = n
            inner = body[j : stmt_end + 1]
            sub = _extract_fields_from_body(inner, parent_cond=combined)
            fields.extend(sub)
            i = stmt_end + 1
            continue

        # Try to match a candidate macro.
        m = _CANDIDATE_RE.match(body, i)
        if m:
            macro_name = m.group(1)
            paren_open = m.end() - 1
            paren_close = _find_balanced_paren(body, paren_open)
            if paren_close == -1:
                i = m.end()
                continue
            args = body[paren_open + 1 : paren_close - 1]
            handler = _MACRO_HANDLERS.get(macro_name)
            condition = _current_cond()
            if handler:
                parsed = handler(args)
                if parsed:
                    name, descriptor = parsed
                    fields.append(
                        SyntaxField(name=name, descriptor=descriptor, condition=condition)
                    )
            elif _POSSIBLE_MACRO_RE.match(body, i):
                # Looks like a READ_* we haven't taught the parser yet.
                # Record the field name (best-effort: first arg) so the
                # user sees the gap rather than silent skipping.
                parts = _split_top_level_args(args)
                if parts:
                    name = parts[0].strip()
                    if name and re.match(r"^[A-Za-z_]\w*$", name):
                        fields.append(
                            SyntaxField(
                                name=name,
                                descriptor=_UNRECOGNIZED,
                                condition=condition,
                            )
                        )
            i = paren_close
            continue

        i += 1

    return fields


# ---------------------------------------------------------------------------
# Public C++ entry point
# ---------------------------------------------------------------------------


def extract_cpp_syntax(cpp_path: Path) -> dict[str, list[SyntaxField]]:
    """Parse a C++ file and return one entry per syntax-table-shaped function.

    A function counts as syntax-table-shaped iff its body contains **at
    least two** recognized ``READ_*`` macro calls (handler match or
    matching the ``READ_*`` naming convention). All other functions are
    skipped.

    Args:
        cpp_path: Either a :class:`Path` to a ``.cpp``/``.h`` file or a
            raw C++ source string. ``str`` input lets tests inline snippets.

    Returns:
        Mapping ``{function_name: [SyntaxField, ...]}``.
    """
    if isinstance(cpp_path, (str, bytes)) and not isinstance(cpp_path, Path):
        # Allow callers to pass raw source for tests / streaming use.
        src = cpp_path if isinstance(cpp_path, str) else cpp_path.decode("utf-8", errors="replace")
    else:
        try:
            src = Path(cpp_path).read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            logging.warning(f"codesync: cannot read C++ file {cpp_path}: {exc}")
            return {}

    src = _strip_cpp_comments(src)
    # Mask the *contents* of string and char literals so tokens like
    # ``printf("READ_FLAG(fake)")`` are not misread as real syntax fields.
    # Comments must be stripped first; literal contents are blanked second.
    src = _strip_string_literals(src)
    out: dict[str, list[SyntaxField]] = {}
    for func in _iter_functions(src):
        fields = _extract_fields_from_body(func.body)
        # Count how many fields came from recognized macros (i.e. anything
        # whose descriptor is not the ``<unrecognized macro>`` sentinel).
        recognized = sum(1 for f in fields if f.descriptor != _UNRECOGNIZED)
        if recognized < 2:
            continue
        # If the same function name appears twice (overload), append a
        # numeric suffix so we don't overwrite the earlier entry.
        key = func.name
        if key in out:
            n = 2
            while f"{func.name}#{n}" in out:
                n += 1
            key = f"{func.name}#{n}"
        out[key] = fields
    return out


# ---------------------------------------------------------------------------
# SDL extraction
# ---------------------------------------------------------------------------

# Soup or path argument type.
SoupOrPath = Union["object", Path, str]


# Table classes that the SDL converter (specbuild/sdl.py) emits, plus a
# couple of common alternatives ("syntax", "syntax-table") so this also
# works on hand-written tables in older specs.
_SDL_TABLE_CLASSES = ("sdl-syntax-table", "syntax", "syntax-table")


def _looks_like_descriptor(text: str) -> bool:
    """True if *text* looks like a bitstream descriptor (e.g. u(8), ue(v))."""
    text = text.strip()
    if not text:
        return False
    return bool(
        re.match(r"^[A-Za-z_][A-Za-z0-9_]*\s*\([^)]*\)\s*;?$", text)
        or text.lower() in {"derived", "computed", "reserved", "required", "optional"}
    )


def _table_caption(table) -> str:
    """Return the function-name caption for a syntax table.

    Order of resolution:
      1. ``data-original-syntax`` attribute (first non-empty line).
      2. ``<caption>`` element (the most specific human-readable label).
      3. First ``<th>``/header cell in ``<thead>`` (skips generic
         column-header words like "Syntax" and "Descriptor").
      4. Fallback: empty string.
    """
    orig = table.get("data-original-syntax", "")
    if orig:
        for line in orig.splitlines():
            line = line.strip()
            if line:
                # Strip trailing "{" if present.
                line = line.rstrip("{").strip()
                return line
    cap = table.find("caption")
    if cap:
        text = cap.get_text(strip=True)
        if text:
            # Strip trailing "( )" / "()" / "{" for a clean function name.
            return re.sub(r"\s*\(\s*\)\s*$|\s*\{\s*$", "", text).strip() or text
    thead = table.find("thead")
    if thead:
        first_th = thead.find(["th", "td"])
        if first_th:
            text = first_th.get_text(strip=True)
            if text and text.lower() not in ("descriptor", "syntax", "syntax element"):
                return text
    return ""


def _extract_table_fields(table) -> list[SyntaxField]:
    """Pull a list of ``SyntaxField`` from a single ``<table>`` element."""
    fields: list[SyntaxField] = []
    # Track an "if (...)" condition introduced by a row whose first cell
    # contains ``if(...)``. Reset when brace nesting decreases.
    cond_stack: list[tuple[str, int]] = []
    depth = 0
    body_rows = []
    tbody = table.find("tbody")
    if tbody:
        body_rows = tbody.find_all("tr")
    else:
        body_rows = [tr for tr in table.find_all("tr") if not tr.find_parent("thead")]

    for tr in body_rows:
        cells = tr.find_all(["td", "th"])
        if not cells:
            continue
        var_text = cells[0].get_text(" ", strip=True).rstrip(";").strip()
        desc_text = cells[1].get_text(" ", strip=True).rstrip(";").strip() if len(cells) > 1 else ""

        # Detect if-statement rows.
        m_if = re.match(r"^if\s*\(\s*(.*?)\s*\)\s*\{?\s*$", var_text)
        if m_if:
            depth += 1
            cond_stack.append((m_if.group(1).strip(), depth))
            continue

        # Detect "}" close rows.
        if var_text in ("}", "} ;", "};"):
            if cond_stack and cond_stack[-1][1] == depth:
                cond_stack.pop()
            depth = max(0, depth - 1)
            continue

        # Skip non-element rows (else, for, while, comments).
        if not var_text or var_text.startswith(("else", "for", "while", "/*", "//")):
            continue

        if not desc_text:
            # Row without a descriptor: skip (probably structural).
            continue

        # Take only the first identifier token from var_text — strips array
        # subscripts and trailing commas.
        m_var = re.match(r"([A-Za-z_]\w*)", var_text)
        name = m_var.group(1) if m_var else var_text
        condition = cond_stack[-1][0] if cond_stack else ""
        fields.append(SyntaxField(name=name, descriptor=desc_text, condition=condition))

    return fields


def extract_sdl_tables(soup_or_path: SoupOrPath) -> dict[str, list[SyntaxField]]:
    """Extract syntax fields from each SDL table in *soup_or_path*.

    Args:
        soup_or_path: A :class:`bs4.BeautifulSoup` (or ``Tag``) instance,
            a :class:`Path` to an HTML/``.bs`` file, or a raw HTML string.

    Returns:
        Mapping ``{caption: [SyntaxField, ...]}``. Tables without a usable
        caption are keyed by ``"<unnamed_table_N>"``.
    """
    BS = get_bs4()
    soup = None
    if hasattr(soup_or_path, "find_all"):
        soup = soup_or_path
    elif isinstance(soup_or_path, Path):
        try:
            text = soup_or_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            logging.warning(f"codesync: cannot read SDL file {soup_or_path}: {exc}")
            return {}
        soup = BS(text, "html.parser")
    elif isinstance(soup_or_path, str):
        soup = BS(soup_or_path, "html.parser")
    else:
        raise TypeError(f"extract_sdl_tables: unsupported argument type {type(soup_or_path)!r}")

    out: dict[str, list[SyntaxField]] = {}
    unnamed = 0
    for table in soup.find_all("table"):
        classes = table.get("class") or []
        if not any(c in classes for c in _SDL_TABLE_CLASSES):
            continue
        caption = _table_caption(table)
        if not caption:
            unnamed += 1
            caption = f"<unnamed_table_{unnamed}>"
        # Normalize: strip parentheses+args to keep only the function name.
        m = re.match(r"([A-Za-z_]\w*)", caption)
        key = m.group(1) if m else caption
        fields = _extract_table_fields(table)
        if not fields:
            continue
        if key in out:
            n = 2
            while f"{key}#{n}" in out:
                n += 1
            key = f"{key}#{n}"
        out[key] = fields
    return out


# ---------------------------------------------------------------------------
# Diffing
# ---------------------------------------------------------------------------


@dataclass
class _DiffEntry:
    function: str
    kind: str
    field: str
    details: str = ""
    cpp: SyntaxField | None = None
    sdl: SyntaxField | None = None


def diff_syntax(
    cpp: dict[str, list[SyntaxField]],
    sdl: dict[str, list[SyntaxField]],
) -> list[dict]:
    """Compare per-function field lists and report differences.

    For each function present in **both** mappings (matched by name), the
    field sequences are aligned by element name; the resulting diffs may
    include:

    - ``added`` — element exists in *sdl* but not *cpp*
    - ``removed`` — element exists in *cpp* but not *sdl*
    - ``descriptor_changed`` — same name on both sides, different descriptor
    - ``condition_changed`` — same name & descriptor, different condition
    - ``reordered`` — same set of names but in different order

    Functions that exist only on one side are reported once at the
    function level (``kind="cpp_only"`` or ``kind="sdl_only"``).

    Returns:
        A list of plain ``dict`` records (JSON-friendly).
    """
    out: list[dict] = []

    cpp_names = set(cpp.keys())
    sdl_names = set(sdl.keys())

    for name in sorted(cpp_names - sdl_names):
        out.append(
            {
                "function": name,
                "kind": "cpp_only",
                "field": "",
                "details": f"Function '{name}' exists in C++ but not in SDL.",
            }
        )
    for name in sorted(sdl_names - cpp_names):
        out.append(
            {
                "function": name,
                "kind": "sdl_only",
                "field": "",
                "details": f"Function '{name}' exists in SDL but not in C++.",
            }
        )

    for name in sorted(cpp_names & sdl_names):
        cpp_fields = cpp[name]
        sdl_fields = sdl[name]
        cpp_by_name = {f.name: f for f in cpp_fields}
        sdl_by_name = {f.name: f for f in sdl_fields}

        # Per-field added/removed/changed comparisons.
        for fname, cf in cpp_by_name.items():
            if fname not in sdl_by_name:
                out.append(
                    {
                        "function": name,
                        "kind": "removed",
                        "field": fname,
                        "details": f"In C++ ({cf.descriptor}) but missing from SDL.",
                    }
                )
        for fname, sf in sdl_by_name.items():
            if fname not in cpp_by_name:
                out.append(
                    {
                        "function": name,
                        "kind": "added",
                        "field": fname,
                        "details": f"In SDL ({sf.descriptor}) but missing from C++.",
                    }
                )
            else:
                cf = cpp_by_name[fname]
                if cf.descriptor != sf.descriptor:
                    out.append(
                        {
                            "function": name,
                            "kind": "descriptor_changed",
                            "field": fname,
                            "details": f"C++ has {cf.descriptor}; SDL has {sf.descriptor}.",
                        }
                    )
                elif cf.condition != sf.condition:
                    out.append(
                        {
                            "function": name,
                            "kind": "condition_changed",
                            "field": fname,
                            "details": (
                                f"C++ condition: {cf.condition!r}; SDL condition: {sf.condition!r}."
                            ),
                        }
                    )

        # Reordering (only if the name sets are identical).
        common = [f.name for f in cpp_fields if f.name in sdl_by_name]
        sdl_common = [f.name for f in sdl_fields if f.name in cpp_by_name]
        if common and sdl_common and common != sdl_common and set(common) == set(sdl_common):
            out.append(
                {
                    "function": name,
                    "kind": "reordered",
                    "field": "",
                    "details": (
                        f"C++ order: {', '.join(common)}; SDL order: {', '.join(sdl_common)}."
                    ),
                }
            )

    return out


# ---------------------------------------------------------------------------
# HTML report
# ---------------------------------------------------------------------------


_KIND_LABEL = {
    "added": "Added (in SDL only)",
    "removed": "Removed (in C++ only)",
    "descriptor_changed": "Descriptor changed",
    "condition_changed": "Condition changed",
    "reordered": "Reordered",
    "cpp_only": "Function in C++ only",
    "sdl_only": "Function in SDL only",
}


def _h(text: object) -> str:
    """Shortcut for ``html.escape`` that also tolerates None/non-str inputs."""
    return html.escape("" if text is None else str(text))


def write_codesync_report(diffs: list[dict], output_path: Path) -> None:
    """Write an HTML report of *diffs* to *output_path*.

    The report has one collapsible ``<details>`` block per function
    showing each diff entry as a styled row. All user-supplied content is
    HTML-escaped — this report is safe to publish.
    """
    # Group by function, preserving "global" function-only entries.
    by_func: dict[str, list[dict]] = {}
    for d in diffs:
        by_func.setdefault(d.get("function", ""), []).append(d)

    lines: list[str] = []
    lines.append("<!doctype html>")
    lines.append('<html lang="en"><head><meta charset="utf-8">')
    lines.append("<title>Codesync Report</title>")
    lines.append(
        "<style>"
        "body{font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;"
        "margin:2em;color:#222;}"
        "h1{font-size:1.6em;margin-bottom:.2em;}"
        ".summary{color:#555;margin-bottom:1.5em;}"
        "details{border:1px solid #ccc;border-radius:6px;margin:.5em 0;"
        "padding:.4em .8em;background:#fafafa;}"
        "summary{cursor:pointer;font-weight:600;}"
        "table.diffs{border-collapse:collapse;margin-top:.4em;width:100%;}"
        "table.diffs th,table.diffs td{border:1px solid #ddd;padding:4px 8px;"
        "font-size:.92em;text-align:left;vertical-align:top;}"
        "table.diffs th{background:#eee;}"
        ".kind-added{background:#e7f7ec;}"
        ".kind-removed{background:#fbe5e5;}"
        ".kind-descriptor_changed{background:#fff5d6;}"
        ".kind-condition_changed{background:#eaf3ff;}"
        ".kind-reordered{background:#f1e7ff;}"
        ".kind-cpp_only,.kind-sdl_only{background:#f5f5f5;}"
        ".empty{color:#888;font-style:italic;}"
        "</style>"
    )
    lines.append("</head><body>")
    lines.append("<h1>C++ &harr; SDL Sync Report</h1>")
    lines.append(
        f'<p class="summary">Functions with differences: '
        f"<strong>{_h(len(by_func))}</strong>. "
        f"Total entries: <strong>{_h(len(diffs))}</strong>.</p>"
    )

    if not diffs:
        lines.append('<p class="empty">No differences detected.</p>')
        lines.append("</body></html>")
        output_path.write_text("\n".join(lines), encoding="utf-8")
        return

    for func in sorted(by_func.keys()):
        entries = by_func[func]
        title = func or "(global)"
        lines.append(
            f"<details open><summary>{_h(title)} "
            f"<span class='count'>({_h(len(entries))})</span></summary>"
        )
        lines.append('<table class="diffs">')
        lines.append("<thead><tr><th>Kind</th><th>Field</th><th>Details</th></tr></thead><tbody>")
        for e in entries:
            kind = e.get("kind", "")
            label = _KIND_LABEL.get(kind, kind)
            lines.append(
                f'<tr class="kind-{_h(kind)}">'
                f"<td>{_h(label)}</td>"
                f"<td>{_h(e.get('field', ''))}</td>"
                f"<td>{_h(e.get('details', ''))}</td>"
                "</tr>"
            )
        lines.append("</tbody></table>")
        lines.append("</details>")

    lines.append("</body></html>")
    output_path.write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# Convenience top-level entry
# ---------------------------------------------------------------------------


def run_codesync(
    cpp_path: Path,
    spec_html_path: Path,
    output_path: Path,
) -> list[dict]:
    """Run the full extract/diff/report pipeline. Returns the diff list."""
    cpp = extract_cpp_syntax(Path(cpp_path))
    sdl = extract_sdl_tables(Path(spec_html_path))
    diffs = diff_syntax(cpp, sdl)
    write_codesync_report(diffs, Path(output_path))
    return diffs


# Re-export the dataclass field default machinery — keeps the import
# surface tidy for tests.
__all__ = [
    "SyntaxField",
    "extract_cpp_syntax",
    "extract_sdl_tables",
    "diff_syntax",
    "write_codesync_report",
    "run_codesync",
]


# Suppress unused-import warning for ``field`` — kept available for callers
# who want to extend ``SyntaxField`` cleanly.
_ = field
