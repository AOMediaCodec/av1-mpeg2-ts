"""Sourcecode callout annotations.

Converts inline callout markers inside ``<pre><code>`` blocks into
numbered badge links paired with a matching ``<ol class="callout-list">``.

Authoring conventions supported
--------------------------------
Inline ``<co>`` element::

    <pre class="highlight language-c">
    <code>int encode(Frame *f);  <co id="co-1"/>
    int decode(Frame *f);  <co id="co-2"/>
    </code></pre>
    <ol class="callout-list">
      <li id="co-1">Encodes a frame …</li>
      <li id="co-2">Decodes a frame …</li>
    </ol>

Text-pattern markers (C, C++, Python, shell-style comments)::

    int encode(Frame *f);  /* <1> */
    int decode(Frame *f);  // <2>
    result = run()         # <3>
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bs4 import BeautifulSoup, Tag

from specbuild.utils import inject_css

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Matches /* <N> */ or // <N> or # <N> style text markers
_TEXT_MARKER_RE = re.compile(r"(?:\/\*\s*|\/\/\s*|#\s*)<(\d+)>\s*(?:\*\/)?")

_CALLOUT_CSS = """
/* Callout annotations */
.callout-marker {
  display: inline-block; min-width: 1.4em; height: 1.4em;
  background: #2563eb; color: #fff; border-radius: 50%;
  text-align: center; font-size: 0.75em; line-height: 1.4em;
  font-weight: bold; cursor: pointer; vertical-align: middle;
}
.callout-list { margin-top: 0.5em; }
.callout-list li { margin-bottom: 0.25em; }
.callout-list li::marker { color: #2563eb; font-weight: bold; }
"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def process_callouts_soup(soup: BeautifulSoup) -> int:
    """Link callout markers in code blocks to numbered explanations.

    Detects ``<co id="co-N"/>`` markers inside ``<pre><code>`` blocks and
    ``<ol class="callout-list">`` after the block.  Wraps markers in
    ``<span class="callout-marker" data-co="co-N">N</span>`` and adds
    ``data-co="co-N"`` links on the list items for bidirectional navigation.

    Also handles text-pattern markers such as ``/* <1> */`` or ``# <1>``
    (converts them to ``<co>`` elements first).

    Returns:
        Number of callout groups processed.
    """
    groups_processed = 0

    for pre in soup.find_all("pre"):
        code = pre.find("code")
        if code is None:
            continue

        # Step 1: convert text-pattern markers to <co> elements
        _convert_text_markers(code, soup)

        # Step 2: collect <co> elements in this block
        co_elements = code.find_all("co")
        if not co_elements:
            continue

        # Step 3: find a matching <ol class="callout-list"> immediately after
        callout_list = _find_callout_list(pre)

        # Step 4: process each <co> element
        for co in co_elements:
            co_id = co.get("id", "")
            if not co_id:
                continue
            # Extract numeric part for the badge label
            num_match = re.search(r"\d+$", co_id)
            label = num_match.group(0) if num_match else co_id

            marker = soup.new_tag(
                "span",
                **{
                    "class": "callout-marker",
                    "data-co": co_id,
                    "title": f"See callout {label}",
                },
            )
            marker.string = label
            co.replace_with(marker)

        # Step 5: link list items back to their markers
        if callout_list is not None:
            for li in callout_list.find_all("li", recursive=False):
                li_id = li.get("id", "")
                if li_id:
                    li["data-co"] = li_id

        groups_processed += 1

    if groups_processed:
        inject_css(soup, "callout-css", _CALLOUT_CSS)
        logging.info(f"Processed {groups_processed} callout group(s)")

    return groups_processed


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _convert_text_markers(code: Tag, soup: BeautifulSoup) -> None:
    """Replace text-pattern callout markers inside *code* with ``<co>`` tags.

    Operates on text nodes within the ``<code>`` element so that the
    surrounding markup is preserved.
    """
    from bs4 import NavigableString

    # Collect text nodes to avoid modifying the tree while iterating
    text_nodes: list[NavigableString] = [
        node for node in code.descendants if isinstance(node, NavigableString)
    ]

    for text_node in text_nodes:
        raw = str(text_node)
        if not _TEXT_MARKER_RE.search(raw):
            continue

        # Split text around the first marker found, then replace the node
        # with the preceding text, a <co> element, and the remaining text.
        # Loop in case there are multiple markers in the same text node.
        parts: list = []
        last_end = 0
        for m in _TEXT_MARKER_RE.finditer(raw):
            if m.start() > last_end:
                parts.append(raw[last_end : m.start()])
            n = m.group(1)
            co_tag = soup.new_tag("co", id=f"co-{n}")
            parts.append(co_tag)
            last_end = m.end()
        if last_end < len(raw):
            parts.append(raw[last_end:])

        # Replace the original text node with the sequence of parts.
        # Guard against orphaned text nodes (should not happen in practice).
        if text_node.parent is None:
            continue
        # Insert after the text node in reverse order, then remove it.
        for part in reversed(parts):
            if isinstance(part, str):
                from bs4 import NavigableString as _NS

                text_node.insert_after(_NS(part))
            else:
                text_node.insert_after(part)
        text_node.extract()


def _find_callout_list(pre: Tag) -> Tag | None:
    """Return the ``<ol class="callout-list">`` immediately following *pre*.

    Skips whitespace-only text nodes between the ``<pre>`` and the list.
    """
    sibling = pre.next_sibling
    while sibling is not None:
        if hasattr(sibling, "name") and sibling.name is not None:
            if sibling.name == "ol" and "callout-list" in sibling.get("class", []):
                return sibling  # type: ignore[return-value]
            # Some non-whitespace element intervenes — stop looking
            break
        # NavigableString — skip pure whitespace
        if str(sibling).strip():
            break
        sibling = sibling.next_sibling
    return None
