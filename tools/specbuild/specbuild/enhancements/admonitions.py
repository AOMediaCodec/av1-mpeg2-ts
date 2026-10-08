"""HTML admonition block processing.

Detects and styles ``<div class="caution|warning|important|tip">`` blocks
by injecting a bold label span and scoped CSS.

Authoring example::

    <div class="warning">
      <p>Do not modify this register while the encoder is active.</p>
    </div>
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bs4 import BeautifulSoup

from specbuild.utils import inject_css

# ---------------------------------------------------------------------------
# Admonition type definitions
# ---------------------------------------------------------------------------

_ADMONITION_TYPES: dict[str, dict[str, str]] = {
    "note": {
        "label": "NOTE",
        "color": "#004085",
        "bg": "#e8f4f8",
        "border": "#5bc0de",
    },
    "caution": {
        "label": "CAUTION",
        "color": "#856404",
        "bg": "#fff3cd",
        "border": "#ffc107",
    },
    "warning": {
        "label": "WARNING",
        "color": "#721c24",
        "bg": "#f8d7da",
        "border": "#dc3545",
    },
    "important": {
        "label": "IMPORTANT",
        "color": "#004085",
        "bg": "#cce5ff",
        "border": "#004085",
    },
    "tip": {
        "label": "TIP",
        "color": "#155724",
        "bg": "#d4edda",
        "border": "#28a745",
    },
}


# ---------------------------------------------------------------------------
# CSS generation
# ---------------------------------------------------------------------------


def _build_admonition_css() -> str:
    lines: list[str] = ["/* Admonition blocks */"]
    lines.append(".admonition-label { font-weight: bold; margin-right: 0.4em; }")
    for kind, spec in _ADMONITION_TYPES.items():
        lines.append(
            f"""div.{kind} {{
  border-left: 4px solid {spec["border"]};
  background: {spec["bg"]};
  padding: 0.6em 1em;
  margin: 1em 0;
  border-radius: 0 4px 4px 0;
}}
div.{kind} .admonition-label {{
  color: {spec["color"]};
}}"""
        )
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def process_admonitions_soup(soup: BeautifulSoup) -> int:
    """Add label spans and inject CSS for admonition blocks.

    Handles ``<div class="caution|warning|important|tip">``.  Adds a
    ``<span class="admonition-label">`` if not already present.

    Returns:
        Number of admonitions processed.
    """
    count = 0

    for kind, spec in _ADMONITION_TYPES.items():
        for div in soup.find_all("div", class_=kind):
            # Skip if a label span is already present
            if div.find("span", class_="admonition-label"):
                continue

            label_span = soup.new_tag("span", **{"class": "admonition-label"})
            label_span.string = spec["label"]

            # Inject the label at the start of the first <p>, or at the top
            # of the div itself when no <p> is present.
            first_p = div.find("p")
            if first_p is not None:
                first_p.insert(0, label_span)
            else:
                div.insert(0, label_span)

            count += 1

    if count:
        inject_css(soup, "admonitions-css", _build_admonition_css())
        logging.info(f"Processed {count} admonition block(s)")

    return count
