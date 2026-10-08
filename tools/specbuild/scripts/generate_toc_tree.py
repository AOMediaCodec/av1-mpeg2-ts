#!/usr/bin/env python3
"""
Generate an interactive HTML tree visualization of the specification's
Table of Contents.

Reads all numbered ``.bs`` files from the ``bikeshed/`` directory, parses
their heading structure, and produces a self-contained HTML page with an
expand/collapse tree, statistics, and level-based filtering controls.

Usage::

    python scripts/generate_toc_tree.py

Output: ``toc_tree.html`` in the repository root.
"""

from __future__ import annotations

import glob
import logging
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Path bootstrap — allow importing the specbuild package as a standalone script
# ---------------------------------------------------------------------------
_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from specbuild.theme import THEME  # noqa: E402

# ---------------------------------------------------------------------------
# Type alias for the nested tree dicts used throughout this module
# ---------------------------------------------------------------------------
TreeNode = dict[str, Any]
"""A heading tree node with keys: level, title, anchor, line, in_toc,
is_file, children."""

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Bikeshed heading syntax:  ## Title ## {#anchor}
# Groups: (1) leading hashes  (2) title text  (3) anchor id
_HEADING_RE = re.compile(r"^(#{2,6})\s+(.+?)\s+\#{2,6}\s+\{#([^}]+)\}")

# Heading levels range from 2 (##) to 6 (######) in Bikeshed source.
_MIN_HEADING_LEVEL = 2
_MAX_HEADING_LEVEL = 6

# Level 1 is a synthetic level used exclusively for file nodes in the tree.
_FILE_NODE_LEVEL = 1

# Default ToC depth when not specified in the Bikeshed header metadata.
_DEFAULT_TOC_DEPTH = 3

# Bikeshed header metadata key for maximum ToC depth.
_TOC_DEPTH_RE = re.compile(r"Max ToC Depth:\s*(\d+)")

# ---------------------------------------------------------------------------
# Heading parsing
# ---------------------------------------------------------------------------


def parse_bikeshed_headings(filepath: str) -> list[TreeNode]:
    """Extract all headings from a single Bikeshed source file.

    Headings are recognised by the pattern ``## Title ## {#anchor}`` where
    the number of ``#`` characters determines the heading level (2--6).

    Args:
        filepath: Path to a ``.bs`` file.

    Returns:
        A list of dicts, each with keys ``level``, ``title``, ``anchor``,
        and ``line`` (1-based line number).
    """
    headings: list[TreeNode] = []

    with open(filepath, encoding="utf-8") as f:
        lines = f.readlines()

    for line_num, line in enumerate(lines, 1):
        match = _HEADING_RE.match(line)
        if match:
            hashes, title, anchor = match.group(1), match.group(2), match.group(3)
            headings.append(
                {
                    "level": len(hashes),
                    "title": title,
                    "anchor": anchor,
                    "line": line_num,
                }
            )

    return headings


# ---------------------------------------------------------------------------
# Tree construction
# ---------------------------------------------------------------------------


def _make_file_node(filename: str) -> TreeNode:
    """Create a synthetic Level-1 tree node representing a source file.

    Args:
        filename: The basename of the ``.bs`` file (e.g. ``03_Symbols.bs``).

    Returns:
        A tree node dict with ``is_file`` set to ``True``.
    """
    return {
        "level": _FILE_NODE_LEVEL,
        "title": filename,
        "anchor": filename.replace(".bs", ""),
        "line": 0,
        "in_toc": True,  # Files are always conceptually "in ToC"
        "is_file": True,
        "children": [],
    }


def _make_heading_node(heading: TreeNode, toc_depth: int) -> TreeNode:
    """Create a tree node from a parsed heading dict.

    Args:
        heading:   A dict produced by :func:`parse_bikeshed_headings`.
        toc_depth: Maximum level that appears in the ToC.

    Returns:
        A tree node dict with ``is_file`` set to ``False``.
    """
    return {
        "level": heading["level"],
        "title": heading["title"],
        "anchor": heading["anchor"],
        "line": heading["line"],
        "in_toc": heading["level"] <= toc_depth,
        "is_file": False,
        "children": [],
    }


