"""Template catalog for specification document types.

Each template captures the structural skeleton of a common document type
(JVET contribution, ISO spec draft, AV2 decoder spec, etc.) so that
``--new-from-template`` can scaffold a new project with the right sections,
metadata, and build profile already in place.
"""

from __future__ import annotations

from specbuild.templates import TEMPLATES

# ---------------------------------------------------------------------------
# JVET meeting contribution
# ---------------------------------------------------------------------------

TEMPLATES["jvet-contribution"] = {
    "name": "jvet-contribution",
    "description": "JVET meeting contribution proposing normative or non-normative changes.",
    "flavor": "jvet",
    "doc_type": "contribution",
    "page_size": "a4",
    "sections": [
        {
            "filename": "00_header.bs",
            "title": "Header",
            "mandatory": True,
            "stub_content": (
                "<pre class='metadata'>\n"
                "Title: JVET-xxxx: Title of Contribution\n"
                "Shortname: jvet-contribution\n"
                "Status: LS\n"
                "Editor: Author Name, Affiliation\n"
                "</pre>\n"
            ),
        },
        {
            "filename": "01_scope.bs",
            "title": "Scope",
            "mandatory": True,
            "stub_content": "# Scope # {#scope}\n\nThis contribution proposes ...\n",
        },
        {
            "filename": "02_changes.bs",
            "title": "Proposed Changes",
            "mandatory": True,
            "stub_content": "# Proposed Changes # {#changes}\n\n...\n",
        },
        {
            "filename": "03_references.bs",
            "title": "References",
            "mandatory": False,
            "stub_content": "# References # {#references}\n\n...\n",
        },
    ],
    "metadata_fields": [
        "Title",
        "Author(s)",
        "Affiliation",
        "Meeting",
        "Document number",
    ],
    "suggested_profile": "jvet",
}

# ---------------------------------------------------------------------------
# MPEG specification draft
# ---------------------------------------------------------------------------

TEMPLATES["mpeg-spec-draft"] = {
    "name": "mpeg-spec-draft",
    "description": "Full ISO/IEC MPEG specification draft with standard clause structure.",
    "flavor": "iso",
    "doc_type": "spec-draft",
    "page_size": "a4",
    "sections": [
        {
            "filename": "00_header.bs",
            "title": "Header",
            "mandatory": True,
            "stub_content": (
                "<pre class='metadata'>\n"
                "Title: ISO/IEC xxxxx-x — Title\n"
                "Shortname: mpeg-spec\n"
                "Status: WD\n"
                "Editor: Editor Name, Organization\n"
                "</pre>\n"
            ),
        },
        {
            "filename": "01_scope.bs",
            "title": "Scope",
            "mandatory": True,
            "stub_content": "# Scope # {#scope}\n\nThis document specifies ...\n",
        },
        {
            "filename": "02_normative_refs.bs",
            "title": "Normative references",
            "mandatory": True,
            "stub_content": (
                "# Normative references # {#normative-references}\n\n"
                "The following documents are referred to in the text ...\n"
            ),
        },
        {
            "filename": "03_terms.bs",
            "title": "Terms and definitions",
            "mandatory": True,
            "stub_content": (
                "# Terms and definitions # {#terms-and-definitions}\n\n"
                "For the purposes of this document, the following terms and definitions apply.\n"
            ),
        },
        {
            "filename": "04_conventions.bs",
            "title": "Conventions",
            "mandatory": True,
            "stub_content": "# Conventions # {#conventions}\n\n...\n",
        },
        {
            "filename": "05_overview.bs",
            "title": "Overview",
            "mandatory": False,
            "stub_content": "# Overview # {#overview}\n\n...\n",
        },
        {
            "filename": "06_body.bs",
            "title": "Specification body",
            "mandatory": True,
            "stub_content": "# Specification # {#specification}\n\n...\n",
        },
    ],
    "metadata_fields": [
        "Title",
        "Document number (ISO/IEC xxxxx-x)",
        "Editor(s)",
        "Stage (WD, CD, DIS, FDIS, IS)",
        "Date",
    ],
    "suggested_profile": "iso",
}

# ---------------------------------------------------------------------------
# AV2/AV1 decoder specification
# ---------------------------------------------------------------------------

