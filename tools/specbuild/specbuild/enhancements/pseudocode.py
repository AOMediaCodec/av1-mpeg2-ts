"""Pseudocode / algorithm block styling.

Detects ``<pre class="pseudocode">``, ``<pre class="algorithm">``, or
``<div class="algorithm">`` blocks and applies ISO-style numbered algorithm
presentation with structured CSS.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bs4 import BeautifulSoup

from specbuild.utils import inject_css

_ALGORITHM_CSS = """
/* Algorithm / pseudocode blocks */
pre.pseudocode, pre.algorithm, div.algorithm {
  border: 1px solid #ccc;
  border-radius: 4px;
  padding: 1em 1.2em;
  margin: 1.2em 0;
  font-family: "Courier New", monospace;
  font-size: 0.92em;
  line-height: 1.6;
  background: #f9f9f9;
  counter-reset: algo-line;
}
.algorithm-title {
  font-weight: bold;
  font-style: italic;
  display: block;
  margin-bottom: 0.5em;
  font-family: inherit;
}
.algorithm-number {
  font-weight: bold;
  margin-right: 0.4em;
}
pre.pseudocode .algo-line,
pre.algorithm .algo-line,
div.algorithm .algo-line {
  display: block;
  padding-left: 2.5em;
  text-indent: -2.5em;
  counter-increment: algo-line;
}
pre.pseudocode .algo-line::before,
pre.algorithm .algo-line::before {
  content: counter(algo-line);
  display: inline-block;
  width: 2em;
  color: #888;
  text-align: right;
  margin-right: 0.5em;
  font-size: 0.85em;
}
"""

_ALGO_TITLE_RE = re.compile(r"(?i)^(Algorithm|Procedure|Process)\s+(\d+[\w.]*)[:\s]+(.*)")


def process_pseudocode_soup(soup: BeautifulSoup) -> int:
    """Style pseudocode/algorithm blocks with line wrapping and optional numbering.

    Handles:
    - ``<pre class="pseudocode">``
    - ``<pre class="algorithm">``
    - ``<div class="algorithm">``

    Injects ``<span class="algo-line">`` wrappers per line for line-number
    pseudo-elements, extracts algorithm titles, and injects scoped CSS.

    Returns count of blocks processed.
    """
    count = 0
    selectors = [
        ("pre", "pseudocode"),
        ("pre", "algorithm"),
        ("div", "algorithm"),
    ]

    for tag_name, cls in selectors:
        for block in soup.find_all(tag_name, class_=cls):
            if block.find("span", class_="algo-line"):
                continue

            # Extract raw text
            raw_text = block.get_text()

            # Check for an algorithm title in the first line
            lines = raw_text.split("\n")
            if not lines:
                continue

            # Try to extract title from first non-empty line
            first_non_empty = next((ln for ln in lines if ln.strip()), "")
            m = _ALGO_TITLE_RE.match(first_non_empty.strip())

            # Clear the block and rebuild with span-wrapped lines
            block.clear()

            if m:
                kind, num, title_text = m.group(1), m.group(2), m.group(3)
                title_span = soup.new_tag("span", **{"class": "algorithm-title"})
                num_span = soup.new_tag("span", **{"class": "algorithm-number"})
                num_span.string = f"{kind} {num}:"
                title_span.append(num_span)
                title_span.append(f" {title_text}")
                block.append(title_span)
                title_idx = next((i for i, ln in enumerate(lines) if ln.strip()), 0)
                lines = lines[title_idx + 1 :]  # skip title line

            from bs4 import NavigableString

            for line in lines:
                span = soup.new_tag("span", **{"class": "algo-line"})
                span.string = line
                block.append(span)
                block.append(NavigableString("\n"))

            count += 1

    if count:
        inject_css(soup, "pseudocode-css", _ALGORITHM_CSS)

    return count
