"""Post-process HEVC-style equation blocks in compiled HTML.

HEVC (ISO/IEC 23008-2) uses the following equation format in its ``.bs`` sources::

    <div class='equation'>
      $$ content $$
      <span class='equation-number'>(N-M)</span>
    </div>

This module:

1. Strips the original ``<span class='equation-number'>`` from source — these
   come from the Word import and are replaced by specbuild's auto-numbering.
2. Renders ``$$ ... $$`` content:
   - Pseudocode (for(, if(, while(, ++) → ``<pre class="equation-code">``
   - Functional math with LaTeX (\\begin{cases}, \\frac, etc.) → MathML via latex2mathml
   - HEVC functional notation (Clip3, Atan2, etc.) → ``<code class="equation-math">``
3. Leaves image-based equations (``<img .../>``) as-is (except strips old number).
4. Wraps plain-text equations in ``<span class="equation-text">``.
5. Converts 2-column ``<table class="data">`` pseudocode tables (with equation-number
   second column) to ``<pre class="equation-code">`` blocks.

After this runs, specbuild's ``number-equations`` enhancement assigns
``(section.N)`` numbers automatically.

Uses BeautifulSoup for structural parsing (not regex) to avoid nested-div issues.
"""

from __future__ import annotations

import html as _html
import logging
import re
from pathlib import Path

# Patterns that indicate pseudocode (C-like control flow).
# Note: \belse\b is intentionally NOT included as it also matches "Otherwise"
# in prose descriptions. Only match C-style constructs with parentheses.
_PSEUDOCODE_PATTERNS = re.compile(
    r"(?:for\s*\(|if\s*\(|while\s*\(|else\s*(?:if\s*\(|\{)|\+\+|--|\bdo\b|\breturn\b|"
    r"=\s*0\s*\n|=\s*1\s*\n|\[\s*[a-z]\+\+\s*\]|\[\s*[a-z]--\s*\])"
)

# Patterns that indicate HEVC functional notation (NOT LaTeX).
# Kept for reference but no longer used in routing — all non-LaTeX, non-pseudocode
# equations default to <code class="equation-math"> to avoid latex2mathml
# treating underscores as subscripts (bit_depth_luma → "bit" sub "depth" sub "luma")
# and CamelCase as individual chars (QpBdOffsetY → "Q p B d O f f s e t Y").
_HEVC_FUNCTIONAL_PATTERNS = re.compile(
    r"(?:"
    r"[A-Z][a-z][A-Za-z0-9]*\s*\[|"  # CamelCase array: ScalingFactor[, PicOrder[
    r"\]\s*\[|"  # chained array brackets ][ (multi-dim)
    r"\bwith\s+\w+\s*=\s*\d+\.\.|"  # with i = 0..N constraint
    r"\d+\.\.\d+|"  # range notation N..M
    r"\t\(\d+[A-Za-z]?\-\d+\)|"  # tab + equation number (7-44) inline
    r"&&|"  # C-style boolean
    r"ScanOrder|RefPicList|CurrRpsIdx|"  # HEVC-specific long identifiers
    r"MatrixCoef|BitDepth[YC]|CtbLog|CbSize|TbSize|MvdL|MvL[01]"
    r")"
)

# LaTeX indicators — presence means MathML is appropriate
_LATEX_PATTERNS = re.compile(
    r"(?:\\begin\{|\\end\{|\\frac\{|\\dfrac\{|\\sqrt\{|"
    r"\\leq|\\geq|\\cdot|\\times|\\pi\b|\\log_|\\text\{|"
    r"\\left|\\right|\\arcsin|\\arctan|\\cos\b|\\sin\b|\\tan\b|"
    r"\\lfloor|\\rfloor|\\lceil|\\rceil|\\infty|\\neq|\\pm)"
)

_DOLLAR_CONTENT_RE = re.compile(r"\$\$(.*?)\$\$", re.DOTALL)

