"""Shared utility functions: HTML I/O, subprocess helpers, Chrome detection, etc.

This module centralises small helpers used across the *specbuild* package so
that higher-level modules (compile, merge, pdf, diff, …) stay focused on their
own domain logic.
"""

from __future__ import annotations

import importlib.util as _ilu
import logging
import os
import platform
import re
import shutil
import subprocess
import sys
import zipfile
from functools import cache, lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

from specbuild import PROJECT_ROOT

if TYPE_CHECKING:
    from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Script module loader
# ---------------------------------------------------------------------------


@cache
def import_script(name: str):
    """Import a Python module from the ``scripts/`` directory by name.

    Results are cached so that repeated imports of the same script return the
    same module object without re-executing the file.

    Args:
        name: Module name (without ``.py`` extension), e.g.
            ``"split_html_to_multipage"``.

    Returns:
        The imported module.

    Raises:
        ImportError: If the script file cannot be found.
    """
    # Primary location: repo scripts/ directory (development / editable install)
    script_path = PROJECT_ROOT / "scripts" / f"{name}.py"
    if not script_path.exists():
        # Fallback: scripts/ bundled as package data under specbuild/scripts/
        # (used when installed via pip with include-package-data = true)
        script_path = Path(__file__).parent / "scripts" / f"{name}.py"
    if not script_path.exists():
        raise ImportError(f"Cannot find script: scripts/{name}.py")
    spec = _ilu.spec_from_file_location(name, script_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load script: scripts/{name}.py")
    mod = _ilu.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# BeautifulSoup lazy import
# ---------------------------------------------------------------------------

# Cached reference populated on first call to get_bs4().
_BeautifulSoup: type | None = None


def get_bs4() -> type[BeautifulSoup]:
    """Import and cache BeautifulSoup (avoids top-level dependency for non-HTML tasks).

    Returns:
        type[BeautifulSoup]: The ``BeautifulSoup`` class.
    """
    global _BeautifulSoup
    if _BeautifulSoup is None:
        from bs4 import BeautifulSoup

        _BeautifulSoup = BeautifulSoup
    return _BeautifulSoup


# ---------------------------------------------------------------------------
# HTML I/O helpers
# ---------------------------------------------------------------------------


def read_html(html_path: Path) -> BeautifulSoup:
    """Read an HTML file and return a BeautifulSoup object.

    Args:
        html_path (Path): Path to the HTML file.

    Returns:
        BeautifulSoup: Parsed HTML document.
    """
    BS = get_bs4()
    with open(html_path, encoding="utf-8") as f:
        markup = f.read()
    # Use a spec-compliant parser so HTML5 table foster-parenting is honored
    # (the stdlib "html.parser" mis-nests <tr>/<td> in dense tables, which
    # downstream recursive find_all() then multiplies). Fall back gracefully.
    for parser in ("lxml", "html5lib", "html.parser"):
        try:
            return BS(markup, parser)
        except Exception:  # noqa: BLE001 - try next available parser
            continue
    return BS(markup, "html.parser")


def write_html(html_path: Path, soup: BeautifulSoup) -> None:
    """Write a BeautifulSoup object back to an HTML file.

    Args:
        html_path (Path): Destination file path.
        soup (BeautifulSoup): Document to serialize.
    """
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(str(soup))


# ---------------------------------------------------------------------------
# Shared DOM helpers
# ---------------------------------------------------------------------------

HEADING_TAGS: frozenset[str] = frozenset(("h1", "h2", "h3", "h4", "h5", "h6"))
"""Frozenset of all HTML heading tag names (h1–h6)."""

HEADING_RE: re.Pattern = re.compile(r"^h[1-6]$")
"""Compiled regex matching any HTML heading tag name (h1–h6)."""

PROSE_TAGS: frozenset[str] = frozenset(("p", "li", "dd", "dt"))
"""Frozenset of HTML prose container tags used for text extraction."""


def find_heading_by_pattern(soup: BeautifulSoup, pattern: str) -> object | None:
    """Find the first h1-h6 element whose text matches *pattern* (regex).

    Args:
        soup: Parsed BeautifulSoup document.
        pattern: Regular expression string to match against heading text.

    Returns:
        The first matching Tag, or ``None`` if no match is found.
    """
    regex = re.compile(pattern)
    for tag in soup.find_all(HEADING_RE):
        text = tag.get_text(strip=True)
        if regex.match(text):
            return tag
    return None


def get_parent_clause_number(tag: object) -> str:
    """Walk up to the nearest parent section and extract its clause number.

    Args:
        tag: A BeautifulSoup Tag whose ancestor sections are searched.

    Returns:
        Clause number string (e.g. ``"5.2"``) or ``""`` if not found.
    """
    for parent in tag.parents:
        if parent.name == "section":
            heading = parent.find(HEADING_RE)
            if heading:
                text = heading.get_text(strip=True)
                m = re.match(r"(?:Clause\s+)?(\d+(?:\.\d+)*)", text)
                if m:
                    return m.group(1)
    return ""


def prepend_heading_text(tag: object, prefix: str) -> None:
    """Prepend *prefix* to a tag's first text node.

    Args:
        tag: A BeautifulSoup Tag to modify in-place.
        prefix: Text to prepend (e.g. ``"Clause "``).
    """
    from bs4 import NavigableString

    for child in tag.children:
        if isinstance(child, NavigableString):
            child.replace_with(NavigableString(prefix + str(child)))
            return
    tag.insert(0, NavigableString(prefix))


def find_nearest_heading(element: object, max_len: int = 60) -> str:
    """Walk up the DOM to find the nearest heading for context.

    Args:
        element: A BeautifulSoup Tag whose ancestor headings are searched.
        max_len: Maximum length of the returned heading text.

    Returns:
        Truncated text of the nearest heading, or ``"(unknown section)"``.
    """
    _id, title = find_nearest_section(element, max_len=max_len)
    return title


def find_nearest_section(
    element: object,
    *,
    max_len: int = 60,
) -> tuple[str, str]:
    """Walk the DOM to find the nearest section heading and its id.

    Args:
        element: A BeautifulSoup Tag whose ancestor headings are searched.
        max_len: Maximum length of the returned heading text.

    Returns:
        ``(section_id, heading_title)`` tuple.  Falls back to
        ``("", "(unknown section)")`` if no heading is found.
    """
    # Check element's own previous siblings first
    for sibling in element.previous_siblings:
        if hasattr(sibling, "name") and sibling.name in HEADING_TAGS:
            return (sibling.get("id", ""), sibling.get_text(strip=True)[:max_len])
    for parent in element.parents:
        if parent is None:
            break
        for sibling in parent.previous_siblings:
            if hasattr(sibling, "name") and sibling.name in HEADING_TAGS:
                return (sibling.get("id", ""), sibling.get_text(strip=True)[:max_len])
        if hasattr(parent, "name") and parent.name in ("section", "div"):
            heading = parent.find(list(HEADING_TAGS))
            if heading:
                sid = heading.get("id", "") or parent.get("id", "")
                return (sid, heading.get_text(strip=True)[:max_len])
    return ("", "(unknown section)")


def extract_toc_html(html_content: str) -> str:
    """Extract the TOC nav block from compiled spec HTML.

    Targets the Bikeshed-generated TOC nav which has
    ``data-fill-with="table-of-contents"`` to avoid false matches
    inside CSS comments.

    Args:
        html_content: Full HTML source of a compiled specification.

    Returns:
        The inner HTML of the TOC ``<nav>`` element, or a fallback message
        if no TOC is found.
    """
    match = re.search(
        r'<nav[^>]*data-fill-with="table-of-contents"[^>]*>(.*?)</nav>',
        html_content,
        re.DOTALL,
    )
    if not match:
        match = re.search(
            r'</style>.*?<nav[^>]*id="toc"[^>]*>(.*?)</nav>',
            html_content,
            re.DOTALL,
        )
    return match.group(1) if match else "<p>No table of contents found.</p>"


def inject_css(soup: BeautifulSoup, css_id: str, css: str) -> None:
    """Inject a ``<style>`` block into the document ``<head>``.

    Args:
        soup: BeautifulSoup document.
        css_id: Value for the ``id`` attribute (used to avoid duplicates).
        css: Raw CSS text.
    """
    head = soup.find("head")
    if not head:
        return
    if soup.find("style", id=css_id):
        return
    style_tag = soup.new_tag("style", id=css_id)
    style_tag.string = css
    head.append(style_tag)


def inject_js(soup: BeautifulSoup, js_id: str, js: str) -> None:
    """Inject a ``<script>`` block into the document ``<head>``.

    Args:
        soup: BeautifulSoup document.
        js_id: Value for the ``id`` attribute (used to avoid duplicates).
        js: Raw JavaScript text.
    """
    head = soup.find("head")
    if not head:
        return
    if soup.find("script", id=js_id):
        return
    script_tag = soup.new_tag("script", id=js_id)
    script_tag.string = js
    head.append(script_tag)


# ---------------------------------------------------------------------------
# Subprocess helpers
# ---------------------------------------------------------------------------


def _forward_subprocess_logs(result, label: str = "") -> None:
    """Parse stdout/stderr from a subprocess and re-emit lines through logging.

    Recognises two formats:

    - The shared ``setup_logging`` format ``[<level>] message`` written by
      subprocess scripts that route through ``specbuild.logsetup``
      (``[info]``, ``[warn]``, ``[ERR ]``, ``[dbg]``, ``[CRIT]``).
    - Legacy uppercase prefixes ``INFO:``, ``WARNING:``, ``ERROR:``.

    Other non-empty stderr lines are emitted at WARNING with an optional label.

    Args:
        result: A ``subprocess.CompletedProcess`` instance.
        label (str): Optional label prepended to unrecognised stderr lines.
    """
    # Map "[<token>] " prefixes to the parent log level.
    _BRACKET_LEVELS = {
        "[dbg] ": logging.DEBUG,
        "[info] ": logging.INFO,
        "[warn] ": logging.WARNING,
        "[ERR ] ": logging.ERROR,
        "[CRIT] ": logging.CRITICAL,
    }

    for stream in (result.stdout, result.stderr):
        if not stream:
            continue
        is_stderr = stream is result.stderr
        for line in stream.strip().split("\n"):
            matched = False
            for prefix, level in _BRACKET_LEVELS.items():
                if line.startswith(prefix):
                    logging.log(level, line[len(prefix) :])
                    matched = True
                    break
            if matched:
                continue

            if line.startswith("INFO:"):
                logging.info(line[5:].strip())
            elif line.startswith("WARNING:"):
                logging.warning(line[8:].strip())
            elif line.startswith("ERROR:"):
                logging.error(line[6:].strip())
            elif is_stderr and line.strip():
                prefix = f"{label} stderr: " if label else "stderr: "
                logging.warning(f"{prefix}{line}")


def resolve_asset_file(rel_path: str | Path) -> Path:
    """Locate an asset file with a workspace-first, build-system fallback.

    Mirrors the overlay semantics of :func:`postprocess._copy_asset_dirs`
    but for inline reads (e.g. CSS/JS that gets injected as ``<style>``
    or ``<script>`` blocks rather than copied as a file).  This lets a
    consumer drop their own ``css/dark-mode.css`` or ``js/foo.js`` into
    their workspace and have it win over the build system's bundled
    version, the same way it would for the bulk-copy path.

    Resolution order:

    1. ``<CWD>/<rel_path>`` — the consumer's workspace override.
    2. ``<PROJECT_ROOT>/<rel_path>`` — the build system's bundled copy.

    Args:
        rel_path: Path relative to either the workspace or PROJECT_ROOT
            (e.g. ``"css/dark-mode.css"``).

    Returns:
        The first existing path.  Falls back to the PROJECT_ROOT path
        even when it does not exist so callers can do ``if path.exists()``
        checks without an extra branch.
    """
    rel = Path(rel_path)
    workspace = Path(".") / rel
    if workspace.exists():
        return workspace
    return PROJECT_ROOT / rel


def run_helper_script(script_name: str, args: list, description: str = "") -> bool:
    """Run a Python helper script from the ``scripts/`` directory.

    The script is located relative to :data:`specbuild.PROJECT_ROOT`.  Its
    stdout/stderr are captured and forwarded through the logging system via
    :func:`_forward_subprocess_logs`.

    Args:
        script_name (str): Filename of the script inside ``scripts/``
            (e.g. ``"renumber_annexes.py"``).
        args (list): Extra command-line arguments passed after the script path.
        description (str): Human-readable label used in log messages.

    Returns:
        bool: ``True`` if the script ran successfully, ``False`` otherwise.
    """
    # Primary location: repo scripts/ directory (development / editable install)
    script_path = PROJECT_ROOT / "scripts" / script_name
    if not script_path.exists():
        # Fallback: scripts/ bundled as package data under specbuild/scripts/
        script_path = Path(__file__).parent / "scripts" / script_name
    desc = description or script_name

    if not script_path.exists():
        logging.warning(f"{desc}: script not found: {script_path}")
        return False

    try:
        # Subprocess stderr is captured and re-emitted via the parent's
        # colored formatter.  Force NO_COLOR so the subprocess's own
        # logger writes plain `[info] ...` prefixes the parent can parse.
        sub_env = dict(os.environ)
        sub_env.pop("FORCE_COLOR", None)
        sub_env["NO_COLOR"] = "1"

        result = subprocess.run(
            [sys.executable, str(script_path)] + [str(a) for a in args],
            check=True,
            capture_output=True,
            text=True,
            env=sub_env,
        )
        _forward_subprocess_logs(result, label=desc)
        return True
    except subprocess.CalledProcessError as e:
        logging.error(f"{desc} failed: {e}")
        if e.stderr:
            logging.error(f"{desc} error output: {e.stderr}")
        return False


# ---------------------------------------------------------------------------
# Chrome detection
# ---------------------------------------------------------------------------


def get_chrome_path() -> str | None:
    """Auto-detect Chrome path based on platform.

    Searches well-known installation locations on macOS, Linux, and Windows,
    then falls back to ``shutil.which()`` for PATH-based discovery.

    Returns:
        str or None: Path to Chrome executable, or ``None`` if not found.
    """
    system = platform.system()

    if system == "Darwin":  # macOS
        paths = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
        ]
    elif system == "Linux":
        paths = [
            "/usr/bin/google-chrome",
            "/usr/bin/google-chrome-stable",
            "/usr/bin/chromium-browser",
            "/usr/bin/chromium",
            "/snap/bin/chromium",
        ]
    else:  # Windows
        paths = [
            "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
            "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
            # Per-user install (default on managed Windows machines)
            str(
                Path(os.environ.get("LOCALAPPDATA", ""))
                / "Google"
                / "Chrome"
                / "Application"
                / "chrome.exe"
            ),
        ]

    for path in paths:
        if Path(path).exists():
            logging.info(f"Found Chrome at: {path}")
            return path

    chrome_from_which = (
        shutil.which("google-chrome")
        or shutil.which("chromium")
        or shutil.which("chromium-browser")
    )
    if chrome_from_which:
        logging.info(f"Found Chrome via which: {chrome_from_which}")
        return chrome_from_which

    logging.warning("Chrome not found on system")
    return None


