"""Change bars: mark text changed since a baseline with vertical margin bars.

Two strategies are supported:

* **data-bs-line strategy** (primary): Bikeshed annotates every HTML element
  with a ``data-bs-line`` attribute recording the source ``.bs`` line number.
  ``git diff`` tells us which lines changed, and we mark the corresponding
  elements.  This is fast and precise, but requires Bikeshed to emit
  ``data-bs-line`` (Bikeshed ≤ 6 and certain Bikeshed 7 configurations).

* **Difflib strategy** (automatic fallback): When no ``data-bs-line``
  attributes are found (e.g. Bikeshed 7 default output), the module falls
  back to comparing the current compiled HTML against an anchor HTML file
  using :mod:`difflib`.  Every leaf block element is extracted from both
  documents in document order; changed or new blocks are marked.  The anchor
  is resolved from (in order):

  1. The ``anchor_html`` keyword argument passed to :func:`add_change_bars`.
  2. ``<main_branch_clone_dir>/index.html`` (``downloads/spec-main/index.html``
     by default) if it exists on disk.
"""

from __future__ import annotations

import logging
import re
import subprocess
from collections import deque
from pathlib import Path

from specbuild.config import CONFIG
from specbuild.theme import THEME
from specbuild.utils import get_bs4, inject_css, read_html, write_html

# Block-level HTML elements eligible for change-bar marking (data-bs-line strategy).
_BLOCK_ELEMENTS = frozenset(
    [
        "p",
        "div",
        "li",
        "dt",
        "dd",
        "tr",
        "pre",
        "blockquote",
        "figure",
        "table",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "section",
        "dl",
        "ul",
        "ol",
    ]
)

# Tags extracted for the difflib fallback: leaf-level blocks only.
# Container tags (div, section, ul, ol, dl, table) are excluded — a changed
# <li> is more useful than its <ul>, and the DFS stops at leaf tags anyway.
_DIFFLIB_LEAF_TAGS = frozenset(
    [
        "p",
        "li",
        "dt",
        "dd",
        "pre",
        "blockquote",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "caption",
        "figcaption",
        "td",
        "th",
    ]
)

# Matches the first hex colour in a CSS shorthand like "3px solid #0066cc".
_HEX_COLOR_RE = re.compile(r"#[0-9a-fA-F]{3,8}")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _extract_color(border_str: str, default: str = "#0066cc") -> str:
    """Extract the first hex colour from a CSS border shorthand string."""
    m = _HEX_COLOR_RE.search(border_str)
    return m.group(0) if m else default


def _normalise(text: str) -> str:
    """Collapse whitespace for stable text comparison."""
    return re.sub(r"\s+", " ", text or "").strip()


def _add_changed_class(el: object, *extra: str) -> bool:
    """Add ``changed-bar`` (plus any *extra* classes) to *el* if not already set.

    Returns ``True`` if the element was newly marked.
    """
    cls = el.get("class", [])
    if "changed-bar" in cls:
        return False
    el["class"] = cls + ["changed-bar"] + list(extra)
    return True


# ---------------------------------------------------------------------------
# Baseline resolution
# ---------------------------------------------------------------------------


