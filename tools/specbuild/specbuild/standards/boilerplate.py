"""Boilerplate section rendering and injection.

Renders HTML fragments from templates (using :class:`string.Template`) and
injects missing mandatory sections into the document soup.  Bilingual (EN/FR)
rendering is supported for the flavors listed in :data:`BILINGUAL_FLAVORS`.

Stage-dependent templates are supported via :func:`render_stage_boilerplate`
and :func:`inject_stage_boilerplate_soup`.  Template lookup order for a given
*section_key* and *stage* is:

1. ``{section_key}.{stage}.html`` (stage-specific)
2. ``{section_key}.html`` (stage-agnostic fallback)
"""

from __future__ import annotations

import html as _html
import logging
from pathlib import Path
from string import Template
from typing import TYPE_CHECKING

from specbuild.utils import HEADING_RE, find_heading_by_pattern, inject_css

if TYPE_CHECKING:
    from bs4 import BeautifulSoup

    from specbuild.standards.flavors import FlavorSpec

import specbuild

_BOILERPLATE_CACHE: dict[str, str] = {}

# ---------------------------------------------------------------------------
# HTML lang / direction injection
# ---------------------------------------------------------------------------

#: Language codes that require right-to-left base direction.
_RTL_LANGS: frozenset[str] = frozenset({"ar", "he", "fa", "ur", "yi", "dv", "ps"})


def inject_html_lang_attr(soup: BeautifulSoup, lang: str = "en") -> bool:
    """Set ``lang`` and ``xml:lang`` on the ``<html>`` element if not already present.

    Also sets ``dir="rtl"`` for known RTL languages when the ``dir``
    attribute is absent.

    Args:
        soup: Parsed document.
        lang: BCP 47 language tag to apply (default ``"en"``).

    Returns:
        ``True`` if any attribute was modified, ``False`` when the
        ``lang`` attribute was already set.
    """
    html_el = soup.find("html")
    if html_el is None:
        return False

    if html_el.get("lang"):
        # Already set — leave untouched
        return False

    html_el["lang"] = lang
    html_el["xml:lang"] = lang

    if lang in _RTL_LANGS and not html_el.get("dir"):
        html_el["dir"] = "rtl"

    return True


# ---------------------------------------------------------------------------
# Stage normalisation
# ---------------------------------------------------------------------------

_STAGE_ALIASES: dict[str, str] = {
    # WD aliases
    "wd": "wd",
    "working draft": "wd",
    "20": "wd",
    "20.00": "wd",
    # CD aliases
    "cd": "cd",
    "committee draft": "cd",
    "30": "cd",
    "30.00": "cd",
    # DIS aliases
    "dis": "dis",
    "draft international standard": "dis",
    "40": "dis",
    "40.00": "dis",
    # FDIS aliases
    "fdis": "fdis",
    "final draft": "fdis",
    "50": "fdis",
    "50.00": "fdis",
    # IS aliases
    "is": "is",
    "international standard": "is",
    "60": "is",
    "60.60": "is",
}


def _normalise_stage(stage: str) -> str:
    """Return the canonical stage code for *stage*, defaulting to ``"is"``.

    Lookup is case-insensitive and strips surrounding whitespace.

    Examples::

        >>> _normalise_stage("Working Draft")
        'wd'
        >>> _normalise_stage("40.00")
        'dis'
        >>> _normalise_stage("unknown")
        'is'
    """
    canonical = _STAGE_ALIASES.get(stage.lower().strip())
    if canonical is None:
        logging.warning(f"Unknown stage code '{stage}' — defaulting to 'is'")
        canonical = "is"
    return canonical


# ---------------------------------------------------------------------------
# List-style CSS
# ---------------------------------------------------------------------------

_LIST_STYLES_CSS = """\
ol[type="a"], ol.list-lower-alpha { list-style-type: lower-alpha; }
ol[type="A"], ol.list-upper-alpha { list-style-type: upper-alpha; }
ol[type="i"], ol.list-lower-roman { list-style-type: lower-roman; }
ol[type="I"], ol.list-upper-roman { list-style-type: upper-roman; }
"""

_LIST_STYLES_CSS_ID = "boilerplate-list-styles"


