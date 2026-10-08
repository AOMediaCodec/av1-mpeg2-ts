#!/usr/bin/env python3

"""
Add collapsible sections to HTML for mobile optimization.

This script:
1. Detects mobile platforms via JavaScript
2. Makes large sections (5, 6, 9) collapsible
3. On mobile: sections start collapsed to reduce initial DOM load
4. On desktop: sections start expanded (normal behavior)
5. Uses progressive disclosure to improve mobile performance

This enables a single build that works well on both mobile and desktop.
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


def add_collapsible_sections(html_path: Path, sections: list[str] | None = None) -> None:
    """
    Add collapsible section functionality to HTML file.

    Args:
        html_path: Path to the HTML file to modify
        sections: List of top-level section numbers to make collapsible.
            Defaults to all h2-level sections (any heading with a numeric
            section number).  Pass an explicit list to restrict to specific
            sections (e.g. ``["5", "6", "9"]``).
    """
    logging.info(f"Adding collapsible sections to {html_path.name}")

    with open(html_path, encoding="utf-8") as f:
        html_content = f.read()

    soup = BeautifulSoup(html_content, "html.parser")

    # When no explicit list is provided, collapse every numbered top-level section.
    collapsible_sections: list[str] | None = sections

    sections_made_collapsible = 0

    # Find all h2 headings that start main sections
    for h2 in soup.find_all("h2"):
        # Get the section number from the heading
        section_num = None

        # Try to extract section number from the heading text
        heading_text = h2.get_text().strip()

        # Pattern: "5. Syntax structures" or "5 Syntax structures"
        if heading_text and heading_text[0].isdigit():
            section_num = heading_text.split(".")[0].split()[0].strip()

            # Security: Validate that section_num contains only digits
            if not section_num.isdigit():
                logging.warning(
                    f"Skipping heading with invalid section number: {heading_text[:50]}"
                )
                continue

        # Check if this is one of our target sections
        if collapsible_sections is not None and section_num not in collapsible_sections:
            continue

        # Find all content between this h2 and the next h2 (same level)
        # We'll wrap this content in a collapsible container
        content_elements = []
        current = h2.next_sibling

        while current:
            # Stop if we hit another h2 (next main section)
            if current.name == "h2":
                break

            # Collect elements (skip NavigableString whitespace-only nodes)
            if hasattr(current, "name"):
                content_elements.append(current)

            current = current.next_sibling

        if not content_elements:
            continue

        # Create collapsible container
        section_id = f"section-{section_num}"

        # Create toggle button
        toggle_button = soup.new_tag(
            "button",
            **{
                "class": "section-toggle",
                "data-section": section_id,
                "aria-expanded": "true",
                "aria-controls": section_id,
            },
        )
        toggle_button.string = f"▼ Show/Hide Section {section_num}"

        # Create collapsible content wrapper
        content_wrapper = soup.new_tag(
            "div",
            **{"class": "section-content", "id": section_id, "data-section-number": section_num},
        )

        # Move all content elements into the wrapper
        for elem in content_elements:
            # Extract returns the element (removing it from its current position)
            extracted = elem.extract()
            content_wrapper.append(extracted)

        # Insert toggle button and wrapper after the h2
        h2.insert_after(content_wrapper)
        h2.insert_after(toggle_button)

        sections_made_collapsible += 1
        logging.info(f"  Made section {section_num} collapsible: {heading_text[:50]}")

    # Add CSS for collapsible sections
    css_content = """
/* Collapsible Sections for Mobile Optimization */

