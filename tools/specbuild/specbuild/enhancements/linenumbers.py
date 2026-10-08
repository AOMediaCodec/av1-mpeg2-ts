"""Line number display for source code blocks.

Adds visible line numbers to ``<pre><code>`` syntax-highlighted blocks via
two modes:

* ``gutter`` — CSS ``::before`` pseudo-element shows ``attr(data-line)`` in a
  fixed-width left column (default, no extra DOM text).
* ``inline`` — prefixes each line with a zero-padded number string (simpler,
  no CSS required for number display).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from specbuild.utils import get_bs4, inject_css

if TYPE_CHECKING:
    from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------

_GUTTER_CSS = """\
/* Line numbers — gutter style */
.line-numbered-block {
    position: relative;
    padding-left: 3.5em;
}
.line-numbered-block .line {
    display: block;
    min-height: 1.2em;
}
.line-numbered-block .line::before {
    content: attr(data-line);
    position: absolute;
    left: 0;
    width: 2.8em;
    text-align: right;
    color: rgba(0,0,0,0.35);
    border-right: 1px solid rgba(0,0,0,0.12);
    padding-right: 0.4em;
    user-select: none;
    -webkit-user-select: none;
    font-size: 0.85em;
    line-height: inherit;
}
"""

_CSS_ID = "line-numbers-css"

# ---------------------------------------------------------------------------
# Core transform
# ---------------------------------------------------------------------------


def _already_numbered(pre) -> bool:
    """Return True if *pre* already contains .line spans."""
    return bool(pre.find("span", class_="line"))


def process_line_numbers_soup(soup: BeautifulSoup, style: str = "gutter") -> int:
    """Add line numbers to all ``<pre><code>`` blocks.

    Args:
        soup: BeautifulSoup document.
        style: ``"gutter"`` (CSS pseudo-element) or ``"inline"`` (text prefix).

    Returns:
        Count of code blocks modified.
    """
    BS = get_bs4()

    modified = 0

    for pre in soup.find_all("pre"):
        code = pre.find("code")
        if code is None:
            continue
        if _already_numbered(pre):
            continue

        inner_html = code.decode_contents()
        lines = inner_html.split("\n")

        # Drop trailing empty artefact line.
        if lines and lines[-1].strip() == "":
            lines = lines[:-1]

        if not lines:
            continue

        width = len(str(len(lines)))
        wrapped: list[str] = []

        for idx, line_content in enumerate(lines, start=1):
            if style == "inline":
                prefix = f"{str(idx).rjust(width)}  "
                wrapped.append(
                    f'<span class="line" data-line="{idx}">{prefix}{line_content}</span>'
                )
            else:
                wrapped.append(f'<span class="line" data-line="{idx}">{line_content}</span>')

        new_inner = "\n".join(wrapped)
        code.clear()
        _frag = BS(new_inner, "html.parser")
        _frag_body = _frag.find("body") or _frag
        for _child in list(_frag_body.children):
            code.append(_child)

        if style == "gutter":
            classes = pre.get("class") or []
            if "line-numbered-block" not in classes:
                pre["class"] = classes + ["line-numbered-block"]

        modified += 1

    if modified and style == "gutter":
        if not soup.find("style", id=_CSS_ID):
            inject_css(soup, _CSS_ID, _GUTTER_CSS)
        log.info("Line numbers (gutter): %d block(s) annotated", modified)
    elif modified:
        log.info("Line numbers (inline): %d block(s) annotated", modified)

    return modified
