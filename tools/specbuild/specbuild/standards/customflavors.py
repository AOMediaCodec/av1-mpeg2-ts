"""TOML-based custom flavor creation and inheritance.

Allows users to define custom SDO flavors in ``specbuild.toml`` that
inherit from built-in flavors, without editing ``registry.py``.
"""

from __future__ import annotations

import logging
from typing import Any

from specbuild.standards.flavors import (
    BibliographyRules,
    FlavorSpec,
    MetadataFields,
    NumberingScheme,
    SectionRule,
    ThemeOverrides,
)
from specbuild.standards.registry import FLAVORS


def load_custom_flavors(config_data: dict[str, Any]) -> int:
    """Load custom flavor definitions from TOML config.

    Expected TOML structure::

        [standards.custom_flavors.my_org]
        inherits = "iso"
        display_name = "My Organization"
        page_size = "letter"
        copyright_template = "© My Org ${copyright_year}"

        [[standards.custom_flavors.my_org.sections]]
        name = "Executive Summary"
        mandatory = true
        order = 1
        heading_pattern = "(?i)^(?:\\\\d+\\\\s+)?executive\\\\s+summary$"

    Returns the number of custom flavors registered.
    """
    count = 0
    for name, definition in config_data.items():
        if not isinstance(definition, dict):
            continue

        flavor = _build_flavor(name, definition)
        if flavor:
            FLAVORS[name.lower()] = flavor
            count += 1
            logging.info(f"Registered custom flavor: {name}")

    return count


def _build_flavor(name: str, definition: dict[str, Any]) -> FlavorSpec | None:
    """Build a FlavorSpec from a TOML definition, optionally inheriting from a base."""
    inherits = definition.get("inherits", "")
    base = FLAVORS.get(inherits.lower()) if inherits else None

    sections = _parse_sections(definition.get("sections", []))
    if not sections and base:
        sections = base.sections

    numbering = _parse_numbering(definition.get("numbering", {}))
    if "numbering" not in definition and base:
        numbering = base.numbering

    metadata = _parse_metadata(definition.get("metadata", {}))
    if "metadata" not in definition and base:
        metadata = base.metadata

    bibliography = _parse_bibliography(definition.get("bibliography", {}))
    if "bibliography" not in definition and base:
        bibliography = base.bibliography

    theme = _parse_theme(definition.get("theme", {}))
    if "theme" not in definition and base:
        theme = base.theme

    return FlavorSpec(
        name=name,
        display_name=definition.get("display_name", name.upper()),
        sections=sections,
        numbering=numbering,
        metadata=metadata,
        bibliography=bibliography,
        boilerplate_dir=definition.get("boilerplate_dir", base.boilerplate_dir if base else ""),
        page_size=definition.get("page_size", base.page_size if base else "a4"),
        copyright_template=definition.get(
            "copyright_template", base.copyright_template if base else ""
        ),
        theme=theme,
        xml_root_tag=definition.get("xml_root_tag", base.xml_root_tag if base else ""),
    )


def _parse_sections(sections_data: list[dict[str, Any]]) -> tuple[SectionRule, ...]:
    """Parse section rules from TOML list of dicts."""
    if not sections_data:
        return ()
    rules = []
    for s in sections_data:
        if isinstance(s, dict):
            rules.append(
                SectionRule(
                    name=s.get("name", ""),
                    mandatory=s.get("mandatory", True),
                    order=s.get("order", 0),
                    heading_pattern=s.get("heading_pattern", ""),
                    boilerplate_key=s.get("boilerplate_key", ""),
                )
            )
    return tuple(rules)


def _parse_numbering(data: dict[str, Any]) -> NumberingScheme:
    """Parse numbering scheme from TOML dict."""
    return NumberingScheme(
        clause_prefix=data.get("clause_prefix", ""),
        annex_style=data.get("annex_style", "letter"),
        annex_label=data.get("annex_label", "Annex"),
        figure_format=data.get("figure_format", "{section}.{n}"),
        table_format=data.get("table_format", "{section}.{n}"),
        equation_format=data.get("equation_format", "({section}.{n})"),
        normative_annex_label=data.get("normative_annex_label", "(normative)"),
        informative_annex_label=data.get("informative_annex_label", "(informative)"),
    )


def _parse_metadata(data: dict[str, Any]) -> MetadataFields:
    """Parse metadata fields from TOML dict."""
    return MetadataFields(
        required=tuple(data.get("required", ())),
        optional=tuple(data.get("optional", ())),
        doc_types=tuple(data.get("doc_types", ())),
        stages=tuple(data.get("stages", ())),
    )


def _parse_bibliography(data: dict[str, Any]) -> BibliographyRules:
    """Parse bibliography rules from TOML dict."""
    return BibliographyRules(
        style=data.get("style", "iso690"),
        normative_heading=data.get("normative_heading", "Normative references"),
        informative_heading=data.get("informative_heading", "Bibliography"),
        require_classification=data.get("require_classification", True),
    )


def _parse_theme(data: dict[str, Any]) -> ThemeOverrides:
    """Parse theme overrides from TOML dict."""
    return ThemeOverrides(
        color_accent=data.get("color_accent", ""),
        color_link=data.get("color_link", ""),
        color_border=data.get("color_border", ""),
        font_sans=data.get("font_sans", ""),
        page_size=data.get("page_size", ""),
        page_number_prefix=data.get("page_number_prefix", ""),
    )
