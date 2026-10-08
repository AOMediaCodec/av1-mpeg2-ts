"""Pre-built specification templates for common document types."""

from __future__ import annotations

TEMPLATES: dict[str, dict] = {}


def get_template(name: str) -> dict | None:
    """Return a template by name (case-insensitive), or ``None``."""
    return TEMPLATES.get(name.lower())


def list_templates() -> list[str]:
    """Return sorted list of available template names."""
    return sorted(TEMPLATES.keys())
