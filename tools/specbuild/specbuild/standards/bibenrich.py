"""Bibliography auto-enrichment via DOI / Crossref / arXiv lookups.

Given bibliography entries that contain only an identifier (DOI, arXiv ID,
ISBN), this module fetches missing metadata (title, authors, year,
publisher) from public APIs and fills in the gaps.  Existing fields are
never overwritten — the user's explicit metadata always wins.

Results are cached on disk under ``cache_dir`` (default
``~/.specbuild_cache/bibenrich/``) so repeated builds are reproducible
and don't hammer the upstream services.

Usage::

    from specbuild.standards.bibenrich import enrich_bib_file
    n = enrich_bib_file(Path("refs.toml"), Path("refs.enriched.toml"))

The CLI entry point ``--bib-enrich FILE`` calls :func:`enrich_bib_file`
and exits — it is a one-shot tool, not part of the regular build.
"""

from __future__ import annotations

import hashlib
import json
import logging
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: Polite User-Agent string sent with every outbound request.
USER_AGENT = "specbuild-bibenrich/1.0 (mailto: build@local)"

#: Default on-disk cache location.
DEFAULT_CACHE_DIR = Path.home() / ".specbuild_cache" / "bibenrich"

#: arXiv Atom XML namespace.
_ATOM_NS = "http://www.w3.org/2005/Atom"

#: Crossref REST API endpoint (works lookup by DOI).
_CROSSREF_URL = "https://api.crossref.org/works/{doi}"

#: arXiv API endpoint (Atom XML response).
_ARXIV_URL = "https://export.arxiv.org/api/query?id_list={arxiv_id}"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _safe_doi_name(doi: str) -> str:
    """Convert a DOI into a filesystem-safe cache filename stem.

    Hashes the DOI with SHA-256 to produce a fixed-length hex string.
    This avoids any path-traversal risk from DOIs containing ``..``,
    ``/``, ``\\`` or other special characters, and works identically on
    every platform we support.  The original DOI is preserved inside the
    cached JSON payload.
    """
    return hashlib.sha256(doi.encode("utf-8")).hexdigest()


def _safe_arxiv_name(arxiv_id: str) -> str:
    """Hash an arXiv ID for use as a cache filename stem.

    Like :func:`_safe_doi_name`, this prevents any path traversal via
    crafted IDs (e.g. ``../foo`` or ``..\\foo``).  The original arXiv
    ID is recorded inside the cached payload.
    """
    return hashlib.sha256(arxiv_id.encode("utf-8")).hexdigest()


def _ensure_cache_dir(cache_dir: Path | None, sub: str) -> Path | None:
    """Create ``cache_dir / sub`` if requested; return the resolved path."""
    if cache_dir is None:
        return None
    target = Path(cache_dir) / sub
    try:
        target.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.warning("Could not create bibenrich cache dir %s: %s", target, exc)
        return None
    return target


def _get_session(_session: Any | None) -> Any:
    """Return a session-like object with a polite User-Agent set.

    Importing ``requests`` is deferred so importing this module remains
    cheap when the caller never makes a network call (e.g. cache hit).
    """
    if _session is not None:
        return _session
    import requests as _requests  # local import keeps module import cheap

    sess = _requests.Session()
    sess.headers.update({"User-Agent": USER_AGENT})
    return sess


def _read_cache(cache_path: Path) -> dict | None:
    """Read a cached JSON payload from disk, or ``None`` on any failure."""
    try:
        return json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _write_cache(cache_path: Path, payload: Any) -> None:
    """Write a payload as JSON to ``cache_path``; warn on failure."""
    try:
        cache_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except (OSError, TypeError) as exc:
        logger.warning("Could not write bibenrich cache %s: %s", cache_path, exc)


# ---------------------------------------------------------------------------
# Crossref / DOI lookup
# ---------------------------------------------------------------------------