def inject_list_styles_css(soup: BeautifulSoup) -> None:
    """Inject ordered-list style variants into *soup* ``<head>`` (once).

    Injects CSS for ``lower-alpha``, ``upper-alpha``, ``lower-roman``, and
    ``upper-roman`` ordered-list variants, keyed by both the HTML ``type``
    attribute and utility CSS classes.
    """
    if not soup.find("style", id=_LIST_STYLES_CSS_ID):
        inject_css(soup, _LIST_STYLES_CSS_ID, _LIST_STYLES_CSS)


# ---------------------------------------------------------------------------
# Bilingual flavors constant
# ---------------------------------------------------------------------------

# Flavors that natively publish in both English and French.
BILINGUAL_FLAVORS: frozenset[str] = frozenset({"iso", "iec", "iso-iec", "iso-video", "itu-video"})

_BILINGUAL_CSS = """\
.bilingual-section {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 2em;
}
.lang-en {
  border-right: 1px solid #ddd;
  padding-right: 1em;
}
.lang-en::before {
  content: "EN";
  font-weight: bold;
  font-size: 0.8em;
  color: #666;
  display: block;
  margin-bottom: 0.5em;
}
.lang-fr::before {
  content: "FR";
  font-weight: bold;
  font-size: 0.8em;
  color: #666;
  display: block;
  margin-bottom: 0.5em;
}
@media print {
  .bilingual-section { grid-template-columns: 1fr 1fr; }
}
"""


def _boilerplate_dir(flavor: FlavorSpec) -> Path:
    """Resolve the boilerplate directory for a flavor."""
    custom = getattr(flavor, "boilerplate_dir", "")
    if not custom:
        return Path()
    root = getattr(specbuild, "PROJECT_ROOT", Path.cwd())
    return root / "specbuild" / "standards" / "boilerplate" / custom


def render_boilerplate(
    flavor: FlavorSpec,
    section_key: str,
    metadata: dict[str, str],
) -> str:
    """Render a boilerplate HTML fragment from template.

    Returns an empty string if the template file does not exist.
    """
    cache_key = f"{flavor.name}:{section_key}"
    if cache_key in _BOILERPLATE_CACHE:
        raw = _BOILERPLATE_CACHE[cache_key]
    else:
        bp_dir = _boilerplate_dir(flavor)
        template_path = bp_dir / f"{section_key}.html"
        if not template_path.exists():
            return ""
        raw = template_path.read_text(encoding="utf-8")
        _BOILERPLATE_CACHE[cache_key] = raw

    try:
        return Template(raw).safe_substitute(metadata)
    except Exception:
        logging.warning(f"Failed to render boilerplate '{section_key}' for {flavor.name}")
        return raw


def _render_fr_boilerplate(
    flavor: FlavorSpec,
    section_key: str,
    metadata: dict[str, str],
) -> str:
    """Render the French variant of a boilerplate template.

    Looks for ``{section_key}.fr.html`` first; falls back to the English
    template so the caller never receives an empty string when an English
    template exists.
    """
    cache_key = f"{flavor.name}:{section_key}:fr"
    if cache_key in _BOILERPLATE_CACHE:
        raw = _BOILERPLATE_CACHE[cache_key]
    else:
        bp_dir = _boilerplate_dir(flavor)
        fr_path = bp_dir / f"{section_key}.fr.html"
        if fr_path.exists():
            raw = fr_path.read_text(encoding="utf-8")
        else:
            # Graceful fallback: use the English template.
            en_path = bp_dir / f"{section_key}.html"
            if not en_path.exists():
                return ""
            raw = en_path.read_text(encoding="utf-8")
        _BOILERPLATE_CACHE[cache_key] = raw

    try:
        return Template(raw).safe_substitute(metadata)
    except Exception:
        logging.warning(f"Failed to render French boilerplate '{section_key}' for {flavor.name}")
        return raw


def render_bilingual_boilerplate(
    flavor: FlavorSpec,
    section_key: str,
    metadata: dict[str, str],
    lang: str = "en",
) -> str:
    """Render a boilerplate section in the requested language.

    Args:
        flavor: The active :class:`~specbuild.standards.flavors.FlavorSpec`.
        section_key: Template file stem (e.g. ``"foreword"``).
        metadata: Substitution variables forwarded to
            :class:`string.Template`.
        lang: ``"en"`` (English only), ``"fr"`` (French only, with
            English fallback when no French template exists), or
            ``"both"`` (bilingual side-by-side HTML fragment).

    Returns:
        Rendered HTML string, or an empty string when no template is
        available at all.
    """
    if lang == "en":
        return render_boilerplate(flavor, section_key, metadata)

    if lang == "fr":
        return _render_fr_boilerplate(flavor, section_key, metadata)

    # lang == "both" — build the bilingual grid fragment.
    en_html = render_boilerplate(flavor, section_key, metadata)
    fr_html = _render_fr_boilerplate(flavor, section_key, metadata)

    if not en_html and not fr_html:
        return ""

    parts = [
        '<div class="bilingual-section">',
        f'  <div class="lang-en" lang="en">{en_html}</div>',
        f'  <div class="lang-fr" lang="fr">{fr_html}</div>',
        "</div>",
    ]
    return "\n".join(parts)