def resolve_baseline(ref: str) -> str:
    """Resolve a baseline reference for change-bar comparison.

    If *ref* is ``"auto"``, tries the latest git tag; falls back to
    ``origin/main`` then ``main``.

    Args:
        ref: A git ref string, or ``"auto"`` for automatic detection.

    Returns:
        A resolved git ref suitable for ``git diff``.
    """
    if ref != "auto":
        return ref

    # Try latest tag
    try:
        result = subprocess.run(
            ["git", "describe", "--tags", "--abbrev=0"],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        tag = result.stdout.strip()
        if tag:
            logging.info(f"Change bars baseline: latest tag '{tag}'")
            return tag
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        pass

    # Try origin/main
    try:
        subprocess.run(
            ["git", "rev-parse", "--verify", "origin/main"],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        logging.info("Change bars baseline: origin/main")
        return "origin/main"
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        pass

    logging.info("Change bars baseline: main")
    return "main"


# ---------------------------------------------------------------------------
# Strategy 1: data-bs-line (Bikeshed ≤ 6 / annotated builds)
# ---------------------------------------------------------------------------


def get_changed_lines(baseline_ref: str, bs_dir: str = "bikeshed") -> dict[str, set[int]]:
    """Get per-file sets of changed line numbers relative to a baseline.

    Uses ``git diff`` with unified context of 0 to identify exactly which
    lines changed.

    Args:
        baseline_ref: Git ref to diff against.
        bs_dir: Path to the bikeshed source directory.

    Returns:
        Mapping of ``.bs`` filename (basename only) to set of changed line
        numbers in the *new* version of the file.
    """
    try:
        result = subprocess.run(
            ["git", "diff", "-U0", baseline_ref, "--", f"{bs_dir}/"],
            capture_output=True,
            text=True,
            check=True,
            timeout=120,
        )
    except subprocess.CalledProcessError as e:
        logging.warning(f"git diff failed: {e}")
        return {}
    except subprocess.TimeoutExpired:
        logging.warning("git diff timed out (120s); skipping change bars")
        return {}

    changed: dict[str, set[int]] = {}
    current_file = None

    for line in result.stdout.split("\n"):
        # Detect file header: +++ b/bikeshed/filename.bs
        if line.startswith("+++ b/"):
            filepath = line[6:]
            current_file = Path(filepath).name
            if current_file not in changed:
                changed[current_file] = set()

        # Parse hunk header: @@ -old,count +new,count @@
        elif line.startswith("@@") and current_file:
            match = re.search(r"\+(\d+)(?:,(\d+))?", line)
            if match:
                start = int(match.group(1))
                count = int(match.group(2)) if match.group(2) else 1
                if count > 0:
                    changed[current_file].update(range(start, start + count))

    total_lines = sum(len(v) for v in changed.values())
    logging.info(
        f"Found {total_lines} changed lines across {len(changed)} files relative to {baseline_ref}"
    )
    return changed


def _mark_by_bs_lines(soup: object, changed_lines: dict[str, set[int]]) -> int:
    """Mark elements using ``data-bs-line`` source annotations (Strategy 1).

    Returns:
        Number of elements marked, or ``-1`` if no ``data-bs-line`` attributes
        were found in the document (so the caller knows to try the difflib
        fallback rather than assuming there are simply no changes).
    """
    all_changed_lines: set[int] = set()
    for lines in changed_lines.values():
        all_changed_lines.update(lines)

    marked = 0
    found_any_annotation = False

    for elem in soup.find_all(attrs={"data-bs-line": True}):
        found_any_annotation = True
        bs_line = elem["data-bs-line"]

        if ":" in bs_line:
            parts = bs_line.split(":", 1)
            filename = parts[0]
            try:
                line_no = int(parts[1])
            except ValueError:
                continue
        else:
            try:
                line_no = int(bs_line)
            except ValueError:
                continue
            filename = None

        if filename and filename in changed_lines:
            is_changed = line_no in changed_lines[filename]
        elif filename is None:
            is_changed = line_no in all_changed_lines
        else:
            is_changed = False

        if is_changed and elem.name in _BLOCK_ELEMENTS:
            if _add_changed_class(elem):
                marked += 1

    if not found_any_annotation:
        return -1  # Signal to caller: no data-bs-line found, try difflib
    return marked


# ---------------------------------------------------------------------------
# Strategy 2: difflib sequence matching (Bikeshed 7 / no data-bs-line)
# ---------------------------------------------------------------------------


def _extract_leaf_blocks(soup: object) -> list[tuple[str, str, object]]:
    """Extract leaf-level block elements from ``<main>`` in document order.

    Uses an iterative DFS that stops descending when it reaches a leaf tag,
    giving O(n) complexity and naturally avoiding double-marking of nested
    elements (e.g. a ``<p>`` inside a ``<li>`` is never reached).

    Returns:
        List of ``(full_text, key, element)`` tuples where *key* is the first
        200 chars of *full_text*, pre-computed for SequenceMatcher.
    """
    main = soup.find("main") or soup.find("body")
    blocks: list[tuple[str, str, object]] = []

    queue = deque(main.children)
    while queue:
        node = queue.popleft()
        if not hasattr(node, "name") or node.name is None:
            continue  # skip NavigableString / Comment nodes
        if node.name in _DIFFLIB_LEAF_TAGS:
            text = _normalise(node.get_text())
            if len(text) >= 3:
                blocks.append((text, text[:200], node))
            # Don't recurse into a leaf element — its children would double-count
        else:
            queue.extend(node.children)

    return blocks


def _mark_by_difflib(soup: object, anchor_html: Path) -> int:
    """Mark changed/new blocks by difflib comparison against an anchor HTML.

    Extracts all leaf block elements from both the current ``soup`` and the
    anchor HTML in document order, then uses :class:`difflib.SequenceMatcher`
    to align them.  Blocks in *replace* operations are marked ``changed-bar``;
    blocks in *insert* operations additionally receive ``cb-new``.

    Args:
        soup: Current document (BeautifulSoup, mutated in place).
        anchor_html: Path to the anchor (baseline) compiled HTML file.

    Returns:
        Number of elements marked.
    """
    from difflib import SequenceMatcher

    try:
        anchor_soup = read_html(anchor_html)
    except Exception as exc:
        logging.warning(f"Could not parse anchor HTML for difflib change bars: {exc}")
        return 0

    logging.info(f"Difflib change bars: anchor = {anchor_html}")

    anchor_blocks = _extract_leaf_blocks(anchor_soup)
    current_blocks = _extract_leaf_blocks(soup)

    logging.info(f"  Blocks — anchor: {len(anchor_blocks)}, current: {len(current_blocks)}")

    matcher = SequenceMatcher(
        None,
        [b[1] for b in anchor_blocks],  # pre-computed 200-char keys
        [b[1] for b in current_blocks],
        autojunk=False,
    )

    marked_changed = 0
    marked_new = 0

    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        if op == "equal":
            # Keys match but full text might differ (edits beyond first 200 chars)
            for i, j in zip(range(i1, i2), range(j1, j2)):
                if anchor_blocks[i][0] != current_blocks[j][0]:
                    if _add_changed_class(current_blocks[j][2]):
                        marked_changed += 1
        elif op == "replace":
            for j in range(j1, j2):
                if _add_changed_class(current_blocks[j][2]):
                    marked_changed += 1
        elif op == "insert":
            for j in range(j1, j2):
                if _add_changed_class(current_blocks[j][2], "cb-new"):
                    marked_new += 1

    total = marked_changed + marked_new
    logging.info(f"  Difflib: {total} elements marked ({marked_changed} changed, {marked_new} new)")
    return total


def _resolve_anchor_html(anchor_html: Path | None) -> Path | None:
    """Find an anchor HTML to use for the difflib fallback.

    Checks (in order):
    1. Explicit ``anchor_html`` argument.
    2. ``<CONFIG.main_branch_clone_dir>/index.html`` on disk.

    Returns ``None`` if no usable anchor is found.
    """
    if anchor_html is not None and anchor_html.exists():
        return anchor_html

    try:
        candidate = Path(CONFIG.main_branch_clone_dir) / "index.html"
        if candidate.exists():
            return candidate
    except AttributeError:
        logging.debug("CONFIG.main_branch_clone_dir not set; skipping anchor auto-resolve")

    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def add_change_bars(
    html_path: Path,
    baseline_ref: str = "auto",
    *,
    anchor_html: Path | None = None,
) -> None:
    """Add change bars to an HTML specification file.

    Tries the ``data-bs-line`` strategy first.  If the compiled HTML contains
    no ``data-bs-line`` attributes (e.g. Bikeshed 7), falls back to difflib
    comparison against *anchor_html* (or the clone directory if omitted).

    Args:
        html_path: Path to the compiled ``index.html``.
        baseline_ref: Git ref to compare against (``"auto"`` for auto-detect).
        anchor_html: Optional path to a pre-compiled anchor ``index.html``.
            Used only by the difflib fallback.
    """
    try:
        get_bs4()
    except ImportError:
        logging.warning("BeautifulSoup not available, skipping change bars")
        return

    ref = resolve_baseline(baseline_ref)
    changed_lines = get_changed_lines(ref)

    soup = read_html(html_path)
    marked = add_change_bars_soup(soup, changed_lines, anchor_html=anchor_html)
    write_html(html_path, soup)

    if marked == 0:
        logging.warning(
            "Change bars: 0 elements marked. "
            "If using Bikeshed 7, ensure an anchor HTML is available "
            f"(e.g. run with --diff first to populate {CONFIG.main_branch_clone_dir})."
        )


def add_change_bars_soup(
    soup: object,
    changed_lines: dict[str, set[int]],
    *,
    anchor_html: Path | None = None,
) -> int:
    """Add change bars to a pre-parsed BeautifulSoup document.

    Args:
        soup: BeautifulSoup document (mutated in place).
        changed_lines: Mapping of ``.bs`` filename → changed line numbers,
            as returned by :func:`get_changed_lines`.
        anchor_html: Optional anchor HTML path for the difflib fallback.

    Returns:
        Number of elements marked with change bars.
    """
    # --- Strategy 1: data-bs-line (Bikeshed ≤ 6 / annotated) ---
    marked = _mark_by_bs_lines(soup, changed_lines)

    if marked == -1:
        # No data-bs-line annotations found — fall through to difflib.
        pass
    elif marked > 0:
        logging.info(f"Change bars (data-bs-line): {marked} elements marked")
        _inject_change_bar_css(soup)
        return marked
    else:
        # data-bs-line annotations exist but no lines changed — nothing to mark.
        logging.info("Change bars (data-bs-line): 0 elements changed")
        return 0

    # --- Strategy 2: difflib (Bikeshed 7 / no data-bs-line) ---
    anchor = _resolve_anchor_html(anchor_html)
    if anchor is None:
        logging.warning(
            "Change bars: no data-bs-line attributes found and no anchor HTML "
            "available for difflib fallback. Run with --diff first to populate "
            f"the anchor directory ({CONFIG.main_branch_clone_dir}), "
            "or pass an explicit anchor HTML path."
        )
        logging.info(f"Marked 0 elements with change bars ({len(changed_lines)} files)")
        return 0

    logging.info(
        "Change bars: no data-bs-line attributes found "
        "(Bikeshed 7 default output) — using difflib fallback"
    )
    marked = _mark_by_difflib(soup, anchor)

    if marked > 0:
        _inject_change_bar_css(soup)

    logging.info(f"Marked {marked} elements with change bars ({len(changed_lines)} files)")
    return marked


# ---------------------------------------------------------------------------
# CSS injection
# ---------------------------------------------------------------------------


def _inject_change_bar_css(soup: object) -> None:
    """Inject change-bar CSS into the document ``<head>``.

    Uses ``box-shadow: inset`` for the bar — immune to ``overflow: hidden``
    on ancestor elements (unlike ``border-left`` with negative ``margin-left``,
    which gets clipped in many spec layouts).
    """
    t = THEME
    bar_color = _extract_color(t.change_bar_border)
    css = f"""
/* Change Bars — marks elements changed since the baseline ref */

/* box-shadow: inset is not clipped by ancestor overflow:hidden */
.changed-bar {{
  box-shadow: inset 4px 0 0 0 {bar_color};
  padding-left: 6px !important;
  background: rgba(0, 102, 204, 0.04);
}}

/* New content (present in current, absent in anchor) */
.changed-bar.cb-new {{
  box-shadow: inset 4px 0 0 0 #008800;
  background: rgba(0, 136, 0, 0.04);
}}

@media print {{
  .changed-bar {{
    border-left: {t.change_bar_border_print};
    padding-left: 3pt;
    margin-left: -5pt;
    background: none;
    box-shadow: none;
  }}
  .changed-bar.cb-new {{
    border-left: 2pt solid #008800;
    background: none;
    box-shadow: none;
  }}
}}
"""
    inject_css(soup, "change-bar-css", css)
