"""
HTML Splitting Module for Multipage Specification Generation.

Splits a single-page Bikeshed-generated HTML specification into multiple pages
(one per h2 "heading settled" section) and builds an anchor-to-filename map so
that internal links can be rewritten to point across pages.

Typical usage (called from compile_multipage.py):

    sections = split_html_to_pages(html_path, output_dir, args)

The returned *sections* list carries metadata (title, anchor, filename,
subsection tree, etc.) consumed by downstream navigation generators.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from bs4 import BeautifulSoup, Tag

# ---------------------------------------------------------------------------
# Bikeshed CSS class selectors used to identify heading elements
# ---------------------------------------------------------------------------
# Bikeshed marks every auto-numbered heading with both of these classes.
HEADING_CLASS = "heading"
SETTLED_CLASS = "settled"

# Heading IDs that belong to the TOC itself and should be skipped when
# enumerating content sections.
TOC_ANCHOR_IDS = {"contents", "toc"}

# Slugification patterns
_RE_NON_SLUG_CHARS = re.compile(r"[^\w\s\-:]")  # chars to strip
_RE_SLUG_SEPARATORS = re.compile(r"[\s:]+")  # whitespace / colons -> hyphens
_RE_MULTI_HYPHENS = re.compile(r"-+")  # collapse runs of hyphens


# ===================================================================
# Filename / slug helpers
# ===================================================================


def slugify(text: str) -> str:
    """Convert arbitrary text to a URL-friendly slug.

    Args:
        text: Human-readable string (e.g. a section title).

    Returns:
        Lower-case, hyphen-separated slug.

    Examples:
        >>> slugify("Syntax structures")
        'syntax-structures'
        >>> slugify("Annex A: Profiles and levels")
        'annex-a-profiles-and-levels'
    """
    text = text.lower()
    text = _RE_NON_SLUG_CHARS.sub("", text)
    text = _RE_SLUG_SEPARATORS.sub("-", text)
    text = _RE_MULTI_HYPHENS.sub("-", text)
    return text.strip("-")


def generate_section_filename(section_title: str, section_anchor: str | None = None) -> str:
    """Build the output filename for a single section page.

    Args:
        section_title: Human-readable section title.
        section_anchor: Bikeshed-assigned ``id`` attribute of the h2.
                        Preferred over *section_title* when available.

    Returns:
        Filename string, e.g. ``"section-syntax-structures.html"``.
    """
    slug = section_anchor if section_anchor else slugify(section_title)
    return f"section-{slug}.html"


# ===================================================================
# Heading metadata extraction helpers
# ===================================================================


def _is_settled_heading(element: Tag) -> bool:
    """Return True if *element* is a Bikeshed "heading settled" element."""
    classes = element.get("class", [])
    return HEADING_CLASS in classes and SETTLED_CLASS in classes


def _extract_heading_metadata(heading: Tag) -> dict[str, str]:
    """Pull title, anchor ID, and section number from a heading element.

    Args:
        heading: A BeautifulSoup ``Tag`` representing an h2/h3/h4 element
                 with Bikeshed's ``heading settled`` classes.

    Returns:
        dict with keys ``'title'``, ``'anchor'``, and ``'number'``
        (any of which may be empty strings).
    """
    content_span = heading.find("span", class_="content")
    title = content_span.get_text(strip=True) if content_span else heading.get_text(strip=True)

    anchor = heading.get("id", "")

    secno_span = heading.find("span", class_="secno")
    number = secno_span.get_text(strip=True) if secno_span else ""

    return {"title": title, "anchor": anchor, "number": number}


def _find_next_settled_heading(
    start: Tag, tag_name: str, boundary: Tag | None = None
) -> Tag | None:
    """Find the next sibling matching *tag_name* with settled-heading classes.

    Stops early if *boundary* (another element) is reached first.

    Args:
        start:     Element whose siblings to search.
        tag_name:  HTML tag name to look for (e.g. ``'h2'``, ``'h3'``).
        boundary:  Optional element that acts as a hard stop.

    Returns:
        The matching ``Tag``, or ``None`` if not found.
    """
    for sibling in start.find_next_siblings():
        if boundary is not None and sibling == boundary:
            return None
        if sibling.name == tag_name and _is_settled_heading(sibling):
            return sibling
    return None


# ===================================================================
# HTML structure parsing
# ===================================================================


def _find_toc_nav(body: Tag) -> Tag | None:
    """Locate the Bikeshed-generated table-of-contents ``<nav>`` element.

    Args:
        body: The ``<body>`` tag of the parsed document.

    Returns:
        The TOC ``<nav>`` element, or ``None`` if not found.
    """
    toc_nav = body.find("nav", id="toc")
    if not toc_nav:
        toc_nav = body.find("nav", class_="toc")
    if toc_nav:
        logging.debug("Found TOC element")
    else:
        logging.warning("TOC element not found - index page may not have full TOC")
    return toc_nav


def _collect_h4_subsections(
    h3_element: Tag, next_h3: Tag | None, next_h2: Tag | None
) -> list[dict]:
    """Collect h4-level sub-subsection metadata beneath an h3.

    Args:
        h3_element: The parent h3 heading.
        next_h3:    The following h3 (upper boundary), or ``None``.
        next_h2:    The following h2 (hard boundary), or ``None``.

    Returns:
        List of dicts with ``'title'``, ``'anchor'``, ``'number'`` keys.
    """
    sub_subsections: list[dict] = []
    for sib in h3_element.find_next_siblings():
        if sib == next_h3 or sib == next_h2:
            break
        if sib.name == "h4" and _is_settled_heading(sib):
            meta = _extract_heading_metadata(sib)
            if meta["anchor"]:
                sub_subsections.append(meta)
    return sub_subsections


def _collect_h3_subsections(h2_element: Tag, next_h2: Tag | None) -> list[dict]:
    """Collect h3-level subsection metadata (with nested h4s) beneath an h2.

    Args:
        h2_element: The parent h2 heading.
        next_h2:    The following h2 (boundary), or ``None``.

    Returns:
        List of subsection dicts, each optionally containing a
        ``'subsections'`` list of h4-level entries.
    """
    subsections: list[dict] = []
    for sibling in h2_element.find_next_siblings():
        if sibling == next_h2:
            break
        if sibling.name == "h3" and _is_settled_heading(sibling):
            meta = _extract_heading_metadata(sibling)
            if not meta["anchor"]:
                continue

            # Determine the next h3 boundary for h4 collection
            next_h3 = _find_next_settled_heading(sibling, "h3", boundary=next_h2)
            meta["subsections"] = _collect_h4_subsections(sibling, next_h3, next_h2)
            subsections.append(meta)
    return subsections


def parse_html_structure(
    html_path: Path,
) -> tuple[BeautifulSoup, list[dict], Tag | None]:
    """Parse a single-page HTML spec and identify all major (h2) sections.

    Each section's metadata includes its title, anchor ID, generated
    filename, section number, and a tree of h3/h4 subsections.

    Args:
        html_path: Path to the Bikeshed-compiled single-page HTML file.

    Returns:
        A 3-tuple of:
        - *soup*: ``BeautifulSoup`` of the full document.
        - *sections*: Ordered list of section-metadata dicts.
        - *toc_nav*: The ``<nav>`` TOC element (or ``None``).
    """
    logging.info(f"Parsing HTML structure from: {html_path}")

    with open(html_path, encoding="utf-8") as f:
        soup = BeautifulSoup(f.read(), "html.parser")

    sections: list[dict] = []

    body = soup.find("body")
    if not body:
        logging.error("No <body> element found in HTML")
        return soup, sections, None

    toc_nav = _find_toc_nav(body)

    # Collect every h2 that Bikeshed has marked as a settled heading.
    h2_elements = [h2 for h2 in body.find_all("h2") if _is_settled_heading(h2)]
    logging.info(f"Found {len(h2_elements)} h2 sections")

    section_count = 0
    for h2 in h2_elements:
        meta = _extract_heading_metadata(h2)

        # Skip headings without an ID (shouldn't happen with Bikeshed output)
        if not meta["anchor"]:
            logging.warning(f"Section '{meta['title']}' has no ID, skipping")
            continue

        # Skip the table-of-contents heading itself
        if meta["anchor"] in TOC_ANCHOR_IDS:
            logging.debug(f"Skipping TOC section: {meta['title']}")
            continue

        # Skip sections excluded from the TOC (abstract, boilerplate, etc.)
        if "no-toc" in h2.get("class", []):
            logging.debug(f"Skipping no-toc section: {meta['title']}")
            continue

        filename = generate_section_filename(meta["title"], meta["anchor"])
        next_h2 = _find_next_settled_heading(h2, "h2")
        subsections = _collect_h3_subsections(h2, next_h2)

        section_info = {
            "index": section_count,
            "title": meta["title"],
            "anchor": meta["anchor"],
            "filename": filename,
            "section_element": h2,
            "section_number": meta["number"],
            "subsections": subsections,
        }

        sections.append(section_info)
        section_count += 1
        logging.debug(
            f"Section {section_count}: '{meta['title']}' -> {filename} "
            f"(#{meta['anchor']}) with {len(subsections)} subsections"
        )

    logging.info(f"Identified {len(sections)} sections to split")
    return soup, sections, toc_nav


# ===================================================================
# Anchor map construction (for cross-page link rewriting)
# ===================================================================


def _collect_ids_in_range(start: Tag, boundary: Tag | None) -> list[str]:
    """Return every ``id`` attribute found between *start* and *boundary*.

    Walks the siblings of *start* (exclusive) and all their descendants,
    collecting every element that carries an ``id``.

    Args:
        start:    Element whose following siblings to scan.
        boundary: Stop element (exclusive), or ``None`` for end-of-parent.

    Returns:
        List of ``id`` strings (duplicates possible if the source HTML
        contains them -- callers typically feed these into a dict so
        last-writer-wins).
    """
    ids: list[str] = []
    for elem in start.find_next_siblings():
        if elem == boundary:
            break
        if elem.get("id"):
            ids.append(elem["id"])
        for nested in elem.find_all(id=True):
            ids.append(nested["id"])
    return ids


def build_anchor_map(soup: BeautifulSoup, sections: list[dict]) -> dict[str, str]:
    """Build a map from every anchor ``id`` to its containing page filename.

    The map is consumed by :func:`rewrite_internal_links` to turn same-page
    ``#anchor`` hrefs into cross-page ``section-foo.html#anchor`` hrefs.

    Args:
        soup:     ``BeautifulSoup`` of the full single-page document.
        sections: Ordered list of section-metadata dicts (as returned by
                  :func:`parse_html_structure`).

    Returns:
        dict mapping ``anchor_id`` to ``section_filename``.
    """
    logging.info("Building anchor map for link rewriting...")

    anchor_map: dict[str, str] = {}

    # Map each section's own h2 anchor first.
    for section in sections:
        anchor_map[section["anchor"]] = section["filename"]

    # Then map every other id-bearing element to the section it lives in.
    for section in sections:
        current_h2 = section["section_element"]
        next_h2 = _find_next_settled_heading(current_h2, "h2")

        for elem_id in _collect_ids_in_range(current_h2, next_h2):
            anchor_map[elem_id] = section["filename"]

    logging.info(f"Built anchor map with {len(anchor_map)} entries")
    logging.debug(f"Sample anchor mappings: {dict(list(anchor_map.items())[:5])}")

    return anchor_map


# ===================================================================
# Section content extraction
# ===================================================================


def _collect_section_body(h2: Tag) -> list[Tag]:
    """Walk siblings after *h2* up to the next settled h2, skipping the TOC.

    Returns only the body elements (not the h2 itself).
    """
    elements: list[Tag] = []
    for sibling in h2.find_next_siblings():
        if sibling.name == "h2" and _is_settled_heading(sibling):
            break
        if sibling.name == "nav" and sibling.get("id") == "toc":
            continue
        elements.append(sibling)
    return elements


def extract_section_content(
    soup: BeautifulSoup, section: dict, next_section: dict | None = None
) -> list[Tag]:
    """Extract every DOM element that belongs to a single section.

    Collects the h2 heading itself plus all following siblings up to (but
    not including) the next settled h2. The Bikeshed TOC ``<nav>`` is
    skipped because multipage output generates its own sidebar.

    Args:
        soup:         ``BeautifulSoup`` of the full document (unused but
                      kept for API symmetry).
        section:      Current section metadata dict.
        next_section: Next section metadata (unused -- boundary is detected
                      dynamically), kept for API compatibility.

    Returns:
        Ordered list of ``Tag`` elements for inclusion in the page.
    """
    h2 = section["section_element"]
    content_elements: list[Tag] = [h2] + _collect_section_body(h2)

    logging.debug(f"Extracted {len(content_elements)} elements for section '{section['title']}'")
    return content_elements


# ===================================================================
# Internal link rewriting
# ===================================================================


def rewrite_internal_links(
    content_elements: list[Tag], anchor_map: dict[str, str], current_section_file: str
) -> None:
    """Rewrite ``#anchor`` hrefs so they point to the correct page file.

    Links whose target lives on the *same* page are left untouched.
    Links targeting a *different* page are rewritten from ``#id`` to
    ``section-foo.html#id``.  Modifies *content_elements* **in-place**.

    Args:
        content_elements:     DOM elements for the current section.
        anchor_map:           Mapping of ``anchor_id`` to ``filename``.
        current_section_file: Filename of the page being built.
    """
    links_rewritten = 0

    for elem in content_elements:
        for link in elem.find_all("a", href=True):
            href = link["href"]

            if not href.startswith("#"):
                continue  # External or relative URL -- leave alone

            anchor_id = href[1:]  # Strip leading '#'
            target_file = anchor_map.get(anchor_id)

            if target_file is None:
                logging.warning(
                    f"Multipage: anchor '#{anchor_id}' not found in anchor map (possible broken link)"
                )
            elif target_file != current_section_file:
                link["href"] = f"{target_file}#{anchor_id}"
                links_rewritten += 1
            # else: same page -- keep the bare #anchor

    if links_rewritten > 0:
        logging.debug(f"Rewrote {links_rewritten} internal links")


# ===================================================================
# Per-section page assembly
# ===================================================================


def _copy_head_element(soup: BeautifulSoup, new_soup: BeautifulSoup, section_title: str) -> Tag:
    """Clone the ``<head>`` from the original document into *new_soup*.

    Handles a Bikeshed quirk where a ``<body>`` tag can appear nested
    inside ``<head>`` -- in that case MathJax scripts are extracted from
    the misplaced body and appended to the new head.

    Also injects ``<link>`` and ``<script>`` tags for the multipage
    navigation CSS/JS assets.

    Args:
        soup:          Original full-document ``BeautifulSoup``.
        new_soup:      The new (empty) document being built.
        section_title: Fallback title text if no ``<head>`` exists.

    Returns:
        The ``<head>`` ``Tag`` that was appended to *new_soup*.
    """
    original_head = soup.find("head")

    if not original_head:
        logging.warning("Original HTML has no <head>, creating minimal head")
        new_head = new_soup.new_tag("head")
        title_tag = new_soup.new_tag("title")
        title_tag.string = section_title
        new_head.append(title_tag)
        return new_head

    new_head = new_soup.new_tag("head")

    # Copy children, but skip any <body> that Bikeshed accidentally nests here
    for child in original_head.children:
        if child.name and child.name != "body":
            new_head.append(child.__copy__())

    # Extract MathJax scripts from the misplaced <body> inside <head>
    misplaced_body = original_head.find("body")
    if misplaced_body:
        mathjax_config = misplaced_body.find("script", string=lambda s: s and "MathJax" in str(s))
        if mathjax_config:
            new_head.append(mathjax_config.__copy__())

        mathjax_script = misplaced_body.find("script", id="MathJax-script")
        if mathjax_script:
            new_head.append(mathjax_script.__copy__())

    # Inject multipage-specific assets
    css_link = new_soup.new_tag("link", rel="stylesheet", href="css/multipage-navigation.css")
    new_head.append(css_link)

    search_css_link = new_soup.new_tag("link", rel="stylesheet", href="css/multipage-search.css")
    new_head.append(search_css_link)

    js_script = new_soup.new_tag("script", src="js/multipage-navigation.js")
    new_head.append(js_script)

    search_index_script = new_soup.new_tag("script", src="search-index.js")
    new_head.append(search_index_script)

    search_script = new_soup.new_tag("script", src="js/multipage-search.js")
    new_head.append(search_script)

    return new_head


def _build_page_body(new_soup: BeautifulSoup, content_elements: list[Tag]) -> Tag:
    """Construct the ``<body>`` skeleton for a section page.

    The body contains placeholder elements for the sidebar, dropdown
    selector, breadcrumb, prev/next buttons -- all populated later by
    ``generate_multipage_navigation.py``.

    Args:
        new_soup:         The document being assembled.
        content_elements: DOM elements to place inside ``<main>``.

    Returns:
        The ``<body>`` ``Tag``.
    """
    body = new_soup.new_tag("body")

    # Sidebar placeholder (filled by navigation generator)
    sidebar = new_soup.new_tag("nav", id="multipage-sidebar")
    sidebar.string = "<!-- Navigation sidebar will be inserted here -->"
    body.append(sidebar)

    # Main content wrapper
    content_wrapper = new_soup.new_tag("div", id="multipage-content")
    body.append(content_wrapper)

    # Dropdown selector placeholder (inside content wrapper, above content)
    dropdown = new_soup.new_tag("div", id="multipage-dropdown")
    dropdown.string = "<!-- Dropdown selector will be inserted here -->"
    content_wrapper.append(dropdown)

    # Breadcrumb placeholder
    breadcrumb = new_soup.new_tag("div", id="multipage-breadcrumb")
    breadcrumb.string = "<!-- Breadcrumb will be inserted here -->"
    content_wrapper.append(breadcrumb)

    # Section content
    main = new_soup.new_tag("main")
    for elem in content_elements:
        main.append(elem.__copy__())
    content_wrapper.append(main)

    # Prev/next navigation buttons placeholder
    nav_buttons = new_soup.new_tag("div", id="multipage-nav-buttons")
    nav_buttons.string = "<!-- Prev/Next buttons will be inserted here -->"
    content_wrapper.append(nav_buttons)

    return body


def create_page_html(soup: BeautifulSoup, section: dict, content_elements: list[Tag]) -> str:
    """Assemble a complete HTML document for one section page.

    Clones ``<head>`` from the original single-page output, injects
    multipage CSS/JS references, and wraps the section content in the
    standard multipage body skeleton.

    Args:
        soup:             Original full-document ``BeautifulSoup``.
        section:          Section metadata dict.
        content_elements: Ordered DOM elements for this section.

    Returns:
        Serialised HTML string ready to be written to disk.
    """
    new_soup = BeautifulSoup("<!DOCTYPE html><html></html>", "html.parser")
    html_tag = new_soup.html

    head = _copy_head_element(soup, new_soup, section["title"])
    html_tag.append(head)

    body = _build_page_body(new_soup, content_elements)
    html_tag.append(body)

    return str(new_soup)


# ===================================================================
# Search index generation
# ===================================================================


def _extract_text(elements: list[Tag]) -> str:
    """Extract plain text from a list of DOM elements, collapsing whitespace."""
    parts: list[str] = []
    for elem in elements:
        text = elem.get_text(separator=" ", strip=True)
        if text:
            parts.append(text)
    # Collapse multiple spaces/newlines
    return re.sub(r"\s+", " ", " ".join(parts)).strip()


def generate_search_index(soup: BeautifulSoup, sections: list[dict], output_dir: Path) -> None:
    """Build a JSON search index and write it as a JS file.

    Each entry contains the section title, number, filename, subsection
    titles, and a plain-text extract of the section body (capped at 5000
    characters to keep the index file manageable).

    Args:
        soup:       Full-document BeautifulSoup.
        sections:   Section metadata list (with 'section_element' keys).
        output_dir: Directory where ``search-index.js`` will be written.
    """
    TEXT_CAP = 5000  # max chars of body text per section

    index: list[dict] = []

    for section in sections:
        h2 = section["section_element"]
        body_elements = _collect_section_body(h2)

        text = _extract_text(body_elements)
        if len(text) > TEXT_CAP:
            text = text[:TEXT_CAP].rsplit(" ", 1)[0]

        # Collect subsection titles for boosted search
        sub_titles: list[str] = []
        for sub in section.get("subsections", []):
            sub_titles.append(sub.get("title", ""))
            for subsub in sub.get("subsections", []):
                sub_titles.append(subsub.get("title", ""))

        entry = {
            "title": section["title"],
            "number": section.get("section_number", ""),
            "filename": section["filename"],
            "anchor": section["anchor"],
            "subsectionTitles": " | ".join(sub_titles),
            "text": text,
        }
        index.append(entry)

    # Write as a JS file that assigns to a global variable
    js_content = "window.SEARCH_INDEX = " + json.dumps(index, ensure_ascii=False) + ";\n"
    index_path = output_dir / "search-index.js"
    index_path.write_text(js_content, encoding="utf-8")

    total_size = sum(len(e.get("text", "")) for e in index)
    logging.info(
        f"Generated search index: {len(index)} entries, "
        f"{len(js_content) // 1024}KB "
        f"({total_size // 1024}KB text)"
    )


# ===================================================================
# Top-level orchestrator
# ===================================================================


def split_html_to_pages(html_path: Path, output_dir: Path, args: object) -> list[dict]:
    """Split a single-page HTML specification into one file per h2 section.

    This is the main entry point for the module. It parses the source
    HTML, builds an anchor map, extracts / rewrites / writes each section
    page, and saves the original TOC for downstream index-page generation.

    Args:
        html_path:  Path to the Bikeshed-compiled single-page HTML.
        output_dir: Directory where section HTML files will be written.
        args:       Command-line argument namespace (currently unused but
                    forwarded for future extensibility).

    Returns:
        Ordered list of section-metadata dicts. Each dict is augmented
        with a ``'file_path'`` key pointing to the written output file.

    Raises:
        ValueError: If no splittable sections are found in the HTML.
    """
    logging.info(f"Splitting HTML: {html_path} -> {output_dir}")

    # Step 1: Parse HTML structure
    soup, sections, toc_nav = parse_html_structure(html_path)

    if not sections:
        raise ValueError("No sections found in HTML")

    # Step 2: Build anchor map for link rewriting
    anchor_map = build_anchor_map(soup, sections)

    # Step 3: Process each section
    for i, section in enumerate(sections):
        logging.info(f"Processing section {i + 1}/{len(sections)}: {section['title']}")

        # Get next section for boundary detection
        next_section = sections[i + 1] if i < len(sections) - 1 else None

        # Extract content for this section
        content_elements = extract_section_content(soup, section, next_section)

        # Rewrite internal links
        rewrite_internal_links(content_elements, anchor_map, section["filename"])

        # Create complete HTML page
        page_html = create_page_html(soup, section, content_elements)

        # Write to file
        output_file = output_dir / section["filename"]
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(page_html)

        # Store file path in section metadata
        section["file_path"] = output_file
        logging.debug(f"Wrote: {output_file}")

    # Generate search index for client-side full-text search
    generate_search_index(soup, sections, output_dir)

    # Also save the original TOC for index page generation
    if toc_nav:
        toc_file = output_dir / "_toc_original.html"
        with open(toc_file, "w", encoding="utf-8") as f:
            f.write(str(toc_nav))
        logging.debug("Saved original TOC for index page")

    logging.info(f"Successfully split HTML into {len(sections)} pages")

    return sections
