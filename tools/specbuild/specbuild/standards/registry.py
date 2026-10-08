"""Pre-built flavor instances for supported standards bodies."""

from __future__ import annotations

from specbuild.standards.flavors import (
    BibliographyRules,
    FlavorSpec,
    MetadataFields,
    NumberingScheme,
    SectionRule,
)

# ---------------------------------------------------------------------------
# ISO (International Organization for Standardization)
# ---------------------------------------------------------------------------

ISO_FLAVOR = FlavorSpec(
    name="iso",
    display_name="ISO/IEC",
    sections=(
        SectionRule(
            name="Foreword",
            mandatory=True,
            order=1,
            heading_pattern=r"(?i)^(?:\d+(?:\.\d+)*\s+)?foreword$",
            boilerplate_key="foreword",
        ),
        SectionRule(
            name="Introduction",
            mandatory=False,
            order=2,
            heading_pattern=r"(?i)^(?:\d+(?:\.\d+)*\s+)?introduction$",
            boilerplate_key="introduction",
        ),
        SectionRule(
            name="Scope",
            mandatory=True,
            order=3,
            heading_pattern=r"(?i)^(?:\d+(?:\.\d+)*\s+)?scope$",
            boilerplate_key="scope",
        ),
        SectionRule(
            name="Normative references",
            mandatory=True,
            order=4,
            heading_pattern=r"(?i)^(?:\d+(?:\.\d+)*\s+)?normative\s+references$",
            boilerplate_key="normative_references",
        ),
        SectionRule(
            name="Terms and definitions",
            mandatory=True,
            order=5,
            heading_pattern=r"(?i)^(?:\d+(?:\.\d+)*\s+)?terms\s+(and|,)\s+definitions$",
            boilerplate_key="terms_and_definitions",
        ),
    ),
    numbering=NumberingScheme(
        clause_prefix="Clause ",
        annex_style="letter",
        annex_label="Annex",
        figure_format="{section}.{n}",
        table_format="{section}.{n}",
        equation_format="({section}.{n})",
        normative_annex_label="(normative)",
        informative_annex_label="(informative)",
    ),
    metadata=MetadataFields(
        required=("docnumber", "edition", "stage"),
        optional=(
            "partnumber",
            "copyright_year",
            "technical_committee",
            "subcommittee",
            "workgroup",
            "secretariat",
            "title_intro",
            "title_main",
            "title_part",
            "language",
        ),
        doc_types=(
            "standard",
            "technical-report",
            "technical-specification",
            "amendment",
            "corrigendum",
            "guide",
        ),
        stages=("WD", "CD", "DIS", "FDIS", "IS"),
    ),
    bibliography=BibliographyRules(
        style="iso690",
        normative_heading="Normative references",
        informative_heading="Bibliography",
        require_classification=True,
    ),
    boilerplate_dir="iso",
    page_size="a4",
    copyright_template=("\u00a9 ISO/IEC ${copyright_year} \u2014 All rights reserved"),
)

# ---------------------------------------------------------------------------
# ITU-T (International Telecommunication Union - Telecommunication)
# ---------------------------------------------------------------------------

ITU_FLAVOR = FlavorSpec(
    name="itu-t",
    display_name="ITU-T",
    sections=(
        SectionRule(
            name="Summary",
            mandatory=True,
            order=1,
            heading_pattern=r"(?i)^(?:\d+(?:\.\d+)*\s+)?summary$",
            boilerplate_key="summary",
        ),
        SectionRule(
            name="Keywords",
            mandatory=False,
            order=2,
            heading_pattern=r"(?i)^(?:\d+(?:\.\d+)*\s+)?keywords$",
        ),
        SectionRule(
            name="References",
            mandatory=True,
            order=3,
            heading_pattern=r"(?i)^(?:\d+(?:\.\d+)*\s+)?references$",
            boilerplate_key="references",
        ),
        SectionRule(
            name="Definitions",
            mandatory=True,
            order=4,
            heading_pattern=r"(?i)^(?:\d+(?:\.\d+)*\s+)?definitions$",
            boilerplate_key="definitions",
        ),
        SectionRule(
            name="Abbreviations and acronyms",
            mandatory=False,
            order=5,
            heading_pattern=r"(?i)^(?:\d+(?:\.\d+)*\s+)?abbreviations\s+(and|&)\s+acronyms$",
        ),
        SectionRule(
            name="Conventions",
            mandatory=False,
            order=6,
            heading_pattern=r"(?i)^(?:\d+(?:\.\d+)*\s+)?conventions$",
        ),
    ),
    numbering=NumberingScheme(
        clause_prefix="",
        annex_style="letter",
        annex_label="Appendix",
        figure_format="{section}-{n}",
        table_format="{section}-{n}",
        equation_format="{section}-{n}",
        normative_annex_label="",
        informative_annex_label="",
    ),
    metadata=MetadataFields(
        required=("docnumber", "series", "study_group"),
        optional=(
            "title_main",
            "approval_date",
            "publication_date",
            "language",
        ),
        doc_types=(
            "recommendation",
            "supplement",
            "amendment",
            "corrigendum",
            "implementers-guide",
        ),
        stages=("draft", "consent", "approved"),
    ),
    bibliography=BibliographyRules(
        style="itu",
        normative_heading="References",
        informative_heading="Bibliography",
        require_classification=False,
    ),
    boilerplate_dir="itu",
    page_size="a4",
    copyright_template="\u00a9 ITU ${copyright_year}",
)

