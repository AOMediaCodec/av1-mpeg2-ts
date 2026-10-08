"""Standards-body document support (ISO, ITU-T, IETF, IEC).

Provides a data-driven flavor system where each SDO's structural rules,
numbering conventions, metadata fields, and boilerplate templates are
captured as frozen dataclasses.  Generic plugins operate on whichever
flavor is active.
"""

from __future__ import annotations

from specbuild.standards.flavors import FlavorSpec
from specbuild.standards.registry import FLAVORS


def get_active_flavor(name: str | None) -> FlavorSpec | None:
    """Look up a flavor by name (case-insensitive).

    Returns ``None`` if *name* is falsy or unknown.
    """
    if not name:
        return None
    return FLAVORS.get(name.lower())


__all__ = ["FlavorSpec", "FLAVORS", "get_active_flavor"]