# Strip source equation-number spans — specbuild will auto-number instead
_EQUATION_NUMBER_RE = re.compile(
    r"\s*<span\s+class=['\"]equation-number['\"][^>]*>.*?</span>", re.DOTALL
)

# 2-column pseudocode table: first td = code, second td = (N-M) equation number.
# The (?:(?!</table>).)*? prevents matching across table boundaries (a greedy bug
# that would otherwise capture abbreviation tables as code content).
_TABLE_PSEUDOCODE_RE = re.compile(
    r"<table\s+class=\"data\">\s*<tbody>\s*<tr>\s*"
    r"<td>((?:(?!</table>).)*?)"  # code: stop at </table> boundary
    r"<td>\s*\(\d+[A-Z]?\-\d+\)\s*\n?\s*</td></td></tr></tbody></table>",
    re.DOTALL,
)

# Single-column pseudocode table: one td, no equation number.
# Matches ONLY when the cell content looks like pseudocode (if/else/while/for)
# and does NOT contain nested <td> elements (which indicates a definition table).
_TABLE_SINGLE_PSEUDOCODE_RE = re.compile(
    r"<table\s+class=\"data\">\s*<tbody>\s*<tr>\s*"
    r"<td>((?:(?!</table>|<td>).)*?)</td></tr></tbody></table>",
    re.DOTALL,
)


def _is_pseudocode(content: str) -> bool:
    """Return True if the content looks like C-style pseudocode."""
    return bool(_PSEUDOCODE_PATTERNS.search(content))


def _is_latex(content: str) -> bool:
    """Return True if the content contains genuine LaTeX commands.

    HEVC equations use programming-style notation (variable assignments,
    array indexing, C arithmetic) rather than LaTeX math commands.
    Only equations explicitly written with LaTeX markers (\\begin{cases},
    \\frac, \\text{}, Greek letters etc.) should go through latex2mathml.

    All other equations — including those with CamelCase HEVC variable names
    like QpBdOffsetY, BitDepthY, MinCbLog2SizeY — should render as monospace
    <code> blocks, because:
    - latex2mathml treats underscore as subscript: bit_depth_luma → spaced mess
    - CamelCase names render as individual <mi> elements: "Q p B d O f f s e t Y"
    """
    return bool(_LATEX_PATTERNS.search(content))


def _render_mathml(latex: str) -> str | None:
    """Try to render LaTeX as MathML via latex2mathml. Returns None on failure."""
    try:
        import latex2mathml.converter as _l2m

        return _l2m.convert(latex.strip(), display="block")
    except Exception:
        return None