# ---------------------------------------------------------------------------
# IETF (Internet Engineering Task Force)
# ---------------------------------------------------------------------------

IETF_FLAVOR = FlavorSpec(
    name="ietf",
    display_name="IETF",
    sections=(
        SectionRule(
            name="Abstract",
            mandatory=True,
            order=1,
            heading_pattern=r"(?i)^abstract$",
        ),
        SectionRule(
            name="Status of This Memo",
            mandatory=True,
            order=2,
            heading_pattern=r"(?i)^status\s+of\s+this\s+memo$",
            boilerplate_key="status_of_this_memo",
        ),
        SectionRule(
            name="Copyright Notice",
            mandatory=True,
            order=3,
            heading_pattern=r"(?i)^copyright\s+notice$",
            boilerplate_key="copyright_notice",
        ),
        SectionRule(
            name="Table of Contents",
            mandatory=False,
            order=4,
            heading_pattern=r"(?i)^table\s+of\s+contents$",
        ),
        SectionRule(
            name="Introduction",
            mandatory=False,
            order=5,
            heading_pattern=r"(?i)^introduction$",
        ),
    ),
    numbering=NumberingScheme(
        clause_prefix="",
        annex_style="letter",
        annex_label="Appendix",
        figure_format="{n}",
        table_format="{n}",
        equation_format="({n})",
        normative_annex_label="(Normative)",
        informative_annex_label="(Informative)",
    ),
    metadata=MetadataFields(
        required=("docnumber", "category", "workgroup"),
        optional=(
            "intended_status",
            "updates",
            "obsoletes",
            "language",
        ),
        doc_types=(
            "rfc",
            "internet-draft",
            "bcp",
        ),
        stages=("draft", "proposed", "standard"),
    ),
    bibliography=BibliographyRules(
        style="rfc",
        normative_heading="Normative References",
        informative_heading="Informative References",
        require_classification=True,
    ),
    boilerplate_dir="ietf",
    page_size="letter",
    copyright_template="Copyright (c) ${copyright_year} IETF Trust",
)

# ---------------------------------------------------------------------------
# IEC (International Electrotechnical Commission)
# ---------------------------------------------------------------------------

IEC_FLAVOR = FlavorSpec(
    name="iec",
    display_name="IEC",
    sections=ISO_FLAVOR.sections,
    numbering=ISO_FLAVOR.numbering,
    metadata=MetadataFields(
        required=("docnumber", "edition", "stage"),
        optional=(
            "partnumber",
            "copyright_year",
            "technical_committee",
            "subcommittee",
            "workgroup",
            "secretariat",
            "title_intro",
            "title_main",
            "title_part",
            "language",
        ),
        doc_types=(
            "standard",
            "technical-report",
            "technical-specification",
            "guide",
        ),
        stages=("WD", "CD", "CDV", "FDIS", "IS"),
    ),
    bibliography=ISO_FLAVOR.bibliography,
    boilerplate_dir="iec",
    page_size="a4",
    copyright_template="\u00a9 IEC ${copyright_year} \u2014 All rights reserved",
)

# ---------------------------------------------------------------------------
# NIST (US National Institute of Standards & Technology)
# ---------------------------------------------------------------------------

NIST_FLAVOR = FlavorSpec(
    name="nist",
    display_name="NIST",
    sections=(
        SectionRule(name="Abstract", mandatory=True, order=1, heading_pattern=r"(?i)^abstract$"),
        SectionRule(name="Keywords", mandatory=False, order=2, heading_pattern=r"(?i)^keywords$"),
        SectionRule(
            name="Introduction", mandatory=False, order=3, heading_pattern=r"(?i)^introduction$"
        ),
    ),
    numbering=NumberingScheme(
        clause_prefix="",
        annex_style="letter",
        annex_label="Appendix",
        figure_format="{n}",
        table_format="{n}",
        equation_format="({n})",
    ),
    metadata=MetadataFields(
        required=("docnumber", "series"),
        optional=("title_main", "author", "publication_date", "language"),
        doc_types=("special-publication", "internal-report", "technical-note"),
        stages=("draft", "final"),
    ),
    bibliography=BibliographyRules(
        style="nist",
        normative_heading="References",
        informative_heading="Bibliography",
        require_classification=False,
    ),
    boilerplate_dir="nist",
    page_size="letter",
    copyright_template="",
)

