"""Automatic equation numbering for compiled HTML specifications."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bs4 import BeautifulSoup, Tag

from specbuild.theme import THEME
from specbuild.utils import get_bs4, inject_css, read_html, write_html

# Mapping of section numbers to Annex letters (matches add_table_numbers_for_pdf.py)
ANNEX_MAPPING = {
    10: "A",
    11: "B",
    12: "C",
    13: "D",
    14: "E",
}

# Regex for display math delimiters: $$...$$
_DISPLAY_MATH_RE = re.compile(r"^\s*\$\$(.+?)\$\$\s*$", re.DOTALL)

# Regex for inline AsciiMath backtick delimiters: `...`
_INLINE_ASCIIMATH_RE = re.compile(r"`([^`]+?)`")

# ---------------------------------------------------------------------------
# AsciiMath → TeX converter
# ---------------------------------------------------------------------------

# Greek letter table (AsciiMath name → TeX command)
_GREEK = {
    "alpha": r"\alpha",
    "beta": r"\beta",
    "gamma": r"\gamma",
    "Gamma": r"\Gamma",
    "delta": r"\delta",
    "Delta": r"\Delta",
    "epsilon": r"\epsilon",
    "varepsilon": r"\varepsilon",
    "zeta": r"\zeta",
    "eta": r"\eta",
    "theta": r"\theta",
    "Theta": r"\Theta",
    "iota": r"\iota",
    "kappa": r"\kappa",
    "lambda": r"\lambda",
    "Lambda": r"\Lambda",
    "mu": r"\mu",
    "nu": r"\nu",
    "xi": r"\xi",
    "Xi": r"\Xi",
    "pi": r"\pi",
    "Pi": r"\Pi",
    "rho": r"\rho",
    "sigma": r"\sigma",
    "Sigma": r"\Sigma",
    "tau": r"\tau",
    "upsilon": r"\upsilon",
    "phi": r"\phi",
    "Phi": r"\Phi",
    "chi": r"\chi",
    "psi": r"\psi",
    "Psi": r"\Psi",
    "omega": r"\omega",
    "Omega": r"\Omega",
}

# Token substitution table applied in order (most specific first)
_SUBSTITUTIONS: list[tuple[str | re.Pattern[str], str]] = [
    # Fraction: (x)/(y) → \frac{x}{y}
    (re.compile(r"\(([^()]+)\)\s*/\s*\(([^()]+)\)"), r"\\frac{\1}{\2}"),
    # Plus-minus / minus-plus
    ("+-", r"\pm"),
    ("-+", r"\mp"),
    # Relational operators
    ("!=", r"\neq"),
    ("<=", r"\leq"),
    (">=", r"\geq"),
    # Infinity (letter-only lookahead so "boom" / "stoop" / "Pool" aren't
    # touched, but `oo_n` / `oo^2` still match — `_` is a word char in Python
    # regex, so plain `\b` would fail before underscores).
    (re.compile(r"\boo(?![a-zA-Z])"), r"\\infty"),
    # Large operators (letter-only lookahead so "summation" / "consumption" /
    # "interest" aren't mangled but `sum_n^N` and `int_a^b` still match).
    (re.compile(r"\bsum(?![a-zA-Z])"), r"\\sum"),
    (re.compile(r"\bprod(?![a-zA-Z])"), r"\\prod"),
    (re.compile(r"\bint(?![a-zA-Z])"), r"\\int"),
    # sqrt(x) → \sqrt{x}
    (re.compile(r"sqrt\(([^()]+)\)"), r"\\sqrt{\1}"),
    # Superscript: x^2 → x^{2} (only when argument is a single token)
    (re.compile(r"\^([A-Za-z0-9]+)"), r"^{\1}"),
    # Subscript: x_n → x_{n} (only when argument is a single token)
    (re.compile(r"_([A-Za-z0-9]+)"), r"_{\1}"),
]


def _asciimath_to_tex(expr: str) -> str:
    """Convert an AsciiMath expression to a best-effort TeX string.

    This is a lightweight structural converter, not full AsciiMath spec
    compliance.  It handles the most common constructs:

    * Fractions: ``(x)/(y)`` → ``\\frac{x}{y}``
    * Square roots: ``sqrt(x)`` → ``\\sqrt{x}``
    * Superscripts / subscripts: ``x^2``, ``x_n``
    * Greek letters: ``alpha`` → ``\\alpha``, etc.
    * Large operators: ``sum``, ``prod``, ``int``
    * Constants: ``oo`` → ``\\infty``
    * Relations: ``!=``, ``<=``, ``>=``
    * Signs: ``+-`` → ``\\pm``, ``-+`` → ``\\mp``

    Args:
        expr: Raw AsciiMath expression (without delimiter backticks).

    Returns:
        Approximate TeX string suitable for MathJax / KaTeX rendering.
    """
    result = expr

    for pattern, replacement in _SUBSTITUTIONS:
        if isinstance(pattern, str):
            result = result.replace(pattern, replacement)
        else:
            result = pattern.sub(replacement, result)

    # Substitute Greek letters (whole-word only to avoid partial matches).
    # Use a callback so the TeX command (e.g. r"\alpha") is treated as a
    # literal replacement, not a re.sub template (where `\a` would be parsed
    # as the alert/bell escape and `\s` as an invalid backreference).
    for name, tex_cmd in _GREEK.items():
        result = re.sub(rf"\b{re.escape(name)}\b", lambda _m, tc=tex_cmd: tc, result)

    return result


def _get_section_label(section_number: int) -> str:
    """Return the display label for a section (letter for Annexes, number otherwise)."""
    return ANNEX_MAPPING.get(section_number, str(section_number))


def _is_display_math_paragraph(elem: Tag) -> bool:
    """Check if a <p> element contains only a display math block ($$...$$)."""
    if elem.name != "p":
        return False
    text = elem.get_text(strip=True)
    return bool(_DISPLAY_MATH_RE.match(text))


def _apply_equation_number(
    target_elem: Tag,
    soup: BeautifulSoup,
    section_number: int,
    eq_counter: int,
    eq_map: dict[str, str],
    tex_source: str | None = None,
) -> bool:
    """Wrap an equation element and add a number span.

    Args:
        target_elem: The element to number (mjx-container or <p> with $$).
        soup: BeautifulSoup document.
        section_number: Current section number.
        eq_counter: Current equation counter within the section.
        eq_map: Dict mapping equation IDs to display labels (mutated).
        tex_source: Original TeX source string; stored as data-tex for STS XML export.

    Returns:
        True if the equation was numbered, False if skipped.
    """
    # Skip if this specific element is already inside an equation-wrapper with a number
    parent = target_elem.parent
    if parent and "equation-wrapper" in parent.get("class", []):
        if parent.find("span", class_="equation-number", recursive=False):
            return False

    # Skip auto-ID generation if the element already has a user-defined id attribute
    if target_elem.get("id"):
        return False

    section_label = _get_section_label(section_number)
    eq_ref = f"{section_label}.{eq_counter}"
    eq_id = f"eq-{section_label}-{eq_counter}"

    num_span = soup.new_tag("span", id=eq_id, **{"class": "equation-number"})
    num_span.string = f"({eq_ref})"

    if parent and "equation-wrapper" in parent.get("class", []):
        parent.append(num_span)
        if tex_source:
            parent["data-tex"] = tex_source
    else:
        wrapper_attrs: dict = {"class": "equation-wrapper"}
        if tex_source:
            wrapper_attrs["data-tex"] = tex_source
        wrapper = soup.new_tag("div", **wrapper_attrs)
        target_elem.wrap(wrapper)
        wrapper.append(num_span)

    eq_map[eq_id] = eq_ref

    # Also register any user-defined eq-* ID on an ancestor <div>,
    # so cross-references like <a href="#eq-wheelbase"> get auto-updated.
    # Only register if not already in eq_map (avoid overwriting pre-existing entries).
    for ancestor in target_elem.parents:
        ancestor_id = ancestor.get("id", "")
        if ancestor_id and ancestor_id.startswith("eq-") and ancestor_id != eq_id:
            if ancestor_id not in eq_map:
                eq_map[ancestor_id] = eq_ref
            break
        if ancestor.name in ("section", "main", "body"):
            break

    return True


def number_equations(html_path: Path) -> int:
    """Number display equations as ``(section.N)`` and update cross-references.

    File-based wrapper around :func:`number_equations_soup`.

    Args:
        html_path: Path to the compiled HTML file.

    Returns:
        Number of equations that were numbered.
    """
    try:
        get_bs4()
    except ImportError:
        logging.warning("BeautifulSoup not available, skipping equation numbering")
        return 0

    logging.info(f"Numbering equations in {html_path.name}")
    soup = read_html(html_path)
    result = number_equations_soup(soup)
    write_html(html_path, soup)
    return result


def number_equations_soup(soup: BeautifulSoup) -> int:
    """Number display equations as ``(section.N)`` and update cross-references.

    Detects display equations in three forms:

    1. ``mjx-container[display="true"]`` — MathJax-rendered equations
    2. ``<p>$$...$$</p>`` — raw TeX display math not yet rendered by MathJax
    3. ``<div class="asciimath-display">`` or ``<span/code class="asciimath">``
       — AsciiMath expressions (converted to TeX via :func:`_asciimath_to_tex`)

    Assigns sequential numbers within each major section (h2) using
    section-based labels like ``(5.1)``, ``(A.2)`` for Annexes, etc.

    Args:
        soup: BeautifulSoup document (mutated in place).

    Returns:
        Number of equations that were numbered.
    """

    main = soup.find("main")
    if not main:
        logging.warning("No <main> element found, cannot number equations")
        return 0

    section_number = 0
    eq_counter = 0
    total_numbered = 0
    eq_map: dict[str, str] = {}  # id -> display label e.g. "5.3"

    # Walk all children of <main> to track section boundaries.
    # Snapshot the children list because Strategy 2/3 may wrap() direct children
    # of <main>, which mutates main.children mid-iteration and would otherwise
    # cause skipped or double-processed elements.
    for elem in list(main.children):
        if not hasattr(elem, "name") or elem.name is None:
            continue

        # Detect numbered h2 headings — read actual secno rather than counting,
        # so intro-zero shifts (section 0 for Introduction) are reflected correctly.
        if (
            elem.name == "h2"
            and "heading" in elem.get("class", [])
            and "settled" in elem.get("class", [])
            and "no-num" not in elem.get("class", [])
        ):
            secno_span = elem.find("span", class_="secno")
            if secno_span:
                raw = secno_span.get_text(strip=True).rstrip(".")
                try:
                    section_number = int(raw.split(".")[0])
                except ValueError:
                    section_number += 1
            else:
                section_number += 1
            eq_counter = 0

        # Strategy 1: Find MathJax-rendered display equations
        display_eqs = elem.find_all("mjx-container", attrs={"display": "true"})

        for mjx in display_eqs:
            if mjx.find("mjx-labels"):
                continue
            # Try to recover TeX source from MathML annotation element
            ann = mjx.find("annotation", {"encoding": "application/x-tex"})
            tex = ann.get_text(strip=True) if ann else None
            if _apply_equation_number(
                mjx, soup, section_number, eq_counter + 1, eq_map, tex_source=tex
            ):
                eq_counter += 1
                total_numbered += 1

        # Strategy 1b: Native MathML display equations (pre-rendered by latex2mathml)
        mathml_display = elem.find_all("math", attrs={"display": "block"})
        for math_el in mathml_display:
            if math_el.get("id", "").startswith("eq-"):
                continue  # already numbered
            tex = math_el.get("alttext") or math_el.get("data-latex")
            if _apply_equation_number(
                math_el, soup, section_number, eq_counter + 1, eq_map, tex_source=tex
            ):
                eq_counter += 1
                total_numbered += 1

        # Strategy 2: Find raw $$...$$ display math in <p> tags
        if not display_eqs and not mathml_display:
            raw_math_paras = []
            if _is_display_math_paragraph(elem):
                raw_math_paras.append(elem)
            else:
                for child in elem.find_all("p"):
                    if _is_display_math_paragraph(child):
                        raw_math_paras.append(child)

            for para in raw_math_paras:
                raw_text = para.get_text(strip=True)
                m = _DISPLAY_MATH_RE.match(raw_text)
                tex = m.group(1).strip() if m else None
                if _apply_equation_number(
                    para, soup, section_number, eq_counter + 1, eq_map, tex_source=tex
                ):
                    eq_counter += 1
                    total_numbered += 1

        # Strategy 3: AsciiMath display blocks
        asciimath_display = elem.find_all("div", class_="asciimath-display")
        for am_div in asciimath_display:
            raw_am = am_div.get_text(strip=True)
            tex = _asciimath_to_tex(raw_am)
            am_div["data-asciimath"] = raw_am
            if _apply_equation_number(
                am_div, soup, section_number, eq_counter + 1, eq_map, tex_source=tex
            ):
                eq_counter += 1
                total_numbered += 1

        # Strategy 4: Inline AsciiMath elements (<span> or <code class="asciimath">)
        for am_el in elem.find_all(["span", "code"], class_="asciimath"):
            raw_am = am_el.get_text(strip=True)
            tex = _asciimath_to_tex(raw_am)
            am_el["data-asciimath"] = raw_am
            am_el["data-tex"] = tex

        # Strategy 5: HEVC-style <div class="equation"> wrapping <code class="equation-math">,
        # <pre class="equation-code">, or <span class="equation-text">.
        # These are produced by hevcequations.py and need auto-numbering.
        if elem.name == "div" and "equation" in elem.get("class", []):
            wrapper = elem.find("div", class_="equation-wrapper")
            if wrapper and not wrapper.find("span", class_="equation-number"):
                if wrapper.find(["code", "pre", "span"]):
                    if _apply_equation_number(
                        wrapper, soup, section_number, eq_counter + 1, eq_map
                    ):
                        eq_counter += 1
                        total_numbered += 1
        else:
            for eq_div in elem.find_all("div", class_="equation"):
                wrapper = eq_div.find("div", class_="equation-wrapper")
                if wrapper and not wrapper.find("span", class_="equation-number"):
                    if wrapper.find(["code", "pre", "span"]):
                        if _apply_equation_number(
                            wrapper, soup, section_number, eq_counter + 1, eq_map
                        ):
                            eq_counter += 1
                            total_numbered += 1

    # Update cross-references: links pointing to #eq-... IDs
    refs_updated = 0
    ref_prefix = THEME.equation_ref_prefix
    for link in soup.find_all("a", href=True):
        href = link["href"]
        if href.startswith("#eq-") and href[1:] in eq_map:
            eq_label = f"({eq_map[href[1:]]})"
            if ref_prefix:
                from bs4 import NavigableString as _NS

                link.clear()
                link.append(_NS(f"{ref_prefix}\u00a0{eq_label}"))
            else:
                from bs4 import NavigableString as _NS

                link.clear()
                link.append(_NS(eq_label))
            refs_updated += 1

    if total_numbered > 0:
        _inject_equation_numbering_css(soup)

    log = logging.info if total_numbered else logging.debug
    log(
        f"Numbered {total_numbered} equations in {section_number} sections, "
        f"updated {refs_updated} cross-references"
    )
    return total_numbered


def _inject_equation_numbering_css(soup: BeautifulSoup) -> None:
    """Inject CSS for equation number positioning into the document <head>."""
    t = THEME
    css = f"""
/* Equation Numbering */
.equation-wrapper {{
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin: 1em 0;
  gap: 2em;
  overflow: visible;
}}
.equation-wrapper > p {{
  flex: 1;
  text-align: center !important;
  margin: 0 !important;
  overflow: visible !important;
}}
.equation-wrapper mjx-container {{
  flex: 1;
  text-align: center !important;
  overflow: visible !important;
}}
/* Override Bikeshed's overflow:auto on <math> — cases/tall expressions must not scroll */
.equation-wrapper math {{
  overflow: visible !important;
  display: block;
  text-align: center;
  flex: 1;
}}
.equation-number {{
  flex: 0 0 auto;
  white-space: nowrap;
  font-size: 1em;
  font-weight: normal;
  color: {t.equation_number_color};
  align-self: center;
}}
@media print {{
  .equation-wrapper {{
    margin: 0.8em 0;
  }}
  .equation-number {{
    font-size: {t.equation_number_font_size};
  }}
}}
"""
    inject_css(soup, "equation-numbering-css", css)
