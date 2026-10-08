"""AOM boilerplate fix: strip spurious ``AOM `` prefix from the status heading.

Bikeshed prepends ``AOM `` to the ``<h3 id="profile-and-date">`` heading
when the ``Group`` metadata field is set to ``AOM``.  This is a temporary
workaround until https://github.com/speced/bikeshed/pull/3303 lands in
upstream Bikeshed.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path


def apply_aom_boilerplate(html_path: Path) -> None:
    """Strip the leading ``AOM `` prefix from the profile-and-date heading.

    Args:
        html_path: Path to the compiled ``index.html``.
    """
    if not html_path.exists():
        logging.warning(f"aom-boilerplate: {html_path} does not exist, skipping")
        return

    html = html_path.read_text(encoding="utf-8")
    pattern = re.compile(r'(<h3[^>]*id="profile-and-date"[^>]*>\s*<span class="content">)\s*AOM\s+')
    new_html, n = pattern.subn(r"\1", html, count=1)
    if n == 0:
        logging.debug("aom-boilerplate: profile-and-date heading not found or no AOM prefix")
        return

    html_path.write_text(new_html, encoding="utf-8")
    logging.info("aom-boilerplate: stripped 'AOM ' prefix from profile-and-date heading")