# ---------------------------------------------------------------------------
# OGC (Open Geospatial Consortium)
# ---------------------------------------------------------------------------

OGC_FLAVOR = FlavorSpec(
    name="ogc",
    display_name="OGC",
    sections=(
        SectionRule(name="Abstract", mandatory=True, order=1, heading_pattern=r"(?i)^abstract$"),
        SectionRule(name="Keywords", mandatory=True, order=2, heading_pattern=r"(?i)^keywords$"),
        SectionRule(name="Preface", mandatory=False, order=3, heading_pattern=r"(?i)^preface$"),
        SectionRule(name="Scope", mandatory=True, order=4, heading_pattern=r"(?i)^scope$"),
        SectionRule(
            name="Normative references",
            mandatory=True,
            order=5,
            heading_pattern=r"(?i)^normative\s+references$",
        ),
        SectionRule(
            name="Terms and definitions",
            mandatory=True,
            order=6,
            heading_pattern=r"(?i)^terms\s+(and|,)\s+definitions$",
        ),
        SectionRule(
            name="Conventions",
            mandatory=False,
            order=7,
            heading_pattern=r"(?i)^conventions$",
        ),
    ),
    numbering=ISO_FLAVOR.numbering,
    metadata=MetadataFields(
        required=("docnumber", "doc_type"),
        optional=("title_main", "edition", "copyright_year", "language"),
        doc_types=(
            "standard",
            "best-practice",
            "engineering-report",
            "discussion-paper",
            "reference-model",
        ),
        stages=("draft", "candidate", "approved", "deprecated", "retired"),
    ),
    bibliography=BibliographyRules(
        style="iso690",
        normative_heading="Normative references",
        informative_heading="Bibliography",
        require_classification=True,
    ),
    boilerplate_dir="ogc",
    page_size="letter",
    copyright_template="\u00a9 ${copyright_year} Open Geospatial Consortium",
)

# ---------------------------------------------------------------------------
# CC (CalConnect)
# ---------------------------------------------------------------------------

CC_FLAVOR = FlavorSpec(
    name="cc",
    display_name="CalConnect",
    sections=(
        SectionRule(name="Foreword", mandatory=False, order=1, heading_pattern=r"(?i)^foreword$"),
        SectionRule(
            name="Introduction", mandatory=False, order=2, heading_pattern=r"(?i)^introduction$"
        ),
        SectionRule(name="Scope", mandatory=True, order=3, heading_pattern=r"(?i)^scope$"),
        SectionRule(
            name="Normative references",
            mandatory=True,
            order=4,
            heading_pattern=r"(?i)^normative\s+references$",
        ),
        SectionRule(
            name="Terms and definitions",
            mandatory=True,
            order=5,
            heading_pattern=r"(?i)^terms\s+(and|,)\s+definitions$",
        ),
    ),
    numbering=ISO_FLAVOR.numbering,
    metadata=MetadataFields(
        required=("docnumber", "edition"),
        optional=("title_main", "copyright_year", "technical_committee", "language"),
        doc_types=("standard", "guide", "specification", "report", "administrative"),
        stages=("proposal", "working-draft", "committee", "published"),
    ),
    bibliography=ISO_FLAVOR.bibliography,
    boilerplate_dir="cc",
    page_size="letter",
    copyright_template="\u00a9 ${copyright_year} The Calendaring and Scheduling Consortium, Inc.",
)

# ---------------------------------------------------------------------------
# BIPM (Bureau International des Poids et Mesures)
# ---------------------------------------------------------------------------

BIPM_FLAVOR = FlavorSpec(
    name="bipm",
    display_name="BIPM",
    sections=(
        SectionRule(name="Foreword", mandatory=True, order=1, heading_pattern=r"(?i)^foreword$"),
        SectionRule(
            name="Introduction", mandatory=False, order=2, heading_pattern=r"(?i)^introduction$"
        ),
        SectionRule(name="Scope", mandatory=True, order=3, heading_pattern=r"(?i)^scope$"),
        SectionRule(
            name="Terms and definitions",
            mandatory=True,
            order=4,
            heading_pattern=r"(?i)^terms\s+(and|,)\s+definitions$",
        ),
    ),
    numbering=NumberingScheme(
        clause_prefix="",
        annex_style="number",
        annex_label="Appendix",
        figure_format="{n}",
        table_format="{n}",
        equation_format="({n})",
    ),
    metadata=MetadataFields(
        required=("docnumber",),
        optional=("title_main", "edition", "copyright_year", "language"),
        doc_types=("brochure", "rapport", "monographie", "guide"),
        stages=("draft", "published"),
    ),
    bibliography=BibliographyRules(
        style="iso690",
        normative_heading="References",
        informative_heading="Bibliography",
        require_classification=False,
    ),
    boilerplate_dir="bipm",
    page_size="a4",
    copyright_template="\u00a9 BIPM ${copyright_year}",
)

