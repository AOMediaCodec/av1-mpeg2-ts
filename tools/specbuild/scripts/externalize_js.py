#!/usr/bin/env python3

"""
Extract inline JavaScript from Bikeshed-generated HTML to external file.
This helps with mobile browser compatibility by reducing initial HTML parse size.
"""

from __future__ import annotations

import logging
import re
import sys
from pathlib import Path


def externalize_js(html_path: Path, js_output_dir: Path | None = None) -> bool:
    """
    Extract inline <script> JavaScript to external file and replace with <script src>.

    Args:
        html_path: Path to the HTML file to process
        js_output_dir: Directory for JS file (defaults to html_path.parent / 'js')

    Returns:
        True if JavaScript was successfully externalized, False otherwise.
    """
    if not html_path.exists():
        logging.error(f"File not found: {html_path}")
        return False

    # Set default JS output directory
    if js_output_dir is None:
        js_output_dir = html_path.parent / "js"

    js_output_dir.mkdir(parents=True, exist_ok=True)

    # Read HTML
    html_content = html_path.read_text(encoding="utf-8")

    # Extract inline scripts (but skip external <script src="...">)
    # Pattern: <script> ... </script> (non-greedy, but NOT <script src=...>)
    script_pattern = r"<script(?![^>]*\bsrc\s*=)([^>]*)>(.*?)</script>"
    matches = list(re.finditer(script_pattern, html_content, re.DOTALL | re.IGNORECASE))

    if not matches:
        logging.warning(f"No inline <script> blocks found in {html_path}")
        return False

    logging.info(f"Found {len(matches)} inline <script> block(s)")

    # Extract all JavaScript content
    all_js = []
    for i, match in enumerate(matches):
        js_content = match.group(2).strip()
        if js_content:  # Skip empty scripts
            all_js.append(f"/* Script block {i + 1} */\n{js_content}\n")

    if not all_js:
        logging.warning("All script blocks were empty")
        return False

    # Write combined JS to external file
    js_filename = "bikeshed-generated.js"
    js_path = js_output_dir / js_filename
    js_path.write_text("\n\n".join(all_js), encoding="utf-8")

    original_size = len(html_content)
    js_size = len("\n\n".join(all_js))

    logging.info(f"Extracted {js_size:,} bytes of JavaScript to {js_path}")

    # Replace all inline <script> blocks with single external <script src>
    new_html = html_content

    # Remove all inline scripts in reverse order (to maintain positions)
    # Filter to non-empty scripts first so skipped entries don't leave stale offsets
    nonempty_matches = [m for m in matches if m.group(2).strip()]
    for match in reversed(nonempty_matches):
        new_html = new_html[: match.start()] + new_html[match.end() :]

    # Add external script reference before </body>
    script_tag = f'<script src="js/{js_filename}"></script>\n'
    body_close = new_html.rfind("</body>")
    if body_close != -1:
        new_html = new_html[:body_close] + script_tag + new_html[body_close:]
    else:
        # If no </body>, append at end
        new_html = new_html + script_tag

    # Write modified HTML
    html_path.write_text(new_html, encoding="utf-8")

    new_size = len(new_html)
    reduction = original_size - new_size
    reduction_pct = (reduction / original_size) * 100

    logging.info(
        f"HTML size: {original_size:,} -> {new_size:,} bytes ({reduction_pct:.1f}% reduction)"
    )
    logging.info(f"Successfully externalized JavaScript for {html_path.name}")

    return True


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    if len(sys.argv) < 2:
        logging.error("Usage: python externalize_js.py <html_file>")
        sys.exit(1)

    html_file = Path(sys.argv[1])
    externalize_js(html_file)