def build_tree_with_files(files: list[str], toc_depth: int = _DEFAULT_TOC_DEPTH) -> list[TreeNode]:
    """Build a hierarchical tree structure with files as Level 1.

    Each ``.bs`` file becomes a synthetic Level-1 node.  Headings parsed
    from that file are nested beneath it according to their level.

    Args:
        files:     Sorted list of ``.bs`` file paths.
        toc_depth: Maximum heading level included in the specification ToC.

    Returns:
        A list of top-level (file) tree nodes, each with nested children.
    """
    tree: list[TreeNode] = []

    for filepath in files:
        filename = Path(filepath).name
        headings = parse_bikeshed_headings(filepath)

        if not headings:
            continue

        file_node = _make_file_node(filename)

        # Stack tracks the current nesting path so each heading can find
        # its nearest ancestor at a shallower level.
        stack: list[TreeNode] = [file_node]

        for heading in headings:
            # Walk back up until the stack top is a valid parent (shallower level).
            while stack[-1]["level"] >= heading["level"]:
                stack.pop()

            node = _make_heading_node(heading, toc_depth)
            stack[-1]["children"].append(node)
            stack.append(node)

        tree.append(file_node)

    return tree


# ---------------------------------------------------------------------------
# Tree statistics
# ---------------------------------------------------------------------------


def count_descendants(node: TreeNode) -> dict[int, int]:
    """Count all non-file descendants of *node*, grouped by heading level.

    Args:
        node: A tree node whose subtree will be counted.

    Returns:
        A dict mapping heading level to occurrence count.
    """
    counts: dict[int, int] = {}

    def _recurse(n: TreeNode) -> None:
        if not n.get("is_file"):
            counts[n["level"]] = counts.get(n["level"], 0) + 1
        for child in n["children"]:
            _recurse(child)

    for child in node["children"]:
        _recurse(child)

    return counts


def count_all_headings(tree: list[TreeNode]) -> dict[int, int]:
    """Count headings by level across the entire tree.

    Args:
        tree: The top-level list of file nodes.

    Returns:
        A dict mapping heading level to total count (file nodes excluded).
    """
    counts: dict[int, int] = {}

    def _recurse(node: TreeNode) -> None:
        if not node.get("is_file"):
            level = node["level"]
            counts[level] = counts.get(level, 0) + 1
        for child in node["children"]:
            _recurse(child)

    for node in tree:
        _recurse(node)

    return counts


# ---------------------------------------------------------------------------
# HTML tree rendering
# ---------------------------------------------------------------------------


def _descendant_count_label(node: TreeNode) -> str:
    """Build an HTML snippet summarising descendant counts per level.

    Args:
        node: A tree node with children.

    Returns:
        An HTML ``<span>`` string like ``(L2:5, L3:12)`` or empty string
        if the node has no children.
    """
    if not node["children"]:
        return ""

    child_counts = count_descendants(node)
    parts = [
        f"L{lvl}:{child_counts[lvl]}"
        for lvl in range(_MIN_HEADING_LEVEL, _MAX_HEADING_LEVEL + 1)
        if lvl in child_counts
    ]
    if parts:
        return f" <span class='count'>({', '.join(parts)})</span>"
    return ""


def _node_css_classes(node: TreeNode, toc_depth: int) -> list[str]:
    """Determine the CSS class list for a tree node.

    Args:
        node:      The tree node.
        toc_depth: Maximum heading level shown in the ToC.

    Returns:
        A list of CSS class name strings.
    """
    level = node["level"]
    is_file = node.get("is_file", False)
    in_toc = True if is_file else (level <= toc_depth)
    has_children = len(node["children"]) > 0

    classes = ["node"]

    if is_file:
        classes += ["file-node", "level-1"]
    else:
        classes.append("in-toc" if in_toc else "not-in-toc")
        classes.append(f"level-{level}")

    if has_children:
        classes += ["has-children", "expanded"]  # Start expanded

    return classes


