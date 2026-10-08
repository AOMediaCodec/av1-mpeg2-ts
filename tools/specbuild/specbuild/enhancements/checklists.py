"""GFM-style checklist conversion.

Bikeshed does not natively convert GitHub Flavored Markdown task-list
syntax (``- [ ]`` / ``- [x]``) into checkbox elements.  After compilation
the output may contain literal ``[ ]`` or ``[x]`` text at the start of
``<li>`` elements.

This module detects those patterns and replaces them with disabled HTML
checkbox inputs, following the same visual convention used by GitHub.

Authoring example (in a ``.bs`` source file)::

    <ul>
      <li>[ ] Define requirements</li>
      <li>[x] Implement encoder</li>
      <li>[ ] Write tests</li>
    </ul>
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bs4 import BeautifulSoup, Tag

# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

# Matches [ ], [x], [X], or [ x ] at the start of stripped li text.
_UNCHECKED_RE = re.compile(r"^\[\s*\]\s*")
_CHECKED_RE = re.compile(r"^\[[xX]\]\s*")

# Combined pattern to detect any checklist prefix (for quick testing)
_ANY_CHECKLIST_RE = re.compile(r"^\[[xX\s]\]\s*")

# CSS id used to avoid duplicate injection
_CSS_ID = "checklist-css"

# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------

_CHECKLIST_CSS = """\
/* GFM-style checklist items */
.checklist { list-style: none; padding-left: 0.5em; }
.checklist-item { display: flex; align-items: baseline; gap: 0.5em; margin: 0.3em 0; }
.checklist-item input[type="checkbox"] { margin: 0; flex-shrink: 0; }
"""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _li_checklist_prefix(li: Tag) -> tuple[bool, bool] | None:
    """Inspect a ``<li>`` and return ``(is_checklist, is_checked)`` or
    ``None`` if the item is not a checklist entry.

    Only inspects the *leading text* of the ``<li>`` (before any child
    elements), so complex nested content is handled gracefully.
    """
    from bs4 import NavigableString

    # Gather the raw text at the very start of the <li> by looking at the
    # first non-empty text node or the full text if the li is text-only.
    raw = ""
    for child in li.children:
        if isinstance(child, NavigableString):
            raw = str(child)
            break
        # If the first child is an element (e.g. <p>), check its text
        if hasattr(child, "get_text"):
            raw = child.get_text()
            break

    stripped = raw.lstrip()
    if _CHECKED_RE.match(stripped):
        return True, True
    if _UNCHECKED_RE.match(stripped):
        return True, False
    return None


def _strip_prefix_from_li(li: Tag, checked: bool) -> None:
    """Remove the ``[ ]`` / ``[x]`` prefix from a ``<li>``'s leading text."""
    from bs4 import NavigableString

    pattern = _CHECKED_RE if checked else _UNCHECKED_RE

    for child in list(li.children):
        if isinstance(child, NavigableString):
            stripped = str(child).lstrip()
            new_text = pattern.sub("", stripped)
            child.replace_with(NavigableString(new_text))
            return
        # The prefix may live inside a child element's text — handle <p>
        if hasattr(child, "get_text"):
            inner_text = child.get_text()
            stripped = inner_text.lstrip()
            if pattern.match(stripped):
                # Find and patch the first NavigableString inside the child
                for node in child.descendants:
                    if isinstance(node, NavigableString):
                        s = str(node).lstrip()
                        if pattern.match(s):
                            node.replace_with(NavigableString(pattern.sub("", s)))
                            return
            return


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def process_checklists_soup(soup: BeautifulSoup) -> int:
    """Convert GFM-style ``[ ]`` / ``[x]`` list items to checkbox elements.

    For each matching ``<li>``:

    - Strips the ``[ ]`` / ``[x]`` prefix from the element text
    - Inserts a disabled ``<input type="checkbox">`` (checked if ``[x]``) at
      the start of the ``<li>``
    - Adds ``class="checklist-item"`` to the ``<li>``

    Parent ``<ul>`` elements whose *all* direct ``<li>`` children are checklist
    items receive ``class="checklist"``.

    Injects scoped CSS when at least one item is converted.

    Args:
        soup: BeautifulSoup document (mutated in place).

    Returns:
        Number of ``<li>`` elements converted.
    """
    from specbuild.utils import inject_css

    count = 0

    for li in soup.find_all("li"):
        result = _li_checklist_prefix(li)
        if result is None:
            continue
        _, checked = result

        # Remove the text prefix
        _strip_prefix_from_li(li, checked)

        # Build the checkbox input element
        if checked:
            checkbox = soup.new_tag("input", type="checkbox", disabled="", checked="")
        else:
            checkbox = soup.new_tag("input", type="checkbox", disabled="")

        # Insert checkbox at the beginning of the <li>
        li.insert(0, checkbox)

        # Mark the <li>
        classes = li.get("class") or []
        if "checklist-item" not in classes:
            li["class"] = classes + ["checklist-item"]

        count += 1

    if count:
        # Mark parent <ul> elements where ALL direct <li> children are checklist items
        for ul in soup.find_all("ul"):
            direct_lis = [c for c in ul.children if getattr(c, "name", None) == "li"]
            if not direct_lis:
                continue
            if all("checklist-item" in (c.get("class") or []) for c in direct_lis):
                ul_classes = ul.get("class") or []
                if "checklist" not in ul_classes:
                    ul["class"] = ul_classes + ["checklist"]

        inject_css(soup, _CSS_ID, _CHECKLIST_CSS)
        logging.info(f"Converted {count} checklist item(s)")

    return count
