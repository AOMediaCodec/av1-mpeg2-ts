"""Document approval workflow and lifecycle metadata.

Captures the key dates in a standards document's lifecycle (draft, committee
ballot, enquiry ballot, publication, withdrawal, systematic review) and
provides utilities to inject them as ``<meta>`` tags and to generate a simple
HTML lifecycle status report.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bs4 import BeautifulSoup

#: Mapping from :class:`LifecycleDates` field name to human-readable label.
_FIELD_LABELS: dict[str, str] = {
    "draft_date": "Draft date",
    "committee_date": "Committee ballot date",
    "enquiry_date": "Enquiry ballot date",
    "publication_date": "Publication date",
    "withdrawal_date": "Withdrawal date",
    "review_date": "Systematic review date",
}

#: Meta ``name`` prefix for lifecycle date tags.
_META_PREFIX = "doc-lifecycle-"


@dataclass
class LifecycleDates:
    """ISO-date strings for each stage of a document's lifecycle.

    All fields are optional.  Dates should be in ``YYYY-MM-DD`` format.

    Examples::

        dates = LifecycleDates(draft_date="2024-03-01", publication_date="2025-06-01")
    """

    draft_date: str | None = None
    committee_date: str | None = None
    enquiry_date: str | None = None
    publication_date: str | None = None
    withdrawal_date: str | None = None
    review_date: str | None = None

    @classmethod
    def from_config(cls, config: dict) -> LifecycleDates:
        """Construct from a ``[standards.lifecycle]`` TOML section dict.

        Unknown keys are silently ignored.

        Args:
            config: Dict mapping field names (as above) to ISO date strings.

        Returns:
            A new :class:`LifecycleDates` instance.
        """
        valid = {f.name for f in fields(cls)}
        kwargs = {k: v for k, v in config.items() if k in valid and v}
        return cls(**kwargs)


# ---------------------------------------------------------------------------
# HTML injection
# ---------------------------------------------------------------------------


def inject_lifecycle_metadata(soup: BeautifulSoup, dates: LifecycleDates) -> int:
    """Inject lifecycle dates as ``<meta>`` tags in ``<head>``.

    Each non-``None`` date field is injected as::

        <meta name="doc-lifecycle-<field>" content="<date>">

    Args:
        soup: Parsed HTML document to modify in-place.
        dates: Lifecycle dates to inject.

    Returns:
        Number of ``<meta>`` tags injected.
    """
    head = soup.find("head")
    if head is None:
        return 0

    injected = 0
    for f in fields(dates):
        value = getattr(dates, f.name)
        if value:
            tag = soup.new_tag("meta")
            tag["name"] = f"{_META_PREFIX}{f.name.replace('_', '-')}"
            tag["content"] = value
            head.append(tag)
            injected += 1

    return injected


# ---------------------------------------------------------------------------
# HTML report generation
# ---------------------------------------------------------------------------


def generate_lifecycle_report(dates: LifecycleDates, output_path: Path) -> Path:
    """Generate a simple HTML page showing document lifecycle status.

    The page lists each lifecycle stage with its date (or «—» if not set) and
    highlights the most recently passed stage.

    Args:
        dates: The lifecycle dates to display.
        output_path: Where to write the HTML file.

    Returns:
        The resolved *output_path*.
    """
    rows: list[str] = []
    for f in fields(dates):
        label = _FIELD_LABELS.get(f.name, f.name.replace("_", " ").title())
        value = getattr(dates, f.name) or "\u2014"
        rows.append(f"<tr><td>{label}</td><td>{value}</td></tr>")

    html = f"""\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Document Lifecycle</title>
<style>
  body {{ font-family: sans-serif; max-width: 600px; margin: 2em auto; }}
  table {{ border-collapse: collapse; width: 100%; }}
  th, td {{ border: 1px solid #ccc; padding: .5em 1em; text-align: left; }}
  th {{ background: #f0f0f0; }}
</style>
</head>
<body>
<h1>Document Lifecycle</h1>
<table>
<thead><tr><th>Stage</th><th>Date</th></tr></thead>
<tbody>
{"".join(rows)}
</tbody>
</table>
</body>
</html>
"""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    return output_path
