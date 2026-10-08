"""Standards document metadata resolution.

Merges metadata from CLI arguments, TOML ``[standards]`` configuration, and
Bikeshed HTML ``<head>`` metadata into a single resolved dictionary.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from bs4 import BeautifulSoup

    from specbuild.standards.flavors import FlavorSpec


_ISO_STAGES: dict[str, str] = {
    "WD": "Working Draft",
    "CD": "Committee Draft",
    "DIS": "Draft International Standard",
    "FDIS": "Final Draft International Standard",
    "IS": "International Standard",
    "CDV": "Committee Draft for Vote",
}


def resolve_metadata(
    args: Any,
    standards_config: Any,
    soup: BeautifulSoup | None = None,
) -> dict[str, str]:
    """Merge CLI / TOML / HTML metadata into a resolved dict.

    Priority (highest to lowest): CLI args > TOML [standards] > HTML <meta>.
    """
    meta: dict[str, str] = {}

    if soup is not None:
        meta.update(_extract_html_metadata(soup))

    from dataclasses import fields as dc_fields

    for f in dc_fields(standards_config):
        val = getattr(standards_config, f.name, "")
        if val:
            meta.setdefault(f.name, str(val))

    cli_overrides = {
        "flavor": getattr(args, "standards_flavor", None),
        "stage": getattr(args, "standards_stage", None),
        "docnumber": getattr(args, "iso_docnumber", None),
    }
    for key, val in cli_overrides.items():
        if val:
            meta[key] = str(val)

    return meta


def _extract_html_metadata(soup: BeautifulSoup) -> dict[str, str]:
    """Extract standards-relevant metadata from HTML <meta> tags."""
    meta: dict[str, str] = {}
    for tag in soup.find_all("meta"):
        name = tag.get("name", "")
        content = tag.get("content", "")
        if not name or not content:
            continue
        name_lower = name.lower().replace("-", "_").replace(" ", "_")
        if name_lower in (
            "docnumber",
            "edition",
            "stage",
            "copyright_year",
            "technical_committee",
        ):
            meta[name_lower] = content

    # Document title: prefer the <h1 id="title"> heading, then <title>.
    # The STS <title-wrap><main> field is required; without this it is empty.
    if not meta.get("title_main") and not meta.get("title"):
        title_text = ""
        h1 = soup.find("h1", id="title") or soup.find("h1")
        if h1 is not None:
            title_text = h1.get_text(" ", strip=True)
        if not title_text and soup.title and soup.title.string:
            title_text = soup.title.string.strip()
        if title_text:
            meta["title_main"] = title_text

    return meta


def validate_metadata(
    meta: dict[str, str],
    flavor: FlavorSpec,
) -> list[dict[str, str]]:
    """Check that all required metadata fields are present.

    Returns a list of issue dicts with keys ``level``, ``rule``, ``message``.
    """
    issues: list[dict[str, str]] = []
    for field_name in flavor.metadata.required:
        if not meta.get(field_name):
            issues.append(
                {
                    "level": "error",
                    "rule": "metadata-required",
                    "message": f"Required metadata field '{field_name}' is missing.",
                }
            )

    stage = meta.get("stage", "")
    if stage and flavor.metadata.stages and stage not in flavor.metadata.stages:
        issues.append(
            {
                "level": "warning",
                "rule": "metadata-stage",
                "message": (
                    f"Stage '{stage}' is not recognized for {flavor.display_name}. "
                    f"Valid stages: {', '.join(flavor.metadata.stages)}"
                ),
            }
        )

    doc_type = meta.get("doc_type", "")
    if doc_type and flavor.metadata.doc_types and doc_type not in flavor.metadata.doc_types:
        issues.append(
            {
                "level": "warning",
                "rule": "metadata-doc-type",
                "message": (
                    f"Document type '{doc_type}' is not recognized for {flavor.display_name}. "
                    f"Valid types: {', '.join(flavor.metadata.doc_types)}"
                ),
            }
        )

    return issues


def stage_display_name(stage: str) -> str:
    """Map a stage code to a human-readable string."""
    return _ISO_STAGES.get(stage.upper(), stage)
