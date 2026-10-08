"""Clause-level scaffolding templates for ``--new-clause``.

Each template is a Bikeshed/Markdown snippet stub.  The placeholders are
``{title}`` and ``{slug}``.  Slugs are auto-derived from the title by
lower-casing and replacing whitespace/punctuation with hyphens.

Supported types:

- ``syntax`` — syntax structure with SDL fenced block
- ``process`` — decoding/parsing process clause
- ``profile`` — profile definition with conformance points
- ``sei``    — SEI / supplemental message clause
- ``annex``  — top-level annex skeleton

All snippets escape user-provided strings before substitution, so it is
safe to pass arbitrary titles.
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Template strings
# ---------------------------------------------------------------------------

_SYNTAX_TEMPLATE = """\
## {title} ## {{#{slug}}}

### Syntax

```sdl
{slug}( ) {{
    f(1) {slug}_flag
    if ( {slug}_flag ) {{
        u(8) {slug}_value
    }}
}}
```

### Semantics

<dfn>{slug}_flag</dfn> equal to 1 specifies that …

<dfn>{slug}_value</dfn> specifies …
"""

_PROCESS_TEMPLATE = """\
## {title} ## {{#{slug}}}

### Inputs to this process

  * Issue: list inputs.

### Outputs of this process

  * Issue: list outputs.

### Process

The decoding process for {title_lc} is invoked when …

  1. …
  2. …
"""

_PROFILE_TEMPLATE = """\
## {title} ## {{#{slug}}}

A bitstream conforming to the {title} shall obey the following constraints:

  * …
  * …

### Tier and level limits

| Level | Max luma sample rate | Max bit rate |
|-------|----------------------|--------------|
| …     | …                    | …            |
"""

_SEI_TEMPLATE = """\
## {title} SEI message ## {{#sei-{slug}}}

### Syntax

```sdl
{slug}( payloadSize ) {{
    f(1) {slug}_present_flag
}}
```

### Semantics

The {title} SEI message provides information that …

<dfn>{slug}_present_flag</dfn> equal to 1 indicates …
"""

_ANNEX_TEMPLATE = """\
# Annex {{#annex-{slug}}}

# {title} # {{#annex-{slug}-title}}

(informative)

## Overview ## {{#annex-{slug}-overview}}

…
"""

_TEMPLATES: dict[str, str] = {
    "syntax": _SYNTAX_TEMPLATE,
    "process": _PROCESS_TEMPLATE,
    "profile": _PROFILE_TEMPLATE,
    "sei": _SEI_TEMPLATE,
    "annex": _ANNEX_TEMPLATE,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def list_clause_types() -> list[str]:
    """Return supported clause types in stable order."""
    return list(_TEMPLATES)


def slugify(title: str) -> str:
    """Convert *title* to a Bikeshed-friendly slug (lowercase, hyphenated)."""
    cleaned = re.sub(r"[^A-Za-z0-9]+", "-", title.strip().lower())
    cleaned = cleaned.strip("-")
    return cleaned or "clause"


def render_clause(clause_type: str, title: str) -> str:
    """Render a clause snippet for *clause_type* with the given *title*.

    Args:
        clause_type: One of :func:`list_clause_types`.
        title: Human-readable clause title.

    Returns:
        A Bikeshed-formatted snippet string with a trailing newline.

    Raises:
        ValueError: If *clause_type* is not supported.
    """
    template = _TEMPLATES.get(clause_type)
    if template is None:
        raise ValueError(
            f"Unknown clause type: {clause_type!r}. Available: {', '.join(list_clause_types())}"
        )
    # Escape braces in the user-supplied title to prevent str.format() from
    # treating them as field delimiters and raising KeyError/IndexError.
    safe_title = (title.strip() or "Untitled").replace("{", "{{").replace("}", "}}")
    return template.format(
        title=safe_title,
        title_lc=safe_title.lower(),
        slug=slugify(safe_title),
    )


__all__ = ["render_clause", "list_clause_types", "slugify"]