TEMPLATES["av2-decoder-spec"] = {
    "name": "av2-decoder-spec",
    "description": "AOMedia decoder specification with SDL syntax tables.",
    "flavor": "aom",
    "doc_type": "decoder-spec",
    "page_size": "letter",
    "sections": [
        {
            "filename": "00_header.bs",
            "title": "Header",
            "mandatory": True,
            "stub_content": (
                "<pre class='metadata'>\n"
                "Title: AV2 Bitstream & Decoding Process Specification\n"
                "Shortname: av2-spec\n"
                "Status: LS\n"
                "Editor: Editor Name, Organization\n"
                "</pre>\n"
            ),
        },
        {
            "filename": "01_scope.bs",
            "title": "Scope",
            "mandatory": True,
            "stub_content": "# Scope # {#scope}\n\nThis specification defines ...\n",
        },
        {
            "filename": "02_normative_refs.bs",
            "title": "Normative references",
            "mandatory": True,
            "stub_content": "# Normative references # {#normative-references}\n\n...\n",
        },
        {
            "filename": "03_terms.bs",
            "title": "Terms and definitions",
            "mandatory": True,
            "stub_content": "# Terms and definitions # {#terms-and-definitions}\n\n...\n",
        },
        {
            "filename": "04_conventions.bs",
            "title": "Conventions",
            "mandatory": True,
            "stub_content": "# Conventions # {#conventions}\n\n...\n",
        },
        {
            "filename": "05_symbols.bs",
            "title": "Symbols",
            "mandatory": True,
            "stub_content": "# Symbols # {#symbols}\n\n...\n",
        },
        {
            "filename": "06_decoding_process.bs",
            "title": "Decoding process",
            "mandatory": True,
            "stub_content": (
                "# Decoding process # {#decoding-process}\n\n"
                "## General ## {#general-decoding}\n\n"
                "The decoding process operates as follows ...\n"
            ),
        },
    ],
    "metadata_fields": [
        "Title",
        "Version",
        "Editor(s)",
        "Working Group",
        "Date",
    ],
    "suggested_profile": "aom",
}

# ---------------------------------------------------------------------------
# ISO/IEC amendment document
# ---------------------------------------------------------------------------

TEMPLATES["iso-amendment"] = {
    "name": "iso-amendment",
    "description": "ISO/IEC amendment document for issuing changes to an existing standard.",
    "flavor": "iso",
    "doc_type": "amendment",
    "page_size": "a4",
    "sections": [
        {
            "filename": "00_header.bs",
            "title": "Header",
            "mandatory": True,
            "stub_content": (
                "<pre class='metadata'>\n"
                "Title: ISO/IEC xxxxx-x:20xx/Amd.1 — Title\n"
                "Shortname: iso-amendment\n"
                "Status: WD\n"
                "Editor: Editor Name, Organization\n"
                "</pre>\n"
            ),
        },
        {
            "filename": "01_foreword.bs",
            "title": "Foreword",
            "mandatory": True,
            "stub_content": (
                "# Foreword # {#foreword}\n\nThis amendment modifies ISO/IEC xxxxx-x:20xx by ...\n"
            ),
        },
        {
            "filename": "02_general.bs",
            "title": "General",
            "mandatory": True,
            "stub_content": (
                "# General # {#general}\n\nThe following changes apply to ISO/IEC xxxxx-x:20xx.\n"
            ),
        },
        {
            "filename": "03_clause_changes.bs",
            "title": "Clause changes",
            "mandatory": True,
            "stub_content": (
                "# Clause changes # {#clause-changes}\n\n"
                "## Clause N — Title ## {#clause-n}\n\n"
                "Replace the text of clause N with the following:\n\n...\n"
            ),
        },
        {
            "filename": "04_annex_changes.bs",
            "title": "Annex changes",
            "mandatory": False,
            "stub_content": "# Annex changes # {#annex-changes}\n\n...\n",
        },
    ],
    "metadata_fields": [
        "Base document (ISO/IEC xxxxx-x:20xx)",
        "Amendment number",
        "Editor(s)",
        "Stage (WD, CD, DAM, FDAM, Amd)",
        "Date",
    ],
    "suggested_profile": "iso",
}

