"""Extract equations from Formula-style paragraphs in Word documents.

Equations in standards documents like H.265/HEVC are typically authored as
``Formula`` or ``Equation`` styled paragraphs.  The equation body may be
plain text, Office MathML (OMML), an embedded OLE object (Microsoft
Equation Editor / MathType \u2014 common in older ISO documents), or a mixture.
An equation number in parentheses (e.g. ``(5-1)``) usually appears at the
right margin.

This module extracts the equation content and number, and formats them
for Bikeshed output.
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------

#: Matches an equation number at the end of text: (5-1), (8-123), (A-2).
#: Supports both hyphens and en-dashes as separators.
EQ_NUMBER_RE = re.compile(r"\(([A-Za-z0-9]+[\-\u2013][A-Za-z0-9]+)\)\s*$")

#: Matches a simple standalone equation number: (1), (42).
EQ_SIMPLE_NUMBER_RE = re.compile(r"\((\d+)\)\s*$")

#: Matches a ``<v:imagedata r:id="rIdXX"/>`` element inside an OLE-equation
#: paragraph.  Equation Editor / MathType OLE objects embed a preview image
#: (WMF / PNG) via this VML imagedata reference.
_VIMAGEDATA_RID_RE = re.compile(r'<v:imagedata[^>]*r:id="([^"]+)"')


#: Words that strongly indicate the "equation" is actually a textual definition
#: (e.g. ``Asin(x) the trigonometric inverse sine function operating on an
#: argument x in units of radians``).  HEVC and other ISO standards style
#: simple function definitions as Formula paragraphs even though they are
#: prose, not math.
_PROSE_KEYWORDS = frozenset(
    [
        "the",
        "is",
        "function",
        "operating",
        "operation",
        "value",
        "argument",
        "inclusive",
        "range",
        "where",
        "with",
        "denotes",
        "specifies",
        "equal",
        "less",
        "greater",
        "smallest",
        "largest",
        "natural",
        "trigonometric",
        "logarithm",
        "such",
        "given",
        "according",
        "respectively",
    ]
)


def _looks_like_prose(text: str) -> bool:
    """Return True if *text* appears to be a textual definition, not math.

    Heuristic: count occurrences of common English prose keywords.  A
    Formula paragraph that contains three or more of these is overwhelmingly
    likely to be a verbal definition (e.g. ``Asin(x) the inverse sine
    function operating on an argument...``) rather than an actual equation.
    """
    if not text:
        return False
    words = re.findall(r"\b[a-z]{2,}\b", text.lower())
    prose_hits = sum(1 for w in words if w in _PROSE_KEYWORDS)
    return prose_hits >= 3


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------


def extract_equation(paragraph) -> dict:
    """Extract equation content and number from a Formula paragraph.

    Args:
        paragraph: A python-docx ``Paragraph`` with a Formula/Equation style.

    Returns:
        Dict with keys:

        * ``text`` — the equation body (stripped of the number)
        * ``number`` — the equation number string (e.g. ``"5-1"``) or ``None``
        * ``has_omml`` — ``True`` if Office MathML is present
        * ``image_path`` — relative path to an embedded OLE-equation preview
          image (e.g. ``"images/image3.wmf"``), or ``None``
    """
    text = paragraph.text.strip()

    # Try compound number first (section-number), then simple
    eq_num: str | None = None
    eq_text = text

    m = EQ_NUMBER_RE.search(text)
    if m is None:
        m = EQ_SIMPLE_NUMBER_RE.search(text)

    if m:
        eq_num = m.group(1)
        eq_text = text[: m.start()].strip()

    return {
        "text": eq_text,
        "number": eq_num,
        "has_omml": _has_omml(paragraph),
        "image_path": _extract_ole_equation_image(paragraph),
    }


def format_equation_bs(eq: dict) -> str:
    """Format an extracted equation for Bikeshed output.

    Wraps the equation text in ``$$`` delimiters.  If an equation number
    is present it is placed in a right-aligned span.  If the equation was
    embedded as an OLE preview image (e.g. MathType equations in older ISO
    docs), the image is emitted inside the equation block.

    Args:
        eq: Dict returned by :func:`extract_equation`.

    Returns:
        Bikeshed-compatible equation markup.
    """
    text = eq.get("text", "").strip()
    number = eq.get("number")
    image_path = eq.get("image_path")

    # Skip a noise text that is just the equation number marker (e.g. "(5-1)")
    if text and re.fullmatch(r"\(\s*[A-Za-z0-9\-–]+\s*\)", text):
        text = ""

    if not text and not image_path:
        return ""

    # If the text is a verbal definition rather than an equation, emit it as
    # prose inside the equation block — without $$ LaTeX wrapping that would
    # otherwise fail to render and corrupt the output.
    text_is_prose = bool(text) and _looks_like_prose(text)

    lines: list[str] = []
    lines.append("<div class='equation'>")
    if image_path:
        # Rendered preview from the embedded OLE object
        lines.append(f'  <img src="{image_path}" alt="Equation {number or ""}">')
    if text:
        if text_is_prose:
            lines.append(f"  {text}")
        else:
            lines.append(f"  $$ {text} $$")
    if number:
        lines.append(f"  <span class='equation-number'>({number})</span>")
    lines.append("</div>")
    lines.append("")

    return "\n".join(lines)


def batch_extract_equations(paragraphs: list) -> list[dict]:
    """Extract equations from a list of Formula/Equation paragraphs.

    Args:
        paragraphs: List of python-docx paragraphs already classified as
            equation type.

    Returns:
        List of equation dicts (see :func:`extract_equation`).
    """
    results: list[dict] = []
    for para in paragraphs:
        eq = extract_equation(para)
        if eq["text"]:
            results.append(eq)
    return results


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _has_omml(paragraph) -> bool:
    """Check if a paragraph contains Office Math ML elements.

    Args:
        paragraph: A python-docx ``Paragraph``.

    Returns:
        ``True`` if the paragraph's underlying XML contains ``oMath``.
    """
    try:
        xml = paragraph._element.xml
        return "oMath" in xml
    except Exception:
        return False


def _extract_ole_equation_image(paragraph) -> str | None:
    """Return the relative image path for an OLE-embedded equation, or None.

    MathType / Equation Editor equations in Word are stored as a binary OLE
    object plus a ``<v:imagedata r:id="rIdX">`` preview image (usually WMF).
    The WMF can be displayed directly even when the OLE source is opaque.

    Returns:
        Path like ``"images/image3.wmf"`` (matching what figureextract.py
        writes to the output ``images/`` dir), or ``None`` if no preview.
    """
    try:
        xml = paragraph._element.xml
    except Exception:
        return None

    m = _VIMAGEDATA_RID_RE.search(xml)
    if not m:
        return None
    rid = m.group(1)
    try:
        rels = paragraph.part.rels
    except AttributeError:
        return None
    if rid not in rels:
        return None
    target = rels[rid].target_ref
    # Strip the "media/" prefix that python-docx returns
    if target.startswith("media/"):
        target = target[len("media/") :]
    return f"images/{target}"
