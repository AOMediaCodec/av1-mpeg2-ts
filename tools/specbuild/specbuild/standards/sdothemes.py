"""SDO-specific theme application.

Applies visual theme overrides from the active standards flavor to the
THEME singleton when a flavor is selected.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from specbuild.standards.flavors import FlavorSpec


_SDO_THEMES: dict[str, dict[str, str]] = {
    "iso": {
        "color_accent": "#003399",
        "color_link": "#003399",
        "color_border": "#003399",
        "page_size": "a4",
    },
    "iec": {
        "color_accent": "#c8102e",
        "color_link": "#c8102e",
        "color_border": "#c8102e",
        "page_size": "a4",
    },
    "itu-t": {
        "color_accent": "#00a1de",
        "color_link": "#00599c",
        "color_border": "#ffc72c",
        "page_size": "a4",
    },
    "itu": {
        "color_accent": "#00a1de",
        "color_link": "#00599c",
        "color_border": "#ffc72c",
        "page_size": "a4",
    },
    "ietf": {
        "color_accent": "#003b5c",
        "color_link": "#003b5c",
        "page_size": "letter",
    },
    "ieee": {
        "color_accent": "#00629b",
        "color_link": "#00629b",
        "color_border": "#00629b",
        "page_size": "letter",
    },
    "3gpp": {
        "color_accent": "#0076a8",
        "color_link": "#0076a8",
        "page_size": "a4",
    },
    "nist": {
        "color_accent": "#005b94",
        "color_link": "#005b94",
        "page_size": "letter",
    },
    "aom": {
        "color_accent": "#1a73e8",
        "color_link": "#1a73e8",
        "page_size": "letter",
    },
    "iso-video": {
        "color_accent": "#003399",
        "color_link": "#003399",
        "color_border": "#003399",
        "page_size": "a4",
    },
    "itu-video": {
        "color_accent": "#00a1de",
        "color_link": "#00599c",
        "color_border": "#ffc72c",
        "page_size": "a4",
    },
    "jvet": {
        "color_accent": "#003399",
        "color_link": "#003399",
        "page_size": "a4",
    },
    "mpeg": {
        "color_accent": "#003399",
        "color_link": "#003399",
        "page_size": "a4",
    },
}


def apply_flavor_theme(flavor: FlavorSpec | None) -> None:
    """Apply SDO-specific theme overrides to the THEME singleton.

    Only sets values that the user hasn't already customized in
    ``specbuild.toml [theme]``.
    """
    if flavor is None:
        return

    from specbuild.theme import THEME

    overrides = {}
    if flavor.theme and flavor.theme.color_accent:
        overrides["color_accent"] = flavor.theme.color_accent
        overrides["color_link"] = flavor.theme.color_link or flavor.theme.color_accent
        if flavor.theme.color_border:
            overrides["color_border"] = flavor.theme.color_border
        if flavor.theme.font_sans:
            overrides["font_sans"] = flavor.theme.font_sans
        if flavor.theme.page_size:
            overrides["page_size"] = flavor.theme.page_size
    else:
        sdo_theme = _SDO_THEMES.get(flavor.name, {})
        overrides.update(sdo_theme)

    if not overrides:
        return

    from dataclasses import MISSING
    from dataclasses import fields as dc_fields

    defaults = {f.name: (f.default if f.default is not MISSING else None) for f in dc_fields(THEME)}
    applied = 0
    for key, value in overrides.items():
        if not hasattr(THEME, key):
            continue
        current = getattr(THEME, key)
        if current == defaults.get(key):
            setattr(THEME, key, value)
            applied += 1

    if applied:
        logging.info(f"Applied {applied} {flavor.display_name} theme override(s)")