# ---------------------------------------------------------------------------
# BSI (British Standards Institution)
# ---------------------------------------------------------------------------

BSI_FLAVOR = FlavorSpec(
    name="bsi",
    display_name="BSI",
    sections=ISO_FLAVOR.sections,
    numbering=ISO_FLAVOR.numbering,
    metadata=MetadataFields(
        required=("docnumber", "edition", "stage"),
        optional=(
            "partnumber",
            "copyright_year",
            "technical_committee",
            "title_main",
            "title_part",
            "language",
        ),
        doc_types=("standard", "published-document", "pas", "guide"),
        stages=("draft", "public-comment", "published", "withdrawn"),
    ),
    bibliography=ISO_FLAVOR.bibliography,
    boilerplate_dir="bsi",
    page_size="a4",
    copyright_template="\u00a9 BSI ${copyright_year}",
)

# ---------------------------------------------------------------------------
# CEN/CENELEC (European Committee for Standardization)
# ---------------------------------------------------------------------------

CEN_FLAVOR = FlavorSpec(
    name="cen",
    display_name="CEN/CENELEC",
    sections=ISO_FLAVOR.sections,
    numbering=ISO_FLAVOR.numbering,
    metadata=MetadataFields(
        required=("docnumber", "edition", "stage"),
        optional=(
            "partnumber",
            "copyright_year",
            "technical_committee",
            "title_main",
            "title_part",
            "language",
        ),
        doc_types=("standard", "technical-specification", "technical-report", "guide"),
        stages=("WI", "prEN", "FprEN", "EN"),
    ),
    bibliography=ISO_FLAVOR.bibliography,
    boilerplate_dir="cen",
    page_size="a4",
    copyright_template="\u00a9 CEN/CENELEC ${copyright_year}",
)

# ---------------------------------------------------------------------------
# IEEE (Institute of Electrical and Electronics Engineers)
# ---------------------------------------------------------------------------

IEEE_FLAVOR = FlavorSpec(
    name="ieee",
    display_name="IEEE",
    sections=(
        SectionRule(name="Abstract", mandatory=True, order=1, heading_pattern=r"(?i)^abstract$"),
        SectionRule(name="Foreword", mandatory=False, order=2, heading_pattern=r"(?i)^foreword$"),
        SectionRule(
            name="Introduction", mandatory=True, order=3, heading_pattern=r"(?i)^introduction$"
        ),
        SectionRule(
            name="Scope",
            mandatory=True,
            order=4,
            heading_pattern=r"(?i)^scope$",
        ),
        SectionRule(
            name="Normative references",
            mandatory=True,
            order=5,
            heading_pattern=r"(?i)^normative\s+references$",
        ),
        SectionRule(
            name="Definitions, acronyms, and abbreviations",
            mandatory=True,
            order=6,
            heading_pattern=r"(?i)^definitions",
        ),
    ),
    numbering=NumberingScheme(
        clause_prefix="Clause ",
        annex_style="letter",
        annex_label="Annex",
        figure_format="{n}",
        table_format="{n}",
        equation_format="({n})",
        normative_annex_label="(normative)",
        informative_annex_label="(informative)",
    ),
    metadata=MetadataFields(
        required=("docnumber", "doc_type"),
        optional=("title_main", "edition", "copyright_year", "working_group", "language"),
        doc_types=("standard", "recommended-practice", "guide", "trial-use"),
        stages=("draft", "balloting", "published"),
    ),
    bibliography=BibliographyRules(
        style="ieee",
        normative_heading="Normative references",
        informative_heading="Bibliography",
        require_classification=True,
    ),
    boilerplate_dir="ieee",
    page_size="letter",
    copyright_template="Copyright \u00a9 ${copyright_year} IEEE. All rights reserved.",
)

# ---------------------------------------------------------------------------
# JIS (Japanese Industrial Standards)
# ---------------------------------------------------------------------------

JIS_FLAVOR = FlavorSpec(
    name="jis",
    display_name="JIS",
    sections=ISO_FLAVOR.sections,
    numbering=ISO_FLAVOR.numbering,
    metadata=MetadataFields(
        required=("docnumber", "edition"),
        optional=(
            "partnumber",
            "copyright_year",
            "technical_committee",
            "title_main",
            "title_part",
            "language",
        ),
        doc_types=("standard", "technical-report", "handbook"),
        stages=("draft", "published", "revised", "withdrawn"),
    ),
    bibliography=ISO_FLAVOR.bibliography,
    boilerplate_dir="jis",
    page_size="a4",
    copyright_template="\u00a9 JSA ${copyright_year}",
)

# ---------------------------------------------------------------------------
# UNECE (United Nations Economic Commission for Europe)
# ---------------------------------------------------------------------------