def _parse_crossref(payload: dict) -> dict | None:
    """Convert a Crossref ``message`` envelope into our entry dict."""
    msg = payload.get("message") if isinstance(payload, dict) else None
    if not isinstance(msg, dict):
        return None

    # Title — Crossref returns a list; first element is canonical.
    title = None
    titles = msg.get("title")
    if isinstance(titles, list) and titles:
        title = str(titles[0]).strip() or None

    # Authors — list of dicts with given/family.
    authors: list[str] = []
    for a in msg.get("author") or []:
        if not isinstance(a, dict):
            continue
        given = (a.get("given") or "").strip()
        family = (a.get("family") or "").strip()
        full = " ".join(p for p in (given, family) if p).strip()
        if full:
            authors.append(full)

    # Year — message.published.date-parts[0][0] (Crossref's preferred path).
    year: str | None = None
    published = msg.get("published")
    if isinstance(published, dict):
        parts = published.get("date-parts")
        if isinstance(parts, list) and parts and isinstance(parts[0], list) and parts[0]:
            year = str(parts[0][0])
    if year is None:
        # Fall back to issued / created if "published" is absent.
        for key in ("issued", "created", "published-online", "published-print"):
            alt = msg.get(key)
            if isinstance(alt, dict):
                parts = alt.get("date-parts")
                if isinstance(parts, list) and parts and isinstance(parts[0], list) and parts[0]:
                    year = str(parts[0][0])
                    break

    publisher = msg.get("publisher")
    publisher = str(publisher).strip() if publisher else None

    doi = msg.get("DOI") or msg.get("doi")
    doi = str(doi).strip() if doi else None

    result: dict[str, Any] = {}
    if title:
        result["title"] = title
    if authors:
        result["authors"] = authors
    if year:
        result["year"] = year
    if publisher:
        result["publisher"] = publisher
    if doi:
        result["doi"] = doi
    return result or None


def lookup_doi(
    doi: str,
    *,
    cache_dir: Path | None = None,
    timeout: float = 10.0,
    _session: Any | None = None,
) -> dict | None:
    """Look up bibliography metadata for a DOI via Crossref.

    Args:
        doi: A DOI such as ``10.1109/TIP.2003.819861``.  Leading
            ``https://doi.org/`` prefixes are stripped.
        cache_dir: Directory to cache raw Crossref responses under
            ``cache_dir/doi/<safe-doi>.json``.  If ``None`` (default),
            no caching is performed.
        timeout: Per-request timeout in seconds.
        _session: Optional ``requests``-compatible session for testing
            (must expose ``.get(url, timeout=...)`` returning an object
            with ``.status_code`` and ``.json()``).

    Returns:
        Dict with keys ``title``, ``authors``, ``year``, ``publisher``,
        ``doi`` (omitted when missing), or ``None`` on any error
        (network failure, 4xx/5xx, malformed JSON).
    """
    if not doi:
        return None
    doi = doi.strip()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if doi.lower().startswith(prefix):
            doi = doi[len(prefix) :]
            break

    cache_root = _ensure_cache_dir(cache_dir, "doi")
    cache_path = cache_root / f"{_safe_doi_name(doi)}.json" if cache_root else None

    payload: dict | None = None
    if cache_path and cache_path.exists():
        cached = _read_cache(cache_path)
        if cached is not None:
            # Cache files store ``{"doi": "...", "response": {...}}``.
            # Older format (raw Crossref envelope) is still recognised
            # so existing caches keep working.
            if isinstance(cached, dict) and "response" in cached:
                payload = cached.get("response")
            else:
                payload = cached
            logger.debug("bibenrich: DOI cache hit for %s", doi)

    if payload is None:
        try:
            sess = _get_session(_session)
            resp = sess.get(_CROSSREF_URL.format(doi=doi), timeout=timeout)
        except Exception as exc:  # noqa: BLE001 — tolerate any network failure
            logger.warning("bibenrich: Crossref lookup failed for %s: %s", doi, exc)
            return None

        status = getattr(resp, "status_code", None)
        if status != 200:
            logger.warning("bibenrich: Crossref returned %s for DOI %s", status, doi)
            return None
        try:
            payload = resp.json()
        except Exception as exc:  # noqa: BLE001
            logger.warning("bibenrich: Crossref JSON parse failed for %s: %s", doi, exc)
            return None

        if cache_path is not None:
            _write_cache(cache_path, {"doi": doi, "response": payload})

    return _parse_crossref(payload)


