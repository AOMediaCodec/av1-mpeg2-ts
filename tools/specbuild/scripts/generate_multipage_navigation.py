"""
Navigation Generation Module for Multipage HTML

This module generates navigation components for multipage HTML:
- Sidebar TOC with current section highlighting
- Breadcrumb trail
- Previous/Next navigation buttons
- Dropdown section selector
- Index page with full TOC
"""

from __future__ import annotations

import logging
from html import escape as html_escape
from pathlib import Path

from bs4 import BeautifulSoup


def generate_sidebar_toc(sections: list[dict], current_section_index: int) -> str:
    """
    Generate sidebar table of contents HTML with collapsible subsections (3 levels).

    Args:
        sections: List of all sections
        current_section_index: Index of the current section

    Returns:
        HTML string for sidebar TOC
    """
    html = ['<div class="multipage-toc-header">']
    html.append('<h2><a href="index.html">Table of Contents</a></h2>')
    html.append("</div>")
    html.append('<ol class="multipage-toc-list">')

    for i, section in enumerate(sections):
        # Mark current section
        current_class = ' class="current-section"' if i == current_section_index else ""

        # Get section number (may be empty for unnumbered sections)
        section_secno = html_escape(section.get("section_number", ""))

        # Create list item
        html.append(f"  <li{current_class}>")

        # Check if section has subsections to determine if we need expand/collapse
        has_subsections = "subsections" in section and section["subsections"]

        if has_subsections:
            # Add collapse/expand button with aria attributes
            subsections_id = f"toc-subsections-{i}"
            html.append(
                f'    <button class="toc-toggle" aria-label="Toggle subsections" aria-expanded="true" aria-controls="{subsections_id}" data-expanded="true">'
            )
            html.append('      <span class="toc-toggle-icon">▼</span>')
            html.append("    </button>")

        html.append(f'    <a href="{section["filename"]}">')
        # Only show number if it exists
        if section_secno:
            html.append(f'      <span class="toc-number">{section_secno}</span>')
        html.append(f'      <span class="toc-title">{html_escape(section["title"])}</span>')
        html.append("    </a>")

        # Add subsections (level 2 - h3) if they exist
        if has_subsections:
            html.append(
                f'    <ol class="multipage-toc-subsections toc-level-2" id="{subsections_id}">'
            )
            for j, subsection in enumerate(section["subsections"]):
                sub_anchor = subsection["anchor"]
                sub_title = html_escape(subsection["title"])
                sub_number = html_escape(subsection.get("number", ""))

                # Check if subsection has sub-subsections
                has_subsubsections = "subsections" in subsection and subsection["subsections"]

                html.append("      <li>")

                if has_subsubsections:
                    subsubsections_id = f"toc-subsubsections-{i}-{j}"
                    html.append(
                        f'        <button class="toc-toggle toc-toggle-level-2" aria-label="Toggle sub-subsections" aria-expanded="false" aria-controls="{subsubsections_id}" data-expanded="false">'
                    )
                    html.append('          <span class="toc-toggle-icon">▶</span>')
                    html.append("        </button>")

                html.append(f'        <a href="{section["filename"]}#{sub_anchor}">')
                # Only show number if it exists
                if sub_number:
                    html.append(f'          <span class="toc-number">{sub_number}</span>')
                html.append(f'          <span class="toc-title">{sub_title}</span>')
                html.append("        </a>")

                # Add sub-subsections (level 3 - h4) if they exist
                if has_subsubsections:
                    html.append(
                        f'        <ol class="multipage-toc-subsubsections toc-level-3" id="{subsubsections_id}" style="display: none;">'
                    )
                    for subsubsection in subsection["subsections"]:
                        h4_anchor = subsubsection["anchor"]
                        h4_title = html_escape(subsubsection["title"])
                        h4_number = html_escape(subsubsection.get("number", ""))

                        html.append("          <li>")
                        html.append(f'            <a href="{section["filename"]}#{h4_anchor}">')
                        # Only show number if it exists
                        if h4_number:
                            html.append(
                                f'              <span class="toc-number">{h4_number}</span>'
                            )
                        html.append(f'              <span class="toc-title">{h4_title}</span>')
                        html.append("            </a>")
                        html.append("          </li>")
                    html.append("        </ol>")

                html.append("      </li>")
            html.append("    </ol>")

        html.append("  </li>")

    html.append("</ol>")

    return "\n".join(html)