UNECE_FLAVOR = FlavorSpec(
    name="unece",
    display_name="UN/ECE",
    sections=(
        SectionRule(name="Foreword", mandatory=False, order=1, heading_pattern=r"(?i)^foreword$"),
        SectionRule(
            name="Introduction", mandatory=True, order=2, heading_pattern=r"(?i)^introduction$"
        ),
        SectionRule(name="Scope", mandatory=True, order=3, heading_pattern=r"(?i)^scope$"),
        SectionRule(
            name="Terms and definitions",
            mandatory=False,
            order=4,
            heading_pattern=r"(?i)^terms\s+(and|,)\s+definitions$",
        ),
    ),
    numbering=NumberingScheme(
        clause_prefix="",
        annex_style="number",
        annex_label="Annex",
        figure_format="{n}",
        table_format="{n}",
        equation_format="({n})",
    ),
    metadata=MetadataFields(
        required=("docnumber",),
        optional=("title_main", "copyright_year", "language"),
        doc_types=("recommendation", "standard", "regulation"),
        stages=("draft", "published"),
    ),
    bibliography=BibliographyRules(
        style="iso690",
        normative_heading="References",
        informative_heading="Bibliography",
        require_classification=False,
    ),
    boilerplate_dir="unece",
    page_size="a4",
    copyright_template="\u00a9 United Nations ${copyright_year}",
)

# ---------------------------------------------------------------------------
# 3GPP (Third Generation Partnership Project)
# ---------------------------------------------------------------------------

THREEGPP_FLAVOR = FlavorSpec(
    name="3gpp",
    display_name="3GPP",
    sections=(
        SectionRule(name="Foreword", mandatory=True, order=1, heading_pattern=r"(?i)^foreword$"),
        SectionRule(
            name="Introduction", mandatory=False, order=2, heading_pattern=r"(?i)^introduction$"
        ),
        SectionRule(name="Scope", mandatory=True, order=3, heading_pattern=r"(?i)^scope$"),
        SectionRule(
            name="References",
            mandatory=True,
            order=4,
            heading_pattern=r"(?i)^references$",
        ),
        SectionRule(
            name="Definitions, symbols and abbreviations",
            mandatory=True,
            order=5,
            heading_pattern=r"(?i)^definitions",
        ),
    ),
    numbering=NumberingScheme(
        clause_prefix="",
        annex_style="letter",
        annex_label="Annex",
        figure_format="{section}.{n}",
        table_format="{section}.{n}",
        equation_format="({section}.{n})",
        normative_annex_label="(normative)",
        informative_annex_label="(informative)",
    ),
    metadata=MetadataFields(
        required=("docnumber", "series", "release"),
        optional=("title_main", "version", "copyright_year", "language"),
        doc_types=("technical-specification", "technical-report"),
        stages=("draft", "under-change-control", "frozen"),
    ),
    bibliography=BibliographyRules(
        style="iso690",
        normative_heading="References",
        informative_heading="Bibliography",
        require_classification=False,
    ),
    boilerplate_dir="3gpp",
    page_size="a4",
    copyright_template="\u00a9 ${copyright_year} 3GPP",
)

# ---------------------------------------------------------------------------
# MPEG/JVET (Joint Video Experts Team)
# ---------------------------------------------------------------------------

JVET_FLAVOR = FlavorSpec(
    name="jvet",
    display_name="JVET",
    sections=(
        SectionRule(name="Scope", mandatory=True, order=1, heading_pattern=r"(?i)^scope$"),
        SectionRule(
            name="Normative references",
            mandatory=True,
            order=2,
            heading_pattern=r"(?i)^(normative\s+)?references$",
        ),
        SectionRule(
            name="Definitions",
            mandatory=True,
            order=3,
            heading_pattern=r"(?i)^definitions$",
        ),
        SectionRule(
            name="Abbreviations",
            mandatory=False,
            order=4,
            heading_pattern=r"(?i)^abbreviations$",
        ),
        SectionRule(
            name="Conventions",
            mandatory=False,
            order=5,
            heading_pattern=r"(?i)^conventions$",
        ),
    ),
    numbering=NumberingScheme(
        clause_prefix="",
        annex_style="letter",
        annex_label="Annex",
        figure_format="{section}-{n}",
        table_format="{section}-{n}",
        equation_format="({section}-{n})",
        normative_annex_label="(normative)",
        informative_annex_label="(informative)",
    ),
    metadata=MetadataFields(
        required=("docnumber",),
        optional=("title_main", "meeting", "source", "copyright_year", "language"),
        doc_types=("contribution", "specification", "test-model"),
        stages=("draft", "published"),
    ),
    bibliography=BibliographyRules(
        style="iso690",
        normative_heading="References",
        informative_heading="Bibliography",
        require_classification=False,
    ),
    boilerplate_dir="jvet",
    page_size="a4",
    copyright_template="",
)

# ---------------------------------------------------------------------------
# Video codec-specific flavors
# ---------------------------------------------------------------------------

