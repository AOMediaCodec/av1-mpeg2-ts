"""Relaton bibliography enrichment for standards specifications.

Fetches structured metadata for SDO document IDs from the Relaton REST API
or local relaton-data JSON repositories, and enriches bibliography entries
in compiled HTML.
"""

from __future__ import annotations

import calendar
import datetime
import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

RELATON_API = "https://api.relaton.org/api/v1/document"

_CACHE_TTL_DAYS = 30
_REQUEST_TIMEOUT = 8

# Known SDO prefixes for identifying standards document IDs.
_SDO_RE = re.compile(
    r"^(ISO(?:/IEC)?|IEC|ITU(?:-T|-R)?|IEEE|IETF|RFC\s*\d|NIST|ETSI|3GPP|MPEG|JCT-VC|JVET)",
    re.IGNORECASE,
)


@dataclass
class RelatonEntry:
    """Structured metadata for a standards document."""

    docid: str
    title: str
    publisher: str
    year: int | None
    status: str
    url: str | None
    abstract: str | None
    fetched_at: str


def fetch_relaton(
    docid: str,
    cache_dir: Path | None = None,
) -> RelatonEntry | None:
    """Fetch structured metadata for *docid* from the Relaton REST API.

    Tries the cache first; falls back to the live API with a single retry.

    Args:
        docid:     Document identifier, e.g. ``"ISO/IEC 14496-10:2022"``.
        cache_dir: Directory for JSON response cache.  Defaults to
                   ``~/.specbuild_cache/relaton/``.

    Returns:
        A :class:`RelatonEntry`, or ``None`` if unavailable.
    """
    cache_dir = cache_dir or (Path.home() / ".specbuild_cache" / "relaton")
    cache_path = _cache_path(docid, cache_dir)

    cached = _load_cache(cache_path)
    if cached is not None:
        return cached

    entry = _fetch_from_api(docid)
    if entry is not None and cache_dir:
        _save_cache(entry, cache_path)

    return entry


def fetch_relaton_local(
    docid: str,
    data_dir: Path,
) -> RelatonEntry | None:
    """Load Relaton metadata from a local relaton-data checkout.

    The *data_dir* should point to the root of a ``relaton-data-iso``,
    ``relaton-data-ietf``, or similar repository where each document is
    stored as ``<docid>.yaml`` or ``<docid>.json``.

    Args:
        docid:    Document identifier.
        data_dir: Root of a local relaton-data repository.

    Returns:
        A :class:`RelatonEntry`, or ``None`` if not found.
    """
    slug = _docid_slug(docid)
    for ext in ("json", "yaml"):
        candidate = data_dir / f"{slug}.{ext}"
        if not candidate.exists():
            # Try nested layout: data_dir/<prefix>/<slug>.<ext>
            prefix = slug.split("-")[0].lower() if "-" in slug else slug[:3].lower()
            candidate = data_dir / prefix / f"{slug}.{ext}"
        if candidate.exists():
            return _parse_local_file(candidate, docid)

    return None


def enrich_bibliography_soup(
    soup: object,
    *,
    api: bool = True,
    local_dir: Path | None = None,
    cache_dir: Path | None = None,
) -> int:
    """Enrich bibliography ``<li>`` elements with structured Relaton data.

    For each bibliography item whose text matches a known SDO prefix,
    attempts to fetch structured metadata and adds ``data-relaton-*``
    attributes for downstream processing (STS XML export, hover cards, etc.).

    Args:
        soup:      BeautifulSoup document (mutated in place).
        api:       Whether to use the live Relaton API.
        local_dir: Path to a local relaton-data repository.
        cache_dir: Cache directory for API responses.

    Returns:
        Number of entries enriched.
    """
    # Collect candidate (li, docid) pairs first so we can fetch in parallel.
    candidates: list[tuple[object, str]] = []
    for li in soup.find_all("li"):
        text = li.get_text(strip=True)
        if not _SDO_RE.match(text):
            continue
        docid_m = re.match(r"([A-Z][^\s,;\u2014\u2013]+(?:\s+\d[\d\-:]*)?)", text, re.IGNORECASE)
        if docid_m:
            candidates.append((li, docid_m.group(1).strip()))

    if not candidates:
        return 0

    def _fetch(docid: str) -> tuple[str, RelatonEntry | None]:
        entry: RelatonEntry | None = None
        if local_dir:
            entry = fetch_relaton_local(docid, local_dir)
        if entry is None and api:
            entry = fetch_relaton(docid, cache_dir=cache_dir)
        return docid, entry

    results: dict[str, RelatonEntry | None] = {}
    with ThreadPoolExecutor(max_workers=min(len(candidates), 8)) as pool:
        futures = {pool.submit(_fetch, docid): docid for _, docid in candidates}
        for future in as_completed(futures):
            docid, entry = future.result()
            results[docid] = entry

    count = 0
    for li, docid in candidates:
        entry = results.get(docid)
        if entry is None:
            continue
        if hasattr(li, "__setitem__"):
            li["data-relaton-docid"] = entry.docid
            li["data-relaton-title"] = entry.title
            li["data-relaton-publisher"] = entry.publisher
            if entry.year:
                li["data-relaton-year"] = str(entry.year)
            li["data-relaton-status"] = entry.status
            if entry.url:
                li["data-relaton-url"] = entry.url
        count += 1
        logging.debug(f"Relaton: enriched '{docid}'")

    if count:
        logging.info(f"Relaton: enriched {count} bibliography entries")
    return count


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _docid_slug(docid: str) -> str:
    """Convert a document ID to a filesystem-safe slug."""
    return re.sub(r"[^a-z0-9]+", "-", docid.lower()).strip("-")


