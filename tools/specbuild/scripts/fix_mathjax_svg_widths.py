#!/usr/bin/env python3

"""
Fix MathJax SVG width attributes for WeasyPrint PDF generation.

WeasyPrint doesn't properly handle width="100%" on SVG elements, causing equations
to render at full page width instead of their natural size. This script changes
width="100%" to explicit pixel widths based on the min-width style attribute.
"""

from __future__ import annotations

import logging
import re
import sys
from pathlib import Path

from bs4 import BeautifulSoup

# Route logging through the shared colored formatter when this script is
# invoked as a subprocess of compile.py.
_repo_root = str(Path(__file__).resolve().parent.parent)
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)
from specbuild.logsetup import setup_logging  # noqa: E402

setup_logging("INFO")


def fix_svg_widths(html_path: Path) -> bool:
    """
    Fix SVG width attributes in MathJax equations.

    Args:
        html_path: Path to HTML file to process (modified in-place)

    Returns:
        True if successful, False otherwise
    """
    logging.info(f"Fixing MathJax SVG widths in: {html_path}")

    try:
        # Read HTML
        with open(html_path, encoding="utf-8") as f:
            soup = BeautifulSoup(f.read(), "html.parser")

        # Find all display equations
        equations = soup.find_all("mjx-container", display="true")
        logging.info(f"  Found {len(equations)} display equations")

        modified = 0
        for eq in equations:
            svg = eq.find("svg")
            if svg and svg.get("width") == "100%":
                # Get the min-width from style attribute (in 'ex' units)
                style = svg.get("style", "")
                min_width_match = re.search(r"min-width:\s*([\d.]+)ex", style)

                if min_width_match:
                    min_width_ex = float(min_width_match.group(1))
                    # Convert ex to pixels: 1ex ~ 8px at the default 10pt font size
                    EX_TO_PX = 8
                    width_px = int(min_width_ex * EX_TO_PX)

                    # Change width from '100%' to explicit pixel width
                    svg["width"] = f"{width_px}px"
                    modified += 1

        logging.info(f"  Modified {modified} SVG width attributes")

        # Write back to file
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(str(soup))

        logging.info("  ✓ Successfully fixed SVG widths")
        return True

    except Exception as e:
        logging.error(f"  Failed to fix SVG widths: {e}")
        return False


if __name__ == "__main__":
    if len(sys.argv) != 2:
        logging.error(f"Usage: {sys.argv[0]} <html_file>")
        sys.exit(1)

    html_path = Path(sys.argv[1])

    if not html_path.exists():
        logging.error(f"HTML file not found: {html_path}")
        sys.exit(1)

    success = fix_svg_widths(html_path)
    sys.exit(0 if success else 1)