# ---------------------------------------------------------------------------
# arXiv lookup
# ---------------------------------------------------------------------------


def _parse_arxiv(xml_text: str) -> dict | None:
    """Parse an arXiv Atom feed for the first ``<entry>``."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        logger.warning("bibenrich: arXiv XML parse failed: %s", exc)
        return None

    entry = root.find(f"{{{_ATOM_NS}}}entry")
    if entry is None:
        return None

    title_el = entry.find(f"{{{_ATOM_NS}}}title")
    title = (title_el.text or "").strip() if title_el is not None else ""
    # arXiv inserts soft newlines/extra whitespace inside <title>.
    title = " ".join(title.split()) or None

    authors: list[str] = []
    for author_el in entry.findall(f"{{{_ATOM_NS}}}author"):
        name_el = author_el.find(f"{{{_ATOM_NS}}}name")
        if name_el is not None and name_el.text:
            n = name_el.text.strip()
            if n:
                authors.append(n)

    year: str | None = None
    pub_el = entry.find(f"{{{_ATOM_NS}}}published")
    if pub_el is not None and pub_el.text:
        text = pub_el.text.strip()
        if len(text) >= 4 and text[:4].isdigit():
            year = text[:4]

    id_el = entry.find(f"{{{_ATOM_NS}}}id")
    arxiv_url = id_el.text.strip() if (id_el is not None and id_el.text) else None

    result: dict[str, Any] = {"publisher": "arXiv"}
    if title:
        result["title"] = title
    if authors:
        result["authors"] = authors
    if year:
        result["year"] = year
    if arxiv_url:
        result["arxiv_url"] = arxiv_url
    # Drop the implicit publisher if nothing else was extracted.
    if set(result.keys()) == {"publisher"}:
        return None
    return result


def lookup_arxiv(
    arxiv_id: str,
    *,
    cache_dir: Path | None = None,
    timeout: float = 10.0,
    _session: Any | None = None,
) -> dict | None:
    """Look up bibliography metadata for an arXiv ID via the arXiv API.

    Args:
        arxiv_id: arXiv identifier such as ``2301.07041`` or
            ``cs.CV/0701001``.  ``arXiv:`` prefixes are stripped.
        cache_dir: Directory to cache the raw Atom XML under
            ``cache_dir/arxiv/<id>.xml``.  ``None`` disables caching.
        timeout: Per-request timeout in seconds.
        _session: Optional injected ``requests`` session for testing.

    Returns:
        Dict in the same shape as :func:`lookup_doi`, plus
        ``arxiv_url``; ``None`` on any failure.
    """
    if not arxiv_id:
        return None
    arxiv_id = arxiv_id.strip()
    if arxiv_id.lower().startswith("arxiv:"):
        arxiv_id = arxiv_id[len("arxiv:") :]

    cache_root = _ensure_cache_dir(cache_dir, "arxiv")
    safe_name = _safe_arxiv_name(arxiv_id)
    cache_path = cache_root / f"{safe_name}.xml" if cache_root else None

    xml_text: str | None = None
    if cache_path and cache_path.exists():
        try:
            xml_text = cache_path.read_text(encoding="utf-8")
            logger.debug("bibenrich: arXiv cache hit for %s", arxiv_id)
        except OSError:
            xml_text = None

    if xml_text is None:
        try:
            sess = _get_session(_session)
            resp = sess.get(_ARXIV_URL.format(arxiv_id=arxiv_id), timeout=timeout)
        except Exception as exc:  # noqa: BLE001
            logger.warning("bibenrich: arXiv lookup failed for %s: %s", arxiv_id, exc)
            return None
        status = getattr(resp, "status_code", None)
        if status != 200:
            logger.warning("bibenrich: arXiv returned %s for %s", status, arxiv_id)
            return None
        xml_text = getattr(resp, "text", None)
        if not isinstance(xml_text, str) or not xml_text:
            return None
        if cache_path is not None:
            try:
                cache_path.write_text(xml_text, encoding="utf-8")
            except OSError as exc:
                logger.warning("bibenrich: could not write %s: %s", cache_path, exc)

    return _parse_arxiv(xml_text)


# ---------------------------------------------------------------------------
# Entry / file enrichment
# ---------------------------------------------------------------------------


def _is_missing(value: Any) -> bool:
    """True if ``value`` should be considered missing (None / ""/ [])."""
    if value is None:
        return True
    if isinstance(value, str) and not value.strip():
        return True
    if isinstance(value, (list, tuple, dict)) and len(value) == 0:
        return True
    return False


def enrich_entry(
    entry: dict,
    *,
    cache_dir: Path | None = None,
    _session: Any | None = None,
) -> dict:
    """Enrich a single bibliography entry with online metadata.

    The entry is consulted for a ``doi`` field first and (if absent or
    the lookup fails) an ``arxiv`` / ``arxiv_id`` field.  Returned
    metadata fills in **only** missing keys — existing values are never
    overwritten, so user-curated data always takes precedence.

    Args:
        entry: Mutable bibliography entry dict, e.g.
            ``{"id": "smith2020", "doi": "10.xxxx/yyy"}``.
        cache_dir: Cache directory passed through to the lookup helpers.
        _session: Optional injected ``requests`` session for testing.

    Returns:
        A new dict containing the merged fields.  The input dict is not
        mutated.
    """
    if not isinstance(entry, dict):
        return entry  # type: ignore[return-value]

    out = dict(entry)
    fetched: dict | None = None

    doi = out.get("doi")
    if isinstance(doi, str) and doi.strip():
        fetched = lookup_doi(doi, cache_dir=cache_dir, _session=_session)

    if fetched is None:
        arxiv = out.get("arxiv") or out.get("arxiv_id") or out.get("eprint")
        if isinstance(arxiv, str) and arxiv.strip():
            fetched = lookup_arxiv(arxiv, cache_dir=cache_dir, _session=_session)

    if not fetched:
        return out

    for key, value in fetched.items():
        if _is_missing(out.get(key)):
            out[key] = value
    return out


# ---------------------------------------------------------------------------
# Bibliography file I/O — minimal TOML/YAML round-trip
# ---------------------------------------------------------------------------


def _read_text_with_bom(path: Path) -> str:
    """Read *path* as text, transparently handling UTF-8 BOM.

    Tries ``utf-8-sig`` first (which strips a UTF-8 BOM and accepts
    plain UTF-8), then falls back to plain ``utf-8`` for files saved by
    editors that do not emit a BOM.  A clear ``RuntimeError`` is raised
    if neither encoding can decode the file (e.g. a UTF-16 file would
    need to be re-saved as UTF-8 first).
    """
    try:
        return path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        try:
            return path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise RuntimeError(
                f"Could not decode {path} as UTF-8 (or UTF-8 with BOM). "
                "Please re-save the file as UTF-8 (no BOM or with BOM both "
                "work; UTF-16 is not supported)."
            ) from exc


def _load_toml(path: Path) -> dict:
    """Load a TOML file using stdlib ``tomllib`` (3.11+) or ``tomli``."""
    try:
        import tomllib  # type: ignore[import-not-found]
    except ModuleNotFoundError:  # pragma: no cover - Python < 3.11
        import tomli as tomllib  # type: ignore[import-not-found, no-redef]
    return tomllib.loads(_read_text_with_bom(path))


def _toml_escape_string(value: str) -> str:
    """Escape a string for TOML basic-string syntax."""
    out = value.replace("\\", "\\\\").replace('"', '\\"')
    out = out.replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")
    return f'"{out}"'


def _toml_format_value(value: Any) -> str:
    """Render a Python value as a TOML scalar / inline-array literal."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, str):
        return _toml_escape_string(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_toml_format_value(v) for v in value) + "]"
    # Fall back to string representation for unsupported types.
    return _toml_escape_string(str(value))


