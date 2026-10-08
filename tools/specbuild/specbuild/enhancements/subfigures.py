"""Subfigure support for compound figures.

Detects ``<figure>`` elements that contain multiple panels (child
``<figure>`` or ``<img>`` elements) and injects alphabetical labels
``(a)``, ``(b)``, … into each panel's ``<figcaption>`` when not already
present.

Authoring example::

    <figure id="fig-3-1">
      <figure id="fig-3-1a">
        <img src="encoder.svg" alt="Encoder structure"/>
        <figcaption>(a) Encoder</figcaption>
      </figure>
      <figure id="fig-3-1b">
        <img src="decoder.svg" alt="Decoder structure"/>
        <figcaption>(b) Decoder</figcaption>
      </figure>
      <figcaption>Figure 3-1 — Encoder and decoder structures</figcaption>
    </figure>
"""

from __future__ import annotations

import logging
import re
import string
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bs4 import BeautifulSoup, Tag

from specbuild.utils import inject_css

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SUBFIG_CSS = """
/* Subfigure labels */
.subfig-label { font-weight: bold; margin-right: 0.3em; }
"""

# Pattern that recognises existing (a), (b), (c) prefixes in caption text
_LABEL_RE = re.compile(r"^\s*\([a-z]\)", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def process_subfigures_soup(soup: BeautifulSoup) -> int:
    """Detect and label subfigure panels (a), (b), (c) within compound figures.

    Finds ``<figure>`` elements that contain multiple ``<figure>`` or
    ``<img>`` children.  For each panel that lacks an explicit ``(a)``/
    ``(b)`` label in its figcaption, injects a label span.

    Returns:
        Number of compound figures processed.
    """
    compound_count = 0

    for fig in soup.find_all("figure"):
        panels = _get_panels(fig)
        if len(panels) < 2:
            continue

        compound_count += 1
        for idx, panel in enumerate(panels):
            if idx >= 26:
                break
            letter = string.ascii_lowercase[idx]
            _label_panel(panel, letter, soup)

    if compound_count:
        inject_css(soup, "subfigure-css", _SUBFIG_CSS)
        logging.info(f"Processed {compound_count} compound figure(s)")

    return compound_count


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_panels(fig: Tag) -> list[Tag]:
    """Return the direct ``<figure>`` or ``<img>`` children that form panels.

    Only direct children are considered so that nested compound figures
    are handled at their own level.
    """
    panels: list[Tag] = []
    for child in fig.children:
        if not hasattr(child, "name") or child.name is None:
            continue
        if child.name in ("figure", "img"):
            panels.append(child)  # type: ignore[arg-type]
    return panels


def _label_panel(panel: Tag, letter: str, soup: BeautifulSoup) -> None:
    """Inject a ``(letter)`` label into *panel*'s figcaption if not present.

    For bare ``<img>`` panels (no enclosing ``<figure>``), the img is
    wrapped in a new ``<figure>`` first.
    """
    # Wrap bare <img> in a <figure>
    if panel.name == "img":
        wrapper = soup.new_tag("figure", **{"class": "subfigure"})
        panel.wrap(wrapper)
        panel = wrapper

    # Find or create a figcaption
    caption = panel.find("figcaption")
    if caption is None:
        caption = soup.new_tag("figcaption")
        panel.append(caption)

    # Check whether the caption already starts with (a)/(b)/… label
    caption_text = caption.get_text(strip=True)
    if _LABEL_RE.match(caption_text):
        return  # already labelled — skip

    label_span = soup.new_tag("span", **{"class": "subfig-label"})
    label_span.string = f"({letter})"
    caption.insert(0, label_span)
