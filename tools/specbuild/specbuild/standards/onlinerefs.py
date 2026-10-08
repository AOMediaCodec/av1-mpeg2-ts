"""Online reference resolution and validation via public APIs.

Queries public APIs (IETF Datatracker, CrossRef/DOI, ISO catalog) to
validate and fetch metadata for standards references.  This is opt-in
via ``--online-refs`` and caches results locally to avoid repeated
network calls.

The module uses only the Python standard library (``urllib.request``,
``json``) and requires no new dependencies.  All network calls have a
10-second timeout and fall back gracefully to the static reference
database when offline or when an API call fails.

Usage::

    from specbuild.standards.onlinerefs import (
        resolve_reference_online,
        validate_references_online,
    )

    # Single reference lookup
    meta = resolve_reference_online("RFC 2119")

    # Batch validation of bibliography entries
    issues = validate_references_online([
        "RFC 2119, Key words for use in RFCs",
        "ISO/IEC 14496-10:2022, Advanced video coding",
    ])
"""

from __future__ import annotations

import json
import logging
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)

#: Default location for the reference cache file.
_DEFAULT_CACHE_PATH = Path(".specbuild_ref_cache.json")

#: Network timeout for all HTTP requests (seconds).
_REQUEST_TIMEOUT = 10

#: Default maximum age for cache entries (days).
_DEFAULT_MAX_AGE_DAYS = 30

# ---------------------------------------------------------------------------
# Cache management
# ---------------------------------------------------------------------------


def _load_cache(path: Path) -> dict:
    """Load the reference cache from disk.

    Args:
        path: Path to the JSON cache file.

    Returns:
        Cache dict mapping identifiers to entry dicts.  Each entry has
        ``"data"`` (the resolved metadata) and ``"timestamp"`` (epoch
        seconds when it was cached).  Returns an empty dict if the file
        does not exist or is malformed.
    """
    if not path.exists():
        return {}
    try:
        text = path.read_text(encoding="utf-8")
        cache = json.loads(text)
        if not isinstance(cache, dict):
            return {}
        return cache
    except (json.JSONDecodeError, OSError):
        logger.debug("Could not load reference cache from %s", path)
        return {}