ISO_VIDEO_FLAVOR = FlavorSpec(
    name="iso-video",
    display_name="ISO/IEC Video Codec",
    sections=(
        SectionRule(
            name="Foreword",
            mandatory=True,
            order=1,
            heading_pattern=r"(?i)^(?:\d+(?:\.\d+)*\s+)?foreword$",
            boilerplate_key="foreword",
        ),
        SectionRule(
            name="Introduction",
            mandatory=False,
            order=2,
            heading_pattern=r"(?i)^(?:\d+(?:\.\d+)*\s+)?introduction$",
        ),
        SectionRule(
            name="Scope",
            mandatory=True,
            order=3,
            heading_pattern=r"(?i)^(?:\d+(?:\.\d+)*\s+)?scope$",
            boilerplate_key="scope",
        ),
        SectionRule(
            name="Normative references",
            mandatory=True,
            order=4,
            heading_pattern=r"(?i)^(?:\d+(?:\.\d+)*\s+)?normative\s+references$",
            boilerplate_key="normative_references",
        ),
        SectionRule(
            name="Definitions",
            mandatory=True,
            order=5,
            heading_pattern=r"(?i)^(?:\d+(?:\.\d+)*\s+)?definitions?$",
        ),
        SectionRule(
            name="Abbreviations",
            mandatory=False,
            order=6,
            heading_pattern=r"(?i)^(?:\d+(?:\.\d+)*\s+)?abbreviations?$",
        ),
        SectionRule(
            name="Conventions",
            mandatory=False,
            order=7,
            heading_pattern=r"(?i)^(?:\d+(?:\.\d+)*\s+)?conventions$",
        ),
        SectionRule(
            name="Profiles and levels",
            mandatory=False,
            order=90,
            heading_pattern=r"(?i)^(?:\d+(?:\.\d+)*\s+)?profiles?\s+(and|,)\s+levels?$",
        ),
    ),
    numbering=ISO_FLAVOR.numbering,
    metadata=MetadataFields(
        required=("docnumber", "edition", "stage"),
        optional=(
            "partnumber",
            "copyright_year",
            "technical_committee",
            "subcommittee",
            "workgroup",
            "title_intro",
            "title_main",
            "title_part",
            "language",
            "base_document",
            "amendment_number",
        ),
        doc_types=(
            "standard",
            "technical-report",
            "technical-specification",
            "amendment",
            "corrigendum",
        ),
        stages=("WD", "CD", "DIS", "FDIS", "IS"),
    ),
    bibliography=ISO_FLAVOR.bibliography,
    boilerplate_dir="iso",
    page_size="a4",
    copyright_template=("\u00a9 ISO/IEC ${copyright_year} \u2014 All rights reserved"),
)

ITU_VIDEO_FLAVOR = FlavorSpec(
    name="itu-video",
    display_name="ITU-T Video Codec",
    sections=(
        SectionRule(
            name="Summary",
            mandatory=True,
            order=1,
            heading_pattern=r"(?i)^(?:\d+(?:\.\d+)*\s+)?summary$",
            boilerplate_key="summary",
        ),
        SectionRule(
            name="References",
            mandatory=True,
            order=2,
            heading_pattern=r"(?i)^(?:\d+(?:\.\d+)*\s+)?references$",
            boilerplate_key="references",
        ),
        SectionRule(
            name="Definitions",
            mandatory=True,
            order=3,
            heading_pattern=r"(?i)^(?:\d+(?:\.\d+)*\s+)?definitions?$",
            boilerplate_key="definitions",
        ),
        SectionRule(
            name="Abbreviations",
            mandatory=False,
            order=4,
            heading_pattern=r"(?i)^(?:\d+(?:\.\d+)*\s+)?abbreviations?$",
        ),
        SectionRule(
            name="Conventions",
            mandatory=False,
            order=5,
            heading_pattern=r"(?i)^(?:\d+(?:\.\d+)*\s+)?conventions$",
        ),
        SectionRule(
            name="Profiles and levels",
            mandatory=False,
            order=90,
            heading_pattern=r"(?i)^(?:\d+(?:\.\d+)*\s+)?profiles?\s+(and|,)\s+levels?$",
        ),
    ),
    numbering=ITU_FLAVOR.numbering,
    metadata=MetadataFields(
        required=("docnumber", "series", "study_group"),
        optional=(
            "title_main",
            "approval_date",
            "publication_date",
            "language",
            "base_document",
            "amendment_number",
        ),
        doc_types=(
            "recommendation",
            "supplement",
            "amendment",
            "corrigendum",
        ),
        stages=("draft", "consent", "approved"),
    ),
    bibliography=ITU_FLAVOR.bibliography,
    boilerplate_dir="itu",
    page_size="a4",
    copyright_template="\u00a9 ITU ${copyright_year}",
)