def _has_unsupported_toml_feature(value: Any) -> str | None:
    """Return a short reason string if *value* uses TOML features the
    minimal serialiser cannot round-trip safely, else ``None``.

    The hand-rolled writer below supports flat scalars and inline
    arrays of scalars only.  Nested tables, dotted keys (which the TOML
    parser flattens into nested dicts), and multi-line strings would be
    silently corrupted, so we detect and reject them up front.
    """
    if isinstance(value, dict):
        return "nested table / dotted key"
    if isinstance(value, str) and ("\n" in value or "\r" in value):
        return "multi-line string"
    if isinstance(value, (list, tuple)):
        for item in value:
            reason = _has_unsupported_toml_feature(item)
            if reason is not None:
                return reason
    return None


def _check_toml_round_trippable(data: dict) -> None:
    """Validate that *data* uses only TOML features we can serialise.

    Raises :class:`RuntimeError` with a clear message pointing the user
    at ``tomli-w`` for full-fidelity output if any unsupported feature
    is found (nested tables, dotted keys, multi-line strings).
    """
    # Top-level "entries" array-of-tables case.
    if isinstance(data.get("entries"), list):
        for i, entry in enumerate(data["entries"]):
            if not isinstance(entry, dict):
                continue
            for key, value in entry.items():
                reason = _has_unsupported_toml_feature(value)
                if reason is not None:
                    raise RuntimeError(
                        f"bibenrich: cannot round-trip entries[{i}].{key} "
                        f"({reason}). Install ``tomli-w`` for full-fidelity "
                        f"writing, or simplify the input to flat scalars."
                    )
        return
    # Table-per-entry case.
    for name, entry in data.items():
        if not isinstance(entry, dict):
            # Top-level scalar: still check it.
            reason = _has_unsupported_toml_feature(entry)
            if reason is not None:
                raise RuntimeError(
                    f"bibenrich: cannot round-trip top-level key {name!r} "
                    f"({reason}). Install ``tomli-w`` for full-fidelity "
                    f"writing, or simplify the input to flat scalars."
                )
            continue
        for key, value in entry.items():
            reason = _has_unsupported_toml_feature(value)
            if reason is not None:
                raise RuntimeError(
                    f"bibenrich: cannot round-trip [{name}].{key} ({reason}). "
                    f"Install ``tomli-w`` for full-fidelity writing, or "
                    f"simplify the input to flat scalars."
                )


