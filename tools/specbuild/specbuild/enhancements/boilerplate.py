"""Boilerplate injection enhancement plugin."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from specbuild.context import BuildContext


def inject_boilerplate(ctx: BuildContext) -> None:
    """Inject boilerplate sections for the active standards flavor."""
    if not ctx.standards_flavor or ctx.soup is None:
        return

    from specbuild.config import STANDARDS
    from specbuild.standards.boilerplate import inject_boilerplate_soup
    from specbuild.standards.metadata import resolve_metadata

    meta = ctx.metadata or resolve_metadata(ctx.args, STANDARDS, ctx.soup)
    count = inject_boilerplate_soup(ctx.soup, ctx.standards_flavor, meta)
    if count:
        ctx.dirty = True
        logging.info(f"Injected {count} boilerplate section(s)")