def inject_boilerplate_soup(
    soup: BeautifulSoup,
    flavor: FlavorSpec,
    metadata: dict[str, str],
) -> int:
    """Inject missing mandatory boilerplate sections into *soup*.

    Only sections that are both mandatory and have a ``boilerplate_key``
    are considered for injection.  Existing sections (matched by heading
    pattern) are not replaced.

    Also injects list-style CSS variants so boilerplate sections that use
    ``<ol type="a">`` etc. render correctly.

    Returns the number of sections injected.
    """
    from bs4 import BeautifulSoup as BS
    from bs4 import NavigableString

    inject_list_styles_css(soup)

    body = soup.find("body")
    if body is None:
        return 0

    injected = 0
    sorted_sections = sorted(flavor.sections, key=lambda s: s.order)
    # Capture the insertion anchor before the loop: calling body.find("section")
    # inside the loop would return the most-recently injected section, reversing
    # the intended injection order.
    first_section = body.find("section") or body.find(HEADING_RE)

    for rule in sorted_sections:
        if not rule.mandatory or not rule.boilerplate_key:
            continue

        if rule.heading_pattern and find_heading_by_pattern(soup, rule.heading_pattern):
            continue

        html = render_boilerplate(flavor, rule.boilerplate_key, metadata)
        if not html:
            html = (
                f'<section id="{_html.escape(rule.boilerplate_key)}">\n'
                f"  <h2>{_html.escape(rule.name)}</h2>\n"
                f"  <p><em>[This section is required by {_html.escape(flavor.display_name)}. "
                f"Please add content.]</em></p>\n"
                f"</section>\n"
            )

        fragment = BS(html, "html.parser")

        if first_section:
            first_section.insert_before(fragment)
            first_section.insert_before(NavigableString("\n"))
        else:
            body.append(NavigableString("\n"))
            body.append(fragment)

        injected += 1
        logging.info(f"Injected boilerplate section: {rule.name}")

    return injected


def inject_bilingual_boilerplate_soup(
    soup: BeautifulSoup,
    flavor: FlavorSpec,
    metadata: dict[str, str],
    lang: str = "both",
) -> int:
    """Inject missing mandatory boilerplate sections into *soup*.

    Wraps :func:`inject_boilerplate_soup` for backward compatibility when
    ``lang="en"``.  For ``lang="fr"`` or ``lang="both"`` the bilingual
    rendering path is used and the bilingual CSS is injected into the document
    ``<head>`` (once, idempotently).

    Returns the number of sections injected.
    """
    if lang == "en":
        return inject_boilerplate_soup(soup, flavor, metadata)

    from bs4 import BeautifulSoup as BS
    from bs4 import NavigableString

    # Inject the bilingual CSS into <head> once.
    head = soup.find("head")
    if head is not None:
        marker = "bilingual-boilerplate-css"
        if not soup.find("style", {"data-specbuild": marker}):
            style_tag = BS(
                f'<style data-specbuild="{marker}">{_BILINGUAL_CSS}</style>',
                "html.parser",
            )
            head.append(style_tag)

    body = soup.find("body")
    if body is None:
        return 0

    injected = 0
    sorted_sections = sorted(flavor.sections, key=lambda s: s.order)
    first_section = body.find("section") or body.find(HEADING_RE)

    for rule in sorted_sections:
        if not rule.mandatory or not rule.boilerplate_key:
            continue

        if rule.heading_pattern and find_heading_by_pattern(soup, rule.heading_pattern):
            continue

        html = render_bilingual_boilerplate(flavor, rule.boilerplate_key, metadata, lang=lang)
        if not html:
            html = (
                f'<section id="{_html.escape(rule.boilerplate_key)}">\n'
                f"  <h2>{_html.escape(rule.name)}</h2>\n"
                f"  <p><em>[This section is required by {_html.escape(flavor.display_name)}. "
                f"Please add content.]</em></p>\n"
                f"</section>\n"
            )

        fragment = BS(html, "html.parser")

        if first_section:
            first_section.insert_before(fragment)
            first_section.insert_before(NavigableString("\n"))
        else:
            body.append(NavigableString("\n"))
            body.append(fragment)

        injected += 1
        logging.info(f"Injected bilingual boilerplate section: {rule.name}")

    return injected


