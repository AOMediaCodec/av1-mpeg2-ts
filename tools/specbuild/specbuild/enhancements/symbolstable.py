"""Sort the symbols table in a Bikeshed ``.bs`` source file.

Sorts ``<tbody>`` rows of a symbols/abbreviated-terms table alphabetically
by symbol name, case-insensitively and with natural numeric ordering
(e.g. ``FOO_2`` sorts before ``FOO_10``).

Expected row shape (exactly 5 lines per row)::

    <tr>
      <td>`SYMBOL_NAME`</td>
      <td ...>`VALUE`</td>
      <td>Description...</td>
    </tr>

The ``<tbody>`` and ``</tbody>`` tags must each appear alone on their own
lines.  If the file has no ``<tbody>`` the content is returned unchanged.
"""

from __future__ import annotations

import re


def _key(row: list[str]) -> list:
    match = re.search(r"`([^`]+)`", row[1])
    if not match:
        raise ValueError(f"name cell has no backticked symbol name: {row[1].rstrip()!r}")
    name = match.group(1)
    return [(1, int(p)) if p.isdigit() else (0, p.upper()) for p in re.split(r"(\d+)", name) if p]


def _validate_row(row: list[str], row_index: int, tbody_start: int) -> None:
    first_line_no = tbody_start + row_index * 5 + 1
    opener = row[0].strip()
    closer = row[-1].strip()
    if opener != "<tr>" or closer != "</tr>":
        raise ValueError(
            f"symbols table row at line {first_line_no} does not have "
            f"<tr>/</tr> on its first/last lines (got {opener!r} / {closer!r}); "
            f"each row must be exactly 5 lines."
        )
    for offset, line in enumerate(row[1:4], start=1):
        stripped = line.strip()
        if not (stripped.startswith("<td") and stripped.endswith("</td>")):
            raise ValueError(
                f"symbols table row at line {first_line_no + offset} is not a "
                f"single-line <td>...</td> cell (got {stripped!r}); each row "
                f"must be exactly 5 lines with one <td> per line."
            )


def sort_symbols_table(content: str) -> tuple[str, int]:
    """Sort ``<tbody>`` rows in *content* alphabetically by symbol name.

    Args:
        content: Raw ``.bs`` file text.

    Returns:
        Tuple of ``(sorted_content, rows_sorted)`` where *rows_sorted* is the
        number of rows found (and sorted).  Returns the original *content*
        unchanged (with ``rows_sorted=0``) when no ``<tbody>`` is found.

    Raises:
        ValueError: If the table structure violates the expected 5-line-per-row
            shape.
    """
    lines = content.splitlines(keepends=True)
    try:
        start = next(i for i, ln in enumerate(lines) if ln.strip() == "<tbody>") + 1
        end = next(i for i, ln in enumerate(lines) if ln.strip() == "</tbody>")
    except StopIteration:
        return content, 0

    block = lines[start:end]
    if len(block) % 5:
        raise ValueError(
            f"<tbody> at line {start} has {len(block)} lines; expected a "
            f"multiple of 5 (each row is exactly 5 lines)."
        )

    rows = [block[i : i + 5] for i in range(0, len(block), 5)]
    for idx, row in enumerate(rows):
        _validate_row(row, idx, start)
    rows.sort(key=_key)
    return "".join(lines[:start] + [ln for r in rows for ln in r] + lines[end:]), len(rows)
