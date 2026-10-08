"""ISO-compliant clause, annex, figure, and table numbering.

Applies numbering conventions specific to the active standards flavor:
- Clause prefix (e.g. "Clause 5" for ISO)
- Letter-based annex numbering with normative/informative labels
- Figure/table renumbering per ISO section.N convention
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from specbuild.utils import HEADING_RE, get_parent_clause_number, prepend_heading_text

if TYPE_CHECKING:
    from bs4 import BeautifulSoup, Tag

    from specbuild.standards.flavors import FlavorSpec

# Pattern to detect annex headings (used to identify annex sections).
_ANNEX_HEADING_RE = re.compile(r"(?i)^(annex|appendix)\s+([A-Z])\b")


def renumber_clauses_soup(soup: BeautifulSoup, flavor: FlavorSpec) -> int:
    """Add clause prefix to section numbers per the flavor's convention.

    Returns the number of headings modified.
    """
    prefix = flavor.numbering.clause_prefix
    if not prefix:
        return 0

    count = 0
    clause_num_re = re.compile(r"^(\d+(?:\.\d+)*)\s+")

    for tag in soup.find_all(HEADING_RE):
        text = tag.get_text(strip=True)
        m = clause_num_re.match(text)
        if not m:
            continue
        if text.lower().startswith("annex"):
            continue
        if text.startswith(prefix):
            continue

        num = m.group(1)
        if "." not in num:
            prepend_heading_text(tag, prefix)
            count += 1

    if count:
        logging.info(f"Added '{prefix.strip()}' prefix to {count} heading(s)")
    return count


def renumber_annexes_soup(soup: BeautifulSoup, flavor: FlavorSpec) -> int:
    """Renumber annexes with letter labels and normative/informative markers.

    Returns the number of annexes modified.
    """
    annex_label = flavor.numbering.annex_label
    norm_label = flavor.numbering.normative_annex_label
    info_label = flavor.numbering.informative_annex_label

    if not annex_label:
        return 0

    annex_pattern = re.compile(r"(?i)^(annex|appendix)\s+([A-Z])\b")
    count = 0

    for tag in soup.find_all(HEADING_RE):
        text = tag.get_text(strip=True)
        m = annex_pattern.match(text)
        if not m:
            continue

        letter = m.group(2)
        has_norm = "(normative)" in text.lower()
        has_info = "(informative)" in text.lower()

        if not has_norm and not has_info and (norm_label or info_label):
            section = tag.find_parent("section")
            obligation = ""
            if section:
                cls = " ".join(section.get("class", []))
                if "normative" in cls:
                    obligation = norm_label
                elif "informative" in cls:
                    obligation = info_label

            if not obligation:
                obligation = info_label

            if obligation:
                remainder = text[m.end() :]
                new_text = f"{annex_label} {letter} {obligation}"
                if remainder:
                    new_text += f" {remainder.lstrip(' .-:')}"
                from bs4 import NavigableString as _NS

                _saved_tags = [c for c in list(tag.children) if getattr(c, "name", None)]
                tag.clear()
                tag.append(_NS(new_text))
                for _ct in _saved_tags:
                    tag.append(_ct)
                count += 1

    if count:
        logging.info(f"Annotated {count} annex(es) with obligation labels")
    return count


def renumber_figures_tables_soup(soup: BeautifulSoup, flavor: FlavorSpec) -> int:
    """Renumber figure and table captions per the flavor's format.

    For ISO: Figure <section>.<n>, Table <section>.<n>
    """
    fig_fmt = flavor.numbering.figure_format
    tbl_fmt = flavor.numbering.table_format

    if "{section}" not in fig_fmt and "{section}" not in tbl_fmt:
        return 0

    count = 0
    count += _renumber_captions(soup, "figure", "Figure", fig_fmt)
    count += _renumber_captions(soup, "table", "Table", tbl_fmt)

    if count:
        logging.info(f"Renumbered {count} figure/table caption(s)")
    return count


def number_figures_soup(
    soup: BeautifulSoup,
    body_format: str = "sequential",
    fmt: str = "{n}",
) -> int:
    """Renumber figure captions with ISO-style numbering.

    body_format="sequential": body figures → Figure 1, 2, …; annexes → Figure A.1, …
    body_format="section": body figures use fmt (default "{section}.{n}")
    """
    if body_format == "section":
        section_fmt = fmt if "{section}" in fmt else "{section}.{n}"
        return _renumber_captions(soup, "figure", "Figure", section_fmt)
    return _renumber_body_annex_captions(soup, "figure", "Figure")


def number_tables_soup(
    soup: BeautifulSoup,
    body_format: str = "sequential",
    fmt: str = "{n}",
) -> int:
    """Renumber table captions with ISO-style numbering.

    body_format="sequential": body tables → Table 1, 2, …; annexes → Table A.1, …
    body_format="section": body tables use fmt (default "{section}.{n}")
    """
    if body_format == "section":
        section_fmt = fmt if "{section}" in fmt else "{section}.{n}"
        return _renumber_captions(soup, "table", "Table", section_fmt)
    return _renumber_body_annex_captions(soup, "table", "Table")


def _renumber_body_annex_captions(
    soup: BeautifulSoup,
    element_type: str,
    label: str,
) -> int:
    """Sequential body captions + per-annex captions (Figure A.1 style)."""
    caption_tag = "figcaption" if element_type == "figure" else "caption"
    caption_pattern = re.compile(rf"^{label}\s+(\w[\w.]*)\b")

    global_counter = 0
    annex_counters: dict[str, int] = {}
    count = 0

    # Collect all <a> tags once so _update_xrefs doesn't re-walk on each caption.
    all_links = soup.find_all("a")

    for cap in soup.find_all(caption_tag):
        text = cap.get_text(strip=True)
        m = caption_pattern.match(text)
        if not m:
            continue

        # Determine annex letter by walking up to the nearest section
        annex_letter = _get_annex_letter(cap)
        old_num = m.group(1)

        if annex_letter:
            annex_counters[annex_letter] = annex_counters.get(annex_letter, 0) + 1
            n = annex_counters[annex_letter]
            new_num = f"{annex_letter}.{n}"
        else:
            global_counter += 1
            new_num = str(global_counter)

        if old_num != new_num:
            _replace_caption_number(cap, old_num, f"{label} {new_num}")
            _update_xrefs(soup, label, old_num, new_num, all_links=all_links)
            count += 1

    return count


def _get_annex_letter(tag: Tag) -> str:
    """Return the annex letter if tag is inside an annex section, else ''."""
    for parent in tag.parents:
        if not hasattr(parent, "name") or parent.name != "section":
            continue
        heading = parent.find(HEADING_RE)
        if heading:
            m = _ANNEX_HEADING_RE.match(heading.get_text(strip=True))
            if m:
                return m.group(2)
    return ""


def _update_xrefs(
    soup: BeautifulSoup,
    label: str,
    old_num: str,
    new_num: str,
    *,
    all_links: list | None = None,
) -> None:
    """Update <a> cross-references that contain the old label+number.

    *all_links* is an optional pre-collected list of ``<a>`` elements; when
    provided the function avoids a repeated ``soup.find_all("a")`` walk.
    """
    old_text = f"{label} {old_num}"
    new_text = f"{label} {new_num}"
    from bs4 import NavigableString

    for a in all_links if all_links is not None else soup.find_all("a"):
        if a.get_text(strip=True) == old_text:
            a.clear()
            a.append(NavigableString(new_text))


def _renumber_captions(
    soup: BeautifulSoup,
    element_type: str,
    label: str,
    fmt: str,
) -> int:
    """Renumber captions for either figures or tables."""
    count = 0
    section_counters: dict[str, int] = {}

    caption_tag = "figcaption" if element_type == "figure" else "caption"
    caption_pattern = re.compile(rf"^{label}\s+(\d+(?:\.\d+)?)\b")

    for cap in soup.find_all(caption_tag):
        text = cap.get_text(strip=True)
        m = caption_pattern.match(text)
        if not m:
            continue

        section_num = _get_parent_section_number(cap)
        if not section_num:
            continue

        section_counters[section_num] = section_counters.get(section_num, 0) + 1
        n = section_counters[section_num]

        new_num = fmt.format(section=section_num, n=n)
        old_num = m.group(1)

        if old_num != new_num:
            _replace_caption_number(cap, old_num, f"{label} {new_num}")
            count += 1

    return count


def _get_parent_section_number(tag: Tag) -> str:
    """Walk up to find the nearest parent section's top-level number."""
    clause = get_parent_clause_number(tag)
    if clause:
        return clause.split(".")[0]
    return ""


def _replace_caption_number(tag: Tag, old_num: str, new_label: str) -> None:
    """Replace the number in a caption element."""
    from bs4 import NavigableString

    for child in list(tag.children):
        if isinstance(child, NavigableString):
            text = str(child)
            figure_pat = f"Figure {old_num}"
            table_pat = f"Table {old_num}"
            if figure_pat in text or table_pat in text:
                new_text = text.replace(figure_pat, new_label).replace(table_pat, new_label)
                child.replace_with(NavigableString(new_text))
                return
        elif hasattr(child, "string") and child.string:
            text = child.string
            figure_pat = f"Figure {old_num}"
            table_pat = f"Table {old_num}"
            if figure_pat in text or table_pat in text:
                child.string = text.replace(figure_pat, new_label).replace(table_pat, new_label)
                return