@lru_cache(maxsize=1)
def chrome_path() -> str | None:
    """Return the cached Chrome path, detecting on first call.

    Returns:
        str or None: Path to Chrome executable, or ``None`` if not found.
    """
    return get_chrome_path()


@lru_cache(maxsize=1)
def homebrew_lib_for_dyld() -> Path | None:
    """Homebrew lib dir on Apple Silicon, when WeasyPrint needs it on PATH.

    On macOS arm64, libgobject/libpango/libharfbuzz live under
    ``/opt/homebrew/lib`` (or a custom Homebrew prefix), but neither dyld nor
    cffi searches there by default — so ``import weasyprint`` raises
    ``OSError: cannot load library 'libgobject-2.0-0'``.  Prepending this dir
    to ``DYLD_FALLBACK_LIBRARY_PATH`` for the WeasyPrint subprocess fixes the
    common case without forcing every contributor to edit their shell rc.

    Returns the lib path if injection is warranted; ``None`` on non-arm64
    macOS, on Linux/Windows, or when the libs are not where we expect.
    """
    if sys.platform != "darwin" or platform.machine() != "arm64":
        return None
    candidates: list[Path] = []
    env_prefix = os.environ.get("HOMEBREW_PREFIX")
    if env_prefix:
        candidates.append(Path(env_prefix))
    candidates.append(Path("/opt/homebrew"))
    for prefix in candidates:
        lib = prefix / "lib"
        if (lib / "libgobject-2.0.0.dylib").exists():
            return lib
    brew = shutil.which("brew")
    if brew:
        try:
            out = subprocess.run(
                [brew, "--prefix"], capture_output=True, text=True, timeout=5, check=True
            ).stdout.strip()
            lib = Path(out) / "lib"
            if (lib / "libgobject-2.0.0.dylib").exists():
                return lib
        except (subprocess.SubprocessError, OSError):
            pass
    return None


