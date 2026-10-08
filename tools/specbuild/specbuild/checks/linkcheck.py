"""External link checker: validate that HTTP/HTTPS URLs in the spec are reachable.

Performs HEAD requests against all external URLs found in ``<a href>``,
``<link href>``, and ``<script src>`` elements.  Unreachable links are
reported with their HTTP status code and the nearest heading for context.

To avoid hammering servers, requests are rate-limited and run concurrently
with a configurable thread pool.

Also provides :func:`check_internal_links_soup` which validates that every
internal fragment link ``<a href="#id">`` resolves to an element with a
matching ``id`` attribute in the same document.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import TYPE_CHECKING

from specbuild.utils import find_nearest_heading, get_bs4, read_html

if TYPE_CHECKING:
    from specbuild.context import BuildContext


def check_external_links(
    html_path: Path,
    *,
    timeout: int = 10,
    max_workers: int = 8,
    allowlist: list[str] | None = None,
) -> list[dict]:
    """File-based wrapper around :func:`check_external_links_soup`.

    Args:
        html_path: Path to the compiled HTML file.
        timeout: Per-request timeout in seconds.
        max_workers: Maximum concurrent requests.
        allowlist: URL prefixes to skip (e.g. ``["https://example.com"]``).

    Returns:
        List of issue dicts with ``url``, ``status``, ``error``, ``context``.
    """
    try:
        get_bs4()
    except ImportError:
        logging.warning("BeautifulSoup not available, skipping link check")
        return []

    logging.info(f"Checking external links in {html_path.name}")
    soup = read_html(html_path)
    return check_external_links_soup(
        soup,
        timeout=timeout,
        max_workers=max_workers,
        allowlist=allowlist,
    )


def check_external_links_soup(
    soup: object,
    *,
    timeout: int = 10,
    max_workers: int = 8,
    allowlist: list[str] | None = None,
    ctx: BuildContext | None = None,
) -> list[dict]:
    """Check external links on a pre-parsed soup object.

    Args:
        soup: BeautifulSoup document (read-only).
        timeout: Per-request timeout in seconds.
        max_workers: Maximum concurrent requests.
        allowlist: URL prefixes to skip.
        ctx: Optional :class:`BuildContext` carrying prebuilt
             ``links_by_href`` map in ``ctx.precomputed`` for O(1) reuse.

    Returns:
        List of issue dicts.
    """
    urls = _collect_urls(soup, ctx)
    if not urls:
        logging.info("No external URLs found")
        return []

    # Deduplicate URLs, keeping first context for each
    unique: dict[str, str] = {}
    for url, context in urls:
        if url not in unique:
            unique[url] = context

    # Block SSRF targets (cloud metadata endpoints, RFC-1918 addresses).
    blocked = {url for url in unique if _is_ssrf_blocked(url)}
    if blocked:
        logging.warning(
            "Link check skipping %d private/metadata URL(s) to prevent SSRF: %s",
            len(blocked),
            ", ".join(sorted(blocked)[:5]),
        )
    filtered_no_ssrf = {url: ctx for url, ctx in unique.items() if url not in blocked}

    # Filter allowlisted URLs
    if allowlist:
        filtered = {
            url: ctx_str
            for url, ctx_str in filtered_no_ssrf.items()
            if not any(url.startswith(prefix) for prefix in allowlist)
        }
    else:
        filtered = filtered_no_ssrf

    logging.info(
        f"Checking {len(filtered)} unique external URL(s) (of {len(urls)} total references)"
    )

    issues = _check_urls(filtered, timeout=timeout, max_workers=max_workers)

    if issues:
        logging.warning(f"Found {len(issues)} broken external link(s)")
    else:
        logging.info("All external links are reachable")

    return issues


def check_internal_links(html_path: Path) -> list[dict]:
    """File-based wrapper around :func:`check_internal_links_soup`.

    Args:
        html_path: Path to the compiled HTML file.

    Returns:
        List of issue dicts with ``href``, ``context`` for each broken anchor.
    """
    try:
        get_bs4()
    except ImportError:
        logging.warning("BeautifulSoup not available, skipping internal link check")
        return []

    logging.info(f"Checking internal fragment links in {html_path.name}")
    soup = read_html(html_path)
    return check_internal_links_soup(soup)


def check_internal_links_soup(soup: object, ctx: BuildContext | None = None) -> list[dict]:
    """Validate that every ``<a href="#id">`` resolves to an element in the page.

    Args:
        soup: BeautifulSoup document (read-only).
        ctx:  Optional :class:`BuildContext` with prebuilt ``ids_by_id`` /
              ``links_by_href`` lookup maps.

    Returns:
        List of issue dicts, each with ``href`` (the broken fragment) and
        ``context`` (nearest heading text for location).
    """
    ids_by_id, links_by_href = _resolve_lookup_maps(soup, ctx)
    all_ids: set[str] = set(ids_by_id.keys())

    issues: list[dict] = []
    seen_broken: set[str] = set()

    # Walk <a> elements via the prebuilt {href: [<a>, ...]} map.  We still
    # iterate <a> elements in document order (within each href bucket) so
    # the "nearest heading" context is taken from the first occurrence —
    # matching the original soup.find_all walk for any single-occurrence
    # href.  Multiple-occurrence broken hrefs are reported once anyway.
    for href, link_list in links_by_href.items():
        if not href.startswith("#"):
            continue
        target = href[1:]
        if not target:
            continue
        if target in all_ids:
            continue
        if target in seen_broken:
            continue
        seen_broken.add(target)
        issues.append(
            {
                "href": href,
                "context": find_nearest_heading(link_list[0]),
            }
        )

    if issues:
        logging.warning(f"Found {len(issues)} broken internal fragment link(s)")
        for issue in issues[:20]:
            logging.warning(f"  {issue['href']} (near: {issue['context']})")
    else:
        logging.info("All internal fragment links are valid")

    return issues


def report_external_links(issues: list[dict], *, strict: bool = False) -> None:
    """Log external link check findings.

    Args:
        issues: List from :func:`check_external_links`.
        strict: If True, exit with error when broken links are found.
    """
    if not issues:
        logging.info("External link check passed: all links reachable")
        return

    logging.warning(f"External link check: {len(issues)} broken link(s)")
    for issue in issues:
        status = issue.get("status", "")
        error = issue.get("error", "")
        detail = f"HTTP {status}" if status else error
        logging.warning(f"  {issue['url']} — {detail} (near: {issue['context']})")

    if strict:
        raise SystemExit(1)


# ---------------------------------------------------------------------------
# URL collection
# ---------------------------------------------------------------------------


def _resolve_lookup_maps(
    soup: object, ctx: BuildContext | None
) -> tuple[dict[str, object], dict[str, list[object]]]:
    """Return ``(ids_by_id, links_by_href)`` from *ctx* or build them locally."""
    if ctx is not None and ctx.precomputed:
        ids_by_id = ctx.precomputed.get("ids_by_id")
        links_by_href = ctx.precomputed.get("links_by_href")
        if ids_by_id is not None and links_by_href is not None:
            return ids_by_id, links_by_href
    from specbuild.context import compute_lookup_maps

    maps = compute_lookup_maps(soup)
    return maps["ids_by_id"], maps["links_by_href"]


def _collect_urls(soup: object, ctx: BuildContext | None = None) -> list[tuple[str, str]]:
    """Collect all external URLs from the HTML with their context.

    Returns:
        List of (url, nearest_heading_text) tuples.
    """
    urls: list[tuple[str, str]] = []

    # <a href="..."> — read from prebuilt {href: [<a>, ...]} when available.
    if ctx is not None and ctx.precomputed and "links_by_href" in ctx.precomputed:
        links_by_href: dict[str, list[object]] = ctx.precomputed["links_by_href"]
        for href, link_list in links_by_href.items():
            if _is_external(href):
                # Emit one entry per occurrence to match the original walk
                # (which fed the duplicate-counting log message).
                for link in link_list:
                    urls.append((href, find_nearest_heading(link)))
    else:
        for link in soup.find_all("a", href=True):
            href = link["href"]
            if _is_external(href):
                urls.append((href, find_nearest_heading(link)))

    # <link href="..."> (stylesheets, etc.) — small, walk directly.
    for link in soup.find_all("link", href=True):
        href = link["href"]
        if _is_external(href):
            urls.append((href, "(document head)"))

    # <script src="..."> — small, walk directly.
    for script in soup.find_all("script", src=True):
        src = script["src"]
        if _is_external(src):
            urls.append((src, find_nearest_heading(script)))

    return urls


def _is_external(url: str) -> bool:
    """Return True if URL is an external HTTP/HTTPS link."""
    return url.startswith(("http://", "https://"))


# IP prefixes that must not be fetched from CI (SSRF / cloud metadata risk).
# Expressed as string prefixes on the raw URL so no DNS lookup is required.
_SSRF_BLOCKED_PREFIXES: tuple[str, ...] = (
    "http://169.254.",  # AWS IMDS / Azure IMDS / link-local
    "https://169.254.",
    "http://127.",  # localhost
    "https://127.",
    "http://[::1]",
    "https://[::1]",
    "http://10.",  # RFC-1918 class A
    "https://10.",
    "http://192.168.",  # RFC-1918 class C
    "https://192.168.",
    "http://172.16.",  # RFC-1918 class B (start only; full range 172.16-31.*)
    "https://172.16.",
)


def _is_ssrf_blocked(url: str) -> bool:
    """Return True if the URL targets a private/metadata address we refuse to fetch."""
    return any(url.startswith(p) for p in _SSRF_BLOCKED_PREFIXES)


# ---------------------------------------------------------------------------
# URL checking
# ---------------------------------------------------------------------------


def _check_urls(
    urls: dict[str, str],
    *,
    timeout: int = 10,
    max_workers: int = 8,
) -> list[dict]:
    """Check URLs concurrently and return issues.

    Args:
        urls: Mapping of URL -> context string.
        timeout: Per-request timeout.
        max_workers: Thread pool size.

    Returns:
        List of issue dicts for unreachable URLs.
    """
    try:
        import requests
    except ImportError:
        logging.warning("requests not available, skipping external link check")
        return []

    issues: list[dict] = []

    with requests.Session() as session:

        def _check_one(url: str) -> dict | None:
            try:
                resp = session.head(url, timeout=timeout, allow_redirects=True)
                if resp.status_code >= 400:
                    return {
                        "url": url,
                        "status": resp.status_code,
                        "error": "",
                        "context": urls[url],
                    }
            except requests.ConnectionError:
                return {
                    "url": url,
                    "status": None,
                    "error": "connection failed",
                    "context": urls[url],
                }
            except requests.Timeout:
                return {
                    "url": url,
                    "status": None,
                    "error": f"timeout ({timeout}s)",
                    "context": urls[url],
                }
            except requests.RequestException as exc:
                return {
                    "url": url,
                    "status": None,
                    "error": str(exc)[:100],
                    "context": urls[url],
                }
            return None

        if not urls:
            return issues
        workers = max(1, min(max_workers, len(urls)))
        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_to_url = {executor.submit(_check_one, url): url for url in urls}
            for future in as_completed(future_to_url):
                try:
                    result = future.result()
                    if result is not None:
                        issues.append(result)
                except Exception as exc:
                    url = future_to_url.get(future, "unknown")
                    logging.warning(f"Link check error for {url}: {exc}")

    return issues
