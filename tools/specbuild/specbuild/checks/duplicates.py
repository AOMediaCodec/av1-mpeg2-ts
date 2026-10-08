"""Duplicate paragraph detection: find near-duplicate text across sections.

Uses a simple shingling approach to detect paragraphs that share
significant text overlap.  This helps identify copy-paste content
that should be consolidated or cross-referenced.
"""

from __future__ import annotations

import html as _html
import json
import logging
from pathlib import Path

from specbuild.utils import find_nearest_heading, get_bs4, read_html


def detect_duplicates(html_path: Path, *, threshold: float = 0.7) -> list[dict]:
    """File-based wrapper around :func:`detect_duplicates_soup`.

    Args:
        html_path: Path to the compiled HTML file.
        threshold: Similarity threshold (0.0–1.0).

    Returns:
        List of duplicate pair dicts.
    """
    try:
        get_bs4()
    except ImportError:
        logging.warning("BeautifulSoup not available, skipping duplicate detection")
        return []

    soup = read_html(html_path)
    return detect_duplicates_soup(soup, threshold=threshold)


def detect_duplicates_soup(
    soup: object,
    *,
    threshold: float = 0.7,
    min_words: int = 20,
) -> list[dict]:
    """Detect near-duplicate paragraphs in the parsed HTML.

    Uses word-level 3-shingles and Jaccard similarity to find
    paragraphs with significant text overlap.

    Args:
        soup: BeautifulSoup document (read-only).
        threshold: Jaccard similarity threshold (0.0–1.0).
        min_words: Minimum word count for a paragraph to be checked.

    Returns:
        List of dicts with ``text_a``, ``text_b``, ``context_a``,
        ``context_b``, ``similarity``.
    """
    # Collect paragraphs with their shingles
    paragraphs: list[tuple[str, str, frozenset[tuple]]] = []

    for elem in soup.find_all("p"):
        text = elem.get_text(strip=True)
        words = text.lower().split()
        if len(words) < min_words:
            continue

        shingles = _shingle(words, k=3)
        if not shingles:
            continue

        context = find_nearest_heading(elem)
        paragraphs.append((text, context, shingles))

    # Cap to avoid excessive O(n^2) comparisons on very large specs
    MAX_PARAGRAPHS = 2000
    if len(paragraphs) > MAX_PARAGRAPHS:
        logging.warning(
            f"Duplicate check: capped at {MAX_PARAGRAPHS} paragraphs (doc has {len(paragraphs)}); "
            "duplicates in the latter portion of the document will not be detected"
        )
    paragraphs = paragraphs[:MAX_PARAGRAPHS]

    # Compare all pairs
    duplicates: list[dict] = []
    n = len(paragraphs)

    for i in range(n):
        text_a, ctx_a, shingles_a = paragraphs[i]
        for j in range(i + 1, n):
            text_b, ctx_b, shingles_b = paragraphs[j]

            sim = _jaccard(shingles_a, shingles_b)

            # Skip near-duplicates within the same section to reduce false
            # positives, but still flag exact duplicates (similarity == 1.0)
            # since those are always genuine copy-paste issues regardless of
            # where in the section they appear.
            if ctx_a == ctx_b and sim < 1.0:
                continue
            if sim >= threshold:
                duplicates.append(
                    {
                        "text_a": text_a[:200],
                        "text_b": text_b[:200],
                        "context_a": ctx_a,
                        "context_b": ctx_b,
                        "similarity": round(sim, 3),
                    }
                )

    # Sort by similarity descending
    duplicates.sort(key=lambda d: d["similarity"], reverse=True)

    if duplicates:
        logging.warning(f"Found {len(duplicates)} near-duplicate paragraph pair(s)")
    else:
        logging.info("No near-duplicate paragraphs found")

    return duplicates


def _shingle(words: list[str], k: int = 3) -> frozenset[tuple]:
    """Create k-shingles from a word list."""
    if len(words) < k:
        return frozenset()
    return frozenset(tuple(words[i : i + k]) for i in range(len(words) - k + 1))


def _jaccard(a: frozenset, b: frozenset) -> float:
    """Compute Jaccard similarity between two sets."""
    if not a or not b:
        return 0.0
    intersection = len(a & b)
    union = len(a | b)
    return intersection / union if union > 0 else 0.0


def report_duplicates(duplicates: list[dict], *, strict: bool = False) -> None:
    """Log duplicate detection findings.

    Args:
        duplicates: List from :func:`detect_duplicates`.
        strict: If True, exit with error when duplicates are found.
    """
    if not duplicates:
        logging.info("Duplicate detection passed: no near-duplicates found")
        return

    logging.warning(f"Duplicate detection: {len(duplicates)} pair(s)")
    for dup in duplicates[:20]:
        logging.warning(
            f'  {dup["similarity"]:.0%} similar — "{dup["context_a"]}" vs "{dup["context_b"]}"'
        )

    if strict:
        raise SystemExit(1)


def write_duplicates(duplicates: list[dict], output_path: Path) -> None:
    """Write duplicate detection results as JSON."""
    output_path.write_text(json.dumps(duplicates, indent=2), encoding="utf-8")
    logging.info(f"Duplicate detection results written to {output_path}")


def render_duplicates_html(duplicates: list[dict]) -> str:
    """Render duplicate detection results as an HTML page."""
    rows = ""
    for dup in duplicates[:100]:
        pct = f"{dup['similarity']:.0%}"
        rows += (
            f"<tr>"
            f'<td class="num">{pct}</td>'
            f"<td>{_html.escape(dup['context_a'])}</td>"
            f"<td>{_html.escape(dup['context_b'])}</td>"
            f'<td class="snippet">{_html.escape(dup["text_a"][:120])}...</td>'
            f"</tr>\n"
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Duplicate Paragraph Detection</title>
<style>
body {{ font-family: system-ui, sans-serif; max-width: 1100px; margin: 2em auto; }}
h1 {{ font-size: 1.4em; }}
.summary {{ color: #666; }}
table {{ border-collapse: collapse; width: 100%; font-size: 0.88em; margin: 1em 0; }}
th, td {{ padding: 6px 10px; border: 1px solid #ddd; text-align: left; }}
th {{ background: #f5f5f5; font-weight: 600; }}
td.num {{ text-align: right; font-weight: 600; }}
td.snippet {{ max-width: 400px; font-size: 0.85em; color: #444; }}
</style>
</head>
<body>
<h1>Duplicate Paragraph Detection</h1>
<p class="summary">{len(duplicates)} near-duplicate pair(s) found</p>

<table>
<thead><tr><th>Similarity</th><th>Section A</th><th>Section B</th><th>Text Preview</th></tr></thead>
<tbody>{rows}</tbody>
</table>
</body>
</html>"""
