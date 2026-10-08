#!/usr/bin/env python3

"""
Add page numbers to List of Figures and List of Tables for Chrome/Paged.js PDF generation.

This script extends the TOC page number extraction to also handle LOF/LOT.
It uses the same two-pass approach as the TOC script.
"""

from __future__ import annotations

import logging
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


def inject_lof_lot_page_numbers(html_path: Path, page_map: dict) -> bool:
    """
    Inject page numbers into List of Figures and List of Tables.

    Args:
        html_path: Path to HTML file
        page_map: Dictionary mapping element IDs to page numbers

    Returns:
        True if successful
    """
    logging.info("Injecting page numbers into LOF/LOT...")

    try:
        with open(html_path, encoding="utf-8") as f:
            html = f.read()

        soup = BeautifulSoup(html, "html.parser")

        lof_count = 0
        lot_count = 0

        # Process List of Figures
        lof_nav = soup.find("nav", id="lof")
        if lof_nav:
            for page_span in lof_nav.find_all("span", class_="lof-page-number"):
                target_id = page_span.get("data-target")
                if target_id and target_id in page_map:
                    page_span.string = str(page_map[target_id])
                    lof_count += 1

        # Process List of Tables
        lot_nav = soup.find("nav", id="lot")
        if lot_nav:
            for page_span in lot_nav.find_all("span", class_="lot-page-number"):
                target_id = page_span.get("data-target")
                if target_id and target_id in page_map:
                    page_span.string = str(page_map[target_id])
                    lot_count += 1

        # Inject figure and table numbers
        inject_figure_table_numbers(soup)

        # Write back
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(str(soup))

        if lof_count > 0:
            logging.info(f"  Injected {lof_count} page numbers into List of Figures")
        if lot_count > 0:
            logging.info(f"  Injected {lot_count} page numbers into List of Tables")

        return True

    except Exception as e:
        logging.error(f"Failed to inject LOF/LOT page numbers: {e}")
        import traceback

        traceback.print_exc()
        return False


def inject_figure_table_numbers(soup: BeautifulSoup) -> None:
    """
    Inject figure and table numbers based on existing caption markup.

    Extracts the "Table X.Y:" or "Figure X.Y:" labels already present in
    the document's <caption> and <figcaption> elements and injects them
    into the corresponding LOF/LOT entry number spans.

    Args:
        soup: BeautifulSoup object
    """
    import re

    figure_numbers = {}
    table_numbers = {}

    # Extract table numbers from existing caption markup in the document body
    # (skip the LOT nav itself)
    for table in soup.find_all("table"):
        # Skip if inside LOT or TOC
        if table.find_parent("nav", id="lot") or table.find_parent("nav", id="toc"):
            continue
        classes = table.get("class", [])
        if "toc-table" in classes or "sdl-syntax-table" in classes:
            continue

        caption = table.find("caption")
        if not caption:
            continue

        # The caption ID is the anchor we use
        caption_id = caption.get("id", "") or table.get("id", "")
        if not caption_id:
            continue

        # Extract number from <strong> tag (e.g. "Table 8.5: ")
        strong = caption.find("strong")
        if strong:
            strong_text = strong.get_text(strip=True)
            m = re.match(r"^(Table\s+[\w]+\.[\w]+)\s*[:\.]?\s*$", strong_text)
            if m:
                table_numbers[caption_id] = m.group(1) + ":"
                continue

        # Fallback: extract from full caption text
        caption_text = caption.get_text(strip=True)
        m = re.match(r"^(Table\s+[\w]+\.[\w]+)\s*[:\.]?\s*", caption_text)
        if m:
            table_numbers[caption_id] = m.group(1) + ":"

    # Extract figure numbers from existing figcaption markup
    for figure in soup.find_all("figure"):
        if figure.find_parent("nav", id="lof"):
            continue

        figcaption = figure.find("figcaption")
        if not figcaption:
            continue

        figure_id = figure.get("id", "") or figcaption.get("id", "")
        if not figure_id:
            continue

        # Extract number from <strong> tag (e.g. "Figure E.1: ")
        strong = figcaption.find("strong")
        if strong:
            strong_text = strong.get_text(strip=True)
            m = re.match(r"^(Figure\s+[\w]+\.[\w]+)\s*[:\.]?\s*$", strong_text)
            if m:
                figure_numbers[figure_id] = m.group(1) + ":"
                continue

        # Fallback: extract from full figcaption text
        caption_text = figcaption.get_text(strip=True)
        m = re.match(r"^(Figure\s+[\w]+\.[\w]+)\s*[:\.]?\s*", caption_text)
        if m:
            figure_numbers[figure_id] = m.group(1) + ":"

    # Inject figure numbers into LOF
    lof_nav = soup.find("nav", id="lof")
    if lof_nav:
        for fig_num_span in lof_nav.find_all("span", class_="figure-number"):
            target_id = fig_num_span.get("data-target")
            if target_id and target_id in figure_numbers:
                fig_num_span.string = figure_numbers[target_id] + " "

    # Inject table numbers into LOT
    lot_nav = soup.find("nav", id="lot")
    if lot_nav:
        for tbl_num_span in lot_nav.find_all("span", class_="table-number"):
            target_id = tbl_num_span.get("data-target")
            if target_id and target_id in table_numbers:
                tbl_num_span.string = table_numbers[target_id] + " "


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: add_lof_lot_page_numbers_chrome.py <html_path> <page_map_file>")
        sys.exit(1)

    html_path = Path(sys.argv[1])
    page_map_file = Path(sys.argv[2])

    # Read page map
    page_map = {}
    if page_map_file.exists():
        with open(page_map_file, encoding="utf-8") as f:
            for line in f:
                parts = line.strip().split(" -> page ")
                if len(parts) == 2:
                    section_id = parts[0]
                    page_num = int(parts[1])
                    page_map[section_id] = page_num

    # Inject page numbers
    if inject_lof_lot_page_numbers(html_path, page_map):
        logging.info("Successfully injected LOF/LOT page numbers")
        sys.exit(0)
    else:
        logging.error("Failed to inject LOF/LOT page numbers")
        sys.exit(1)