# ---------------------------------------------------------------------------
# Stage-dependent boilerplate
# ---------------------------------------------------------------------------


def render_stage_boilerplate(
    flavor: FlavorSpec,
    section_key: str,
    metadata: dict[str, str],
    stage: str = "is",
) -> str:
    """Render a boilerplate section for a specific document stage.

    Template lookup order:

    1. ``{section_key}.{stage}.html`` — stage-specific template.
    2. ``{section_key}.html`` — stage-agnostic fallback via
       :func:`render_boilerplate`.

    Args:
        flavor: The active :class:`~specbuild.standards.flavors.FlavorSpec`.
        section_key: Template file stem (e.g. ``"foreword"``).
        metadata: Substitution variables forwarded to
            :class:`string.Template`.
        stage: Document stage string — normalised via
            :func:`_normalise_stage` before lookup (e.g. ``"wd"``,
            ``"40.00"``, ``"Working Draft"`` all resolve to ``"wd"``).

    Returns:
        Rendered HTML string, or an empty string when no template is
        available.
    """
    canonical = _normalise_stage(stage)
    cache_key = f"{flavor.name}:{section_key}:{canonical}"

    if cache_key in _BOILERPLATE_CACHE:
        raw = _BOILERPLATE_CACHE[cache_key]
    else:
        bp_dir = _boilerplate_dir(flavor)
        stage_path = bp_dir / f"{section_key}.{canonical}.html"
        if stage_path.exists():
            raw = stage_path.read_text(encoding="utf-8")
            _BOILERPLATE_CACHE[cache_key] = raw
        else:
            # Fall back to stage-agnostic template — result is cached under
            # that function's own key, not the stage key.
            return render_boilerplate(flavor, section_key, metadata)

    try:
        return Template(raw).safe_substitute(metadata)
    except Exception:
        logging.warning(
            f"Failed to render stage boilerplate '{section_key}' "
            f"(stage={canonical}) for {flavor.name}"
        )
        return raw


def inject_stage_boilerplate_soup(
    soup: BeautifulSoup,
    flavor: FlavorSpec,
    metadata: dict[str, str],
    stage: str = "is",
) -> int:
    """Inject missing mandatory boilerplate sections using stage-aware templates.

    Wraps :func:`inject_boilerplate_soup` logic but calls
    :func:`render_stage_boilerplate` for each section so that stage-specific
    templates (e.g. ``foreword.wd.html``) are used when available.

    Args:
        soup: Parsed document.
        flavor: The active :class:`~specbuild.standards.flavors.FlavorSpec`.
        metadata: Template substitution variables.
        stage: Document stage (normalised via :func:`_normalise_stage`).

    Returns:
        Number of sections injected.
    """
    from bs4 import BeautifulSoup as BS
    from bs4 import NavigableString

    inject_list_styles_css(soup)

    body = soup.find("body")
    if body is None:
        return 0

    injected = 0
    sorted_sections = sorted(flavor.sections, key=lambda s: s.order)
    first_section = body.find("section") or body.find(HEADING_RE)

    for rule in sorted_sections:
        if not rule.mandatory or not rule.boilerplate_key:
            continue

        if rule.heading_pattern and find_heading_by_pattern(soup, rule.heading_pattern):
            continue

        html = render_stage_boilerplate(flavor, rule.boilerplate_key, metadata, stage=stage)
        if not html:
            html = (
                f'<section id="{_html.escape(rule.boilerplate_key)}">\n'
                f"  <h2>{_html.escape(rule.name)}</h2>\n"
                f"  <p><em>[This section is required by {_html.escape(flavor.display_name)}. "
                f"Please add content.]</em></p>\n"
                f"</section>\n"
            )

        fragment = BS(html, "html.parser")

        if first_section:
            first_section.insert_before(fragment)
            first_section.insert_before(NavigableString("\n"))
        else:
            body.append(NavigableString("\n"))
            body.append(fragment)

        injected += 1
        logging.info(f"Injected stage boilerplate section: {rule.name} (stage={stage})")

    return injected