def generate_breadcrumb(section: dict, section_number: int) -> str:
    """
    Generate breadcrumb trail HTML.

    Args:
        section: Current section metadata
        section_number: Section number (1-indexed)

    Returns:
        HTML string for breadcrumb
    """
    html = ['<nav class="multipage-breadcrumb" aria-label="Breadcrumb">']
    html.append('  <ol class="breadcrumb-list">')
    html.append('    <li class="breadcrumb-item">')
    html.append('      <a href="index.html">Home</a>')
    html.append("    </li>")
    html.append('    <li class="breadcrumb-separator">›</li>')
    html.append('    <li class="breadcrumb-item breadcrumb-current">')
    html.append(f"      Section {section_number}: {html_escape(section['title'])}")
    html.append("    </li>")
    html.append("  </ol>")
    html.append("</nav>")

    return "\n".join(html)


def generate_prev_next_buttons(sections: list[dict], current_index: int) -> str:
    """
    Generate previous/next navigation buttons HTML.

    Args:
        sections: List of all sections
        current_index: Current section index

    Returns:
        HTML string for navigation buttons
    """
    html = ['<nav class="multipage-nav-buttons" aria-label="Page navigation">']

    # Previous button
    if current_index > 0:
        prev_section = sections[current_index - 1]
        prev_title = html_escape(prev_section["title"])
        html.append(
            f'  <a href="{prev_section["filename"]}" class="nav-btn nav-prev" title="Previous: {prev_title}">'
        )
        html.append('    <span class="nav-arrow">←</span>')
        html.append('    <span class="nav-label">')
        html.append('      <span class="nav-label-text">Previous</span>')
        html.append(f'      <span class="nav-label-title">{prev_title}</span>')
        html.append("    </span>")
        html.append("  </a>")
    else:
        # No previous, show disabled button
        html.append('  <span class="nav-btn nav-prev nav-disabled">')
        html.append('    <span class="nav-arrow">←</span>')
        html.append('    <span class="nav-label">Previous</span>')
        html.append("  </span>")

    # Home/TOC button
    html.append('  <a href="index.html" class="nav-btn nav-home" title="Table of Contents">')
    html.append('    <span class="nav-label">Table of Contents</span>')
    html.append("  </a>")

    # Next button
    if current_index < len(sections) - 1:
        next_section = sections[current_index + 1]
        next_title = html_escape(next_section["title"])
        html.append(
            f'  <a href="{next_section["filename"]}" class="nav-btn nav-next" title="Next: {next_title}">'
        )
        html.append('    <span class="nav-label">')
        html.append('      <span class="nav-label-text">Next</span>')
        html.append(f'      <span class="nav-label-title">{next_title}</span>')
        html.append("    </span>")
        html.append('    <span class="nav-arrow">→</span>')
        html.append("  </a>")
    else:
        # No next, show disabled button
        html.append('  <span class="nav-btn nav-next nav-disabled">')
        html.append('    <span class="nav-label">Next</span>')
        html.append('    <span class="nav-arrow">→</span>')
        html.append("  </span>")

    html.append("</nav>")

    return "\n".join(html)


def generate_dropdown_selector(sections: list[dict], current_index: int) -> str:
    """
    Generate dropdown section selector HTML.

    Formats section labels based on their type:
    - Regular numbered sections: "1. Scope", "2. Terms and definitions", etc.
    - Annex sections: "Annex A: ...", "Annex B: ...", etc. (no "Section" prefix)
    - Unnumbered sections: "Conformance", "Index", "References" (just the title)

    Args:
        sections: List of all sections
        current_index: Current section index

    Returns:
        HTML string for dropdown selector
    """
    html = ['<div class="multipage-dropdown-container">']
    html.append('  <label for="section-selector" class="dropdown-label">Jump to section:</label>')
    html.append('  <select id="section-selector" class="section-selector">')
    html.append('    <option value="index.html">Table of Contents</option>')

    for i, section in enumerate(sections):
        selected = " selected" if i == current_index else ""
        title = html_escape(section["title"])
        section_number = html_escape(section.get("section_number", ""))

        # Determine the label for the dropdown option
        # Case 1: Annex sections (title contains "Annex")
        if "Annex" in title:
            # Extract the Annex letter from the title (e.g., "Annex A: ..." -> "Annex A: ...")
            # The title should already be properly formatted after renumbering
            label = title
        # Case 2: Unnumbered sections (no section_number)
        elif not section_number:
            # Just use the title (e.g., "Conformance", "Index", "References")
            label = title
        # Case 3: Regular numbered sections
        else:
            # Format as "N. Title" (e.g., "1. Scope", "2. Terms and definitions")
            label = f"{section_number} {title}"

        html.append(f'    <option value="{section["filename"]}"{selected}>')
        html.append(f"      {label}")
        html.append("    </option>")

    html.append("  </select>")
    html.append("</div>")

    return "\n".join(html)


