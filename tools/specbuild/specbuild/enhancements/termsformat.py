"""Terms and definitions section formatting per ISO 10241.

Formats the Terms and definitions section with sequential numbering,
structured term entries (preferred term, definition, notes, examples),
and cross-references between terms.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from specbuild.utils import HEADING_RE

if TYPE_CHECKING:
    from bs4 import BeautifulSoup, Tag


def _extract_term_metadata(dt_el: Tag, dd_el: Tag | None) -> dict:
    """Extract ISO 10241 metadata from a dt/dd pair.

    Returns a dict with term_type, domain, source, notes, examples.
    """
    meta: dict = {}
    meta["term_type"] = dt_el.get("data-term-type", "preferred")

    domain_span = dt_el.find("span", class_="domain")
    if domain_span is None and dd_el is not None:
        domain_span = dd_el.find("span", class_="domain")
    domain = dt_el.get("data-term-domain", "")
    if not domain and domain_span:
        domain = domain_span.get_text(strip=True)
    meta["domain"] = domain

    source = ""
    if dd_el is not None:
        source_span = dd_el.find("span", class_="term-source")
        source = dd_el.get("data-term-source", "")
        if not source and source_span:
            source = source_span.get_text(strip=True)
    meta["source"] = source

    meta["notes"] = []
    meta["examples"] = []
    if dd_el is not None:
        meta["notes"] = list(dd_el.find_all("p", class_="note-to-entry"))
        meta["examples"] = list(dd_el.find_all("p", class_="example"))

    return meta


def _annotate_term_entry(dt: Tag, dd: Tag | None) -> None:
    """Annotate a dt/dd pair with ISO 10241 metadata classes and attributes."""
    term_type = dt.get("data-term-type", "preferred")
    existing_classes = dt.get("class", [])
    type_class = f"term-{term_type}"
    if type_class not in existing_classes:
        dt["class"] = existing_classes + [type_class]

    domain_span = dt.find("span", class_="domain")
    if domain_span is None and dd is not None:
        domain_span = dd.find("span", class_="domain")
    domain = dt.get("data-term-domain", "")
    if not domain and domain_span:
        domain = domain_span.get_text(strip=True)
    if domain:
        dt["data-term-domain"] = domain

    if dd is not None:
        source_span = dd.find("span", class_="term-source")
        source = dd.get("data-term-source", "")
        if not source and source_span:
            source = source_span.get_text(strip=True)
        if source:
            dd["data-term-source"] = source
        notes = dd.find_all("p", class_="note-to-entry")
        if notes:
            dd["data-notes-count"] = str(len(notes))
        examples = dd.find_all("p", class_="example")
        if examples:
            dd["data-examples-count"] = str(len(examples))


def format_term_types_soup(soup: BeautifulSoup) -> int:
    """Apply admitted/deprecated styling to all <dt> elements with term-type metadata.

    Returns the number of dt elements modified.
    """
    from bs4 import BeautifulSoup as BS
    from bs4 import NavigableString

    count = 0
    for dt in soup.find_all("dt"):
        term_type = dt.get("data-term-type", "")
        if not term_type or term_type == "preferred":
            continue
        existing = dt.get("class", [])
        if term_type == "admitted":
            if "term-admitted" not in existing:
                dt["class"] = existing + ["term-admitted"]
            if not dt.find("span", class_="term-admitted"):
                text = dt.get_text()
                if text.strip():
                    frag = BS(
                        f'<span class="term-admitted">{dt.decode_contents()}</span>',
                        "html.parser",
                    )
                    dt.clear()
                    dt.append(frag)
            count += 1
        elif term_type == "deprecated":
            if "term-deprecated" not in existing:
                dt["class"] = existing + ["term-deprecated"]
            if not dt.get_text(strip=True).startswith("DEPRECATED:"):
                dt.insert(0, NavigableString("DEPRECATED: "))
            count += 1

    if count:
        logging.info(f"Applied term-type styling to {count} term(s)")
    return count


def format_terms_section_soup(soup: BeautifulSoup) -> int:
    """Format Terms and definitions section per ISO 10241.

    Each term gets numbered as 3.1, 3.2, etc. (assuming Terms is clause 3).
    Terms in <dt> elements of <dl> lists get sequential numbering.

    Returns the number of terms formatted.
    """
    terms_heading = _find_terms_heading(soup)
    if terms_heading is None:
        return 0

    section = terms_heading.find_parent("section")
    if section is None:
        return 0

    clause_num = _extract_clause_number(terms_heading)
    if not clause_num:
        clause_num = "3"

    count = 0

    dls = section.find_all("dl", recursive=False)
    for dl in dls:
        count += _number_dl_terms(dl, clause_num, count)

    sub_headings = section.find_all(re.compile(r"^h[3-6]$"))
    if not dls and sub_headings:
        for i, heading in enumerate(sub_headings, 1):
            text = heading.get_text(strip=True)
            num_pattern = re.compile(rf"^{re.escape(clause_num)}\.\d+")
            if not num_pattern.match(text):
                heading_section = heading.find_parent("section")
                if heading_section and heading_section != section:
                    continue
                _add_term_class(heading)
                count += 1

    if count:
        logging.info(f"Formatted {count} term(s) in Terms and definitions")

    return count


def _find_terms_heading(soup: BeautifulSoup):
    """Find the Terms and definitions heading."""
    pattern = re.compile(r"(?i)^(?:\d+\s+)?terms\s+(and|,)\s+definitions$")
    for tag in soup.find_all(HEADING_RE):
        text = tag.get_text(strip=True)
        if pattern.match(text):
            return tag
    return None


def _extract_clause_number(heading) -> str:
    """Extract the clause number from a heading (e.g. '3' from '3 Terms and definitions')."""
    text = heading.get_text(strip=True)
    m = re.match(r"(\d+)", text)
    return m.group(1) if m else ""


def _number_dl_terms(dl, clause_num: str, start_offset: int) -> int:
    """Number <dt> elements within a <dl> as 3.1, 3.2, etc."""
    count = 0
    for dt in dl.find_all("dt", recursive=False):
        count += 1
        term_num = f"{clause_num}.{start_offset + count}"

        existing = dt.get("id", "")
        if not existing:
            term_text = dt.get_text(strip=True)
            safe_id = re.sub(r"[^a-z0-9]+", "-", term_text.lower()).strip("-")
            dt["id"] = f"term-{safe_id}"

        dt["data-term-number"] = term_num

        if "term-entry" not in dt.get("class", []):
            dt["class"] = dt.get("class", []) + ["term-entry"]

        dd = dt.find_next_sibling("dd")
        _annotate_term_entry(dt, dd)

    return count


def _add_term_class(heading) -> None:
    """Add a CSS class to mark a heading as a term entry."""
    classes = heading.get("class", [])
    if "term-heading" not in classes:
        heading["class"] = classes + ["term-heading"]


# ---------------------------------------------------------------------------
# Auto-link term references
# ---------------------------------------------------------------------------

_SKIP_TAGS = re.compile(r"^(a|dfn|h[1-6]|code|pre)$", re.IGNORECASE)
_BODY_TEXT_TAGS = {"p", "li", "td"}


def _collect_defined_terms(soup: BeautifulSoup) -> dict[str, str]:
    """Return {term_text: "#term-<slug>"} from all <dt id="term-*"> elements.

    Also collects text from <dfn> children of those <dt> elements.
    Both singular and common plural forms (append "s", "es") are collected.
    Only terms whose <dt> has an id attribute starting with "term-" are included.
    """
    terms: dict[str, str] = {}

    for dt in soup.find_all("dt"):
        dt_id = dt.get("id", "")
        if not dt_id.startswith("term-"):
            continue
        href = f"#{dt_id}"

        # Collect candidate surface forms: the dt text itself + any dfn children
        candidates: list[str] = []
        dfns = dt.find_all("dfn")
        if dfns:
            for dfn in dfns:
                text = dfn.get_text(strip=True)
                if text:
                    candidates.append(text)
        else:
            text = dt.get_text(strip=True)
            if text:
                candidates.append(text)

        for term in candidates:
            lower = term.lower()
            if lower not in terms:
                terms[lower] = href
            # Add plural forms — only if they don't shadow an existing entry
            plural_s = lower + "s"
            if plural_s not in terms:
                terms[plural_s] = href
            plural_es = lower + "es"
            if plural_es not in terms:
                terms[plural_es] = href

    return terms


def _find_terms_section(soup: BeautifulSoup):
    """Return the <section> containing the Terms and definitions heading, or None."""
    heading = _find_terms_heading(soup)
    if heading is None:
        return None
    return heading.find_parent("section")


def _make_term_pattern(term: str) -> re.Pattern:
    """Build a word-boundary, case-insensitive regex for an exact term match."""
    escaped = re.escape(term)
    return re.compile(rf"\b{escaped}\b", re.IGNORECASE)


def auto_link_term_references_soup(soup: BeautifulSoup) -> int:
    """Scan body text nodes and wrap first-per-section term occurrences in links.

    Only wraps text in <p>, <li>, <td> elements (outside the Terms section).
    Skips text already inside <a>, <dfn>, <h1>-<h6>, <code>, <pre>.

    Returns the total number of links injected.
    """

    terms = _collect_defined_terms(soup)
    if not terms:
        return 0

    terms_section = _find_terms_section(soup)

    # Build sorted list of (term, href, pattern) — longest terms first to avoid
    # partial shadowing (e.g. "coding unit" before "unit").
    term_entries: list[tuple[str, str, re.Pattern]] = [
        (term, href, _make_term_pattern(term))
        for term, href in sorted(terms.items(), key=lambda kv: -len(kv[0]))
    ]

    total = 0

    # Walk all sections in the body; for each section track which terms have
    # already been linked so we only do the first occurrence per section.
    body = soup.find("body") or soup
    sections = body.find_all("section")
    if not sections:
        # Fallback: treat the whole body as one virtual section.
        sections = [body]

    for section in sections:
        # Skip the Terms section itself.
        if terms_section is not None and section is terms_section:
            continue
        # Also skip any section that is a descendant of the terms section.
        if terms_section is not None and terms_section in section.parents:
            continue

        linked_in_section: set[str] = set()
        total += _link_terms_in_section(section, term_entries, linked_in_section, soup)

    if total:
        _inject_term_ref_css(soup)
        logging.info(f"Auto-linked {total} term reference(s)")

    return total


def _ancestor_tag_matches(node, pattern: re.Pattern) -> bool:
    """Return True if any ancestor tag name matches *pattern*."""
    for parent in node.parents:
        if parent.name and pattern.match(parent.name):
            return True
    return False


def _link_terms_in_section(
    section,
    term_entries: list[tuple[str, str, re.Pattern]],
    linked_in_section: set[str],
    soup: BeautifulSoup,
) -> int:
    """Inject links for first occurrence of each term within *section*."""
    from bs4 import NavigableString

    count = 0

    # Collect all candidate text-bearing tags in document order.
    for container in section.find_all(_BODY_TEXT_TAGS):
        # Walk direct NavigableString children only (we must not recurse into
        # already-linked or skip tags).
        for string_node in list(container.strings):
            # The string must not have a skip-tag ancestor.
            if _ancestor_tag_matches(string_node, _SKIP_TAGS):
                continue

            text = str(string_node)

            # Try each term in longest-first order.
            replacements: list[tuple[int, int, str, str]] = []  # (start, end, term, href)
            covered: list[tuple[int, int]] = []

            for term, href, pat in term_entries:
                if term in linked_in_section:
                    continue
                m = pat.search(text)
                if not m:
                    continue
                start, end = m.start(), m.end()
                # Ensure this span doesn't overlap a replacement already found.
                if any(s < end and start < e for s, e in covered):
                    continue
                replacements.append((start, end, term, href))
                covered.append((start, end))

            if not replacements:
                continue

            # Sort replacements by position (left to right) so we can rebuild text.
            replacements.sort(key=lambda r: r[0])

            parent = string_node.parent
            if parent is None:
                continue

            # Build a list of new nodes to replace the single NavigableString.
            new_nodes = []
            cursor = 0
            for start, end, term, href in replacements:
                if start > cursor:
                    new_nodes.append(NavigableString(text[cursor:start]))
                link = soup.new_tag("a", href=href, attrs={"class": "term-ref"})
                link.string = text[start:end]
                new_nodes.append(link)
                linked_in_section.add(term)
                count += 1
                cursor = end
            if cursor < len(text):
                new_nodes.append(NavigableString(text[cursor:]))

            # Replace the original string node with the new nodes.
            string_node.replace_with(new_nodes[0])
            prev = new_nodes[0]
            for node in new_nodes[1:]:
                prev.insert_after(node)
                prev = node

    return count


def _inject_term_ref_css(soup: BeautifulSoup) -> None:
    from specbuild.utils import inject_css

    css = ".term-ref { text-decoration: none; border-bottom: 1px dotted currentColor; }"
    inject_css(soup, "term-ref-styles", css)