AOM_FLAVOR = FlavorSpec(
    name="aom",
    display_name="Alliance for Open Media",
    sections=(
        SectionRule(
            name="Scope",
            mandatory=True,
            order=1,
            heading_pattern=r"(?i)^(?:\d+(?:\.\d+)*\s+)?scope$",
        ),
        SectionRule(
            name="Normative references",
            mandatory=True,
            order=2,
            heading_pattern=r"(?i)^(?:\d+(?:\.\d+)*\s+)?normative\s+references$",
        ),
        SectionRule(
            name="Definitions",
            mandatory=True,
            order=3,
            heading_pattern=r"(?i)^(?:\d+(?:\.\d+)*\s+)?definitions?$",
        ),
        SectionRule(
            name="Abbreviations",
            mandatory=False,
            order=4,
            heading_pattern=r"(?i)^(?:\d+(?:\.\d+)*\s+)?abbreviations?$",
        ),
        SectionRule(
            name="Conventions",
            mandatory=False,
            order=5,
            heading_pattern=r"(?i)^(?:\d+(?:\.\d+)*\s+)?conventions$",
        ),
    ),
    numbering=NumberingScheme(
        clause_prefix="",
        annex_style="letter",
        annex_label="Annex",
        figure_format="{section}-{n}",
        table_format="{section}-{n}",
        equation_format="({section}-{n})",
        normative_annex_label="(normative)",
        informative_annex_label="(informative)",
    ),
    metadata=MetadataFields(
        required=("docnumber",),
        optional=("title_main", "version", "copyright_year", "language"),
        doc_types=("specification", "test-vector", "errata"),
        stages=("draft", "v1.0", "v2.0", "published"),
    ),
    bibliography=BibliographyRules(
        style="iso690",
        normative_heading="Normative references",
        informative_heading="Bibliography",
        require_classification=True,
    ),
    boilerplate_dir="aom",
    page_size="letter",
    copyright_template="Copyright \u00a9 ${copyright_year} Alliance for Open Media",
)

# ---------------------------------------------------------------------------
# GB (Chinese National Standard — Guobiao)
# ---------------------------------------------------------------------------

GB_FLAVOR = FlavorSpec(
    name="gb",
    display_name="GB/T (Guobiao)",
    sections=(
        SectionRule(
            name="前言",
            mandatory=True,
            order=1,
            heading_pattern=r"^前言$",
        ),
        SectionRule(
            name="范围",
            mandatory=True,
            order=2,
            heading_pattern=r"^(?:\d+(?:\.\d+)*\s+)?范围$",
        ),
    ),
    numbering=NumberingScheme(
        clause_prefix="",
        annex_style="letter",
        annex_label="附录",
        figure_format="图{n}",
        table_format="表{n}",
        equation_format="({n})",
        normative_annex_label="(规范性)",
        informative_annex_label="(资料性)",
    ),
    metadata=MetadataFields(
        required=("docnumber",),
        optional=("title_main", "edition", "copyright_year", "technical_committee", "language"),
        doc_types=("standard", "technical-specification", "guide"),
        stages=("draft", "published", "revised", "withdrawn"),
    ),
    bibliography=BibliographyRules(
        style="iso690",
        normative_heading="规范性引用文件",
        informative_heading="参考文献",
        require_classification=False,
    ),
    boilerplate_dir="gb",
    page_size="a4",
    copyright_template="\u00a9 SAC ${copyright_year}",
)

# ---------------------------------------------------------------------------
# ETSI (European Telecommunications Standards Institute)
# ---------------------------------------------------------------------------

ETSI_FLAVOR = FlavorSpec(
    name="etsi",
    display_name="ETSI",
    sections=(
        SectionRule(
            name="Scope",
            mandatory=True,
            order=1,
            heading_pattern=r"(?i)^(?:\d+(?:\.\d+)*\s+)?scope$",
        ),
        SectionRule(
            name="References",
            mandatory=True,
            order=2,
            heading_pattern=r"(?i)^(?:\d+(?:\.\d+)*\s+)?references$",
        ),
        SectionRule(
            name="Definitions",
            mandatory=True,
            order=3,
            heading_pattern=r"(?i)^(?:\d+(?:\.\d+)*\s+)?definitions",
        ),
    ),
    numbering=NumberingScheme(
        clause_prefix="Clause ",
        annex_style="letter",
        annex_label="Annex",
        figure_format="{section}.{n}",
        table_format="{section}.{n}",
        equation_format="({section}.{n})",
        normative_annex_label="(normative)",
        informative_annex_label="(informative)",
    ),
    metadata=MetadataFields(
        required=("docnumber",),
        optional=(
            "title_main",
            "edition",
            "copyright_year",
            "technical_committee",
            "workgroup",
            "language",
        ),
        doc_types=("ts", "tr", "es", "en", "eg", "sr"),
        stages=("draft", "stable-draft", "published", "withdrawn"),
    ),
    bibliography=BibliographyRules(
        style="iso690",
        normative_heading="References",
        informative_heading="Bibliography",
        require_classification=False,
    ),
    boilerplate_dir="etsi",
    page_size="a4",
    copyright_template="\u00a9 ETSI ${copyright_year}",
)