# ---------------------------------------------------------------------------
# ITU-T Recommendation
# ---------------------------------------------------------------------------

TEMPLATES["itu-recommendation"] = {
    "name": "itu-recommendation",
    "description": "ITU-T Recommendation document structure.",
    "flavor": "itu-t",
    "doc_type": "recommendation",
    "page_size": "a4",
    "sections": [
        {
            "filename": "00_header.bs",
            "title": "Header",
            "mandatory": True,
            "stub_content": (
                "<pre class='metadata'>\n"
                "Title: Recommendation ITU-T X.xxx — Title\n"
                "Shortname: itu-rec\n"
                "Status: LS\n"
                "Editor: Editor Name, Organization\n"
                "</pre>\n"
            ),
        },
        {
            "filename": "01_summary.bs",
            "title": "Summary",
            "mandatory": True,
            "stub_content": "# Summary # {#summary}\n\nThis Recommendation ...\n",
        },
        {
            "filename": "02_references.bs",
            "title": "References",
            "mandatory": True,
            "stub_content": (
                "# References # {#references}\n\n"
                "## Normative references ## {#normative-references}\n\n...\n\n"
                "## Informative references ## {#informative-references}\n\n...\n"
            ),
        },
        {
            "filename": "03_definitions.bs",
            "title": "Definitions",
            "mandatory": True,
            "stub_content": "# Definitions # {#definitions}\n\n...\n",
        },
        {
            "filename": "04_abbreviations.bs",
            "title": "Abbreviations and acronyms",
            "mandatory": True,
            "stub_content": "# Abbreviations and acronyms # {#abbreviations}\n\n...\n",
        },
        {
            "filename": "05_conventions.bs",
            "title": "Conventions",
            "mandatory": True,
            "stub_content": "# Conventions # {#conventions}\n\n...\n",
        },
        {
            "filename": "06_body.bs",
            "title": "Body",
            "mandatory": True,
            "stub_content": "# Specification # {#specification}\n\n...\n",
        },
    ],
    "metadata_fields": [
        "Recommendation number (ITU-T X.xxx)",
        "Title",
        "Editor(s)",
        "Study Group",
        "Date",
    ],
    "suggested_profile": "itu",
}

# ---------------------------------------------------------------------------
# IEEE Standard
# ---------------------------------------------------------------------------

TEMPLATES["ieee-standard"] = {
    "name": "ieee-standard",
    "description": "IEEE Standard document structure.",
    "flavor": "ieee",
    "doc_type": "standard",
    "page_size": "letter",
    "sections": [
        {
            "filename": "00_header.bs",
            "title": "Header",
            "mandatory": True,
            "stub_content": (
                "<pre class='metadata'>\n"
                "Title: IEEE Std xxxx — Title\n"
                "Shortname: ieee-std\n"
                "Status: LS\n"
                "Editor: Editor Name, Organization\n"
                "</pre>\n"
            ),
        },
        {
            "filename": "01_scope.bs",
            "title": "Scope",
            "mandatory": True,
            "stub_content": "# Scope # {#scope}\n\nThis standard specifies ...\n",
        },
        {
            "filename": "02_normative_refs.bs",
            "title": "Normative references",
            "mandatory": True,
            "stub_content": "# Normative references # {#normative-references}\n\n...\n",
        },
        {
            "filename": "03_definitions.bs",
            "title": "Definitions, acronyms, and abbreviations",
            "mandatory": True,
            "stub_content": (
                "# Definitions, acronyms, and abbreviations # {#definitions}\n\n"
                "## Definitions ## {#term-definitions}\n\n...\n\n"
                "## Acronyms and abbreviations ## {#acronyms}\n\n...\n"
            ),
        },
        {
            "filename": "04_overview.bs",
            "title": "Overview",
            "mandatory": False,
            "stub_content": "# Overview # {#overview}\n\n...\n",
        },
        {
            "filename": "05_body.bs",
            "title": "Standard body",
            "mandatory": True,
            "stub_content": "# Specification # {#specification}\n\n...\n",
        },
    ],
    "metadata_fields": [
        "Standard number (IEEE Std xxxx)",
        "Title",
        "Editor(s)",
        "Working Group",
        "Date",
    ],
    "suggested_profile": "ieee",
}