def _node_to_html(node: TreeNode, toc_depth: int, parent_in_toc: bool = True) -> str:
    """Recursively render a single tree node (and its children) as HTML.

    Args:
        node:          The tree node to render.
        toc_depth:     Maximum heading level shown in the ToC.
        parent_in_toc: Whether the parent node is within the ToC depth.

    Returns:
        An HTML string for this node and all descendants.
    """
    level = node["level"]
    is_file = node.get("is_file", False)
    in_toc = True if is_file else (level <= toc_depth)
    has_children = len(node["children"]) > 0

    classes = _node_css_classes(node, toc_depth)
    count_label = _descendant_count_label(node)

    # --- toggle arrow / placeholder ---
    if has_children:
        toggle_html = '<span class="toggle" onclick="toggleNode(this)">▼</span>'
    else:
        toggle_html = '<span class="toggle-placeholder"></span>'

    # --- level badge and ToC visibility badge ---
    title_html = f'<span class="title">{node["title"]}</span>'

    if is_file:
        level_badge = '<span class="level-badge level-1">FILE</span>'
        toc_badge = ""
    else:
        level_badge = f'<span class="level-badge level-{level}">L{level}</span>'
        toc_badge = "" if in_toc else '<span class="toc-badge out">hidden</span>'

    # --- assemble node markup ---
    html = f'<div class="{" ".join(classes)}">'
    html += toggle_html
    html += f'<span class="heading">{level_badge} {title_html} {toc_badge}{count_label}</span>'

    if has_children:
        html += '<div class="children">'
        for child in node["children"]:
            html += _node_to_html(child, toc_depth, in_toc)
        html += "</div>"

    html += "</div>"
    return html


def generate_html_tree(tree: list[TreeNode], toc_depth: int = _DEFAULT_TOC_DEPTH) -> str:
    """Generate the HTML fragment for the interactive heading tree.

    Args:
        tree:      List of top-level file nodes.
        toc_depth: Maximum heading level shown in the ToC.

    Returns:
        An HTML string wrapped in a ``<div class="tree-root">`` container.
    """
    html = '<div class="tree-root">'
    for node in tree:
        html += _node_to_html(node, toc_depth)
    html += "</div>"

    return html


# ---------------------------------------------------------------------------
# Full-page HTML generation
# ---------------------------------------------------------------------------


def _build_css(t: Any) -> str:
    """Return the full ``<style>`` content for the ToC tree page.

    Args:
        t: The THEME object providing colour tokens.

    Returns:
        A CSS string (without surrounding ``<style>`` tags).
    """
    return f"""
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}

        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            padding: 20px;
            background: #f5f5f5;
            color: {t.color_meta};
        }}

        .header {{
            background: white;
            padding: 20px;
            border-radius: 8px;
            margin-bottom: 20px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}

        h1 {{
            color: {t.color_body};
            margin-bottom: 10px;
        }}

        .stats {{
            display: flex;
            gap: 20px;
            margin: 15px 0;
            flex-wrap: wrap;
        }}

        .stat {{
            background: #f8f9fa;
            padding: 10px 15px;
            border-radius: 6px;
            border-left: 4px solid #007bff;
        }}

        .stat-label {{
            font-size: 12px;
            color: {t.color_muted};
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}

        .stat-value {{
            font-size: 24px;
            font-weight: bold;
            color: {t.color_body};
        }}

        .controls {{
            margin: 15px 0;
            display: flex;
            gap: 10px;
            flex-wrap: wrap;
        }}

        button {{
            padding: 8px 16px;
            border: none;
            border-radius: 4px;
            background: #007bff;
            color: white;
            cursor: pointer;
            font-size: 14px;
        }}

        button:hover {{
            background: #0056b3;
        }}

        .legend {{
            display: flex;
            gap: 15px;
            margin: 15px 0;
            flex-wrap: wrap;
        }}

        .legend-item {{
            display: flex;
            align-items: center;
            gap: 5px;
            font-size: 14px;
        }}

        .tree-container {{
            background: white;
            padding: 20px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}

        .tree-root {{
            font-family: 'Monaco', 'Menlo', monospace;
            font-size: 13px;
            line-height: 1.6;
        }}

        .node {{
            margin: 2px 0;
        }}

        .file-node {{
            margin: 15px 0;
            font-weight: bold;
            color: #0056b3;
        }}

        .toggle {{
            display: inline-block;
            width: 16px;
            cursor: pointer;
            user-select: none;
            color: {t.color_muted};
            transition: transform 0.2s;
        }}

        .toggle-placeholder {{
            display: inline-block;
            width: 16px;
        }}

        .node.collapsed .toggle {{
            transform: rotate(-90deg);
        }}

        .node.collapsed > .children {{
            display: none;
        }}

        .heading {{
            display: inline-block;
            padding: 2px 0;
        }}

        .title {{
            margin-left: 5px;
        }}

        .level-badge {{
            display: inline-block;
            padding: 2px 6px;
            border-radius: 3px;
            font-size: 11px;
            font-weight: bold;
            margin-right: 5px;
        }}

        .level-badge.level-1 {{ background: #6f42c1; color: white; }}
        .level-badge.level-2 {{ background: #007bff; color: white; }}
        .level-badge.level-3 {{ background: #28a745; color: white; }}
        .level-badge.level-4 {{ background: #ffc107; color: black; }}
        .level-badge.level-5 {{ background: #6c757d; color: white; }}
        .level-badge.level-6 {{ background: #343a40; color: white; }}

        .toc-badge {{
            display: inline-block;
            padding: 2px 6px;
            border-radius: 3px;
            font-size: 10px;
            font-weight: bold;
            margin-left: 5px;
        }}

        .toc-badge.out {{
            background: #f8d7da;
            color: #721c24;
        }}

        .count {{
            font-size: 11px;
            color: {t.color_muted};
            margin-left: 5px;
        }}

        .children {{
            margin-left: 25px;
            border-left: 1px solid #e0e0e0;
            padding-left: 10px;
        }}

        .level-2 {{
            font-weight: bold;
            color: {t.color_body};
        }}

        .level-3 {{
            color: #2c3e50;
        }}

        .level-4 {{
            color: #5a6c7d;
        }}

        .not-in-toc {{
            opacity: 0.7;
        }}

        .timestamp {{
            color: {t.color_muted};
            font-size: 14px;
            margin-top: 10px;
        }}
    """