def _save_cache(path: Path, cache: dict) -> None:
    """Save the reference cache to disk.

    Args:
        path: Path to the JSON cache file.
        cache: Full cache dict to serialize.
    """
    try:
        path.write_text(
            json.dumps(cache, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError:
        logger.debug("Could not save reference cache to %s", path)


def _is_cache_fresh(entry: dict, max_age_days: int = _DEFAULT_MAX_AGE_DAYS) -> bool:
    """Check if a cache entry is still fresh.

    Args:
        entry: A cache entry dict with a ``"timestamp"`` key.
        max_age_days: Maximum age in days before the entry is stale.

    Returns:
        ``True`` if the entry is younger than *max_age_days*.
    """
    ts = entry.get("timestamp")
    if not isinstance(ts, (int, float)):
        return False
    age_secs = time.time() - ts
    return age_secs < max_age_days * 86400


# ---------------------------------------------------------------------------
# Identifier parsing helpers
# ---------------------------------------------------------------------------

#: Pattern for RFC identifiers (e.g. "RFC 2119", "RFC2119").
_RFC_RE = re.compile(r"RFC\s*(\d{3,5})", re.IGNORECASE)

#: Pattern for DOI identifiers (e.g. "10.1000/xyz123").
_DOI_RE = re.compile(r"\b(10\.\d{4,}/[^\s,;]+)")

#: Pattern for ISO/IEC document numbers (e.g. "ISO/IEC 14496-10",
#: "ISO 8601-1").
_ISO_RE = re.compile(
    r"(?:ISO/?IEC|ISO)\s+(\d[\d.-]+)",
    re.IGNORECASE,
)


def _extract_rfc_number(identifier: str) -> str | None:
    """Extract an RFC number from an identifier string.

    Returns the bare number (e.g. ``"2119"``) or ``None``.
    """
    m = _RFC_RE.search(identifier)
    return m.group(1) if m else None


def _extract_doi(identifier: str) -> str | None:
    """Extract a DOI from an identifier string.

    Returns the DOI (e.g. ``"10.1000/xyz123"``) or ``None``.
    """
    m = _DOI_RE.search(identifier)
    return m.group(1) if m else None


def _extract_iso_docnumber(identifier: str) -> str | None:
    """Extract an ISO/IEC document number from an identifier string.

    Returns the document number portion (e.g. ``"14496-10"``) or
    ``None``.
    """
    m = _ISO_RE.search(identifier)
    return m.group(1) if m else None


# ---------------------------------------------------------------------------
# IETF Datatracker resolver
# ---------------------------------------------------------------------------


def _resolve_ietf(docnumber: str) -> dict | None:
    """Query IETF Datatracker for RFC metadata.

    Uses the public JSON API at
    ``https://datatracker.ietf.org/api/v1/doc/document/``.

    Args:
        docnumber: Bare RFC number (e.g. ``"2119"``).

    Returns:
        Dict with keys ``title``, ``current_year``, ``status``,
        ``abstract``, ``body``, ``docnumber`` on success, or ``None``
        on failure.
    """
    url = f"https://datatracker.ietf.org/api/v1/doc/document/?name=rfc{docnumber}&format=json"
    logger.debug("IETF lookup: %s", url)
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, json.JSONDecodeError, ValueError) as exc:
        logger.debug("IETF lookup failed for RFC %s: %s", docnumber, exc)
        return None

    objects = data.get("objects", [])
    if not objects:
        return None

    doc = objects[0]
    if not isinstance(doc, dict):
        return None
    title = doc.get("title", "")
    # The time field is ISO-format; extract the year.
    rfc_time = doc.get("time", "")
    year = rfc_time[:4] if len(rfc_time) >= 4 else ""
    status = doc.get("std_level", "") or doc.get("intended_std_level", "") or ""
    abstract = doc.get("abstract", "")

    return {
        "title": title,
        "current_year": year,
        "status": status,
        "abstract": abstract[:500] if abstract else "",
        "body": "IETF",
        "docnumber": f"RFC {docnumber}",
    }


# ---------------------------------------------------------------------------
# CrossRef / DOI resolver
# ---------------------------------------------------------------------------


def _resolve_doi(doi: str) -> dict | None:
    """Query CrossRef API for document metadata from a DOI.

    Uses the public API at ``https://api.crossref.org/works/{doi}``.

    Args:
        doi: A DOI string (e.g. ``"10.1000/xyz123"``).

    Returns:
        Dict with keys ``title``, ``current_year``, ``authors``,
        ``publisher``, ``body``, ``docnumber`` on success, or ``None``
        on failure.
    """
    url = f"https://api.crossref.org/works/{doi}"
    logger.debug("CrossRef lookup: %s", url)
    try:
        req = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "specbuild/1.0 (https://github.com/AOMMediaCodec; mailto:noreply@aomedia.org)",
            },
        )
        with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, json.JSONDecodeError, ValueError) as exc:
        logger.debug("CrossRef lookup failed for DOI %s: %s", doi, exc)
        return None

    message = data.get("message", {})
    if not message:
        return None

    title_list = message.get("title", [])
    title = title_list[0] if title_list else ""

    # Extract year from published-print or published-online
    year = ""
    for date_field in ("published-print", "published-online", "created"):
        parts = message.get(date_field, {}).get("date-parts", [[]])
        if parts and parts[0]:
            year = str(parts[0][0])
            break

    # Authors
    authors_raw = message.get("author", [])
    authors = []
    for a in authors_raw[:10]:  # cap at 10
        if not isinstance(a, dict):
            continue
        family = a.get("family", "")
        given = a.get("given", "")
        if family:
            authors.append(f"{given} {family}".strip())

    publisher = message.get("publisher", "")

    return {
        "title": title,
        "current_year": year,
        "authors": ", ".join(authors),
        "publisher": publisher,
        "body": "DOI",
        "docnumber": doi,
    }


# ---------------------------------------------------------------------------
# ISO pattern resolver (simulated / format-based)
# ---------------------------------------------------------------------------

#: Pattern to parse ISO document numbers into parts.
#: Matches: "14496-10", "8601-1:2019", "80000-2"
_ISO_PARTS_RE = re.compile(
    r"^(\d+)(?:-(\d+))?(?::(\d{4}))?",
)


def _resolve_iso(docnumber: str) -> dict | None:
    """Resolve ISO standard metadata from document number pattern.

    This is a format-based resolver that validates the ISO document
    number pattern and constructs metadata heuristically.  It does not
    perform a live ISO catalog lookup (the ISO OBP does not offer a
    stable public API).

    Actual live ISO lookup can be enhanced in a future iteration.

    Args:
        docnumber: ISO document number (e.g. ``"14496-10"``,
            ``"8601-1"``).

    Returns:
        Dict with keys ``title``, ``current_year``, ``status``,
        ``body``, ``docnumber`` if the format is valid, or ``None``
        if the docnumber does not match ISO patterns.
    """
    m = _ISO_PARTS_RE.match(docnumber)
    if not m:
        return None

    main_number = m.group(1)
    part = m.group(2) or ""
    year = m.group(3) or ""

    # Construct a canonical docnumber
    canonical = main_number
    if part:
        canonical = f"{main_number}-{part}"

    # Try the static refdb for a title before falling back
    from specbuild.standards.refdb import lookup_standard

    # Try both ISO and ISO/IEC prefixes
    for prefix in ("ISO/IEC", "ISO"):
        ref = lookup_standard(f"{prefix} {canonical}")
        if ref is not None:
            return {
                "title": ref.title,
                "current_year": ref.current_year,
                "status": ref.status,
                "body": ref.body,
                "docnumber": f"{ref.body} {ref.docnumber}",
            }

    # Format is valid but not in the static database
    return {
        "title": "",
        "current_year": year,
        "status": "unknown",
        "body": "ISO",
        "docnumber": f"ISO {canonical}",
    }