def _process_equation_divs_soup(soup: object) -> tuple[int, int, int, int]:
    """Process all <div class="equation"> elements using BeautifulSoup.

    Uses structural parsing rather than regex to correctly handle nested elements.

    Returns:
        (changed_math, changed_code, changed_plain, changed_img)
    """
    changed_math = changed_code = changed_plain = changed_img = 0

    for eq_div in list(soup.find_all("div", class_="equation")):
        # Get inner HTML as string for $$ detection
        inner_html = eq_div.decode_contents()

        # Strip source equation-number span
        inner_html_clean = _EQUATION_NUMBER_RE.sub("", inner_html)

        # Image-based equations — strip old number only
        has_img = eq_div.find("img") is not None
        if has_img and "$$" not in inner_html:
            if inner_html_clean.strip() != inner_html.strip():
                eq_div.clear()
                from bs4 import BeautifulSoup as _BS4

                fragment = _BS4(inner_html_clean, "html.parser")
                for child in list(fragment.children):
                    eq_div.append(child.__copy__())
                changed_img += 1
            continue

        dollar_m = _DOLLAR_CONTENT_RE.search(inner_html_clean)
        if not dollar_m:
            # Plain-text equation — wrap text in <span class="equation-text">
            # Preserve child elements (e.g. <p class="equation-desc">)
            from bs4 import BeautifulSoup as _BS4
            from bs4 import Tag

            plain_html = inner_html_clean.strip()
            if not plain_html:
                continue

            # Build new content: wrap bare text nodes in a span
            wrapper_tag = soup.new_tag("div", attrs={"class": "equation-wrapper"})
            fragment = _BS4(plain_html, "html.parser")
            # Check if content is already wrapped in block elements
            has_block = any(
                isinstance(c, Tag) and c.name in ("p", "div", "pre", "code", "table")
                for c in fragment.children
            )
            if has_block:
                for child in list(fragment.children):
                    wrapper_tag.append(child.__copy__() if hasattr(child, "__copy__") else child)
            else:
                span = soup.new_tag("span", attrs={"class": "equation-text"})
                span.string = fragment.get_text()
                wrapper_tag.append(span)

            eq_div.clear()
            eq_div.append(wrapper_tag)
            changed_plain += 1
            continue

        raw = _html.unescape(dollar_m.group(1))

        # Extract supplementary content (e.g. <p class="equation-desc">...)
        supplementary_html = _DOLLAR_CONTENT_RE.sub("", inner_html_clean).strip()

        if _is_pseudocode(raw):
            code_clean = _html.escape(_normalize_indent(raw))
            math_html = f'<pre class="equation-code">{code_clean}</pre>'
            changed_code += 1
        elif _is_latex(raw):
            # Has genuine LaTeX commands (\\begin{cases}, \\frac, \\text{} etc.)
            # — try MathML rendering.
            mathml = _render_mathml(raw)
            if mathml:
                math_html = mathml
                changed_math += 1
            else:
                escaped = _html.escape(raw.strip())
                math_html = f'<code class="equation-math">{escaped}</code>'
                changed_math += 1
        else:
            # HEVC programming-style notation (variable assignments, array indexing,
            # CamelCase names like QpBdOffsetY, BitDepthY, MinCbLog2SizeY, etc.).
            # Do NOT send through latex2mathml:
            # - Underscores → subscript mode → bit_depth_luma renders as "bit" sub "depth" sub "luma"
            # - CamelCase → individual <mi> → "Q p B d O f f s e t Y"
            escaped = _html.escape(raw.strip())
            math_html = f'<code class="equation-math">{escaped}</code>'
            changed_math += 1

        from bs4 import BeautifulSoup as _BS4

        eq_div.clear()
        wrapper = soup.new_tag("div", attrs={"class": "equation-wrapper"})
        frag = _BS4(math_html, "html.parser")
        for child in list(frag.children):
            wrapper.append(child.__copy__() if hasattr(child, "__copy__") else child)
        eq_div.append(wrapper)

        if supplementary_html:
            supp_frag = _BS4(supplementary_html, "html.parser")
            for child in list(supp_frag.children):
                eq_div.append(child.__copy__() if hasattr(child, "__copy__") else child)

    return changed_math, changed_code, changed_plain, changed_img


