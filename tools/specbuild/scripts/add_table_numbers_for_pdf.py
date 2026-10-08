#!/usr/bin/env python3

"""
Pre-process HTML to add table and figure numbers for PDF generation.
This script modifies the HTML to hardcode table and figure numbers in captions,
which ensures they appear correctly in the PDF.

For Annex sections (sections 10-14), uses letter-based numbering (A-E).
"""

from __future__ import annotations

import logging
from pathlib import Path

from bs4 import BeautifulSoup

# Mapping of section numbers to Annex letters (sections 10-14 -> A-E)
ANNEX_MAPPING: dict[int, str] = {
    10: "A",
    11: "B",
    12: "C",
    13: "D",
    14: "E",
}


def get_section_label(section_number: int) -> str:
    """
    Get the section label for table numbering.

    For Annex sections (10-14), returns the letter (A-E).
    For other sections, returns the section number.
    """
    return ANNEX_MAPPING.get(section_number, str(section_number))


def add_table_numbers_for_pdf(html_path: Path) -> None:
    """
    Add hardcoded table and figure numbers to captions for PDF generation.

    Walks the ``<main>`` element sequentially, incrementing section counters
    at each numbered ``<h2>`` and assigning per-section table/figure numbers
    to ``<caption>`` and ``<figcaption>`` elements.  Also updates any
    ``table-ref`` or ``figure-ref`` cross-reference links.

    Args:
        html_path: Path to the HTML file to modify in place.
    """

    with open(html_path, encoding="utf-8") as f:
        html = f.read()

    soup = BeautifulSoup(html, "html.parser")

    # Find main element
    main = soup.find("main")
    if not main:
        logging.error("No <main> element found")
        return

    section_number = 0
    table_number = 0
    figure_number = 0
    table_numbers = {}  # Map caption IDs to their numbers
    figure_numbers = {}  # Map figure IDs to their numbers

    # Process all children of main
    for elem in main.children:
        if not hasattr(elem, "name"):
            continue

        # Check if this is a numbered h2
        if (
            elem.name == "h2"
            and "heading" in elem.get("class", [])
            and "settled" in elem.get("class", [])
            and "no-num" not in elem.get("class", [])
        ):
            # Increment section, reset table and figure counters
            section_number += 1
            table_number = 0
            figure_number = 0

        # Check if this is a table with a caption
        if elem.name == "table":
            caption = elem.find("caption")
            if caption and "sdl-syntax-table" not in elem.get("class", []):
                table_number += 1

                # Get the section label (letter for Annexes, number otherwise)
                section_label = get_section_label(section_number)
                table_ref = f"{section_label}.{table_number}"

                # Store the table number for this caption ID
                if caption.get("id"):
                    table_numbers[caption.get("id")] = table_ref

                # Check if number is already added
                caption_text = caption.get_text()
                if not caption_text.startswith("Table "):
                    # Add the table number at the beginning
                    prefix = soup.new_tag("strong")
                    prefix.string = f"Table {table_ref}: "
                    caption.insert(0, prefix)

        # Check if this is a figure with a figcaption
        if elem.name == "figure":
            figcaption = elem.find("figcaption")
            if figcaption:
                figure_number += 1

                section_label = get_section_label(section_number)
                figure_ref = f"{section_label}.{figure_number}"

                # Store the figure number for this figure/figcaption ID
                figure_id = elem.get("id") or figcaption.get("id")
                if figure_id:
                    figure_numbers[figure_id] = figure_ref

                # Check if number is already added
                caption_text = figcaption.get_text()
                if not caption_text.startswith("Figure "):
                    prefix = soup.new_tag("strong")
                    prefix.string = f"Figure {figure_ref}: "
                    figcaption.insert(0, prefix)
                    # Add class to suppress Bikeshed's CSS counter numbering
                    existing = figcaption.get("class", [])
                    figcaption["class"] = existing + ["has-figure-number"]

    log = logging.info if (table_numbers or figure_numbers) else logging.debug
    log(
        f"Added numbers to {len(table_numbers)} tables and {len(figure_numbers)} figures in {section_number} sections"
    )

    # Update table cross-references
    table_refs = soup.find_all("a", class_="table-ref")
    for link in table_refs:
        href = link.get("href", "")
        if href.startswith("#"):
            target_id = href[1:]
            if target_id in table_numbers:
                link.string = f"Table {table_numbers[target_id]}"

    if table_refs:
        logging.info(f"Updated {len(table_refs)} table cross-references")

    # Update figure cross-references
    figure_refs = soup.find_all("a", class_="figure-ref")
    for link in figure_refs:
        href = link.get("href", "")
        if href.startswith("#"):
            target_id = href[1:]
            if target_id in figure_numbers:
                link.string = f"Figure {figure_numbers[target_id]}"

    if figure_refs:
        logging.info(f"Updated {len(figure_refs)} figure cross-references")

    # Write back
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(str(soup))

    logging.info(f"Pre-processed HTML for PDF: {html_path}")


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    if len(sys.argv) > 1:
        html_path = Path(sys.argv[1])
    else:
        # Default to the latest build
        builds = sorted(Path(".").glob("????????_*_Spec_Draft"))
        if builds:
            html_path = builds[-1] / "index.html"
        else:
            logging.error("No build directory found. Specify an HTML file.")
            sys.exit(1)

    add_table_numbers_for_pdf(html_path)
