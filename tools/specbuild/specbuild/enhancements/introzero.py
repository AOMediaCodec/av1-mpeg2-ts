"""Renumber Introduction as section 0 (ISO/IEC convention).

ISO and IEC standards number the Introduction as clause "0", with all
subsequent top-level clauses shifted down by one relative to Bikeshed's
auto-assignment (which starts at 1).

Enabled via ``introduction_section_zero = true`` in ``specbuild.toml``.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from specbuild.utils import read_html, write_html


def _decrement_secno(text: str, max_top: int) -> str:
    """Decrement every dotted section number N[.x[.y...]] where N >= 1, N <= max_top.

    Processes from the highest N downwards to avoid prefix collisions (e.g.
    renaming "11" before "1" so "11" doesn't accidentally match the "1" rule).

    Only matches at word/token boundaries so "b(1)" or "read_bits(1)" are not touched.
    """
    # Match a section number: starts at a non-digit boundary, first component is
    # a decimal integer, optionally followed by dot-separated sub-numbers.
    _SECNO_RE = re.compile(r"(?<!\w)(\d+)(\.\d+)*(?!\w|\()")

    def _replace(m: re.Match) -> str:
        top = int(m.group(1))
        if top < 1 or top > max_top:
            return m.group(0)
        rest = m.group(0)[len(m.group(1)) :]
        return str(top - 1) + rest

    return _SECNO_RE.sub(_replace, text)


def renumber_introduction_as_zero(html_path: Path) -> None:
    """Renumber Introduction→0 and decrement all subsequent top-level clause numbers.

    Bikeshed assigns Introduction the number "1" (since Foreword is .no-num).
    ISO convention puts Introduction at "0".  This function:

    1. Finds the Introduction h2 and confirms it is section "1".
    2. Decrements every section number N.x... → (N-1).x... in headings,
       the TOC, cross-references, and figure/table captions, for all
       top-level clause numbers 1..max.

    Only the ``<secno>`` spans and link href targets are touched; surrounding
    prose (which may contain bare digits) is left alone.

    Args:
        html_path: Path to the compiled ``index.html`` to modify in place.
    """
    soup = read_html(html_path)

    # Find the first numbered top-level heading
    headings = soup.find_all("h2", class_="heading")
    numbered = [
        h
        for h in headings
        if (s := h.find("span", class_="secno")) and re.match(r"^\d+\.\s*$", s.get_text())
    ]

    if not numbered:
        logging.warning("introduction-section-zero: no numbered h2 headings found")
        return

    first = numbered[0]
    first_secno = first.find("span", class_="secno")
    first_content = (first.find("span", class_="content") or first).get_text(strip=True)
    if "introduction" not in first_content.lower():
        logging.warning(
            f"introduction-section-zero: first numbered h2 is '{first_content}', "
            "not 'Introduction' — skipping renumbering"
        )
        return

    top_num = int(re.match(r"^(\d+)", first_secno.get_text()).group(1))
    if top_num != 1:
        logging.warning(
            f"introduction-section-zero: Introduction has secno {top_num}, expected 1 — skipping"
        )
        return

    max_top = int(
        re.match(r"^(\d+)", numbered[-1].find("span", class_="secno").get_text()).group(1)
    )

    logging.info(
        f"introduction-section-zero: renumbering {len(numbered)} top-level clause(s) "
        f"(Introduction: 1→0, last: {max_top}→{max_top - 1})"
    )

    # We operate on specific elements only — not raw prose text — to avoid
    # mangling numbers that appear in algorithm pseudocode or prose.
    changes = 0

    # 1. Section number <span class="secno"> in headings and TOC
    for span in soup.find_all("span", class_="secno"):
        old = span.get_text()
        new = _decrement_secno(old, max_top)
        if new != old:
            span.string = new
            changes += 1

    # 2. data-level attributes on headings (e.g. data-level="2" → "1")
    for h in soup.find_all(re.compile(r"h[2-6]"), attrs={"data-level": True}):
        old = h["data-level"]
        new = _decrement_secno(old, max_top)
        if new != old:
            h["data-level"] = new
            changes += 1

    # 3. Figure/table caption prefix text injected by renumber_annexes.py:
    #    <strong>Figure 7.1: </strong> → <strong>Figure 6.1: </strong>
    #    renumber_annexes runs before introzero, so figure numbers still use
    #    the pre-shift section numbers.
    _PREFIX_RE = re.compile(r"^(Figure|Table)\s+(\d+)([\.\-].*)$")
    for strong in soup.find_all("strong"):
        text = strong.get_text()
        m = _PREFIX_RE.match(text.strip())
        if m:
            kind, top_str, rest = m.group(1), m.group(2), m.group(3)
            top = int(top_str)
            if 1 <= top <= max_top:
                strong.string = f"{kind} {top - 1}{rest}"
                changes += 1

    # 4. Figure/table IDs and hrefs: id="figure-7-1" → id="figure-6-1"
    #    Pattern: (figure|table)-N-M or (figure|table)-N
    _ID_RE = re.compile(r"^(figure|table)-(\d+)(-.*)?$")

    def _decrement_id(id_val: str) -> str:
        m = _ID_RE.match(id_val)
        if not m:
            return id_val
        top = int(m.group(2))
        if top < 1 or top > max_top:
            return id_val
        suffix = m.group(3) or ""
        return f"{m.group(1)}-{top - 1}{suffix}"

    for el in soup.find_all(id=_ID_RE):
        old_id = el["id"]
        new_id = _decrement_id(old_id)
        if new_id != old_id:
            el["id"] = new_id
            changes += 1

    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.startswith("#"):
            frag = href[1:]
            new_frag = _decrement_id(frag)
            if new_frag != frag:
                a["href"] = "#" + new_frag
                changes += 1

    write_html(html_path, soup)

    logging.info(f"introduction-section-zero: {changes} element(s) updated")