.section-toggle {
    display: none; /* Hidden by default, shown on mobile via JS */
    width: 100%;
    padding: 12px 16px;
    margin: 16px 0 8px 0;
    background: linear-gradient(to bottom, #f8f9fa, #e9ecef);
    border: 1px solid #dee2e6;
    border-radius: 4px;
    font-size: 14px;
    font-weight: 600;
    color: #495057;
    text-align: left;
    cursor: pointer;
    transition: background-color 0.2s, border-color 0.2s;
}

.section-toggle:hover {
    background: linear-gradient(to bottom, #e9ecef, #dee2e6);
    border-color: #adb5bd;
}

.section-toggle:active {
    background: #dee2e6;
}

.section-toggle[aria-expanded="false"] {
    background: linear-gradient(to bottom, #fff, #f8f9fa);
}

/* Content wrapper - visible by default (desktop) */
.section-content {
    display: block;
}

/* Mobile-specific styles */
@media (max-width: 768px) {
    .section-toggle {
        display: block; /* Show toggle buttons on mobile */
    }
}

/* When JavaScript has initialized mobile mode and section is collapsed */
body.mobile-optimized .section-content.collapsed {
    display: none;
}

/* Loading indicator */
.section-loading {
    padding: 20px;
    text-align: center;
    color: #6c757d;
    font-style: italic;
}
"""

    # Find or create style tag
    head = soup.find("head")
    if head:
        style_tag = soup.new_tag("style", id="collapsible-sections-css")
        style_tag.string = css_content
        head.append(style_tag)
        logging.info("  Added CSS for collapsible sections")
    else:
        logging.error("No <head> tag found - cannot add CSS for collapsible sections")
        return

    # Add JavaScript for mobile detection and collapsible functionality
    js_content = """
// Mobile Detection and Collapsible Sections
(function() {
    'use strict';

    // Detect if we're on a mobile device
    function isMobileDevice() {
        // Check multiple indicators
        const userAgent = navigator.userAgent.toLowerCase();
        const isMobileUA = /android|webos|iphone|ipad|ipod|blackberry|iemobile|opera mini/i.test(userAgent);
        const isSmallScreen = window.innerWidth <= 768;
        const isTouchDevice = 'ontouchstart' in window || navigator.maxTouchPoints > 0;

        // Consider it mobile if it matches mobile UA or is a small touch device
        return isMobileUA || (isSmallScreen && isTouchDevice);
    }

    // Initialize collapsible sections
    function initCollapsibleSections() {
        const isMobile = isMobileDevice();

        console.log('[Collapsible Sections] Platform detection:', {
            isMobile: isMobile,
            userAgent: navigator.userAgent.substring(0, 50) + '...',
            screenWidth: window.innerWidth,
            touchDevice: 'ontouchstart' in window
        });

        if (isMobile) {
            // Add mobile class to body for CSS targeting
            document.body.classList.add('mobile-optimized');

            // Collapse large sections on mobile to reduce initial DOM load
            const sections = document.querySelectorAll('.section-content');
            let collapsedCount = 0;

            sections.forEach(function(section) {
                const sectionNum = section.getAttribute('data-section-number');
                // Collapse sections 5, 6, and 9 (the largest ones with SDL tables)
                if (sectionNum === '5' || sectionNum === '6' || sectionNum === '9') {
                    section.classList.add('collapsed');
                    // Update corresponding toggle button
                    // Security: Use querySelector with escaped ID to prevent injection
                    const toggleBtn = document.querySelector('button[data-section="' + CSS.escape(section.id) + '"]');
                    if (toggleBtn) {
                        toggleBtn.setAttribute('aria-expanded', 'false');
                        toggleBtn.textContent = '▶ Show Section ' + sectionNum;
                    }
                    collapsedCount++;
                }
            });

            console.log('[Collapsible Sections] Collapsed ' + collapsedCount + ' sections on mobile');
        } else {
            console.log('[Collapsible Sections] Desktop mode - all sections expanded');
        }

        // Add click handlers to toggle buttons
        const toggleButtons = document.querySelectorAll('.section-toggle');
        toggleButtons.forEach(function(button) {
            button.addEventListener('click', function() {
                const sectionId = this.getAttribute('data-section');
                const section = document.getElementById(sectionId);

                // Safety check: ensure section exists before accessing properties
                if (!section) {
                    console.error('[Collapsible Sections] Section not found:', sectionId);
                    return;
                }

                const sectionNum = section.getAttribute('data-section-number');

                if (section.classList.contains('collapsed')) {
                    // Expand section
                    section.classList.remove('collapsed');
                    this.setAttribute('aria-expanded', 'true');
                    this.textContent = '▼ Hide Section ' + sectionNum;
                    console.log('[Collapsible Sections] Expanded section ' + sectionNum);
                } else {
                    // Collapse section
                    section.classList.add('collapsed');
                    this.setAttribute('aria-expanded', 'false');
                    this.textContent = '▶ Show Section ' + sectionNum;
                    console.log('[Collapsible Sections] Collapsed section ' + sectionNum);

                    // Scroll to the heading for better UX
                    this.scrollIntoView({ behavior: 'smooth', block: 'start' });
                }
            });
        });

        console.log('[Collapsible Sections] Initialization complete');
    }

    // Run after DOM is loaded
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initCollapsibleSections);
    } else {
        // DOM already loaded
        initCollapsibleSections();
    }
})();
"""

    # Add JavaScript before closing body tag
    body = soup.find("body")
    if body:
        script_tag = soup.new_tag("script", id="collapsible-sections-js")
        script_tag.string = js_content
        body.append(script_tag)
        logging.info("  Added JavaScript for mobile detection and collapsible functionality")
    else:
        logging.error("No <body> tag found - cannot add JavaScript for collapsible sections")
        return

    # Write modified HTML back to file
    # Use str(soup) to preserve original formatting and avoid extra whitespace
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(str(soup))

    logging.info(f"Successfully made {sections_made_collapsible} sections collapsible")
    logging.info(f"Modified HTML written to {html_path.name}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        logging.error(f"Usage: {sys.argv[0]} <html_file> [--sections 5,6,9]")
        sys.exit(1)

    html_path = Path(sys.argv[1])

    if not html_path.exists():
        logging.error(f"HTML file not found: {html_path}")
        sys.exit(1)

    # Optional --sections flag: comma-separated list of section numbers
    _sections = None
    if "--sections" in sys.argv:
        idx = sys.argv.index("--sections")
        if idx + 1 < len(sys.argv):
            _sections = sys.argv[idx + 1].split(",")

    add_collapsible_sections(html_path, sections=_sections)

    add_collapsible_sections(html_path)