def inject_navigation(
    page_path: Path,
    sidebar_html: str,
    breadcrumb_html: str,
    buttons_html: str,
    dropdown_html: str,
    args,
) -> None:
    """
    Inject navigation components into a page HTML file.

    Replaces placeholder comments with actual navigation HTML.

    Args:
        page_path: Path to the HTML file
        sidebar_html: HTML for sidebar TOC
        breadcrumb_html: HTML for breadcrumb
        buttons_html: HTML for prev/next buttons
        dropdown_html: HTML for dropdown selector
        args: Command-line arguments (for no_sidebar, no_breadcrumb flags)
    """
    with open(page_path, encoding="utf-8") as f:
        content = f.read()

    soup = BeautifulSoup(content, "html.parser")

    # Inject sidebar (unless disabled)
    if not args.no_sidebar:
        sidebar_elem = soup.find(id="multipage-sidebar")
        if sidebar_elem:
            sidebar_elem.clear()
            sidebar_elem.append(BeautifulSoup(sidebar_html, "html.parser"))
        else:
            logging.warning(f"No sidebar placeholder found in {page_path}")
    else:
        # Remove sidebar if disabled
        sidebar_elem = soup.find(id="multipage-sidebar")
        if sidebar_elem:
            sidebar_elem.decompose()

    # Inject breadcrumb (unless disabled)
    if not args.no_breadcrumb:
        breadcrumb_elem = soup.find(id="multipage-breadcrumb")
        if breadcrumb_elem:
            breadcrumb_elem.clear()
            breadcrumb_elem.append(BeautifulSoup(breadcrumb_html, "html.parser"))
    else:
        # Remove breadcrumb if disabled
        breadcrumb_elem = soup.find(id="multipage-breadcrumb")
        if breadcrumb_elem:
            breadcrumb_elem.decompose()

    # Inject prev/next buttons
    buttons_elem = soup.find(id="multipage-nav-buttons")
    if buttons_elem:
        buttons_elem.clear()
        buttons_elem.append(BeautifulSoup(buttons_html, "html.parser"))
    else:
        logging.warning(f"No nav buttons placeholder found in {page_path}")

    # Inject dropdown
    dropdown_elem = soup.find(id="multipage-dropdown")
    if dropdown_elem:
        dropdown_elem.clear()
        dropdown_elem.append(BeautifulSoup(dropdown_html, "html.parser"))
    else:
        logging.warning(f"No dropdown placeholder found in {page_path}")

    # Add body class based on sidebar position
    body = soup.find("body")
    if body:
        if args.no_sidebar:
            body["class"] = body.get("class", []) + ["no-sidebar"]
        else:
            sidebar_class = f"sidebar-{args.sidebar_position}"
            body["class"] = body.get("class", []) + [sidebar_class]

    # Write back to file
    with open(page_path, "w", encoding="utf-8") as f:
        f.write(str(soup))


def generate_navigation_for_all_pages(sections: list[dict], output_dir: Path, args) -> None:
    """
    Generate and inject navigation for all section pages.

    Args:
        sections: List of section metadata
        output_dir: Directory containing the HTML files
        args: Command-line arguments
    """
    logging.info("Generating navigation for all pages...")

    for i, section in enumerate(sections):
        logging.debug(f"Adding navigation to: {section['filename']}")

        # Generate navigation components
        sidebar_html = generate_sidebar_toc(sections, i)
        breadcrumb_html = generate_breadcrumb(section, i + 1)
        buttons_html = generate_prev_next_buttons(sections, i)
        dropdown_html = generate_dropdown_selector(sections, i)

        # Inject into page
        inject_navigation(
            section["file_path"], sidebar_html, breadcrumb_html, buttons_html, dropdown_html, args
        )

    logging.info(f"Navigation added to {len(sections)} pages")


