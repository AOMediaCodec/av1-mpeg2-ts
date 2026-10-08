"""Reviewer annotation blocks.

Renders elements with class='reviewer-note' as styled sidebar annotations
with reviewer name, date, comment text, and optional resolution tracking.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bs4 import BeautifulSoup

# Status badge configuration: status -> (label, background colour)
_STATUS_CONFIG: dict[str, tuple[str, str]] = {
    "open": ("OPEN", "#e65100"),
    "resolved": ("RESOLVED", "#2e7d32"),
    "wontfix": ("WON'T FIX", "#555"),
    "deferred": ("DEFERRED", "#1565c0"),
}
_DEFAULT_STATUS = "open"


def strip_reviewer_notes_soup(soup: BeautifulSoup) -> int:
    """Remove all reviewer annotation blocks for publication builds.

    Completely removes elements with class ``reviewer-note`` from the
    document, leaving no trace of editorial review comments.

    Returns the number of annotations removed.
    """
    notes = soup.find_all(class_="reviewer-note")
    count = len(notes)
    for note in notes:
        note.decompose()
    if count:
        logging.info(f"Stripped {count} reviewer annotation(s) for publication")
    return count


def process_reviewer_notes_soup(soup: BeautifulSoup) -> int:
    """Process reviewer annotation blocks.

    Scans for elements with class 'reviewer-note'. Each should have:
    - data-reviewer="Name" attribute
    - data-date="YYYY-MM-DD" attribute (optional)
    - data-status="open|resolved|wontfix|deferred" attribute (optional, default "open")
    - data-resolution="..." attribute (optional, resolution description)
    - data-resolution-date="YYYY-MM-DD" attribute (optional)
    - Content is the review comment

    Wraps each in a styled annotation container with reviewer badge.

    Returns the number of annotations processed.
    """
    notes = soup.find_all(class_="reviewer-note")
    if not notes:
        return 0

    count = 0
    for note in notes:
        reviewer = note.get("data-reviewer", "Reviewer")
        date = note.get("data-date", "")
        status = (note.get("data-status") or _DEFAULT_STATUS).lower().strip()
        resolution = note.get("data-resolution", "")
        resolution_date = note.get("data-resolution-date", "")

        # Normalise unknown statuses to "open"
        if status not in _STATUS_CONFIG:
            status = _DEFAULT_STATUS

        # Skip already-processed notes
        classes = note.get("class", [])
        if "reviewer-processed" in classes:
            continue
        note["class"] = classes + ["reviewer-processed"]

        from bs4 import NavigableString

        # --- Build header badge ---
        header = soup.new_tag("div", attrs={"class": "reviewer-header"})

        name_span = soup.new_tag("span", attrs={"class": "reviewer-name"})
        name_span.string = reviewer
        header.append(name_span)

        if date:
            date_span = soup.new_tag("span", attrs={"class": "reviewer-date"})
            date_span.string = date
            header.append(NavigableString(" "))
            header.append(date_span)

        # Status badge
        label, bg_color = _STATUS_CONFIG[status]
        badge = soup.new_tag(
            "span",
            attrs={
                "class": "reviewer-status-badge",
                "data-status": status,
                "style": f"background:{bg_color};",
            },
        )
        badge.string = label
        header.append(NavigableString(" "))
        header.append(badge)

        note.insert(0, header)
        note.insert(1, NavigableString("\n"))

        # --- Resolution block ---
        if resolution:
            res_div = soup.new_tag("div", attrs={"class": "reviewer-resolution"})
            res_text = resolution
            if resolution_date:
                res_text = f"{resolution} ({resolution_date})"
            res_div.string = res_text
            note.append(NavigableString("\n"))
            note.append(res_div)

        count += 1

    if count:
        _inject_reviewer_css(soup)
        logging.info(f"Processed {count} reviewer annotation(s)")

    return count


def generate_review_summary_soup(soup: BeautifulSoup) -> dict[str, int]:
    """Return counts of reviewer notes by status.

    Scans all elements with class 'reviewer-processed' for their status badge
    and tallies counts by status.

    Returns a dict with keys: total, open, resolved, wontfix, deferred.
    """
    counts: dict[str, int] = {k: 0 for k in _STATUS_CONFIG}
    for badge in soup.find_all(class_="reviewer-status-badge"):
        status = badge.get("data-status", _DEFAULT_STATUS)
        if status in counts:
            counts[status] += 1
    total = sum(counts.values())
    return {"total": total, **counts}


def _inject_reviewer_css(soup: BeautifulSoup) -> None:
    from specbuild.utils import inject_css

    css = """
.reviewer-note {
  background: #fff8e1; border: 1px solid #ffcc02; border-left: 4px solid #ffcc02;
  padding: 0.75em 1em; margin: 1em 0; border-radius: 4px;
  font-size: 0.9em; position: relative;
}
.reviewer-header { font-weight: 600; margin-bottom: 0.25em; }
.reviewer-name { color: #d84315; }
.reviewer-date { color: #666; font-size: 0.85em; font-weight: normal; }
.reviewer-status-badge {
  display: inline-block; color: #fff; font-size: 0.75em; font-weight: 700;
  padding: 0.1em 0.5em; border-radius: 3px; vertical-align: middle;
  letter-spacing: 0.04em; text-transform: uppercase;
}
.reviewer-resolution {
  margin-top: 0.5em; padding: 0.4em 0.6em;
  background: #f1f8e9; border-left: 3px solid #558b2f;
  font-size: 0.85em; color: #33691e;
}
@media print {
  .reviewer-note { border: 1px solid #ccc; background: #f5f5f5; page-break-inside: avoid; }
}
"""
    inject_css(soup, "reviewer-note-styles", css)
