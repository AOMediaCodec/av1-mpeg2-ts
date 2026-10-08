"""Clipboard and code block utilities.

Provides two independent features for code blocks:

1. **Copy buttons** (``inject_copy_buttons_soup``): injects a "Copy" button
   into every ``<pre>`` block so readers can copy code with one click.

2. **Code attribution** (``process_code_attribution_soup``): detects source
   attribution hints attached to ``<pre>`` blocks and renders a visible
   attribution line after each block.

Attribution hints are detected via:
- ``data-source`` attribute on the ``<pre>`` element
- A preceding ``<p class="code-source">`` or ``<p class="source-ref">``
  sibling element
- A containing ``<figure>`` whose ``<figcaption>`` text starts with
  ``"Source:"``
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bs4 import BeautifulSoup, Tag

from specbuild.utils import inject_css, inject_js

# ---------------------------------------------------------------------------
# Copy buttons
# ---------------------------------------------------------------------------

_COPY_BUTTON_CSS = """\
/* Code copy buttons */
.pre-wrapper { position: relative; }
.copy-btn {
  position: absolute; top: 0.4em; right: 0.4em;
  padding: 0.2em 0.5em; font-size: 0.75em;
  background: #e5e7eb; border: 1px solid #9ca3af;
  border-radius: 4px; cursor: pointer; opacity: 0.7;
  transition: opacity 0.2s;
}
.copy-btn:hover { opacity: 1; }
.copy-btn.copied { background: #d1fae5; border-color: #6ee7b7; }
"""

_COPY_BUTTON_JS = """\
(function() {
  document.querySelectorAll('.copy-btn').forEach(function(btn) {
    btn.addEventListener('click', function() {
      var pre = btn.closest('.pre-wrapper').querySelector('pre');
      navigator.clipboard.writeText(pre.innerText || pre.textContent).then(function() {
        btn.textContent = 'Copied!';
        btn.classList.add('copied');
        setTimeout(function() {
          btn.textContent = 'Copy';
          btn.classList.remove('copied');
        }, 2000);
      });
    });
  });
})();
"""


def inject_copy_buttons_soup(soup: BeautifulSoup) -> int:
    """Inject a "Copy" button into every ``<pre>`` element.

    Each ``<pre>`` is wrapped in a ``<div class="pre-wrapper">`` (if not
    already wrapped) and a ``<button class="copy-btn">Copy</button>`` is
    inserted inside the wrapper.

    Returns:
        Number of copy buttons injected.
    """
    count = 0
    for pre in soup.find_all("pre"):
        # Skip if already wrapped
        parent = pre.parent
        if parent and parent.name == "div" and "pre-wrapper" in parent.get("class", []):
            continue

        wrapper: Tag = soup.new_tag("div", **{"class": "pre-wrapper"})
        pre.replace_with(wrapper)
        wrapper.append(pre)

        btn: Tag = soup.new_tag("button", **{"class": "copy-btn"})
        btn.string = "Copy"
        wrapper.append(btn)

        count += 1

    if count:
        inject_css(soup, "copy-button-css", _COPY_BUTTON_CSS)
        inject_js(soup, "copy-button-js", _COPY_BUTTON_JS)
        logging.info(f"Injected {count} copy button(s)")

    return count


# ---------------------------------------------------------------------------
# Code attribution
# ---------------------------------------------------------------------------

_ATTRIBUTION_CSS = """\
/* Code block attribution */
.code-attribution {
  font-size: 0.8em; color: #666;
  margin-top: 0.2em; margin-bottom: 0.5em;
  font-style: italic;
}
"""


def process_code_attribution_soup(soup: BeautifulSoup) -> int:
    """Detect source attribution hints and render attribution lines.

    Detection strategy (in priority order):

    1. ``<pre data-source="...">`` attribute on the ``<pre>`` element.
    2. A preceding ``<p class="code-source">`` or ``<p class="source-ref">``
       sibling immediately before the ``<pre>``.
    3. A ``<figure>`` containing the ``<pre>`` whose ``<figcaption>`` text
       starts with ``"Source:"``.

    For cases 1 and 2 a ``<p class="code-attribution">Source: {text}</p>``
    is inserted after the ``<pre>`` (or after the ``pre-wrapper`` div if
    copy buttons have already been injected).

    For case 3 the existing ``<figcaption>`` text is left in place; no
    additional paragraph is added.

    Returns:
        Number of attribution lines added (case 3 is *not* counted since no
        new element is created).
    """
    count = 0

    for pre in soup.find_all("pre"):
        attribution_text: str | None = None
        source_p: Tag | None = None

        # --- Strategy 1: data-source attribute ---
        data_source = pre.get("data-source", "").strip()
        if data_source:
            attribution_text = data_source

        # --- Strategy 2: preceding sibling <p class="code-source|source-ref"> ---
        if attribution_text is None:
            prev = _prev_element_sibling(pre)
            if prev is not None and prev.name == "p":
                classes = prev.get("class", [])
                if "code-source" in classes or "source-ref" in classes:
                    attribution_text = prev.get_text(strip=True)
                    source_p = prev

        # --- Strategy 3: figure with figcaption starting with "Source:" ---
        if attribution_text is None:
            figure = _get_figure_parent(pre)
            if figure is not None:
                figcaption = figure.find("figcaption")
                if figcaption is not None:
                    caption_text = figcaption.get_text(strip=True)
                    if caption_text.lower().startswith("source:"):
                        # No new element needed; attribution is already visible
                        continue

        if attribution_text is None:
            continue

        # Remove the source hint paragraph so it isn't shown twice
        if source_p is not None:
            source_p.decompose()

        # Find insertion point: after any pre-wrapper div, or after the pre
        insert_after = pre
        parent = pre.parent
        if parent and parent.name == "div" and "pre-wrapper" in parent.get("class", []):
            insert_after = parent

        attr_p: Tag = soup.new_tag("p", **{"class": "code-attribution"})
        attr_p.string = f"Source: {attribution_text}"
        insert_after.insert_after(attr_p)

        count += 1

    if count:
        inject_css(soup, "code-attribution-css", _ATTRIBUTION_CSS)
        logging.info(f"Added {count} code attribution(s)")

    return count


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _prev_element_sibling(tag: Tag) -> Tag | None:
    """Return the nearest preceding sibling that is an element (not text)."""
    from bs4 import NavigableString

    sibling = tag.previous_sibling
    while sibling is not None:
        if not isinstance(sibling, NavigableString):
            return sibling  # type: ignore[return-value]
        sibling = sibling.previous_sibling
    return None


def _get_figure_parent(tag: Tag) -> Tag | None:
    """Return the nearest ``<figure>`` ancestor of *tag*, or ``None``."""
    for parent in tag.parents:
        if parent.name == "figure":
            return parent  # type: ignore[return-value]
        if parent.name in ("body", "html"):
            break
    return None
