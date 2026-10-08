"""Math/equation lint check for spec equations.

Scans MathML, LaTeX-style spans, AsciiMath, and inline ``<code>`` math
fragments for common authoring bugs:

* Unbalanced ``(``/``)``, ``[``/``]``, ``{``/``}``
* Inconsistent capitalization of the same identifier (e.g. ``MaxCuSize``
  vs ``maxCuSize``) across the spec
* Identifiers used in math contexts that have no matching ``<dfn>`` in
  the document (when a glossary is built from the spec)

The check is read-only — it never mutates the soup. All three sub-checks
share a single pass over the document so the cost stays linear in the
number of math fragments.
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from collections.abc import Iterable, Iterator

from specbuild.utils import find_nearest_heading

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Markers indicating that a <code> block is "math-like" rather than plain
# code/identifier text. If none of these appear, the block is skipped by
# the math-lint heuristic so we don't false-flag prose <code> elements.
_MATH_MARKERS: tuple[str, ...] = (
    "_",
    "^",
    "\\frac",
    "\\sum",
    "\\prod",
    "\\int",
    "\\sqrt",
    "\\log",
    "\\sin",
    "\\cos",
    "\\tan",
    "\\alpha",
    "\\beta",
    "\\gamma",
    "\\theta",
    "\\pi",
    "\\Sigma",
    "(",
    "[",
    "{",
    "≤",
    "≥",
    "≠",
    "÷",
    "·",
    "×",
)

# Brace pairs that must balance. Order matters: each entry is (open, close).
_BRACE_PAIRS: tuple[tuple[str, str, str], ...] = (
    ("(", ")", "paren"),
    ("[", "]", "bracket"),
    ("{", "}", "brace"),
)

# Math-context identifier regex: at least three characters, alphanumeric +
# optional digits/underscores. We accept both ``MaxCuSize`` (CamelCase) and
# ``maxCuSize`` (camelCase) forms by requiring the first character to be a
# letter and at least one subsequent character.
_IDENT_RE = re.compile(r"\b([A-Za-z][A-Za-z0-9]{2,})\b")

# Identifiers that should never be flagged as undefined — these are common
# math constants and standard functions that appear unprototyped in spec
# equations and have no corresponding <dfn>.
_KNOWN_CONSTANTS: frozenset[str] = frozenset(
    {
        "e",
        "i",
        "pi",
        "Pi",
        "PI",
        "inf",
        "Inf",
        "INF",
        "nan",
        "NaN",
        "NAN",
        "true",
        "True",
        "TRUE",
        "false",
        "False",
        "FALSE",
        # Standard functions
        "sin",
        "cos",
        "tan",
        "asin",
        "acos",
        "atan",
        "atan2",
        "sinh",
        "cosh",
        "tanh",
        "log",
        "log2",
        "log10",
        "ln",
        "exp",
        "min",
        "max",
        "abs",
        "floor",
        "ceil",
        "round",
        "sqrt",
        "sum",
        "prod",
        "mod",
        "div",
        "and",
        "or",
        "not",
        "xor",
        "if",
        "else",
        "for",
        "while",
        "Sin",
        "Cos",
        "Tan",
        "Log",
        "Exp",
        "Min",
        "Max",
        "Abs",
        "Floor",
        "Ceil",
        "Round",
        "Sqrt",
        "Sum",
    }
)

# CSS class markers for non-MathML "math-like" spans. Inline LaTeX is
# typically rendered into ``<span class="math">`` (or .katex / .mathjax
# wrappers) by Bikeshed and friends.
_MATH_SPAN_CLASSES: frozenset[str] = frozenset(
    {"math", "mathml", "katex", "mathjax", "asciimath", "latex"}
)


# ---------------------------------------------------------------------------
# Math fragment collection (single pass)
# ---------------------------------------------------------------------------


def _is_math_like_code(text: str) -> bool:
    """Heuristic: does this <code> block contain math markers?

    Plain code identifiers like ``foo()`` should NOT be flagged just for
    parens — we require at least one of: an underscore (subscript), a
    caret (superscript), a TeX command, or a typographic math operator.
    Bare parens/brackets/braces alone are not enough.
    """
    if not text:
        return False
    # Strong markers — any of these indicates math intent.
    for m in ("_", "^", "\\", "≤", "≥", "≠", "÷", "·", "×", "∑", "∫", "∏", "√"):
        if m in text:
            return True
    return False


def _has_math_class(elem) -> bool:
    """Check if an element has a math-like CSS class."""
    classes = elem.get("class") or []
    if isinstance(classes, str):
        classes = classes.split()
    return any(c in _MATH_SPAN_CLASSES for c in classes)


def _iter_math_fragments(soup) -> Iterator[tuple[object, str, str]]:
    """Yield ``(element, kind, text)`` for every math-like fragment.

    *kind* is one of ``"mathml"``, ``"math-span"``, or ``"code"``.
    """
    # MathML elements
    for elem in soup.find_all("math"):
        text = elem.get_text(" ", strip=True)
        if text:
            yield elem, "mathml", text

    # Math-flavored spans (LaTeX/AsciiMath rendered inline)
    for elem in soup.find_all("span"):
        if _has_math_class(elem):
            text = elem.get_text(" ", strip=True)
            if text:
                yield elem, "math-span", text

    # <code> elements containing math markers
    for elem in soup.find_all("code"):
        text = elem.get_text(" ", strip=True)
        if text and _is_math_like_code(text):
            yield elem, "code", text


# ---------------------------------------------------------------------------
# Brace-balance check
# ---------------------------------------------------------------------------


def _strip_string_literals(text: str) -> str:
    """Remove single-/double-quoted substrings before counting braces.

    Quoted strings can legitimately contain unbalanced punctuation — we
    don't want a string like ``")"`` to throw off the balance counter.
    """
    # Drop double-quoted strings (greedy minimal)
    text = re.sub(r'"[^"]*"', "", text)
    # Drop single-quoted strings
    text = re.sub(r"'[^']*'", "", text)
    return text


def _count_balance(text: str, open_ch: str, close_ch: str) -> tuple[int, int]:
    """Return (open_count, close_count) for the given pair."""
    return text.count(open_ch), text.count(close_ch)


def check_paren_balance(soup) -> list[dict]:
    """Detect unbalanced parens/brackets/braces in math fragments.

    Args:
        soup: BeautifulSoup document (read-only).

    Returns:
        List of issue dicts with keys ``element_id``, ``snippet``, ``kind``,
        ``brace``, ``expected``, ``actual``, ``context``.
    """
    issues: list[dict] = []
    for elem, kind, text in _iter_math_fragments(soup):
        cleaned = _strip_string_literals(text)
        for open_ch, close_ch, brace_name in _BRACE_PAIRS:
            opens, closes = _count_balance(cleaned, open_ch, close_ch)
            if opens != closes:
                issues.append(
                    {
                        "element_id": elem.get("id") or "",
                        "snippet": _truncate(text, 80),
                        "kind": kind,
                        "brace": brace_name,
                        "expected": opens,
                        "actual": closes,
                        "context": find_nearest_heading(elem),
                    }
                )
    return issues


# ---------------------------------------------------------------------------
# Symbol-casing check
# ---------------------------------------------------------------------------


def _extract_identifiers(text: str) -> Iterable[str]:
    """Yield identifier tokens (length >= 3) from a math fragment."""
    for match in _IDENT_RE.finditer(text):
        token = match.group(1)
        # Skip pure-numeric or single-case tokens that look like
        # standards acronyms (HEVC, AV1) — these aren't identifiers.
        # We keep tokens that have at least one lowercase letter, OR
        # mixed-case tokens that look like CamelCase.
        if token.isupper() and len(token) <= 5:
            continue
        yield token


def check_symbol_casing(soup) -> list[dict]:
    """Detect identifiers used with inconsistent capitalization.

    Groups all identifiers by their lowercase form; if a group has more
    than one distinct surface form, every member is reported.

    Args:
        soup: BeautifulSoup document (read-only).

    Returns:
        List of issue dicts with keys ``lowercase``, ``variants``, ``count``.
    """
    by_lower: dict[str, set[str]] = defaultdict(set)
    for _elem, _kind, text in _iter_math_fragments(soup):
        for token in _extract_identifiers(text):
            by_lower[token.lower()].add(token)

    issues: list[dict] = []
    for lower, variants in sorted(by_lower.items()):
        if len(variants) > 1:
            issues.append(
                {
                    "lowercase": lower,
                    "variants": sorted(variants),
                    "count": len(variants),
                }
            )
    return issues


# ---------------------------------------------------------------------------
# Undefined-symbol check
# ---------------------------------------------------------------------------


def _slugify(name: str) -> str:
    """Replicate the lightweight slugification used by Bikeshed dfn ids."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _collect_dfn_ids(soup) -> set[str]:
    """Return the set of slugified ids/text for every <dfn> in the doc."""
    ids: set[str] = set()
    for elem in soup.find_all("dfn"):
        if elem.get("id"):
            ids.add(elem["id"].lower())
        text = elem.get_text(strip=True)
        if text:
            ids.add(_slugify(text))
            ids.add(text.lower())
    return ids


