"""Build cross-reference maps from Word bookmarks and field codes.

Word documents use bookmarks and REF field codes for internal
cross-references (section, table, figure, equation references).
This module extracts those relationships and maps them to Bikeshed-style
HTML ``id`` attributes and ``<a href="#...">`` links.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING
from xml.etree import ElementTree as ET

if TYPE_CHECKING:
    from docx.document import Document

from specbuild.input.utils import W_TAG as _W_PREFIX
from specbuild.input.utils import make_html_id as _make_html_id

# ---------------------------------------------------------------------------
# Bookmark extraction
# ---------------------------------------------------------------------------


def extract_bookmarks(doc: Document) -> dict[str, str]:
    """Extract bookmark definitions from Word XML.

    Parses the document body for ``w:bookmarkStart`` elements and returns
    a mapping from bookmark name to the text content near the bookmark
    (used for context when generating Bikeshed IDs).

    Args:
        doc: A python-docx ``Document``.

    Returns:
        Dict mapping bookmark name (e.g. ``"_Ref12345678"``) to the
        nearby text content.
    """
    bookmarks: dict[str, str] = {}

    try:
        root = doc.element.body
    except Exception as exc:
        logging.warning(f"Failed to parse document XML for bookmarks: {exc}")
        return bookmarks

    # Find all bookmarkStart elements
    for elem in root.iter(f"{_W_PREFIX}bookmarkStart"):
        name = elem.get(f"{_W_PREFIX}name", "")
        bm_id = elem.get(f"{_W_PREFIX}id", "")
        if name and not name.startswith("_GoBack"):
            # Try to get nearby text for context
            context = _get_bookmark_context(root, bm_id)
            bookmarks[name] = context

    logging.debug(f"Extracted {len(bookmarks)} bookmarks")
    return bookmarks


def _get_bookmark_context(root: ET.Element, bookmark_id: str) -> str:
    """Get text content near a bookmark for context.

    Looks for the nearest paragraph containing the bookmark and extracts
    its text.
    """
    # Walk through paragraphs looking for one containing a bookmarkStart
    # with this ID
    for para in root.iter(f"{_W_PREFIX}p"):
        for bm in para.iter(f"{_W_PREFIX}bookmarkStart"):
            if bm.get(f"{_W_PREFIX}id") == bookmark_id:
                # Collect all text runs in this paragraph
                texts = []
                for run in para.iter(f"{_W_PREFIX}t"):
                    if run.text:
                        texts.append(run.text)
                return " ".join(texts).strip()
    return ""


# ---------------------------------------------------------------------------
# REF field extraction
# ---------------------------------------------------------------------------

#: Matches REF field instructions: REF _Ref12345678 \h, REF bookmark \* MERGEFORMAT
_REF_FIELD_RE = re.compile(r"REF\s+(\S+)")


def extract_ref_fields(doc: Document) -> list[dict]:
    """Extract REF field codes that reference bookmarks.

    Looks for both ``w:fldSimple`` elements (simple fields) and
    ``w:fldChar`` / ``w:instrText`` sequences (complex fields).

    Args:
        doc: A python-docx ``Document``.

    Returns:
        List of dicts with keys: ``bookmark`` (target name),
        ``display_text`` (visible text), ``paragraph_index`` (position).
    """
    refs: list[dict] = []

    try:
        root = doc.element.body
    except Exception as exc:
        logging.warning(f"Failed to parse document XML for REF fields: {exc}")
        return refs

    # Simple fields: <w:fldSimple w:instr="REF _Ref123 \h">
    for fld in root.iter(f"{_W_PREFIX}fldSimple"):
        instr = fld.get(f"{_W_PREFIX}instr", "")
        m = _REF_FIELD_RE.search(instr)
        if m:
            bookmark_name = m.group(1)
            display = _collect_text(fld)
            refs.append(
                {
                    "bookmark": bookmark_name,
                    "display_text": display,
                }
            )

    # Complex fields: <w:fldChar w:fldCharType="begin"/> ... <w:instrText>REF ...</w:instrText>
    in_field = False
    for elem in root.iter():
        tag = elem.tag
        if tag == f"{_W_PREFIX}fldChar":
            fld_type = elem.get(f"{_W_PREFIX}fldCharType", "")
            if fld_type == "begin":
                in_field = True
            elif fld_type == "end":
                in_field = False
        elif tag == f"{_W_PREFIX}instrText" and in_field:
            instr = elem.text or ""
            m = _REF_FIELD_RE.search(instr)
            if m:
                refs.append(
                    {
                        "bookmark": m.group(1),
                        "display_text": "",
                    }
                )

    logging.debug(f"Extracted {len(refs)} REF fields")
    return refs


def _collect_text(element: ET.Element) -> str:
    """Recursively collect all w:t text from an element."""
    texts = []
    for t in element.iter(f"{_W_PREFIX}t"):
        if t.text:
            texts.append(t.text)
    return " ".join(texts).strip()


# ---------------------------------------------------------------------------
# ID mapping
# ---------------------------------------------------------------------------


def build_id_map(
    bookmarks: dict[str, str],
    sections: list[dict] | None = None,
) -> dict[str, str]:
    """Build a mapping from Word bookmark names to Bikeshed HTML IDs.

    Args:
        bookmarks: Dict from :func:`extract_bookmarks` (name -> context).
        sections:  Optional list of section dicts with ``heading_text`` and
                   ``heading_id`` keys, used to match bookmarks to sections.

    Returns:
        Dict mapping bookmark name -> HTML id string.
    """
    id_map: dict[str, str] = {}
    used_ids: set[str] = set()

    # Build section lookup for matching
    section_lookup: dict[str, str] = {}
    if sections:
        for sec in sections:
            h_text = sec.get("heading_text", "")
            h_id = sec.get("heading_id", "")
            if h_text and h_id:
                section_lookup[h_text.lower().strip()] = h_id

    for bm_name, context in bookmarks.items():
        # Try to match bookmark context to a known section heading
        ctx_lower = context.lower().strip()
        if ctx_lower in section_lookup:
            html_id = section_lookup[ctx_lower]
        else:
            # Generate an ID from the context or bookmark name
            base = context if context else bm_name
            html_id = _make_html_id(base)

        # Ensure uniqueness
        if html_id in used_ids:
            suffix = 2
            while f"{html_id}-{suffix}" in used_ids:
                suffix += 1
            html_id = f"{html_id}-{suffix}"

        used_ids.add(html_id)
        id_map[bm_name] = html_id

    return id_map


# ---------------------------------------------------------------------------
# Reference resolution
# ---------------------------------------------------------------------------

#: Matches Word-style cross-reference text patterns.
_XREF_TEXT_RE = re.compile(
    r"(?:Section|Clause|Table|Figure|Equation|Annex)\s+[\d\.\-A-Za-z]+",
    re.IGNORECASE,
)


def resolve_references(text: str, id_map: dict[str, str]) -> str:
    """Replace Word cross-reference bookmark names with Bikeshed links.

    This is a best-effort replacement: it looks for patterns like
    ``Section 5.1`` and wraps them in ``<a href="#id">`` if a matching
    ID is found in the map.

    Args:
        text:   The Bikeshed source text to process.
        id_map: Mapping from bookmark names to HTML IDs.

    Returns:
        Text with cross-references replaced by ``<a>`` links.
    """
    if not id_map:
        return text

    # Build a reverse lookup from context snippets to IDs
    context_to_id: dict[str, str] = {}
    for _bm_name, html_id in id_map.items():
        # The html_id itself is derived from the context
        context_to_id[html_id] = html_id

    def _replace_xref(m: re.Match) -> str:
        ref_text = m.group(0)
        candidate_id = _make_html_id(ref_text)
        # Check if we have a matching ID
        for _ctx, html_id in context_to_id.items():
            if candidate_id == html_id or html_id.startswith(candidate_id):
                return f'<a href="#{html_id}">{ref_text}</a>'
        return ref_text

    return _XREF_TEXT_RE.sub(_replace_xref, text)


# ---------------------------------------------------------------------------
# Text-pattern cross-reference resolution (post-conversion)
# ---------------------------------------------------------------------------

_CLAUSE_REF_RE = re.compile(r"\b(?:Clause|Subclause|clause|subclause)\s+(\d+(?:\.\d+)*)")
_TABLE_REF_RE = re.compile(r"\bTable\s+([A-I][\-\.]?\d+(?:[\-\.]\d+)*|\d+[\-\.]\d+(?:[\-\.]\d+)*)")
_FIGURE_REF_RE = re.compile(r"\bFigure\s+([A-I][\-\.]?\d+(?:[\-\.]\d+)*|\d+(?:[\-\.]\d+)*)")
_ANNEX_REF_RE = re.compile(r"\bAnnex\s+([A-I])\b")
_EQ_REF_RE = re.compile(r"\bEquation\s+\(?(\d+[\-\.]\d+)\)?")
_SECTION_NUM_RE = re.compile(r"\b(\d+\.\d+(?:\.\d+)+)\b")


def build_content_id_map(sections: list[dict]) -> dict[str, str]:
    """Build a cross-reference map from generated section data.

    Scans heading text, table captions, and figure captions to produce
    a mapping from reference patterns (e.g., ``"7.3.2"``, ``"Table 7-1"``,
    ``"Figure 8-3"``, ``"Annex A"``) to the HTML IDs assigned during
    conversion.

    Args:
        sections: Section dicts from :func:`_split_into_sections`, each
            with ``heading_text``, ``heading_id``, ``elements``.

    Returns:
        Dict mapping reference key -> HTML id.
    """
    id_map: dict[str, str] = {}

    for section in sections:
        heading = section.get("heading_text", "")
        heading_id = section.get("heading_id", "")
        annex_letter = section.get("annex_letter", "")

        if annex_letter and heading_id:
            id_map[f"annex-{annex_letter}"] = heading_id

        clause_m = re.match(r"^(\d+(?:\.\d+)*)\s+", heading)
        if clause_m and heading_id:
            id_map[f"clause-{clause_m.group(1)}"] = heading_id

        for _elem_type, elem in section.get("elements", []):
            if not hasattr(elem, "style"):
                continue
            style_name = getattr(getattr(elem, "style", None), "name", None)
            text = getattr(elem, "text", "").strip()

            if style_name in (
                "Heading 2",
                "Heading 3",
                "Heading 4",
                "Heading 5",
                "Heading 6",
                "a2",
                "a3",
                "a4",
                "a5",
                "a6",
            ):
                sub_m = re.match(r"^([A-Z]?\.\d+(?:\.\d+)*|\d+(?:\.\d+)+)\s+", text)
                if sub_m:
                    sub_id = _make_html_id(text)
                    id_map[f"clause-{sub_m.group(1)}"] = sub_id

            if style_name == "Table title":
                table_m = re.match(
                    r"Table\s+([A-I]?[\-\.]?\d+[\-\.]\d+(?:[\-\.]\d+)*)",
                    text,
                )
                if table_m:
                    table_num = table_m.group(1)
                    table_id = _make_html_id(f"table-{table_num}")
                    id_map[f"table-{table_num}"] = table_id

            if style_name == "Figure title":
                fig_m = re.match(
                    r"Figure\s+([A-I]?[\-\.]?\d+[\-\.]\d+(?:[\-\.]\d+)*)",
                    text,
                )
                if fig_m:
                    fig_num = fig_m.group(1)
                    fig_id = _make_html_id(f"figure-{fig_num}")
                    id_map[f"figure-{fig_num}"] = fig_id

    logging.info(f"Built content ID map: {len(id_map)} reference targets")
    return id_map


def resolve_text_references(
    content: str,
    id_map: dict[str, str],
) -> tuple[str, int]:
    """Replace text-pattern cross-references with HTML links.

    Scans for patterns like ``Clause 7.3.2``, ``Table 7-1``,
    ``Figure 8-3``, ``Annex A``, and replaces with
    ``<a href="#id">original text</a>`` when a matching target exists.

    Args:
        content: Bikeshed ``.bs`` source text.
        id_map: Mapping from :func:`build_content_id_map`.

    Returns:
        Tuple of (modified content, number of references resolved).
    """
    resolved = 0

    def _replace(pattern: re.Pattern, key_prefix: str, content: str) -> tuple[str, int]:
        count = 0

        def _sub(m: re.Match) -> str:
            nonlocal count
            ref_num = m.group(1)
            key = f"{key_prefix}-{ref_num}"
            target_id = id_map.get(key)
            if target_id:
                count += 1
                return f'<a href="#{target_id}">{m.group(0)}</a>'
            return m.group(0)

        result = pattern.sub(_sub, content)
        return result, count

    content, n = _replace(_CLAUSE_REF_RE, "clause", content)
    resolved += n

    content, n = _replace(_TABLE_REF_RE, "table", content)
    resolved += n

    content, n = _replace(_FIGURE_REF_RE, "figure", content)
    resolved += n

    content, n = _replace(_EQ_REF_RE, "equation", content)
    resolved += n

    def _replace_annex(m: re.Match) -> str:
        nonlocal resolved
        letter = m.group(1)
        key = f"annex-{letter}"
        target_id = id_map.get(key)
        if target_id:
            resolved += 1
            return f'<a href="#{target_id}">{m.group(0)}</a>'
        return m.group(0)

    content = _ANNEX_REF_RE.sub(_replace_annex, content)

    return content, resolved
