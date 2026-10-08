#!/usr/bin/env python3

"""
Extract inline CSS from Bikeshed-generated HTML to external file.
This helps with mobile browser compatibility by reducing initial HTML parse size.
"""

from __future__ import annotations

import logging
import re
import sys
from pathlib import Path


def externalize_css(html_path: Path, css_output_dir: Path | None = None) -> bool:
    """
    Extract inline <style> CSS to external file and replace with <link>.

    Args:
        html_path: Path to the HTML file to process
        css_output_dir: Directory for CSS file (defaults to html_path.parent / 'css')

    Returns:
        True if CSS was successfully externalized, False otherwise.
    """
    if not html_path.exists():
        logging.error(f"File not found: {html_path}")
        return False

    # Set default CSS output directory
    if css_output_dir is None:
        css_output_dir = html_path.parent / "css"

    css_output_dir.mkdir(parents=True, exist_ok=True)

    # Read HTML
    html_content = html_path.read_text(encoding="utf-8")

    # Extract inline CSS (everything between <style> and </style>)
    style_pattern = r"<style[^>]*>(.*?)</style>"
    matches = list(re.finditer(style_pattern, html_content, re.DOTALL))

    if not matches:
        logging.warning(f"No inline <style> blocks found in {html_path}")
        return False

    logging.info(f"Found {len(matches)} <style> block(s)")

    # Extract all CSS content
    all_css = []
    for i, match in enumerate(matches):
        css_content = match.group(1)
        all_css.append(f"/* Style block {i + 1} */\n{css_content}\n")

    # Write combined CSS to external file
    css_filename = "bikeshed-generated.css"
    css_path = css_output_dir / css_filename
    css_path.write_text("\n".join(all_css), encoding="utf-8")

    original_size = len(html_content)
    css_size = len("\n".join(all_css))

    logging.info(f"Extracted {css_size:,} bytes of CSS to {css_path}")

    # Replace all <style> blocks with single <link> to external CSS
    link_tag = f'<link rel="stylesheet" href="css/{css_filename}">\n'

    # Remove all <style> blocks and insert link at first position
    new_html = html_content
    for match in reversed(matches):
        new_html = new_html[: match.start()] + new_html[match.end() :]

    # Insert link tag at the position where first style was
    # Find <head> tag to insert after it
    head_match = re.search(r"<head[^>]*>", new_html)
    if head_match:
        insert_pos = head_match.end()
        new_html = new_html[:insert_pos] + "\n" + link_tag + new_html[insert_pos:]

    # Write modified HTML
    html_path.write_text(new_html, encoding="utf-8")

    new_size = len(new_html)
    reduction = original_size - new_size
    reduction_pct = (reduction / original_size) * 100

    logging.info(
        f"HTML size: {original_size:,} -> {new_size:,} bytes ({reduction_pct:.1f}% reduction)"
    )
    logging.info(f"Successfully externalized CSS for {html_path.name}")

    return True


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    if len(sys.argv) < 2:
        logging.error("Usage: python externalize_css.py <html_file>")
        sys.exit(1)

    html_file = Path(sys.argv[1])
    externalize_css(html_file)