def _normalize_indent(code: str, indent_size: int = 2) -> str:
    """Normalize over-indented pseudocode to indent_size spaces per level.

    HEVC Word documents export pseudocode with large fixed indentation
    (often 19-31 spaces per level). This function normalises by detecting
    the smallest non-zero indent step and remapping it to ``indent_size``.

    Also strips embedded tab-separated equation numbers like ``(8-1)``
    that appear inline in the pseudocode (they will be auto-numbered instead).
    """
    lines = code.split("\n")

    # Strip trailing inline equation numbers: "...\t(8-1)" → "..."
    lines = [re.sub(r"\t\s*\(\d+[A-Za-z]?\-\d+\)\s*$", "", ln) for ln in lines]

    # Strip non-breaking spaces (\xa0) used as padding in some HEVC source
    lines = [ln.replace("\xa0", " ") for ln in lines]

    # Find indent levels of non-empty lines
    indents = sorted(
        {len(ln) - len(ln.lstrip(" ")) for ln in lines if ln.strip()},
    )
    if len(indents) <= 1:
        return "\n".join(ln.rstrip() for ln in lines).strip()

    # Build mapping: original indent → normalised indent.
    # Assign each distinct indent level an ordinal (0, 1, 2, ...) and multiply
    # by indent_size, rather than dividing by min_step (which over-inflates when
    # source steps are large, e.g. 19 spaces → 8 instead of 2).
    indent_map = {level: idx * indent_size for idx, level in enumerate(indents)}

    result = []
    for ln in lines:
        stripped = ln.lstrip(" ")
        orig_indent = len(ln) - len(stripped)
        # Find the closest mapped indent level
        mapped = indent_map.get(orig_indent)
        if mapped is None:
            # Interpolate: find nearest lower known level
            lower = max((k for k in indents if k <= orig_indent), default=0)
            mapped = indent_map.get(lower, 0)
        result.append(" " * mapped + stripped.rstrip())

    return "\n".join(result).strip()


def process_hevc_equations(html_path: Path) -> None:
    """Post-process HEVC-style ``<div class='equation'>`` blocks and pseudocode tables.

    Args:
        html_path: Path to the compiled ``index.html`` (modified in place).
    """
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        logging.debug("BeautifulSoup not available — skipping HEVC equation processing")
        return

    text = html_path.read_text(encoding="utf-8")

    if '<div class="equation">' not in text and "<div class='equation'>" not in text:
        return

    # Use BeautifulSoup for structural equation div processing (avoids nested-div regex bugs)
    soup = BeautifulSoup(text, "html.parser")
    changed_math, changed_code, changed_plain, changed_img = _process_equation_divs_soup(soup)

    # Convert 2-column pseudocode tables (still safe to do with regex since the table
    # structure is unambiguous — single-row, second td = equation number pattern)
    new_text = str(soup)

    def _convert_pseudocode_table(m: re.Match) -> str:
        code = _html.unescape(m.group(1))
        code_clean = _html.escape(_normalize_indent(code))
        return (
            f'<div class="equation">\n'
            f'<div class="equation-wrapper"><pre class="equation-code">{code_clean}</pre></div>\n'
            f"</div>"
        )

    pseudocode_count = len(_TABLE_PSEUDOCODE_RE.findall(new_text))
    if pseudocode_count:
        new_text = _TABLE_PSEUDOCODE_RE.sub(_convert_pseudocode_table, new_text)

    # Also convert single-column pseudocode tables (no equation number).
    # Only convert cells whose content matches pseudocode patterns.
    single_pseudocode_count = 0

    def _convert_single_pseudocode(m: re.Match) -> str:
        raw = _html.unescape(m.group(1))
        if not _is_pseudocode(raw):
            return m.group(0)  # not pseudocode — leave definition tables alone
        return _convert_pseudocode_table.__wrapped__(m)  # reuse normalisation

    # Simpler inline version (no wrapper needed):
    def _maybe_convert_single(m: re.Match) -> str:
        nonlocal single_pseudocode_count
        raw = _html.unescape(m.group(1))
        if not _is_pseudocode(raw):
            return m.group(0)
        code_clean = _html.escape(_normalize_indent(raw))
        single_pseudocode_count += 1
        return (
            f'<div class="equation">\n'
            f'<div class="equation-wrapper"><pre class="equation-code">{code_clean}</pre></div>\n'
            f"</div>"
        )

    new_text = _TABLE_SINGLE_PSEUDOCODE_RE.sub(_maybe_convert_single, new_text)

    if new_text != text:
        html_path.write_text(new_text, encoding="utf-8")
        logging.info(
            f"HEVC equations: {changed_math} math, {changed_code} pseudocode, "
            f"{changed_plain} plain-text, {changed_img} image block(s) processed; "
            f"{pseudocode_count} 2-col + {single_pseudocode_count} 1-col pseudocode table(s) converted; "
            f"source equation numbers stripped (specbuild will auto-number)"
        )