# ---------------------------------------------------------------------------
# Main resolution interface
# ---------------------------------------------------------------------------


def resolve_reference_online(
    identifier: str,
    cache_path: Path | None = None,
    *,
    _cache: dict | None = None,
) -> dict[str, str] | None:
    """Resolve a reference identifier via online APIs.

    Tries resolvers in order: IETF -> CrossRef -> ISO pattern.
    Caches successful results in a local JSON file.

    Args:
        identifier: Document identifier (e.g. ``"RFC 2119"``,
            ``"ISO 14496-10"``, or a DOI).
        cache_path: Path to cache file (default:
            ``.specbuild_ref_cache.json`` in the current directory).
        _cache: Pre-loaded cache dict (internal, used by
            :func:`validate_references_online` to avoid repeated disk
            reads).  When provided the caller is responsible for saving
            the cache after the batch is complete.

    Returns:
        Dict with keys ``title``, ``current_year``, ``status``,
        ``body``, ``docnumber`` on success, or ``None`` if resolution
        failed.
    """
    if not identifier or not identifier.strip():
        return None

    if cache_path is None:
        cache_path = _DEFAULT_CACHE_PATH

    # Normalize cache key
    cache_key = identifier.strip().upper()

    # Use caller-supplied cache or load from disk
    _owns_cache = _cache is None
    if _owns_cache:
        _cache = _load_cache(cache_path)

    # Check cache first
    entry = _cache.get(cache_key)
    if entry and _is_cache_fresh(entry):
        logger.debug("Cache hit for %s", cache_key)
        return entry.get("data")

    # Try resolvers in order
    result: dict | None = None

    # 1. IETF / RFC
    rfc_num = _extract_rfc_number(identifier)
    if rfc_num is not None:
        result = _resolve_ietf(rfc_num)

    # 2. CrossRef / DOI
    if result is None:
        doi = _extract_doi(identifier)
        if doi is not None:
            result = _resolve_doi(doi)

    # 3. ISO pattern
    if result is None:
        iso_num = _extract_iso_docnumber(identifier)
        if iso_num is not None:
            result = _resolve_iso(iso_num)

    # Cache the result (even None results are NOT cached to allow retry)
    if result is not None:
        _cache[cache_key] = {
            "data": result,
            "timestamp": time.time(),
        }
        # Only write to disk when we own the cache (single-reference call)
        if _owns_cache:
            _save_cache(cache_path, _cache)

    return result


# ---------------------------------------------------------------------------
# Batch validation interface
# ---------------------------------------------------------------------------


def validate_references_online(
    entries: list[str],
    cache_path: Path | None = None,
) -> list[dict[str, str]]:
    """Validate a list of bibliography entries using online APIs.

    For each entry:

    1. Extract the document identifier.
    2. Try online resolution.
    3. Compare cited year vs resolved current year.
    4. Check if the standard is still active.

    The reference cache is loaded once before the loop and saved once
    at the end to minimise disk I/O.

    Args:
        entries: List of bibliography entry text strings.
        cache_path: Path to cache file (default:
            ``.specbuild_ref_cache.json``).

    Returns:
        List of issue dicts, each with keys ``level``, ``rule``,
        ``message``, ``section``, and ``reference``.
    """
    from specbuild.standards.refdb import extract_cited_year, extract_doc_identifier

    if cache_path is None:
        cache_path = _DEFAULT_CACHE_PATH

    # Load the cache once for the entire batch
    shared_cache: dict = _load_cache(cache_path)
    cache_dirty = False

    issues: list[dict[str, str]] = []

    for entry_text in entries:
        doc_id = extract_doc_identifier(entry_text)
        if not doc_id:
            continue

        cache_key = doc_id.strip().upper()
        prev_entry = shared_cache.get(cache_key)
        meta = resolve_reference_online(doc_id, cache_path=cache_path, _cache=shared_cache)
        if shared_cache.get(cache_key) is not prev_entry:
            cache_dirty = True

        if meta is None:
            continue

        # Compare cited year vs current year from API
        cited_year = extract_cited_year(entry_text)
        api_year = meta.get("current_year", "")
        if cited_year and api_year and cited_year < api_year:
            issues.append(
                {
                    "level": "warning",
                    "rule": "online-ref-outdated",
                    "message": (
                        f"'{doc_id}' cites year {cited_year}, but online "
                        f"lookup found year {api_year}."
                    ),
                    "section": "",
                    "reference": entry_text[:120],
                }
            )

        # Check status if available
        status = meta.get("status", "")
        if isinstance(status, str):
            status_lower = status.lower()
            if "obsolete" in status_lower or "withdrawn" in status_lower:
                issues.append(
                    {
                        "level": "warning",
                        "rule": "online-ref-status",
                        "message": (
                            f"'{doc_id}' has online status '{status}' "
                            f"— may be obsolete or withdrawn."
                        ),
                        "section": "",
                        "reference": entry_text[:120],
                    }
                )

    # Save the cache once at the end if any new entries were added
    if cache_dirty:
        _save_cache(cache_path, shared_cache)

    return issues