# ---------------------------------------------------------------------------
# UN (United Nations documents)
# ---------------------------------------------------------------------------

UN_FLAVOR = FlavorSpec(
    name="un",
    display_name="UN Document",
    sections=(),
    numbering=NumberingScheme(
        clause_prefix="",
        annex_style="letter",
        annex_label="Annex",
        figure_format="{n}",
        table_format="{n}",
        equation_format="({n})",
        normative_annex_label="",
        informative_annex_label="",
    ),
    metadata=MetadataFields(
        required=("docnumber",),
        optional=("title_main", "copyright_year", "language"),
        doc_types=("resolution", "report", "decision", "working-paper"),
        stages=("draft", "published"),
    ),
    bibliography=BibliographyRules(
        style="iso690",
        normative_heading="References",
        informative_heading="Bibliography",
        require_classification=False,
    ),
    boilerplate_dir="un",
    page_size="a4",
    copyright_template="\u00a9 United Nations ${copyright_year}",
)

# ---------------------------------------------------------------------------
# SMPTE (Society of Motion Picture and Television Engineers)
# ---------------------------------------------------------------------------

SMPTE_FLAVOR = FlavorSpec(
    name="smpte",
    display_name="SMPTE",
    sections=(
        SectionRule(
            name="Abstract",
            mandatory=True,
            order=1,
            heading_pattern=r"(?i)^(?:\d+(?:\.\d+)*\s+)?abstract$",
        ),
        SectionRule(
            name="Scope",
            mandatory=True,
            order=2,
            heading_pattern=r"(?i)^(?:\d+(?:\.\d+)*\s+)?scope$",
        ),
        SectionRule(
            name="Conformance",
            mandatory=True,
            order=3,
            heading_pattern=r"(?i)^(?:\d+(?:\.\d+)*\s+)?conformance$",
            boilerplate_key="conformance",
        ),
        SectionRule(
            name="Normative References",
            mandatory=True,
            order=4,
            heading_pattern=r"(?i)^(?:\d+(?:\.\d+)*\s+)?normative\s+references$",
            boilerplate_key="normative_references",
        ),
        SectionRule(
            name="Terms and Definitions",
            mandatory=False,
            order=5,
            heading_pattern=r"(?i)^(?:\d+(?:\.\d+)*\s+)?terms\s+(and|,)\s+definitions$",
        ),
    ),
    numbering=NumberingScheme(
        clause_prefix="",
        annex_style="letter",
        annex_label="Annex",
        figure_format="{n}",
        table_format="{n}",
        equation_format="({n})",
        normative_annex_label="(normative)",
        informative_annex_label="(informative)",
    ),
    metadata=MetadataFields(
        required=("docnumber",),
        optional=(
            "title_main",
            "edition",
            "copyright_year",
            "working_group",
            "language",
        ),
        doc_types=("st", "rp", "eg", "er", "ag", "oc"),
        stages=("draft", "published", "revised", "withdrawn"),
    ),
    bibliography=BibliographyRules(
        style="ieee",
        normative_heading="Normative References",
        informative_heading="Bibliography",
        require_classification=True,
    ),
    boilerplate_dir="smpte",
    page_size="letter",
    copyright_template="Copyright © ${copyright_year} SMPTE. All rights reserved.",
)

# ---------------------------------------------------------------------------
# Flavor registry
# ---------------------------------------------------------------------------

FLAVORS: dict[str, FlavorSpec] = {
    "iso": ISO_FLAVOR,
    "itu-t": ITU_FLAVOR,
    "itu": ITU_FLAVOR,
    "ietf": IETF_FLAVOR,
    "iec": IEC_FLAVOR,
    "nist": NIST_FLAVOR,
    "ogc": OGC_FLAVOR,
    "cc": CC_FLAVOR,
    "bipm": BIPM_FLAVOR,
    "bsi": BSI_FLAVOR,
    "cen": CEN_FLAVOR,
    "cenelec": CEN_FLAVOR,
    "ieee": IEEE_FLAVOR,
    "jis": JIS_FLAVOR,
    "unece": UNECE_FLAVOR,
    "un": UN_FLAVOR,
    "3gpp": THREEGPP_FLAVOR,
    "jvet": JVET_FLAVOR,
    "mpeg": JVET_FLAVOR,
    "iso-video": ISO_VIDEO_FLAVOR,
    "itu-video": ITU_VIDEO_FLAVOR,
    "aom": AOM_FLAVOR,
    "av1": AOM_FLAVOR,
    "av2": AOM_FLAVOR,
    "gb": GB_FLAVOR,
    "etsi": ETSI_FLAVOR,
    "smpte": SMPTE_FLAVOR,
}