# ---------------------------------------------------------------------------
# File helpers
# ---------------------------------------------------------------------------


def download_file(url: str, file_name: Path) -> None:
    """Download a file from a URL if it does not already exist locally.

    Args:
        url (str): The URL from which to download the file.
        file_name (Path): The path where the downloaded file should be saved.
    """
    if not file_name.exists():
        import requests

        try:
            logging.info(f"Downloading {file_name} from {url}")
            response = requests.get(url)
            response.raise_for_status()
            file_name.write_bytes(response.content)
            logging.info(f"{file_name} downloaded successfully.")
        except requests.RequestException as e:
            logging.error(f"Failed to download {file_name}. Error: {e}")
    else:
        logging.info(f"{file_name} already exists.")


def zip_directory(output_zip: Path, target_dir: Path) -> None:
    """Create a ZIP archive containing the contents of a target directory.

    Args:
        output_zip (Path): The path to the output ZIP archive.
        target_dir (Path): The directory whose contents will be added.
    """
    logging.info(f"Create ZIP archive: {output_zip}")
    base_dir = target_dir.parent
    with zipfile.ZipFile(output_zip, "w", zipfile.ZIP_DEFLATED) as zipf:
        for file_path in target_dir.rglob("*"):
            if file_path.is_file():
                arcname = file_path.relative_to(base_dir)
                zipf.write(file_path, arcname)


