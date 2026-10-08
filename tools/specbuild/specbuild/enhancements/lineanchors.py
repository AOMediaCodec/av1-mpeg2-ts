"""Deep-linkable line number anchors for code blocks.

Wraps each line of highlighted ``<pre>`` code blocks in a ``<span>``
with a unique ``id`` attribute, enabling direct URL linking to specific
lines (e.g., ``index.html#section-5-code-1-L42``).
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING

from specbuild.utils import get_bs4, inject_css, read_html, write_html

if TYPE_CHECKING:
    from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

# Match a Pygments-style highlight span that may contain \n.  Non-nested
# (Pygments rarely nests highlight spans inside one another).
_HL_SPAN_NL_RE = re.compile(
    r"(<span\b[^>]*>)((?:[^<]|<(?!/?span\b))*?)</span>",
    re.DOTALL,
)


def _presplit_multiline_spans(html: str) -> str:
    """Split highlight spans whose body contains ``\\n`` into one span per line.

    Pygments emits ``<span class="...">line1\\nline2</span>`` for multi-line
    constructs (block comments, raw-string literals).  Naïvely splitting the
    parent ``<pre>`` on ``\\n`` would leave unbalanced ``<span>`` tags on
    each line.  Pre-splitting these spans preserves the highlight class on
    every line.
    """

    def repl(m: re.Match[str]) -> str:
        opening, body = m.group(1), m.group(2)
        if "\n" not in body:
            return m.group(0)
        parts = body.split("\n")
        # Recombine each part as its own complete span.  Empty parts (between
        # consecutive \n) emit an empty span so line counting stays correct.
        return "\n".join(f"{opening}{p}</span>" for p in parts)

    return _HL_SPAN_NL_RE.sub(repl, html)


# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------

_LINE_ANCHOR_CSS = """\
/* Line anchors for code blocks */
pre.highlight .code-line {
    display: block;
    position: relative;
    padding-left: 3.5em;
    min-height: 1.2em;
}
pre.highlight .code-line::before {
    content: attr(data-line);
    position: absolute;
    left: 0;
    width: 2.8em;
    text-align: right;
    color: rgba(0,0,0,0.3);
    border-right: 1px solid rgba(0,0,0,0.1);
    padding-right: 0.4em;
    margin-right: 0.5em;
    user-select: none;
    -webkit-user-select: none;
    font-size: 0.85em;
}
pre.highlight .code-line:target {
    background: rgba(255, 213, 79, 0.3);
    outline: 1px solid rgba(255, 213, 79, 0.6);
}
pre.highlight .code-line:hover {
    background: rgba(0, 0, 0, 0.02);
}
/* When line anchors are active, the pre needs no extra padding since lines handle it */
pre.highlight.has-line-anchors {
    padding-left: 0;
    counter-reset: none;
}
"""

_CSS_ID = "line-anchors-css"


def _get_line_anchor_css() -> str:
    """Return the CSS for line anchor styling."""
    return _LINE_ANCHOR_CSS


# ---------------------------------------------------------------------------
# Heading lookup
# ---------------------------------------------------------------------------

_HEADING_TAGS = frozenset({"h2", "h3", "h4", "h5", "h6"})


def _find_nearest_heading_id(pre_tag) -> str | None:
    """Walk backwards from *pre_tag* to find the nearest heading with an id.

    Only considers ``h2``–``h6`` elements.

    Returns:
        The ``id`` attribute value of the nearest heading, or ``None``.
    """
    for sibling in pre_tag.previous_elements:
        if getattr(sibling, "name", None) in _HEADING_TAGS:
            hid = sibling.get("id")
            if hid:
                return hid
    return None


# ---------------------------------------------------------------------------
# Core transform
# ---------------------------------------------------------------------------


def _escape_html_attr(value: str) -> str:
    """Minimal escaping for an HTML attribute value."""
    return value.replace("&", "&amp;").replace('"', "&quot;")


def add_line_anchors_soup(soup: object) -> bool:
    """Add line anchors to all highlighted code blocks.

    Each line in every ``<pre class="highlight">`` block is wrapped in a
    ``<span class="code-line">`` carrying a unique ``id`` and a
    ``data-line`` attribute for the CSS line-number gutter.

    Block IDs are derived from the nearest preceding heading's ``id``
    attribute plus a per-section counter.  If no heading is found, a
    global counter is used as fallback.

    Args:
        soup: A BeautifulSoup document.

    Returns:
        True if any modifications were made.
    """
    BS = get_bs4()

    pre_tags = soup.find_all("pre", class_="highlight")
    if not pre_tags:
        return False

    modified = False
    # Track per-heading code block counts and a global fallback counter.
    heading_counters: dict[str, int] = {}
    global_counter = 0

    for pre in pre_tags:
        # Skip blocks already processed.
        classes = pre.get("class", [])
        if "has-line-anchors" in classes:
            continue

        # --- Determine block ID ---
        heading_id = _find_nearest_heading_id(pre)
        if heading_id:
            heading_counters.setdefault(heading_id, 0)
            heading_counters[heading_id] += 1
            block_id = f"{heading_id}-code-{heading_counters[heading_id]}"
        else:
            global_counter += 1
            block_id = f"codeblock-{global_counter}"

        # --- Get inner HTML and split into lines ---
        inner_html = pre.decode_contents()
        # Pygments may produce multi-line highlight spans; pre-split them so
        # the line-by-line split below doesn't leave unbalanced tags.
        inner_html = _presplit_multiline_spans(inner_html)
        lines = inner_html.split("\n")

        # Remove a trailing empty line that is just an artefact of the
        # closing </pre> being on a new line.
        if lines and lines[-1].strip() == "":
            lines = lines[:-1]

        if not lines:
            continue

        # --- Wrap each line ---
        wrapped_parts: list[str] = []
        for idx, line_content in enumerate(lines, start=1):
            line_id = f"{block_id}-L{idx}"
            safe_id = _escape_html_attr(line_id)
            wrapped_parts.append(
                f'<span class="code-line" id="{safe_id}" data-line="{idx}">{line_content}</span>'
            )

        new_inner = "\n".join(wrapped_parts)

        # --- Replace pre contents ---
        pre.clear()
        _frag = BS(new_inner, "html.parser")
        for _child in list((_frag.body or _frag).children):
            pre.append(_child)

        # Set block-level attributes.
        pre["id"] = block_id
        if "has-line-anchors" not in classes:
            pre["class"] = classes + ["has-line-anchors"]

        modified = True

    # Inject CSS if we made changes.
    if modified:
        # Avoid duplicate style blocks.
        if not soup.find("style", id=_CSS_ID):
            inject_css(soup, _CSS_ID, _LINE_ANCHOR_CSS)

    return modified


# ---------------------------------------------------------------------------
# File-based wrapper
# ---------------------------------------------------------------------------


def add_line_anchors(html_path: Path) -> None:
    """Read an HTML file, add line anchors, and write it back.

    This is the main entry point for callers that want a simple
    file-in / file-out interface.

    Args:
        html_path: Path to an HTML file produced by Bikeshed.
    """
    log.info("Adding line anchors to code blocks in %s", html_path.name)

    soup = read_html(html_path)
    changed = add_line_anchors_soup(soup)

    if changed:
        write_html(html_path, soup)
        log.info("Line anchors added successfully.")
    else:
        log.info("No highlighted code blocks found; nothing to do.")


# ---------------------------------------------------------------------------
# Code language labels
# ---------------------------------------------------------------------------

#: Mapping from Prism/highlight.js ``language-*`` class suffixes to display names.
_LANG_DISPLAY: dict[str, str] = {
    "python": "Python",
    "py": "Python",
    "javascript": "JavaScript",
    "js": "JavaScript",
    "typescript": "TypeScript",
    "ts": "TypeScript",
    "cpp": "C++",
    "c++": "C++",
    "cxx": "C++",
    "c": "C",
    "cs": "C#",
    "csharp": "C#",
    "java": "Java",
    "kotlin": "Kotlin",
    "rust": "Rust",
    "go": "Go",
    "bash": "Bash",
    "sh": "Shell",
    "shell": "Shell",
    "html": "HTML",
    "xml": "XML",
    "css": "CSS",
    "json": "JSON",
    "yaml": "YAML",
    "toml": "TOML",
    "sql": "SQL",
    "r": "R",
    "matlab": "MATLAB",
    "octave": "MATLAB",
}

_LANG_LABEL_CSS = """\
.code-labeled-block { position: relative; margin: 1em 0; }
.code-lang-label {
    font-size: 0.7em; font-weight: 600; letter-spacing: 0.08em;
    text-transform: uppercase; color: #888;
    padding: 0.2em 0.5em; background: #f0f0f0;
    border: 1px solid #ddd; border-bottom: none;
    display: inline-block; border-radius: 3px 3px 0 0;
    font-family: monospace;
}
"""

_LANG_LABEL_CSS_ID = "code-lang-label-css"


def _extract_language_name(code_elem) -> str | None:
    """Return the display name for the language from a ``<code>`` element's classes.

    Scans for a class of the form ``language-<name>`` and maps it through
    :data:`_LANG_DISPLAY`.  Unknown languages are returned title-cased.

    Returns:
        Display name string, or ``None`` if no ``language-*`` class is found.
    """
    for cls in code_elem.get("class", []):
        if cls.startswith("language-"):
            lang_key = cls[len("language-") :]
            return _LANG_DISPLAY.get(lang_key.lower(), lang_key.capitalize())
    return None


def inject_code_language_labels_soup(soup: BeautifulSoup) -> int:
    """Inject language labels above ``<pre><code class="language-*">`` blocks.

    For each ``<pre>`` that contains a ``<code class="language-*">`` child:

    1. Extracts the language display name (via :data:`_LANG_DISPLAY`).
    2. Creates a ``<div class="code-lang-label">LANGUAGE</div>`` element.
    3. Wraps the ``<pre>`` in a ``<div class="code-labeled-block">`` (if not
       already wrapped) and inserts the label *before* the ``<pre>``.

    Args:
        soup: A BeautifulSoup document (mutated in place).

    Returns:
        The number of language labels injected.
    """
    count = 0

    for pre in list(soup.find_all("pre")):
        # Find a direct or nested <code class="language-*">
        code = pre.find("code")
        if code is None:
            continue

        lang_name = _extract_language_name(code)
        if lang_name is None:
            continue

        # Check whether the pre is already inside a .code-labeled-block
        parent = pre.parent
        already_wrapped = (
            parent is not None
            and getattr(parent, "name", None) == "div"
            and "code-labeled-block" in (parent.get("class") or [])
        )

        if already_wrapped:
            wrapper = parent
        else:
            # Create wrapper div and replace pre with wrapper
            wrapper = soup.new_tag("div", attrs={"class": "code-labeled-block"})
            pre.replace_with(wrapper)
            wrapper.append(pre)

        # Insert label div before pre (i.e. at position 0 in wrapper)
        label_tag = soup.new_tag("div", attrs={"class": "code-lang-label"})
        label_tag.string = lang_name
        pre.insert_before(label_tag)

        count += 1

    if count and not soup.find("style", id=_LANG_LABEL_CSS_ID):
        inject_css(soup, _LANG_LABEL_CSS_ID, _LANG_LABEL_CSS)

    return count
