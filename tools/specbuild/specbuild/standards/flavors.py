"""Core data model for standards-body document flavors.

Each SDO (Standards Development Organization) declares its structural rules
as frozen dataclasses.  A single set of generic plugins operates on
whichever :class:`FlavorSpec` is active — no per-SDO subclass hierarchies.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SectionRule:
    """A section required or expected by a flavor."""

    name: str
    mandatory: bool = True
    order: int = 0
    heading_pattern: str = ""
    boilerplate_key: str = ""


@dataclass(frozen=True)
class NumberingScheme:
    """How clauses, annexes, figures, and tables are numbered."""

    clause_prefix: str = ""
    annex_style: str = "letter"
    annex_label: str = "Annex"
    figure_format: str = "{section}.{n}"
    table_format: str = "{section}.{n}"
    equation_format: str = "({section}.{n})"
    normative_annex_label: str = "(normative)"
    informative_annex_label: str = "(informative)"


@dataclass(frozen=True)
class MetadataFields:
    """Expected metadata fields for this flavor."""

    required: tuple[str, ...] = ()
    optional: tuple[str, ...] = ()
    doc_types: tuple[str, ...] = ()
    stages: tuple[str, ...] = ()


@dataclass(frozen=True)
class BibliographyRules:
    """Bibliography formatting rules."""

    style: str = "iso690"
    normative_heading: str = "Normative references"
    informative_heading: str = "Bibliography"
    require_classification: bool = True


@dataclass(frozen=True)
class ThemeOverrides:
    """Per-SDO visual theme overrides applied when this flavor is active."""

    color_accent: str = ""
    color_link: str = ""
    color_border: str = ""
    font_sans: str = ""
    page_size: str = ""
    page_number_prefix: str = ""


@dataclass(frozen=True)
class FlavorSpec:
    """Complete specification of an SDO's document rules."""

    name: str
    display_name: str
    sections: tuple[SectionRule, ...] = ()
    numbering: NumberingScheme = field(default_factory=NumberingScheme)
    metadata: MetadataFields = field(default_factory=MetadataFields)
    bibliography: BibliographyRules = field(default_factory=BibliographyRules)
    boilerplate_dir: str = ""
    page_size: str = "a4"
    copyright_template: str = ""
    theme: ThemeOverrides = field(default_factory=ThemeOverrides)
    xml_root_tag: str = ""