def move_and_overwrite(src: Path, dst_dir: Path) -> None:
    """Move a file to a destination directory, overwriting any existing file.

    Args:
        src (Path): The source file path to move.
        dst_dir (Path): The destination directory.
    """
    dst_path = dst_dir / src.name
    try:
        if dst_path.exists():
            logging.debug(f"Overwriting existing file: {dst_path}")
            dst_path.unlink()
        logging.debug(f"Moving {src} to {dst_path}")
        shutil.move(str(src), str(dst_path))
    except FileNotFoundError as e:
        logging.error(f"File not found: {src}. Error: {e}")
    except PermissionError as e:
        logging.error(f"Permission denied when moving {src} to {dst_path}. Error: {e}")
    except Exception as e:
        logging.error(f"Failed to move {src} to {dst_path}. Error: {e}")


# ---------------------------------------------------------------------------
# JSON report helper
# ---------------------------------------------------------------------------


def write_json(data: dict, output_path: Path, label: str = "") -> None:
    """Write a dict as pretty-printed JSON.

    Args:
        data: Data to serialize.
        output_path: Destination file path.
        label: Human-readable label for the log message.
    """
    import json

    output_path.write_text(json.dumps(data, indent=2, default=list), encoding="utf-8")
    desc = label or output_path.stem
    logging.info(f"{desc} written to {output_path}")