# Inline JavaScript providing expand/collapse behaviour for the tree.
_TREE_JS = """
    <script>
        function toggleNode(element) {
            const node = element.parentElement;
            node.classList.toggle('collapsed');
        }

        function expandAll() {
            document.querySelectorAll('.node').forEach(node => {
                node.classList.remove('collapsed');
            });
        }

        function collapseAll() {
            document.querySelectorAll('.node.has-children').forEach(node => {
                node.classList.add('collapsed');
            });
        }

        function collapseToFiles() {
            document.querySelectorAll('.node').forEach(node => {
                if (node.classList.contains('has-children')) {
                    if (node.classList.contains('file-node')) {
                        node.classList.add('collapsed');
                    }
                }
            });
        }

        function expandToLevel(maxLevel) {
            document.querySelectorAll('.node').forEach(node => {
                if (node.classList.contains('has-children')) {
                    // Get level from class
                    const levelMatch = node.className.match(/level-(\\d+)/);
                    if (levelMatch) {
                        const level = parseInt(levelMatch[1]);
                        if (level < maxLevel) {
                            node.classList.remove('collapsed');
                        } else {
                            node.classList.add('collapsed');
                        }
                    }
                }
            });
        }
    </script>
    """


def _build_header_html(
    spec_name: str,
    level_counts: dict[int, int],
    in_toc_count: int,
    total_count: int,
) -> list[str]:
    """Build the HTML lines for the page header (title, stats, controls, legend).

    Args:
        spec_name:    Human-readable specification name.
        level_counts: Heading counts keyed by level.
        in_toc_count: Total headings that appear in the ToC.
        total_count:  Total heading count across all levels.

    Returns:
        A list of HTML line strings.
    """
    lines: list[str] = []

    lines.append('    <div class="header">')
    lines.append(f"        <h1>{spec_name} - Table of Contents Tree</h1>")
    lines.append(
        "        <p>Interactive visualization of the specification's heading structure</p>"
    )

    # --- statistics badges ---
    lines.append('        <div class="stats">')
    lines.append(
        f'            <div class="stat"><div class="stat-label">ToC Entries (L2 + L3)</div><div class="stat-value">{in_toc_count}</div></div>'
    )
    lines.append(
        f'            <div class="stat"><div class="stat-label">Level 2</div><div class="stat-value">{level_counts.get(2, 0)}</div></div>'
    )
    lines.append(
        f'            <div class="stat"><div class="stat-label">Level 3</div><div class="stat-value">{level_counts.get(3, 0)}</div></div>'
    )
    lines.append(
        f'            <div class="stat"><div class="stat-label">Level 4</div><div class="stat-value">{level_counts.get(4, 0)}</div></div>'
    )
    lines.append(
        f'            <div class="stat"><div class="stat-label">Total Headings</div><div class="stat-value">{total_count}</div></div>'
    )
    lines.append("        </div>")

    # --- expand / collapse controls ---
    lines.append('        <div class="controls">')
    lines.append('            <button onclick="expandAll()">Expand All</button>')
    lines.append('            <button onclick="collapseAll()">Collapse All</button>')
    lines.append('            <button onclick="collapseToFiles()">Show Files Only</button>')
    lines.append('            <button onclick="expandToLevel(2)">Show L2</button>')
    lines.append('            <button onclick="expandToLevel(3)">Show L2-L3</button>')
    lines.append('            <button onclick="expandToLevel(4)">Show All</button>')
    lines.append("        </div>")

    # --- colour legend ---
    lines.append('        <div class="legend">')
    lines.append(
        '            <div class="legend-item"><span class="level-badge level-1">FILE</span> Bikeshed source file</div>'
    )
    lines.append(
        '            <div class="legend-item"><span class="level-badge level-2">L2</span> Level 2 (Major sections)</div>'
    )
    lines.append(
        '            <div class="legend-item"><span class="level-badge level-3">L3</span> Level 3 (Subsections)</div>'
    )
    lines.append(
        '            <div class="legend-item"><span class="level-badge level-4">L4</span> Level 4 (Details)</div>'
    )
    lines.append(
        '            <div class="legend-item"><span class="toc-badge out">hidden</span> Hidden from ToC (not visible in spec ToC)</div>'
    )
    lines.append("        </div>")
    lines.append(
        f'        <div class="timestamp">Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</div>'
    )
    lines.append("    </div>")

    return lines


