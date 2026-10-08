"""MathML accessibility and structural improvements.

Enhances existing ``<math>`` elements produced by MathJax or similar
renderers by adding ARIA labels, ``alttext`` attributes, correct
``display`` attributes, and appropriate CSS spacing.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bs4 import BeautifulSoup


# Map common LaTeX symbols to their MathML equivalents for fallback rendering
_LATEX_TO_MATHML: dict[str, str] = {
    r"\times": "<mo>×</mo>",
    r"\cdot": "<mo>·</mo>",
    r"\leq": "<mo>≤</mo>",
    r"\geq": "<mo>≥</mo>",
    r"\neq": "<mo>≠</mo>",
    r"\approx": "<mo>≈</mo>",
    r"\rightarrow": "<mo>→</mo>",
    r"\leftarrow": "<mo>←</mo>",
    r"\infty": "<mi>∞</mi>",
    r"\alpha": "<mi>α</mi>",
    r"\beta": "<mi>β</mi>",
    r"\gamma": "<mi>γ</mi>",
    r"\delta": "<mi>δ</mi>",
    r"\lambda": "<mi>λ</mi>",
    r"\mu": "<mi>μ</mi>",
    r"\pi": "<mi>π</mi>",
    r"\sigma": "<mi>σ</mi>",
    r"\sum": "<mo>∑</mo>",
    r"\prod": "<mo>∏</mo>",
    r"\int": "<mo>∫</mo>",
    r"\sqrt": "<msqrt>",
}

# Tags whose direct children are treated as block-level math context
_BLOCK_PARENT_TAGS = frozenset({"p", "div", "figure", "section"})


def process_mathml_accessibility_soup(soup: BeautifulSoup) -> int:
    """Add aria-label and alttext to existing ``<math>`` elements for screen readers.

    For each ``<math>`` element:

    1. Set ``display="block"`` when the element is a direct child of a block
       container (``<p>``, ``<div>``, ``<figure>``, ``<section>``), or
       ``display="inline"`` otherwise — unless the attribute is already present.
    2. Extract text content and set ``alttext`` if not already set.
    3. Set ``aria-label`` to match ``alttext`` for WCAG compliance if not
       already set.

    Args:
        soup: Parsed BeautifulSoup document to modify in-place.

    Returns:
        Count of ``<math>`` elements enhanced (all ``<math>`` elements are
        counted, including those that already had all attributes).
    """
    count = 0

    for math in soup.find_all("math"):
        # Set display attribute based on parent context
        parent = math.parent
        parent_name = getattr(parent, "name", None)
        if parent_name in _BLOCK_PARENT_TAGS:
            if not math.get("display"):
                math["display"] = "block"
        elif not math.get("display"):
            math["display"] = "inline"

        # Build text content for aria-label
        text_content = math.get_text(strip=True)
        if text_content and not math.get("alttext"):
            math["alttext"] = text_content
        if math.get("alttext") and not math.get("aria-label"):
            math["aria-label"] = math["alttext"]

        count += 1

    return count


def generate_mathml_fallback(latex_fragment: str) -> str:
    """Convert a simple LaTeX fragment to a MathML string (partial coverage).

    Handles basic cases: single symbols, simple fractions, superscripts,
    and subscripts.  For complex expressions, wraps the original text in an
    ``<mi>`` element.

    This is intentionally minimal — full LaTeX→MathML conversion requires the
    ``latex2mathml`` library or equivalent.

    Args:
        latex_fragment: LaTeX math expression (without surrounding ``$`` or
            ``\\[…\\]`` delimiters).

    Returns:
        A MathML string fragment (not a complete ``<math>`` element).
    """
    fragment = latex_fragment.strip()

    # Apply known symbol substitutions
    for latex_sym, mathml_elem in _LATEX_TO_MATHML.items():
        fragment = fragment.replace(latex_sym, mathml_elem)

    # Handle \frac{num}{den}
    def _replace_frac(m: re.Match) -> str:
        num = m.group(1)
        den = m.group(2)
        return f"<mfrac><mrow>{num}</mrow><mrow>{den}</mrow></mfrac>"

    fragment = re.sub(r"\\frac\{([^}]*)\}\{([^}]*)\}", _replace_frac, fragment)

    # Handle superscripts: x^{n} or x^n
    def _replace_sup(m: re.Match) -> str:
        base = m.group(1)
        exp = m.group(2)
        return f"<msup><mi>{base}</mi><mn>{exp}</mn></msup>"

    fragment = re.sub(r"(\w)\^\{([^}]+)\}", _replace_sup, fragment)
    fragment = re.sub(r"(\w)\^(\w)", _replace_sup, fragment)

    # Handle subscripts: x_{n} or x_n
    def _replace_sub(m: re.Match) -> str:
        base = m.group(1)
        sub = m.group(2)
        return f"<msub><mi>{base}</mi><mn>{sub}</mn></msub>"

    fragment = re.sub(r"(\w)_\{([^}]+)\}", _replace_sub, fragment)
    fragment = re.sub(r"(\w)_(\w)", _replace_sub, fragment)

    # If no MathML tags were produced, wrap entire expression in <mi>
    if "<" not in fragment:
        return f"<mi>{fragment}</mi>"

    return fragment


def inject_mathml_css(soup: BeautifulSoup) -> None:
    """Inject CSS to properly size and space MathML block and inline equations.

    Args:
        soup: Parsed BeautifulSoup document to modify in-place.
    """
    from specbuild.utils import inject_css

    inject_css(
        soup,
        "mathml-spacing-css",
        """
math[display="block"] {
  display: block;
  margin: 1em auto;
  text-align: center;
  overflow-x: auto;
}
math[display="inline"] {
  /* display:inline-block prevents browsers whose native MathML UA stylesheet
     uses display:math (block-level) from creating unwanted line breaks around
     inline variables. inline-block keeps the element in the text flow while
     still rendering the MathML content correctly. */
  display: inline-block !important;
  vertical-align: -0.2em;
  line-height: 1;
}
""",
    )