def _dump_toml_bib(data: dict) -> str:
    """Serialize a flat bibliography dict to TOML.

    Supports two shapes:
      1. ``{"entries": [ {entry}, ... ]}``  — array of tables.
      2. ``{"<id>": {entry}, ...}``         — table-per-entry.

    Limitations
    -----------
    This is a deliberately minimal hand-rolled writer; it preserves
    insertion order (Python 3.7+ dicts) but does **not** preserve
    comments, blank lines, or the exact whitespace of the input.  It
    also cannot represent nested tables, dotted keys, or multi-line
    strings — :func:`_check_toml_round_trippable` raises
    :class:`RuntimeError` if any of those appear in the input.

    For full-fidelity round-tripping, install the optional ``tomli-w``
    package; this writer will use it automatically when available.
    """
    # Prefer ``tomli_w`` when the user has installed it: it preserves
    # nested tables / multi-line strings that the hand-rolled fallback
    # cannot represent.
    try:
        import tomli_w  # type: ignore[import-not-found]
    except ModuleNotFoundError:
        tomli_w = None  # type: ignore[assignment]

    if tomli_w is not None:
        return tomli_w.dumps(data)

    _check_toml_round_trippable(data)

    lines: list[str] = []

    if isinstance(data.get("entries"), list):
        for entry in data["entries"]:
            if not isinstance(entry, dict):
                continue
            lines.append("[[entries]]")
            for k, v in entry.items():
                lines.append(f"{k} = {_toml_format_value(v)}")
            lines.append("")
        # Render any other top-level keys as scalars after the array.
        for k, v in data.items():
            if k == "entries":
                continue
            lines.append(f"{k} = {_toml_format_value(v)}")
        return "\n".join(lines).rstrip() + "\n"

    # Table-per-entry shape.
    scalars = {k: v for k, v in data.items() if not isinstance(v, dict)}
    tables = {k: v for k, v in data.items() if isinstance(v, dict)}
    for k, v in scalars.items():
        lines.append(f"{k} = {_toml_format_value(v)}")
    if scalars and tables:
        lines.append("")
    for name, entry in tables.items():
        lines.append(f"[{name}]")
        for k, v in entry.items():
            lines.append(f"{k} = {_toml_format_value(v)}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _load_yaml(path: Path) -> dict:
    """Load a YAML bibliography file (``PyYAML`` required)."""
    try:
        import yaml  # type: ignore[import-not-found]
    except ModuleNotFoundError as exc:  # pragma: no cover - optional dep
        raise RuntimeError(
            "YAML bibliography support requires PyYAML; install with `pip install pyyaml`."
        ) from exc
    loaded = yaml.safe_load(_read_text_with_bom(path))
    return loaded if isinstance(loaded, dict) else {}


def _dump_yaml(data: dict) -> str:
    try:
        import yaml  # type: ignore[import-not-found]
    except ModuleNotFoundError as exc:  # pragma: no cover - optional dep
        raise RuntimeError(
            "YAML bibliography support requires PyYAML; install with `pip install pyyaml`."
        ) from exc
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)