def generate_full_html(
    bikeshed_dir: str,
    output_file: str,
    toc_depth: int = _DEFAULT_TOC_DEPTH,
    spec_name: str = "Specification",
) -> None:
    """Generate a complete, self-contained HTML document with the ToC tree.

    Args:
        bikeshed_dir: Path to the directory containing ``.bs`` source files.
        output_file:  Destination path for the generated HTML file.
        toc_depth:    Maximum heading level included in the specification ToC.
        spec_name:    Human-readable name shown in the page title/header.
    """
    theme = THEME

    # --- collect data ---
    files = sorted(glob.glob(f"{bikeshed_dir}/*.bs"))
    tree = build_tree_with_files(files, toc_depth)
    level_counts = count_all_headings(tree)

    in_toc_count = sum(level_counts.get(lvl, 0) for lvl in range(_MIN_HEADING_LEVEL, toc_depth + 1))
    total_count = sum(level_counts.values())

    # --- assemble HTML document ---
    html_parts: list[str] = []

    # Document head
    html_parts.append("<!DOCTYPE html>")
    html_parts.append('<html lang="en">')
    html_parts.append("<head>")
    html_parts.append('    <meta charset="UTF-8">')
    html_parts.append('    <meta name="viewport" content="width=device-width, initial-scale=1.0">')
    html_parts.append(f"    <title>{spec_name} - Table of Contents Tree</title>")
    html_parts.append("    <style>")
    html_parts.append(_build_css(theme))
    html_parts.append("    </style>")
    html_parts.append("</head>")
    html_parts.append("<body>")

    # Page header (stats, controls, legend)
    html_parts += _build_header_html(spec_name, level_counts, in_toc_count, total_count)

    # Interactive tree
    html_parts.append('    <div class="tree-container">')
    html_parts.append("        <h2>Complete Structure</h2>")
    html_parts.append(generate_html_tree(tree, toc_depth))
    html_parts.append("    </div>")

    # Client-side JavaScript
    html_parts.append(_TREE_JS)
    html_parts.append("</body>")
    html_parts.append("</html>")

    # --- write output ---
    with open(output_file, "w", encoding="utf-8") as f:
        f.write("\n".join(html_parts))

    logging.info(f"Generated ToC tree: {output_file}")
    logging.info(f"Statistics: Total headings: {total_count}, In ToC (L2 + L3): {in_toc_count}")
    for level in sorted(level_counts.keys()):
        visibility = "IN TOC" if level <= toc_depth else "(hidden)"
        logging.info(f"  Level {level}: {level_counts[level]} {visibility}")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    script_dir = Path(__file__).parent
    repo_root = script_dir.parent
    bikeshed_dir = repo_root / "bikeshed"
    output_file = repo_root / "toc_tree.html"

    # Read ToC depth from the Bikeshed header metadata (fall back to default).
    toc_depth = _DEFAULT_TOC_DEPTH
    header_file = bikeshed_dir / "00_Header.bs"
    if header_file.exists():
        with open(header_file, encoding="utf-8") as f:
            for line in f:
                match = _TOC_DEPTH_RE.search(line)
                if match:
                    toc_depth = int(match.group(1))
                    break

    logging.info(f"ToC Depth: {toc_depth}")
    logging.info(f"Bikeshed directory: {bikeshed_dir}")
    logging.info(f"Output file: {output_file}")

    generate_full_html(str(bikeshed_dir), str(output_file), toc_depth)