def check_undefined_symbols(soup, dfn_ids: set[str] | None = None) -> list[dict]:
    """Flag identifiers in math contexts that have no matching ``<dfn>``.

    Args:
        soup: BeautifulSoup document (read-only).
        dfn_ids: Optional pre-collected set of dfn ids/slugs. When ``None``
            (the default), the set is computed from the soup.

    Returns:
        List of issue dicts with keys ``identifier``, ``snippet``,
        ``context``, ``element_id``.
    """
    if dfn_ids is None:
        dfn_ids = _collect_dfn_ids(soup)

    # If the spec has no dfn glossary, we can't make an informed call —
    # silently return an empty list so we don't spam findings.
    if not dfn_ids:
        return []

    seen: set[tuple[str, str]] = set()
    issues: list[dict] = []
    for elem, _kind, text in _iter_math_fragments(soup):
        context = find_nearest_heading(elem)
        for token in _extract_identifiers(text):
            if token in _KNOWN_CONSTANTS or token.lower() in _KNOWN_CONSTANTS:
                continue
            slug = _slugify(token)
            if slug in dfn_ids or token.lower() in dfn_ids:
                continue
            key = (token, context)
            if key in seen:
                continue
            seen.add(key)
            issues.append(
                {
                    "identifier": token,
                    "snippet": _truncate(text, 80),
                    "context": context,
                    "element_id": elem.get("id") or "",
                }
            )
    return issues


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def run_math_lint(soup) -> dict:
    """Run all three math-lint checks and aggregate the result.

    Args:
        soup: BeautifulSoup document (read-only).

    Returns:
        Dict with keys ``paren``, ``casing``, ``undefined`` (each a list of
        issue dicts) and ``total`` (overall count).
    """
    paren = check_paren_balance(soup)
    casing = check_symbol_casing(soup)
    # Reuse the dfn-id set rather than recomputing per-call.
    dfn_ids = _collect_dfn_ids(soup)
    undefined = check_undefined_symbols(soup, dfn_ids=dfn_ids)
    return {
        "paren": paren,
        "casing": casing,
        "undefined": undefined,
        "total": len(paren) + len(casing) + len(undefined),
    }