def generate_index_page(
    sections: list[dict], output_dir: Path, branch_info: dict, spec_title: str = "Specification"
) -> None:
    """
    Generate index.html page with full table of contents.

    Args:
        sections: List of section metadata
        output_dir: Directory for output
        branch_info: Dictionary with branch_name, sha, date
        spec_title: Specification title for the index page header
    """
    logging.info("Generating index.html page...")

    # Build anchor map for link rewriting
    anchor_map = {}
    for section in sections:
        anchor_map[section["anchor"]] = section["filename"]
        # Also map all subsections (h3)
        if "subsections" in section:
            for subsection in section["subsections"]:
                anchor_map[subsection["anchor"]] = section["filename"]
                # Also map sub-subsections (h4)
                if "subsections" in subsection:
                    for subsubsection in subsection["subsections"]:
                        anchor_map[subsubsection["anchor"]] = section["filename"]

    # Read original TOC if available
    toc_file = output_dir / "_toc_original.html"
    original_toc_html = ""

    if toc_file.exists():
        with open(toc_file, encoding="utf-8") as f:
            toc_soup = BeautifulSoup(f.read(), "html.parser")
            # Rewrite TOC links to point to section files
            for link in toc_soup.find_all("a", href=True):
                href = link["href"]
                if href.startswith("#"):
                    # Find which file this anchor belongs to
                    anchor = href[1:]
                    target_file = anchor_map.get(anchor)
                    if target_file:
                        link["href"] = f"{target_file}#{anchor}"
            original_toc_html = str(toc_soup)

    # If no original TOC, generate one from sections
    if not original_toc_html:
        toc_html_parts = ['<nav id="toc"><h2>Table of Contents</h2><ol class="toc">']
        for i, section in enumerate(sections):
            toc_html_parts.append(
                f'  <li><a href="{section["filename"]}">{section["title"]}</a></li>'
            )
        toc_html_parts.append("</ol></nav>")
        original_toc_html = "\n".join(toc_html_parts)

    # Create index page HTML
    html = ["<!DOCTYPE html>"]
    html.append('<html lang="en">')
    html.append("<head>")
    html.append('  <meta charset="UTF-8">')
    html.append('  <meta name="viewport" content="width=device-width, initial-scale=1.0">')
    html.append(
        f"  <title>{spec_title} - {branch_info['branch_name']}@{branch_info['sha']}</title>"
    )
    html.append('  <link rel="stylesheet" href="css/custom.css">')
    html.append('  <link rel="stylesheet" href="css/multipage-navigation.css">')
    html.append('  <link rel="stylesheet" href="css/multipage-search.css">')
    html.append("  <style>")
    html.append("    body { max-width: 1200px; margin: 0 auto; padding: 20px; }")
    html.append(
        "    .index-header { background: #f8f9fa; padding: 20px; border-radius: 8px; margin-bottom: 30px; }"
    )
    html.append("    .index-title { margin: 0 0 10px 0; color: #333; }")
    html.append("    .index-subtitle { margin: 0; color: #666; font-size: 14px; }")
    html.append(
        "    .index-info { background: #e9ecef; padding: 15px; border-radius: 4px; margin-bottom: 20px; }"
    )
    html.append("    .index-info code { background: white; padding: 2px 6px; border-radius: 3px; }")
    html.append("    #toc { background: white; }")
    html.append("    /* Hide ordered list numbers - section numbers are in .secno spans */")
    html.append("    ol.toc { list-style: none; }")
    html.append("  </style>")
    html.append("</head>")
    html.append("<body>")
    html.append('  <div class="index-header">')
    html.append(f'    <h1 class="index-title">{spec_title}</h1>')
    html.append('    <p class="index-subtitle">Multipage HTML Version</p>')
    html.append("  </div>")
    html.append('  <div class="index-info">')
    html.append(
        f"    <p><strong>Branch:</strong> <code>{branch_info['branch_name']}@{branch_info['sha']}</code></p>"
    )
    html.append(f"    <p><strong>Last commit:</strong> {branch_info['date']}</p>")
    html.append(f"    <p><strong>Total sections:</strong> {len(sections)}</p>")
    html.append("  </div>")
    html.append(
        '  <div id="multipage-sidebar" style="position:relative; width:380px; height:auto; margin:0 0 20px;">'
    )
    html.append("  </div>")
    html.append(original_toc_html)
    html.append('  <hr style="margin: 40px 0;">')
    html.append('  <footer style="text-align: center; color: #666; font-size: 12px;">')
    html.append("    <p>Generated by compile_multipage.py</p>")
    html.append("  </footer>")
    html.append('  <script src="search-index.js"></script>')
    html.append('  <script src="js/multipage-search.js"></script>')
    html.append("</body>")
    html.append("</html>")

    # Write index.html
    index_path = output_dir / "index.html"
    with open(index_path, "w", encoding="utf-8") as f:
        f.write("\n".join(html))

    logging.info(f"Index page created: {index_path}")
