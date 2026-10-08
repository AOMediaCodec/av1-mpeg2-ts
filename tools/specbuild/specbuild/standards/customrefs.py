"""Custom reference database extension.

Loads user-defined references from ``[standards.custom_references]`` in
``specbuild.toml`` and merges them into the known standards database.
"""

from __future__ import annotations

import logging
from typing import Any

from specbuild.standards.refdb import KNOWN_STANDARDS, StandardRef


def load_custom_references(config_data: dict[str, Any]) -> int:
    """Load custom references from TOML config into the standards database.

    Expected TOML structure::

        [standards.custom_references]
        "ACME-001" = { title = "ACME Widget Spec", body = "ACME", year = "2024", status = "active" }
        "INTERNAL-002" = { title = "Internal Protocol", body = "Internal", year = "2023" }

    Or as a list::

        [[standards.custom_references.entries]]
        docnumber = "ACME-001"
        title = "ACME Widget Spec"
        body = "ACME"
        current_year = "2024"
        status = "active"

    Returns the number of references added.
    """
    count = 0

    entries = config_data.get("entries", [])
    if isinstance(entries, list):
        for entry in entries:
            if isinstance(entry, dict) and entry.get("docnumber"):
                ref = _entry_to_ref(entry)
                if ref:
                    KNOWN_STANDARDS[ref.docnumber.lower()] = ref
                    count += 1

    for key, value in config_data.items():
        if key == "entries":
            continue
        if isinstance(value, dict):
            entry = dict(value)  # don't mutate caller's dict
            entry["docnumber"] = entry.get("docnumber", key)
            ref = _entry_to_ref(entry)
            if ref:
                KNOWN_STANDARDS[ref.docnumber.lower()] = ref
                count += 1

    if count:
        logging.info(f"Loaded {count} custom reference(s) into standards database")
    return count


def _entry_to_ref(entry: dict[str, Any]) -> StandardRef | None:
    """Convert a TOML entry dict to a StandardRef."""
    docnumber = entry.get("docnumber", "")
    if not docnumber:
        return None

    return StandardRef(
        body=entry.get("body", ""),
        docnumber=docnumber,
        title=entry.get("title", ""),
        current_year=entry.get("current_year", entry.get("year", "")),
        status=entry.get("status", "active"),
        successor=entry.get("successor", ""),
        parts=tuple(entry.get("parts", ())),
    )