def report_math_lint(result: dict, *, strict: bool = False) -> None:
    """Log math-lint findings at WARNING level.

    Args:
        result: Output of :func:`run_math_lint`.
        strict: If ``True`` and any issues exist, raise ``SystemExit(1)``.
    """
    total = result.get("total", 0)
    if total == 0:
        logging.info("Math-lint passed: no issues found")
        return

    logging.warning(f"Math-lint: {total} issue(s)")

    for issue in result.get("paren", []):
        logging.warning(
            f"  unbalanced {issue['brace']} in {issue['kind']}: "
            f"{issue['expected']} open vs {issue['actual']} close — "
            f'"{issue["snippet"]}" (near: {issue["context"]})'
        )

    for issue in result.get("casing", []):
        logging.warning(
            f"  inconsistent casing for '{issue['lowercase']}': {', '.join(issue['variants'])}"
        )

    for issue in result.get("undefined", []):
        logging.warning(
            f"  undefined symbol '{issue['identifier']}' in math (near: {issue['context']})"
        )

    if strict:
        raise SystemExit(1)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _truncate(text: str, n: int) -> str:
    """Return *text* truncated to *n* characters with an ellipsis."""
    text = text.strip()
    if len(text) <= n:
        return text
    return text[: n - 1] + "…"
