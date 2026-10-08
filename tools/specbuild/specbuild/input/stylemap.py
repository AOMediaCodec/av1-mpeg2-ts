"""Map Word paragraph styles to Bikeshed element types.

Supports multiple spec flavors:

* ``h265`` — H.265/HEVC and similar ITU/MPEG video coding specs.  Uses
  standard ``Heading N`` styles, ``Formula``/``Equation`` paragraphs, and
  two-column SDL syntax tables.
* ``cmaf`` — ISO publication Word files (CMAF, ISOBMFF, etc.).  Uses
  ``ANNEX``/``a2``-``a6`` heading styles, ``TermNum``/``Term(s)``/
  ``Definition`` for terms, ``Code (-)`` for code/ABNF blocks, and ISO
  publication cover-page skip styles.
* ``auto`` — auto-detect from document content (default).

Unknown styles always fall back to ``"paragraph"`` so content is never
silently dropped.
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Base style map (shared across all flavors)
# ---------------------------------------------------------------------------

STYLE_MAP: dict[str, dict] = {
    # --- Headings ---
    "Heading 1": {"type": "heading", "level": 1},
    "Heading 2": {"type": "heading", "level": 2},
    "Heading 3": {"type": "heading", "level": 3},
    "Heading 4": {"type": "heading", "level": 4},
    "Heading 5": {"type": "heading", "level": 5},
    "Heading 6": {"type": "heading", "level": 6},
    "heading 1": {"type": "heading", "level": 1},
    "heading 2": {"type": "heading", "level": 2},
    "heading 3": {"type": "heading", "level": 3},
    "heading 4": {"type": "heading", "level": 4},
    "heading 5": {"type": "heading", "level": 5},
    "heading 6": {"type": "heading", "level": 6},
    # Annex title — triggers section split like Heading 1; obligation parsed separately
    "ANNEX": {"type": "heading", "level": 1, "is_annex": True},
    "Annex": {"type": "heading", "level": 1, "is_annex": True},
    "annex": {"type": "heading", "level": 1, "is_annex": True},
    # ITU-T H.265 numbered annex styles ("Annex 1" = top-level annex heading)
    "Annex 1": {"type": "heading", "level": 1, "is_annex": True},
    "Annex 2": {"type": "heading", "level": 2},
    "Annex 3": {"type": "heading", "level": 3},
    "Annex 4": {"type": "heading", "level": 4},
    "Annex 5": {"type": "heading", "level": 5},
    "Annex 6": {"type": "heading", "level": 6},
    # Annex sub-heading styles (ITU-T / ISO publication numbering)
    "a2": {"type": "heading", "level": 2},
    "a3": {"type": "heading", "level": 3},
    "a4": {"type": "heading", "level": 4},
    "a5": {"type": "heading", "level": 5},
    "a6": {"type": "heading", "level": 6},
    # ITU-T H.265 body heading styles (3H0–3H4) — used within multi-layer annexes
    # as sub-section headings (NOT top-level; main body uses standard Heading 1)
    "3H0": {"type": "heading", "level": 2},
    "3H1": {"type": "heading", "level": 3},
    "3H2": {"type": "heading", "level": 4},
    "3H3": {"type": "heading", "level": 5},
    "3H4": {"type": "heading", "level": 6},
    # ITU-T annex body paragraphs (NOT headings)
    "3N0": {"type": "paragraph"},
    "3N": {"type": "paragraph"},
    # ITU-T H.265 indented body paragraphs (3D = "Description" at indent levels 0–3)
    "3D0": {"type": "paragraph"},
    "3D1": {"type": "paragraph"},
    "3D2": {"type": "paragraph"},
    "3D3": {"type": "paragraph"},
    # ITU-T H.265 pseudocode/equation blocks at indent levels 0–5
    # (3E = "Example"/"Equation" — multi-line pseudocode and formulas)
    "3E0": {"type": "code"},
    "3E1": {"type": "code"},
    "3E2": {"type": "code"},
    "3E3": {"type": "code"},
    "3E4": {"type": "equation"},
    "3E5": {"type": "equation"},
    # ITU-T H.265 list styles
    "3L1": {"type": "list_item", "list_type": "bullet", "list_depth": 1},
    "3U1": {"type": "list_item", "list_type": "bullet", "list_depth": 1},
    # Equation style variants (tab-indented equation lines)
    "Equation smaller tabs": {"type": "equation"},
    # Annex_NoTitle: bibliography / non-titled annex section
    "Annex_NoTitle": {"type": "paragraph"},
    "Annex_Ref": {"type": "paragraph"},
    # table of figures (LOF entries — skip, not content)
    "table of figures": {"type": "skip"},
    "Pa16": {"type": "paragraph"},
    "enumlev1": {"type": "list_item", "list_type": "bullet", "list_depth": 1},
    # --- Body text ---
    "Body Text": {"type": "paragraph"},
    "Body Text Indent": {"type": "paragraph"},
    "Body Text indent 1": {"type": "paragraph"},
    "Body Text Indent 211": {"type": "paragraph"},
    "Normal": {"type": "paragraph"},
    "Default": {"type": "paragraph"},
    "normal": {"type": "paragraph"},
    # --- Equations ---
    "Formula": {"type": "equation"},
    "Equation": {"type": "equation"},
    "formula": {"type": "equation"},
    # Typo/corrupted variant of "Formula" seen in some ISO publication source docs
    "Formu]": {"type": "equation"},
    # --- Code / verbatim ---
    "Code": {"type": "code"},
    "code": {"type": "code"},
    "Code Block": {"type": "code"},
    "Source Code": {"type": "code"},
    "Code (-)": {"type": "code"},  # ISO publication ABNF/pseudocode blocks
    # --- Examples ---
    "Example": {"type": "example"},
    # --- Terms and definitions ---
    "Term(s)": {"type": "dfn"},
    "Terms": {"type": "dfn"},
    "TermNum": {"type": "dfn_num"},
    "Definition": {"type": "definition"},
    "definition": {"type": "definition"},
    # --- Tables and figures ---
    "Table title": {"type": "table_caption"},
    "Table Title": {"type": "table_caption"},
    "Figure title": {"type": "figure_caption"},
    "Figure Title": {"type": "figure_caption"},
    "Figure Graphic": {"type": "figure_graphic"},
    "figure graphic": {"type": "figure_graphic"},
    # --- Notes ---
    "Note": {"type": "note"},
    "Note indent": {"type": "note"},
    "Note indent 2": {"type": "note"},
    "Note continued": {"type": "note"},
    "note": {"type": "note"},
    # Word comment / review annotation paragraphs — not part of the spec body
    "annotation text": {"type": "skip"},
    # --- Lists (bulleted) ---
    "List Continue": {"type": "list_item", "list_type": "bullet", "list_depth": 1},
    "List Continue 1": {"type": "list_item", "list_type": "bullet", "list_depth": 1},
    "List Continue 1 (-)": {"type": "list_item", "list_type": "bullet", "list_depth": 1},
    "List Continue 2": {"type": "list_item", "list_type": "bullet", "list_depth": 2},
    "List Continue 2 (-)": {"type": "list_item", "list_type": "bullet", "list_depth": 2},
    "List Continue 3": {"type": "list_item", "list_type": "bullet", "list_depth": 3},
    "List Continue 3 (-)": {"type": "list_item", "list_type": "bullet", "list_depth": 3},
    "List Continue 4": {"type": "list_item", "list_type": "bullet", "list_depth": 4},
    "List Continue 5": {"type": "list_item", "list_type": "bullet", "list_depth": 5},
    "List Continue 6": {"type": "list_item", "list_type": "bullet", "list_depth": 6},
    "List Paragraph": {"type": "list_item", "list_type": "bullet", "list_depth": 1},
    "List Bullet": {"type": "list_item", "list_type": "bullet", "list_depth": 1},
    "List Bullet 2": {"type": "list_item", "list_type": "bullet", "list_depth": 2},
    "List Bullet 3": {"type": "list_item", "list_type": "bullet", "list_depth": 3},
    # --- Lists (numbered) ---
    "List Number": {"type": "list_item", "list_type": "ordered", "list_depth": 1},
    "List Number 1": {"type": "list_item", "list_type": "ordered", "list_depth": 1},
    "List Number 2": {"type": "list_item", "list_type": "ordered", "list_depth": 2},
    "List Number 3": {"type": "list_item", "list_type": "ordered", "list_depth": 3},
    "List Number 4": {"type": "list_item", "list_type": "ordered", "list_depth": 4},
    "List Number 5": {"type": "list_item", "list_type": "ordered", "list_depth": 5},
    # --- Bibliography / references ---
    "Biblio Entry": {"type": "biblio"},
    "RefNorm": {"type": "ref_norm"},
    "Bibliography": {"type": "biblio"},
    # --- Front matter ---
    "Foreword Text": {"type": "paragraph"},
    "Foreword Title": {"type": "heading", "level": 1},
    "Intro Title": {"type": "heading", "level": 1},
    "Intro Text": {"type": "paragraph"},
    # --- Skip styles (cover page, ToC, headers/footers) ---
    "zzCover": {"type": "skip"},
    "zzCover large": {"type": "skip"},
    "zzCopyright": {"type": "skip"},
    "zzCopyright address": {"type": "skip"},
    "zzSTDTitle": {"type": "skip"},
    "Cover Title_A1": {"type": "skip"},
    "Cover Title_A2": {"type": "skip"},
    "Cover Title_B": {"type": "skip"},
    "Main Title 1": {"type": "skip"},
    "Main Title 2": {"type": "skip"},
    "Key Title": {"type": "skip"},
    "Key text": {"type": "skip"},
    "Key": {"type": "skip"},
    "TOC Heading": {"type": "skip"},
    "toc 1": {"type": "skip"},
    "toc 2": {"type": "skip"},
    "toc 3": {"type": "skip"},
    "toc 4": {"type": "skip"},
    "header": {"type": "skip"},
    "footer": {"type": "skip"},
    "Header": {"type": "skip"},
    "Footer": {"type": "skip"},
}

# ---------------------------------------------------------------------------
# Flavor-specific overrides
# ---------------------------------------------------------------------------

#: Per-flavor additions / overrides applied on top of the base STYLE_MAP.
FLAVOR_OVERRIDES: dict[str, dict[str, dict]] = {
    # H.265 / HEVC and similar ITU-T / MPEG video coding specs.
    # Standard Heading N + Formula/Equation paragraphs.
    # Cover/front-matter styles are typically absent; if present, skip them.
    "h265": {
        "Foreword Title": {"type": "skip"},
        "Intro Title": {"type": "skip"},
    },
    # ISO publication Word (CMAF, ISOBMFF, etc.).
    # Uses ANNEX/a2-a5 headings, ISO terms/def block, ABNF Code (-) blocks.
    # Foreword and Introduction are part of the content.
    "cmaf": {
        "Foreword Title": {"type": "paragraph"},
        "Intro Title": {"type": "paragraph"},
        "Body Text indent 1": {"type": "paragraph"},
        "Note indent": {"type": "note"},
        "Code (-)": {"type": "code"},
    },
}


# ---------------------------------------------------------------------------
# Flavor detection
# ---------------------------------------------------------------------------

# Styles characteristic of ISO publication Word files
_ISO_PUB_STYLES = frozenset(
    {
        "ANNEX",
        "a2",
        "a3",
        "Code (-)",
        "TermNum",
        "Term(s)",
        "RefNorm",
        "Biblio Entry",
        "zzCover",
        "zzCopyright",
        "Cover Title_A1",
    }
)

# Styles characteristic of H.265-style video coding spec Word files
_H265_STYLES = frozenset({"Formula", "Equation"})


def detect_flavor(doc) -> str:
    """Auto-detect the document flavor by sampling paragraph styles.

    Scans the first 300 paragraphs and scores the document against known
    indicator style sets.

    Returns:
        ``"cmaf"`` for ISO publication docs, ``"h265"`` for video coding
        specs, or ``"h265"`` as a safe default if ambiguous.
    """
    style_names: set[str] = set()
    for para in doc.paragraphs[:300]:
        sn = getattr(getattr(para, "style", None), "name", None)
        if sn:
            style_names.add(sn)

    iso_score = sum(1 for s in _ISO_PUB_STYLES if s in style_names)
    h265_score = sum(1 for s in _H265_STYLES if s in style_names)

    if iso_score >= 2:
        return "cmaf"
    if h265_score >= 1:
        return "h265"
    # Fallback: if we see ANNEX style, assume ISO publication
    if "ANNEX" in style_names or "a2" in style_names:
        return "cmaf"
    return "h265"


# ---------------------------------------------------------------------------
# Style map construction
# ---------------------------------------------------------------------------


def build_style_map(flavor: str) -> dict[str, dict]:
    """Build an effective style map by merging the base map with flavor overrides.

    Args:
        flavor: One of ``"h265"``, ``"cmaf"``, or ``"auto"`` (returns base map).

    Returns:
        Merged style map dict.
    """
    effective = dict(STYLE_MAP)
    overrides = FLAVOR_OVERRIDES.get(flavor, {})
    effective.update(overrides)
    return effective


# ---------------------------------------------------------------------------
# Regex helpers
# ---------------------------------------------------------------------------

_HEADING_RE = re.compile(r"(?i)^heading\s+(\d)$")


# ---------------------------------------------------------------------------
# Classification helpers (operate on an explicit style map)
# ---------------------------------------------------------------------------


def classify_with_map(style_name: str | None, style_map: dict) -> dict:
    """Classify a style name using a provided style map.

    Args:
        style_name: ``paragraph.style.name`` from python-docx.
        style_map:  Style map dict (e.g. from :func:`build_style_map`).

    Returns:
        Dict with at least ``{"type": ...}``.
    """
    if not style_name:
        return {"type": "paragraph"}
    info = style_map.get(style_name)
    if info is not None:
        return info
    m = _HEADING_RE.match(style_name)
    if m:
        return {"type": "heading", "level": int(m.group(1))}
    return {"type": "paragraph"}


def is_heading_in_map(style_name: str | None, style_map: dict) -> bool:
    return classify_with_map(style_name, style_map).get("type") == "heading"


def heading_level_in_map(style_name: str | None, style_map: dict) -> int:
    info = classify_with_map(style_name, style_map)
    if info.get("type") == "heading":
        return info.get("level", 0)
    return 0


def should_skip_in_map(style_name: str | None, style_map: dict) -> bool:
    return classify_with_map(style_name, style_map).get("type") == "skip"


# ---------------------------------------------------------------------------
# Legacy helpers (use base STYLE_MAP — kept for backward compatibility)
# ---------------------------------------------------------------------------


def classify_paragraph(style_name: str | None) -> dict:
    """Classify using the base STYLE_MAP (flavor-agnostic)."""
    return classify_with_map(style_name, STYLE_MAP)


def is_heading(style_name: str | None) -> bool:
    return classify_paragraph(style_name).get("type") == "heading"


def heading_level(style_name: str | None) -> int:
    info = classify_paragraph(style_name)
    if info.get("type") == "heading":
        return info.get("level", 0)
    return 0


def should_skip(style_name: str | None) -> bool:
    return classify_paragraph(style_name).get("type") == "skip"
