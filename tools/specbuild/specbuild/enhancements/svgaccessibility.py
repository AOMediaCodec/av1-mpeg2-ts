"""SVG accessibility processing.

Ensures inline ``<svg>`` elements are accessible by adding ARIA roles,
``<title>`` elements, ``aria-labelledby``/``aria-describedby`` attributes,
namespace declarations, ``viewBox`` normalisation, and IE11 focus guards.

Authoring example::

    <figure>
      <svg width="200" height="100">
        <!-- paths omitted -->
      </svg>
      <figcaption>Block diagram of the encoder pipeline</figcaption>
    </figure>

After processing the SVG will receive ``role="img"``, a ``<title>`` derived
from the ``<figcaption>`` text, ``aria-labelledby`` pointing at that title,
a normalised ``viewBox``, and ``focusable="false"``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bs4 import BeautifulSoup, Tag

from specbuild.utils import inject_css

# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------

_SVG_CSS = """\
/* SVG accessibility */
svg { max-width: 100%; height: auto; }
figure > svg { display: block; margin: auto; }
"""

# ---------------------------------------------------------------------------
# SVG namespace
# ---------------------------------------------------------------------------

_SVG_XMLNS = "http://www.w3.org/2000/svg"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _derive_title_text(svg: Tag) -> str:
    """Return the best available title text for an SVG element.

    Priority order:
    1. Sibling/parent ``<figcaption>`` text
    2. ``aria-label`` attribute on the SVG itself
    3. ``data-caption`` attribute on the SVG itself
    4. Fallback: ``"Figure"``
    """
    # 1. Look for a <figcaption> that is a sibling (same <figure>) or a direct
    #    child of the SVG's parent element.
    parent = svg.parent
    if parent is not None:
        figcaption = parent.find("figcaption")
        if figcaption is not None:
            text = figcaption.get_text(strip=True)
            if text:
                return text

    # 2. aria-label on the SVG
    aria_label = svg.get("aria-label", "").strip()
    if aria_label:
        return aria_label

    # 3. data-caption on the SVG
    data_caption = svg.get("data-caption", "").strip()
    if data_caption:
        return data_caption

    # 4. Fallback
    return "Figure"


def _ensure_title(soup: BeautifulSoup, svg: Tag, counter: int) -> str:
    """Ensure the SVG has a ``<title>`` with a stable id.

    If no ``<title>`` is present, one is injected.  The title id is always
    set to ``svgtitle-<counter>``.

    Returns the id string so the caller can wire up ``aria-labelledby``.
    """
    title_id = f"svgtitle-{counter}"
    title_tag = svg.find("title")

    if title_tag is None:
        # Inject a new <title> as the first child of the SVG.
        title_tag = soup.new_tag("title", id=title_id)
        title_tag.string = _derive_title_text(svg)
        svg.insert(0, title_tag)
    else:
        # Title already exists — just ensure it has the correct id.
        title_tag["id"] = title_id

    return title_id


def _normalize_viewbox(svg: Tag) -> None:
    """Set ``viewBox`` from ``width``/``height`` when both are numeric.

    Removes ``width`` and ``height`` attributes so that CSS can scale the SVG
    freely after the ``viewBox`` is established.
    """
    if svg.get("viewBox"):
        return  # Already has a viewBox; nothing to do.

    width_str = svg.get("width", "")
    height_str = svg.get("height", "")

    try:
        w = float(width_str)
        h = float(height_str)
    except (ValueError, TypeError):
        return  # Non-numeric or absent — cannot synthesise viewBox.

    import math

    if not (math.isfinite(w) and math.isfinite(h)):
        return

    svg["viewBox"] = f"0 0 {int(w) if w == int(w) else w} {int(h) if h == int(h) else h}"
    del svg["width"]
    del svg["height"]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def process_svg_accessibility_soup(soup: BeautifulSoup) -> int:
    """Add ARIA and accessibility attributes to all inline SVG elements.

    For each ``<svg>`` element:

    * Adds ``role="img"`` if absent.
    * Ensures a ``<title id="svgtitle-N">`` child is present (injected from
      the nearest ``<figcaption>``, ``aria-label``, or ``data-caption`` if
      the SVG lacks one).
    * Sets ``aria-labelledby="svgtitle-N"`` on the SVG.
    * If a ``<desc>`` child exists, adds its id to ``aria-describedby``.
    * Ensures ``xmlns="http://www.w3.org/2000/svg"`` is set.
    * Normalises ``viewBox`` from ``width``/``height`` when both are numeric,
      then removes those attributes so CSS can scale the SVG.
    * Sets ``focusable="false"`` to prevent the IE11 focus trap.

    Returns:
        Number of SVG elements processed.
    """
    svgs = soup.find_all("svg")
    count = 0

    for idx, svg in enumerate(svgs, start=1):
        # --- role="img" ---
        if not svg.get("role"):
            svg["role"] = "img"

        # --- <title> and aria-labelledby ---
        title_id = _ensure_title(soup, svg, idx)
        svg["aria-labelledby"] = title_id

        # --- <desc> and aria-describedby ---
        desc_tag = svg.find("desc")
        if desc_tag is not None:
            desc_id = desc_tag.get("id") or f"svgdesc-{idx}"
            desc_tag["id"] = desc_id
            svg["aria-describedby"] = desc_id

        # --- xmlns ---
        if not svg.get("xmlns"):
            svg["xmlns"] = _SVG_XMLNS

        # --- viewBox normalisation ---
        _normalize_viewbox(svg)

        # --- focusable="false" (IE11 fix) ---
        svg["focusable"] = "false"

        count += 1

    if count:
        logging.info(f"Processed {count} SVG element(s) for accessibility")

    return count


def inject_svg_accessibility_css(soup: BeautifulSoup) -> None:
    """Inject responsive SVG layout CSS into the document ``<head>``.

    Adds::

        svg { max-width: 100%; height: auto; }
        figure > svg { display: block; margin: auto; }
    """
    inject_css(soup, "svg-accessibility-css", _SVG_CSS)