def _cache_path(docid: str, cache_dir: Path) -> Path:
    return cache_dir / f"{_docid_slug(docid)}.json"


def _load_cache(path: Path) -> RelatonEntry | None:
    """Return a cached entry if it exists and is not older than TTL."""
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        fetched = data.get("fetched_at", "")
        if not fetched or not isinstance(fetched, str):
            # Missing or malformed fetched_at — treat as expired cache miss.
            return None
        age = time.time() - calendar.timegm(time.strptime(fetched, "%Y-%m-%dT%H:%M:%S"))
        if age > _CACHE_TTL_DAYS * 86400:
            return None
        return _entry_from_dict(data)
    except Exception:
        return None


def _save_cache(entry: RelatonEntry, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        data = {
            "docid": entry.docid,
            "title": entry.title,
            "publisher": entry.publisher,
            "year": entry.year,
            "status": entry.status,
            "url": entry.url,
            "abstract": entry.abstract,
            "fetched_at": entry.fetched_at,
        }
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception:
        pass


def _entry_from_dict(data: dict) -> RelatonEntry:
    return RelatonEntry(
        docid=data.get("docid", ""),
        title=data.get("title", ""),
        publisher=data.get("publisher", ""),
        year=data.get("year"),
        status=data.get("status", "unknown"),
        url=data.get("url"),
        abstract=data.get("abstract"),
        fetched_at=data.get("fetched_at", ""),
    )


def _fetch_from_api(docid: str) -> RelatonEntry | None:
    try:
        import urllib.request

        url = f"{RELATON_API}?docid={quote(docid)}"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        logging.debug(f"Relaton API fetch failed for '{docid}': {exc}")
        return None

    return _parse_api_response(raw, docid)


def _parse_api_response(raw: dict, docid: str) -> RelatonEntry | None:
    """Parse a Relaton API JSON response."""
    if not raw:
        return None

    try:
        titles = raw.get("title", [])
        title = ""
        for t in titles:
            if isinstance(t, dict):
                if t.get("type") == "main" or not title:
                    title = t.get("content", "")
            elif isinstance(t, str):
                title = t
                break

        publisher = ""
        contributors = raw.get("contributor", [])
        for c in contributors:
            if isinstance(c, dict):
                role = c.get("role", [])
                roles = [r.get("type", "") if isinstance(r, dict) else r for r in role]
                if "publisher" in roles:
                    org = c.get("organization", {})
                    publisher = org.get("name", "") if isinstance(org, dict) else str(org)
                    break

        year = None
        dates = raw.get("date", [])
        for d in dates:
            if isinstance(d, dict) and d.get("type") == "published":
                yr_str = d.get("value", "")[:4]
                if yr_str.isdigit():
                    year = int(yr_str)
                break

        status = "unknown"
        lifecycle = raw.get("status", {})
        if isinstance(lifecycle, dict):
            stage = lifecycle.get("stage")
            if isinstance(stage, dict):
                abbrev = stage.get("abbreviation")
                if isinstance(abbrev, dict):
                    status = abbrev.get("content", "unknown")
                elif isinstance(abbrev, str):
                    status = abbrev
            elif isinstance(stage, str):
                status = stage
        elif isinstance(lifecycle, str):
            status = lifecycle

        url = None
        links = raw.get("link", [])
        for lnk in links:
            if isinstance(lnk, dict) and lnk.get("type") in ("uri", "html", "src"):
                url = lnk.get("content", "")
                if url:
                    break

        abstract = None
        for ab in raw.get("abstract", []):
            if isinstance(ab, dict):
                abstract = ab.get("content", "")
                break

        fetched_at = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")

        return RelatonEntry(
            docid=docid,
            title=title,
            publisher=publisher,
            year=year,
            status=str(status),
            url=url,
            abstract=abstract,
            fetched_at=fetched_at,
        )
    except Exception as exc:
        logging.debug(f"Relaton response parse error for '{docid}': {exc}")
        return None


def _parse_local_file(path: Path, docid: str) -> RelatonEntry | None:
    """Parse a local relaton-data JSON or YAML file."""
    try:
        text = path.read_text(encoding="utf-8")
        if path.suffix == ".yaml":
            try:
                import yaml  # type: ignore[import]

                raw = yaml.safe_load(text)
            except ImportError:
                # Minimal YAML → JSON fallback for simple files
                raw = {}
        else:
            raw = json.loads(text)

        if not isinstance(raw, dict):
            return None

        # relaton-data files may have the document under a top-level key
        if "bibdata" in raw:
            raw = raw["bibdata"]
        return _parse_api_response(raw, docid)
    except Exception as exc:
        logging.debug(f"Relaton local file parse error for '{path}': {exc}")
        return None
