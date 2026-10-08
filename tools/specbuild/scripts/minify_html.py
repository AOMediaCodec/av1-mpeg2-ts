#!/usr/bin/env python3

"""
Minify HTML to reduce file size for mobile browsers.
Removes unnecessary whitespace while preserving functionality.
"""

from __future__ import annotations

import logging
import re
import sys
from pathlib import Path


def minify_html(html_path: Path) -> bool:
    """
    Minify HTML file by removing unnecessary whitespace and comments.

    Protected tags (<pre>, <code>, <script>, <style>, <textarea>) are
    preserved verbatim.

    Args:
        html_path: Path to the HTML file to minify

    Returns:
        True if the file was successfully minified, False otherwise.
    """
    if not html_path.exists():
        logging.error(f"File not found: {html_path}")
        return False

    logging.info(f"Minifying {html_path.name}")

    # Read HTML
    html_content = html_path.read_text(encoding="utf-8")
    original_size = len(html_content)

    # 1. Remove HTML comments (but preserve conditional comments for IE)
    html_content = re.sub(r"<!--(?!\[if).*?-->", "", html_content, flags=re.DOTALL)

    # 2. Remove whitespace between tags (but preserve <pre>, <code>, <textarea> content)
    # First, protect content in special tags
    protected_blocks = []

    def protect_block(match: re.Match[str]) -> str:
        """Store block content and return a placeholder."""
        protected_blocks.append(match.group(0))
        return f"__PROTECTED_{len(protected_blocks) - 1}__"

    # Protect <pre>, <code>, <script>, <style>, and <textarea> blocks
    html_content = re.sub(
        r"(?i)<(pre|code|script|style|textarea)([^>]*)>(.*?)</\1>",
        protect_block,
        html_content,
        flags=re.DOTALL,
    )

    # 3. Collapse multiple spaces/newlines into single space
    html_content = re.sub(r"\s+", " ", html_content)

    # 4. Remove spaces around tags
    html_content = re.sub(r">\s+<", "><", html_content)

    # 5. Remove spaces after opening tags and before closing tags
    html_content = re.sub(r"<\s+", "<", html_content)
    html_content = re.sub(r"\s+>", ">", html_content)

    # 6. Restore protected blocks
    for i, block in enumerate(protected_blocks):
        html_content = html_content.replace(f"__PROTECTED_{i}__", block)

    # Write minified HTML
    html_path.write_text(html_content, encoding="utf-8")

    new_size = len(html_content)
    reduction = original_size - new_size
    reduction_pct = (reduction / original_size) * 100

    logging.info(f"HTML size: {original_size:,} → {new_size:,} bytes")
    logging.info(f"Reduction: {reduction:,} bytes ({reduction_pct:.1f}%)")
    logging.info(f"Successfully minified {html_path.name}")

    return True


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    if len(sys.argv) < 2:
        logging.error("Usage: python minify_html.py <html_file>")
        sys.exit(1)

    html_file = Path(sys.argv[1])
    minify_html(html_file)
