#!/usr/bin/env python3

"""
Generate a simplified syntax browser with only sections 5 & 6.

This script creates a lightweight, standalone HTML page containing only:
- Section 5: Syntax Structures (left pane)
- Section 6: Semantics (right pane)

No TOC, no other sections, no Bikeshed overhead.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from bs4 import BeautifulSoup, Tag

# Route logging through the shared colored formatter when this script is
# invoked as a subprocess of compile.py.
_repo_root = str(Path(__file__).resolve().parent.parent)
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)
from specbuild.logsetup import setup_logging  # noqa: E402

setup_logging("INFO")


def extract_section(soup: BeautifulSoup, section_id: str, end_section_id: str) -> list[Tag]:
    """
    Extract all content between two h2 sections.

    Args:
        soup: Parsed HTML document.
        section_id: The ``id`` attribute of the starting h2.
        end_section_id: The ``id`` attribute of the h2 that marks the end boundary.

    Returns:
        List of Tag elements found between the two headings.
    """
    start_section = soup.find("h2", id=section_id)
    end_section = soup.find("h2", id=end_section_id)

    if not start_section:
        logging.error(f"Could not find section: {section_id}")
        return []

    content = []
    current = start_section.next_sibling

    while current and current != end_section:
        if current.name:  # Only include tag elements
            content.append(current)
        current = current.next_sibling

    return content


def extract_head_essentials(soup: BeautifulSoup) -> list[Tag]:
    """Extract only essential head elements (CSS for tables/syntax, meta tags).

    Excludes Bikeshed's main stylesheet which contains TOC sidebar padding.

    Args:
        soup: Parsed HTML document.

    Returns:
        List of essential ``<meta>`` and ``<link>`` tags.
    """
    head = soup.find("head")
    if not head:
        return []

    essentials = []

    # Get meta tags
    for meta in head.find_all("meta"):
        essentials.append(meta)

    # Get ONLY custom.css link, not the main Bikeshed stylesheet
    for link in head.find_all("link", rel="stylesheet"):
        href = link.get("href", "")
        # Only include custom.css which has SDL table styles
        if "custom.css" in href:
            essentials.append(link)
        # Skip bikeshed default styles which add TOC padding

    # Don't include style tags as they contain Bikeshed's TOC layout CSS
    # We'll provide our own minimal styling

    return essentials


def attach_semantics_to_syntax_tables(
    syntax_content: list[Tag], semantics_content: list[Tag]
) -> None:
    """
    Find each syntax table and attach its corresponding semantics text as a data attribute.

    Args:
        syntax_content: List of syntax section elements
        semantics_content: List of semantics section elements
    """
    logging.info("Attaching semantics to syntax tables")

    # Build a map of semantics sections by ID
    semantics_map = {}

    for elem in semantics_content:
        if elem.name in ["h3", "h4"] and elem.get("id", "").endswith("_semantics"):
            section_id = elem.get("id")
            # Collect all paragraphs until the next heading
            paragraphs = []
            current = elem.next_sibling
            while current:
                if hasattr(current, "name"):
                    if current.name in ["h3", "h4", "h2"]:
                        break
                    if current.name == "p":
                        # Get the text content, preserving structure
                        paragraphs.append(current.get_text(separator=" ", strip=True))
                current = current.next_sibling

            if paragraphs:
                semantics_map[section_id] = "\n\n".join(paragraphs)

    logging.info(f"Found {len(semantics_map)} semantics sections")

    # Now find syntax tables and attach their semantics
    attached_count = 0

    for elem in syntax_content:
        # Find all syntax tables
        if hasattr(elem, "find_all"):
            tables = elem.find_all("table", class_="sdl-syntax-table")

            for table in tables:
                heading = None

                # Walk up and back to find the heading
                current = table
                while current:
                    # Check previous siblings
                    prev = current.previous_sibling
                    while prev:
                        if hasattr(prev, "name") and prev.name in ["h3", "h4"]:
                            heading = prev
                            break
                        prev = prev.previous_sibling

                    if heading:
                        break

                    # Move up to parent
                    current = current.parent
                    if not current or current.name in ["html", "body"]:
                        break

                if heading and heading.get("id", "").endswith("_syntax"):
                    syntax_id = heading.get("id")
                    semantics_id = syntax_id.replace("_syntax", "_semantics")

                    if semantics_id in semantics_map:
                        # Add the semantics as a data attribute
                        semantics_text = semantics_map[semantics_id]
                        table["data-semantics"] = semantics_text
                        attached_count += 1
                        logging.debug(f"Attached semantics to {syntax_id}")

    logging.info(f"Attached semantics to {attached_count} syntax tables")


def generate_syntax_browser(
    input_html_path: Path, output_html_path: Path, spec_name: str = "Specification"
) -> None:
    """
    Generate the simplified syntax browser.

    Reads the full compiled spec HTML, extracts sections 5 (syntax) and
    6 (semantics), attaches semantics text to syntax tables as data
    attributes, and writes a self-contained two-pane HTML page.

    Args:
        input_html_path: Path to the compiled specification HTML.
        output_html_path: Path for the generated syntax browser HTML.
        spec_name: Human-readable specification name for the page title.
    """
    logging.info(f"Loading HTML from {input_html_path}")

    with open(input_html_path, encoding="utf-8") as f:
        soup = BeautifulSoup(f.read(), "html.parser")

    logging.info("Extracting sections 5 and 6")

    # Extract section 5 (syntax) and section 6 (semantics)
    syntax_content = extract_section(soup, "syntax_structures", "syntax_structures_semantics")
    semantics_content = extract_section(soup, "syntax_structures_semantics", "decoding_process")

    if not syntax_content or not semantics_content:
        logging.error("Failed to extract sections")
        return

    logging.info(
        f"Extracted {len(syntax_content)} syntax elements and {len(semantics_content)} semantics elements"
    )

    # Attach semantics to syntax tables
    attach_semantics_to_syntax_tables(syntax_content, semantics_content)

    # Get head essentials
    head_elements = extract_head_essentials(soup)

    # Extract version info from the compiled spec
    title = f"{spec_name} Syntax Browser"
    date_text = "Working Group Draft"
    version_text = "Unknown"

    # Extract date from time element
    date_elem = soup.find("time", class_="dt-updated")
    if date_elem:
        date_text = f"AOM Working Group Draft, {date_elem.get_text(strip=True)}"

    # Extract version from the metadata dl/dt/dd structure
    # Note: Bikeshed generates malformed HTML where <dd> is inside <dt>
    dt_elements = soup.find_all("dt")
    for dt in dt_elements:
        # Get only the direct text content of dt, not all descendants
        dt_text = "".join(dt.find_all(string=True, recursive=False)).strip()
        logging.debug(f"Checking dt: '{dt_text}'")

        if dt_text == "Version:":
            logging.info(f"Found Version dt: '{dt_text}'")
            # The dd is actually INSIDE the dt (malformed HTML from Bikeshed)
            dd = dt.find("dd")
            if dd:
                # Get only the text and link from this specific dd, not nested elements
                # Extract text directly from dd and its immediate children
                texts = []
                for child in dd.children:
                    if isinstance(child, str):
                        texts.append(child.strip())
                    elif child.name == "a":
                        texts.append(child.get_text(strip=True))
                    elif child.name not in ["dt", "dd"]:  # Skip nested dt/dd
                        texts.append(child.get_text(strip=True))

                version_text = " ".join(texts).strip()
                # Remove "branch: " prefix if present
                version_text = version_text.replace("branch: ", "")
                logging.info(f"Extracted version: '{version_text}'")
                break
            else:
                logging.warning("Found Version dt but no dd inside")

    if version_text == "Unknown":
        logging.warning("Could not extract version from HTML")

    # Create new minimal HTML structure
    logging.info("Building syntax browser HTML")

    html_template = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    {head_content}
    <link rel="stylesheet" href="css/syntax_browser.css">
</head>
<body>
    <!-- Collapsed header tab -->
    <div class="header-tab" id="header-tab">
        <span class="header-tab-text">▼ {title}</span>
        <button type="button" class="search-trigger" id="search-trigger-tab" title="Search (⌘K or /)">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <circle cx="11" cy="11" r="8"></circle>
                <path d="m21 21-4.35-4.35"></path>
            </svg>
        </button>
    </div>

    <!-- Full header -->
    <div class="spec-header" id="spec-header">
        <div class="spec-header-content">
            <img src="images/av2-logo.svg" alt="Logo" class="spec-logo">
            <div class="spec-info">
                <h1>{title}</h1>
                <p class="spec-meta">{date}</p>
                <p class="spec-version"><strong>Version:</strong> {version}</p>
            </div>
            <button type="button" class="search-trigger" id="search-trigger" title="Search (⌘K or /)">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <circle cx="11" cy="11" r="8"></circle>
                    <path d="m21 21-4.35-4.35"></path>
                </svg>
            </button>
            <button type="button" class="header-close" id="header-close" title="Hide header">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M18 6L6 18M6 6l12 12"></path>
                </svg>
            </button>
        </div>
        <div class="warning-banner">
            This is not the official specification. See <a href="index.html">Full Specification</a>
        </div>
    </div>

    <!-- Search Overlay -->
    <div class="search-overlay" id="search-overlay">
        <div class="search-container">
            <div class="search-header">
                <input type="text" class="search-input" id="search-input" placeholder="Search variables..." autocomplete="off">
                <button type="button" class="search-close" id="search-close">✕</button>
            </div>
            <div class="search-results" id="search-results"></div>
        </div>
    </div>

    <div class="sidebyside-container">
        <div class="sidebyside-pane sidebyside-left" id="syntax-pane">
            <div class="pane-header">Section 5: Syntax Structures</div>
            <div class="breadcrumb-container" id="breadcrumb-syntax">
                <span class="breadcrumb-item"></span>
            </div>
            <div class="pane-content" id="syntax-content">
                {syntax_content}
            </div>
        </div>
        <div class="sidebyside-divider" id="divider"></div>
        <div class="sidebyside-pane sidebyside-right" id="semantics-pane">
            <div class="pane-header">Section 6: Semantics</div>
            <div class="breadcrumb-container" id="breadcrumb-semantics">
                <span class="breadcrumb-item"></span>
            </div>
            <div class="pane-content" id="semantics-content">
                {semantics_content}
            </div>
        </div>
    </div>
    <footer class="syntax-browser-footer">
        <p><a href="https://github.com/AOMediaCodec/av2-spec-internal" target="_blank">{version}</a></p>
    </footer>
    <script src="js/syntax_browser.js"></script>
</body>
</html>
"""

    # Convert head elements to HTML
    head_html = "\n".join(str(elem) for elem in head_elements)

    # Convert content to HTML
    syntax_html = "\n".join(str(elem) for elem in syntax_content)
    semantics_html = "\n".join(str(elem) for elem in semantics_content)

    # Fill template
    output_html = html_template.format(
        head_content=head_html,
        title=title,
        date=date_text,
        version=version_text,
        syntax_content=syntax_html,
        semantics_content=semantics_html,
    )

    # Write output
    logging.info(f"Writing output to {output_html_path}")
    with open(output_html_path, "w", encoding="utf-8") as f:
        f.write(output_html)

    logging.info("Syntax browser generated successfully")


def main():
    """Main entry point."""
    if len(sys.argv) < 3:
        logging.error(
            "Usage: python generate_syntax_browser.py <input_html> <output_html> [spec_name]"
        )
        sys.exit(1)

    input_path = Path(sys.argv[1])
    output_path = Path(sys.argv[2])
    spec_name = sys.argv[3] if len(sys.argv) > 3 else "Specification"

    if not input_path.exists():
        logging.error(f"Input file not found: {input_path}")
        sys.exit(1)

    generate_syntax_browser(input_path, output_path, spec_name)
    logging.info("Done!")


if __name__ == "__main__":
    main()