def _iter_entries(data: dict) -> list[tuple[Any, dict]]:
    """Return ``[(key, entry), ...]`` for the recognised bib shapes."""
    entries: list[tuple[Any, dict]] = []
    if isinstance(data.get("entries"), list):
        for i, e in enumerate(data["entries"]):
            if isinstance(e, dict):
                entries.append((i, e))
        return entries
    for k, v in data.items():
        if isinstance(v, dict):
            entries.append((k, v))
    return entries


def enrich_bib_file(
    input_path: Path,
    output_path: Path,
    *,
    cache_dir: Path | None = None,
    _session: Any | None = None,
) -> int:
    """Enrich every entry in a TOML or YAML bibliography file.

    Format is auto-detected by the input file's extension
    (``.toml`` → TOML, ``.yaml`` / ``.yml`` → YAML).  Each entry that
    has a ``doi``, ``arxiv``, ``arxiv_id``, or ``eprint`` field is
    looked up and merged; existing fields are preserved.

    Args:
        input_path: Path to the bibliography file to read.
        output_path: Path to write the enriched bibliography to.  May
            equal ``input_path`` for in-place editing.
        cache_dir: On-disk cache directory (default
            :data:`DEFAULT_CACHE_DIR`).
        _session: Optional injected ``requests`` session for testing.

    Returns:
        The number of entries that received at least one new field.
    """
    input_path = Path(input_path)
    output_path = Path(output_path)
    if cache_dir is None:
        cache_dir = DEFAULT_CACHE_DIR

    suffix = input_path.suffix.lower()
    if suffix == ".toml":
        data = _load_toml(input_path)
        dump = _dump_toml_bib
    elif suffix in (".yaml", ".yml"):
        data = _load_yaml(input_path)
        dump = _dump_yaml
    else:
        raise ValueError(
            f"Unsupported bibliography format: {input_path.suffix!r} "
            "(expected .toml, .yaml, or .yml)"
        )

    enriched_count = 0
    new_entries: list[tuple[Any, dict]] = []
    for key, entry in _iter_entries(data):
        before = dict(entry)
        merged = enrich_entry(entry, cache_dir=cache_dir, _session=_session)
        if merged != before:
            enriched_count += 1
        new_entries.append((key, merged))

    # Write merged values back into the original structure.
    if isinstance(data.get("entries"), list):
        data["entries"] = [e for _, e in new_entries]
    else:
        for key, e in new_entries:
            data[key] = e

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(dump(data), encoding="utf-8")
    return enriched_count


__all__ = [
    "DEFAULT_CACHE_DIR",
    "USER_AGENT",
    "enrich_bib_file",
    "enrich_entry",
    "lookup_arxiv",
    "lookup_doi",
]