def fix_operator_tables(html_path: Path) -> None:
    """Remove empty first column and style operator tables in HEVC conventions.

    The original Word document has a 3-column operator table where the first
    column is always empty (used for spacing). Bikeshed renders these without
    closing ``</td>`` tags (HTML5 open-tag style).

    Also marks the operator symbol cells with ``class="operator-symbol"`` so
    CSS can reliably apply ``white-space: nowrap`` regardless of open-tag quirks.

    Args:
        html_path: Path to the compiled ``index.html`` (modified in place).
    """
    text = html_path.read_text(encoding="utf-8")

    # Open HTML5 style: <tr>\n<td>\n<td>CONTENT  (no </td> on empty cell)
    _OPEN_EMPTY_TD_RE = re.compile(r"(<tr>\s*)<td>\s*\n(\s*<td>)")
    # Closed style: <tr><td></td><td>CONTENT
    _CLOSED_EMPTY_TD_RE = re.compile(r"(<tr>\s*)<td>\s*</td>(\s*<td>)")

    new_text, n1 = _OPEN_EMPTY_TD_RE.subn(r"\1\2", text)
    new_text, n2 = _CLOSED_EMPTY_TD_RE.subn(r"\1\2", new_text)
    count = n1 + n2

    # Mark first td in each operator table row with class="operator-symbol"
    # so CSS can reliably target it for white-space: nowrap.
    # After stripping the empty first td, each row now starts with the symbol cell.
    # We identify operator table rows by their section context — but it's simpler
    # to just mark ALL first <td> cells in the <table class="data"> blocks that
    # immediately follow the operator section headings.
    _OPERATOR_SECTION_IDS = (
        "arithmetic-operators",
        "logical-operators",
        "relational-operators",
        "bit-wise-operators",
        "assignment-operators",
        "range-notation",
    )
    for section_id in _OPERATOR_SECTION_IDS:
        marker = f'id="{section_id}"'
        idx = new_text.find(marker)
        if idx < 0:
            continue
        # Find the next <table class="data"> after the heading
        table_start = new_text.find('<table class="data">', idx)
        if table_start < 0 or table_start - idx > 500:
            continue
        table_end = new_text.find("</table>", table_start)
        if table_end < 0:
            continue
        # In the table's tbody, mark each first <td> after <tr> as operator-symbol
        # and strip trailing whitespace/newlines from operator cell content so
        # white-space:pre-line doesn't create extra blank lines.
        table_html = new_text[table_start : table_end + 8]
        # Mark first td and strip its trailing newline before the next <td>
        marked = re.sub(
            r"(<tr>\s*)<td>([^\n<]*)\n(\s*<td>)",
            r'\1<td class="operator-symbol">\2\3',
            table_html,
        )
        # Also mark multi-word operators (e.g. "x<sup>y</sup>") that may span markup
        marked = re.sub(
            r"(<tr>\s*)<td>(?!class)",
            r'\1<td class="operator-symbol">',
            marked,
        )
        new_text = new_text[:table_start] + marked + new_text[table_end + 8 :]

    # Mark data tables whose cells contain meaningful newlines (e.g. Table 7-1
    # with "0\n1" and "TRAIL_N\nTRAIL_R") with class="multiline-cells" so
    # CSS white-space:pre-line applies only to those tables.
    _MULTILINE_TABLE_RE = re.compile(
        r'<table class="data"([^>]*)>(?=(?:(?!</table>).)*<td>[^\n<]+\n[^\n<\s])',
        re.DOTALL,
    )
    new_text = _MULTILINE_TABLE_RE.sub(
        r'<table class="data multiline-cells"\1>',
        new_text,
    )

    if count:
        html_path.write_text(new_text, encoding="utf-8")
        logging.info(f"Operator tables: removed {count} empty leading <td> cells")
