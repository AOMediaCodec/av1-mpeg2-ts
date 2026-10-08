"""Errata tracking: record, link, and export corrections to published standards."""

from __future__ import annotations

import csv
import json
import logging
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bs4 import BeautifulSoup


@dataclass
class ErrataEntry:
    """A single errata record for a published standard."""

    errata_id: str  # e.g. "ERR-2024-001"
    date: str  # ISO date "2024-03-15"
    clause_ref: str  # e.g. "7.3.2"
    type: str  # "technical" / "editorial"
    description: str  # What was wrong
    correction: str  # What it should be
    status: str  # "confirmed" / "pending" / "rejected"
    clause_id: str  # HTML id of the affected clause


def load_errata_csv(csv_path: Path) -> list[ErrataEntry]:
    """Parse a CSV file of errata records.

    Expected columns (in any order): errata_id, date, clause_ref, type,
    description, correction, status, clause_id.

    Args:
        csv_path: Path to the ``.csv`` file.

    Returns:
        List of :class:`ErrataEntry` objects.
    """
    entries: list[ErrataEntry] = []
    with csv_path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            entries.append(
                ErrataEntry(
                    errata_id=row.get("errata_id", "").strip(),
                    date=row.get("date", "").strip(),
                    clause_ref=row.get("clause_ref", "").strip(),
                    type=row.get("type", "").strip(),
                    description=row.get("description", "").strip(),
                    correction=row.get("correction", "").strip(),
                    status=row.get("status", "").strip(),
                    clause_id=row.get("clause_id", "").strip(),
                )
            )
    logging.info(f"Errata: loaded {len(entries)} entries from {csv_path}")
    return entries


def load_errata_json(json_path: Path) -> list[ErrataEntry]:
    """Parse a JSON array of errata objects.

    Each object should have the same keys as the CSV columns.

    Args:
        json_path: Path to the ``.json`` file.

    Returns:
        List of :class:`ErrataEntry` objects.
    """
    raw: list[dict] = json.loads(json_path.read_text(encoding="utf-8"))
    entries = [
        ErrataEntry(
            errata_id=item.get("errata_id", ""),
            date=item.get("date", ""),
            clause_ref=item.get("clause_ref", ""),
            type=item.get("type", ""),
            description=item.get("description", ""),
            correction=item.get("correction", ""),
            status=item.get("status", ""),
            clause_id=item.get("clause_id", ""),
        )
        for item in raw
    ]
    logging.info(f"Errata: loaded {len(entries)} entries from {json_path}")
    return entries


def inject_errata_markers_soup(soup: BeautifulSoup, errata: list[ErrataEntry]) -> int:
    """Inject errata warning markers into the document at affected clauses.

    For each entry, attempts to locate the clause element by:
    1. ``entry.clause_id`` — looks for an element with that HTML ``id``.
    2. ``entry.clause_ref`` — searches heading text for a matching clause number.

    Inserts immediately after the located heading::

        <span class="errata-marker"
              data-errata-id="ERR-2024-001"
              title="Errata ERR-2024-001 (technical)">⚠</span>

    Args:
        soup:   BeautifulSoup document (mutated in place).
        errata: List of :class:`ErrataEntry` objects to inject.

    Returns:
        Count of markers successfully injected.
    """
    from bs4 import BeautifulSoup as BS4
    from bs4 import Tag

    count = 0
    for entry in errata:
        target = None

        # Try clause_id first
        if entry.clause_id:
            target = soup.find(id=entry.clause_id)

        # Fall back to matching clause_ref in heading text
        if target is None and entry.clause_ref:
            pattern = re.compile(r"(^|\s)" + re.escape(entry.clause_ref) + r"(\s|$|\.|:)")
            for heading in soup.find_all(re.compile(r"^h[1-6]$")):
                if pattern.search(heading.get_text(strip=True)):
                    target = heading
                    break

        if target is None:
            continue

        # Build the marker span
        marker = BS4("", "html.parser").new_tag(
            "span",
            attrs={
                "class": "errata-marker",
                "data-errata-id": entry.errata_id,
                "title": f"Errata {entry.errata_id} ({entry.type})",
            },
        )
        marker.string = "\u26a0"  # ⚠

        # Insert after the target element if it's a heading; or append to it
        if isinstance(target, Tag) and target.name and target.name.startswith("h"):
            target.insert_after(marker)
        else:
            target.append(marker)

        count += 1
        logging.debug(
            f"Errata: injected marker for {entry.errata_id} at #{entry.clause_id or entry.clause_ref}"
        )

    if count:
        logging.info(f"Errata: injected {count} marker(s)")
    return count


def generate_errata_html(errata: list[ErrataEntry], output_path: Path) -> Path:
    """Write a standalone HTML table listing all errata entries.

    Args:
        errata:      List of :class:`ErrataEntry` objects.
        output_path: Destination HTML file path.

    Returns:
        ``output_path`` after writing.
    """
    rows = ""
    for e in errata:
        badge_class = {
            "confirmed": "badge-confirmed",
            "pending": "badge-pending",
            "rejected": "badge-rejected",
        }.get(e.status.lower(), "badge-unknown")
        rows += (
            f"<tr>"
            f"<td>{_html_escape(e.errata_id)}</td>"
            f"<td>{_html_escape(e.date)}</td>"
            f"<td>{_html_escape(e.clause_ref)}</td>"
            f"<td>{_html_escape(e.type)}</td>"
            f"<td>{_html_escape(e.description)}</td>"
            f"<td>{_html_escape(e.correction)}</td>"
            f'<td><span class="badge {badge_class}">{_html_escape(e.status)}</span></td>'
            f"</tr>\n"
        )

    html = (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '<meta charset="UTF-8"/>\n'
        "<title>Errata</title>\n"
        "<style>\n"
        "body{font-family:sans-serif;margin:2em}\n"
        "table{border-collapse:collapse;width:100%}\n"
        "th,td{border:1px solid #bbb;padding:.4em .6em;text-align:left}\n"
        "th{background:#eee}\n"
        ".badge{padding:.2em .5em;border-radius:3px;font-size:.85em}\n"
        ".badge-confirmed{background:#cfc;color:#060}\n"
        ".badge-pending{background:#ffc;color:#660}\n"
        ".badge-rejected{background:#fcc;color:#600}\n"
        ".badge-unknown{background:#eee;color:#333}\n"
        "</style>\n"
        "</head>\n"
        "<body>\n"
        "<h1>Errata</h1>\n"
        "<table>\n"
        "<thead><tr>"
        "<th>ID</th><th>Date</th><th>Clause</th><th>Type</th>"
        "<th>Description</th><th>Correction</th><th>Status</th>"
        "</tr></thead>\n"
        f"<tbody>\n{rows}</tbody>\n"
        "</table>\n"
        "</body></html>"
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    logging.info(f"Errata: HTML written to {output_path}")
    return output_path


def export_errata_json(errata: list[ErrataEntry], output_path: Path) -> Path:
    """Write errata list as a JSON array.

    Args:
        errata:      List of :class:`ErrataEntry` objects.
        output_path: Destination ``.json`` file path.

    Returns:
        ``output_path`` after writing.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    data = [asdict(e) for e in errata]
    output_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    logging.info(f"Errata: JSON written to {output_path}")
    return output_path


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _html_escape(text: str) -> str:
    """Escape characters for safe embedding in HTML."""
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )
