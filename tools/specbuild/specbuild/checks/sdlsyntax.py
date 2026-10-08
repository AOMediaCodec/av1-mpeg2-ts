"""SDL syntax validation against the MPEG SDL grammar.

Extracts SDL code blocks from ``.bs`` source files and pipes them through
the ``@mpeggroup/mpeg-sdl-parser`` Node.js package (via
``scripts/sdl_parse.mjs``) to verify each block parses cleanly against
ISO/IEC 23001-15 SDL.

Block detection
---------------

Three styles of SDL block are recognised:

1. ``\\`\\`\\`sdl`` fenced blocks — always recognised, anywhere.
2. ``\\`\\`\\`cpp`` fenced blocks — recognised in files listed in
   ``CONFIG.sdl_files`` (matches the existing ``--convert-sdl`` scoping).
   When ``CONFIG.sdl_files`` is empty, ``\\`\\`\\`cpp`` is recognised in
   every ``.bs`` file.
3. ``<pre class="sdl">`` and ``<xmp class="sdl">`` HTML blocks.

File scope
----------

If ``CONFIG.sdl_files`` is non-empty, only those files are checked.
Otherwise every ``.bs`` file in ``CONFIG.bikeshed_dir`` is checked,
excluding the merge target (``CONFIG.main_bs_file``) so the check does
not run twice on auto-generated content.
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
from pathlib import Path

from specbuild import PROJECT_ROOT
from specbuild.config import CONFIG

# Triple-backtick HTML block (`pre`/`xmp`) where the class attribute
# contains "sdl" (whitespace-separated, case-insensitive).
_SDL_TAG_RE = re.compile(
    r"<(?P<tag>pre|xmp)\b[^>]*\bclass\s*=\s*[\"']?[^\"'>]*\bsdl\b[^\"'>]*[\"']?[^>]*>"
    r"(?P<content>.*?)"
    r"</(?P=tag)\s*>",
    re.DOTALL | re.IGNORECASE,
)

# Maximum number of error lines forwarded per block to keep the build
# log readable when a block has dozens of errors.
_MAX_ERRORS_PER_BLOCK = 20


def _extract_sdl_blocks(content: str, filename: str, *, recognise_cpp: bool) -> list[dict]:
    """Return SDL blocks found in *content*.

    Each block is ``{"id", "content", "lineno", "lang"}`` where ``id`` is a
    stable identifier of the form ``"<filename>:<lineno>"`` used to map the
    parser's response back to its source location.
    """
    blocks: list[dict] = []
    lines = content.split("\n")

    in_fence = False
    fence_lang: str | None = None
    fence_content: list[str] = []
    fence_start_lineno = 0

    for idx, raw in enumerate(lines, start=1):
        stripped = raw.strip()
        if in_fence:
            if stripped == "```":
                blocks.append(
                    {
                        "id": f"{filename}:{fence_start_lineno}",
                        "content": "\n".join(fence_content),
                        "lineno": fence_start_lineno,
                        "lang": fence_lang,
                    }
                )
                in_fence = False
                fence_lang = None
                fence_content = []
            else:
                fence_content.append(raw)
        else:
            if stripped.startswith("```"):
                # Trim trailing space/info-string portion: ``` cpp args
                lang = stripped[3:].strip().split(" ", 1)[0].lower()
                if lang == "sdl" or (recognise_cpp and lang == "cpp"):
                    in_fence = True
                    fence_lang = lang
                    fence_content = []
                    fence_start_lineno = idx + 1  # content begins on next line

    # <pre class="sdl"> / <xmp class="sdl">
    for match in _SDL_TAG_RE.finditer(content):
        # Compute line number from match start
        prefix_lines = content.count("\n", 0, match.start())
        blocks.append(
            {
                "id": f"{filename}:{prefix_lines + 1}",
                "content": match.group("content"),
                "lineno": prefix_lines + 1,
                "lang": match.group("tag").lower(),
            }
        )

    return blocks


def _resolve_files_to_check() -> list[Path]:
    """List the ``.bs`` files this check should scan, per the scope rules."""
    bs_dir = Path(CONFIG.bikeshed_dir)
    sdl_files = list(CONFIG.sdl_files or ())

    if sdl_files:
        return [bs_dir / f for f in sdl_files]

    if not bs_dir.exists():
        return []

    # All .bs files except the merge target (which is a generated artifact).
    merge_target_name = Path(CONFIG.main_bs_file).name
    return sorted(f for f in bs_dir.glob("*.bs") if f.name != merge_target_name)


def _node_modules_present() -> bool:
    """Check whether the parser is npm-installed under PROJECT_ROOT."""
    return (PROJECT_ROOT / "node_modules" / "@mpeggroup" / "mpeg-sdl-parser").exists()


def _run_node_shim(blocks: list[dict]) -> list[dict] | None:
    """Pipe *blocks* through the Node parser shim.  Returns parsed results
    or ``None`` on infrastructure failure (missing shim, Node, or package).
    """
    shim = PROJECT_ROOT / "scripts" / "sdl_parse.mjs"
    if not shim.exists():
        logging.error(f"SDL parser shim not found: {shim}")
        return None
    if not _node_modules_present():
        logging.error(
            "SDL parser not installed.  Run `npm install` in the SpecBuild "
            "root to fetch @mpeggroup/mpeg-sdl-parser."
        )
        return None

    payload = json.dumps([{"id": b["id"], "content": b["content"]} for b in blocks])
    try:
        result = subprocess.run(
            ["node", str(shim)],
            input=payload,
            capture_output=True,
            text=True,
            timeout=300,
            check=True,
            cwd=str(PROJECT_ROOT),
        )
    except FileNotFoundError:
        logging.error("Node.js not found on PATH.  Install Node to enable SDL syntax checks.")
        return None
    except subprocess.CalledProcessError as exc:
        logging.error(f"SDL parser shim failed (exit {exc.returncode})")
        if exc.stderr:
            for line in exc.stderr.strip().splitlines()[-10:]:
                logging.error(f"  sdl_parse: {line}")
        return None
    except subprocess.TimeoutExpired:
        logging.error("SDL parser shim timed out after 5 min")
        return None

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        logging.error(f"SDL parser shim returned invalid JSON: {exc}")
        logging.error(f"  raw stdout (first 500 chars): {result.stdout[:500]!r}")
        return None


def run_sdl_syntax_check(*, strict: bool = False) -> int:
    """Validate SDL syntax across the configured ``.bs`` files.

    Args:
        strict: If True, return a positive error count so the caller can
            fail the build.  Otherwise just warn.

    Returns:
        Number of SDL syntax errors found across all blocks.  ``-1`` when
        the check infrastructure (Node, shim, npm package) is missing —
        the caller may treat this as a soft skip.
    """
    files = _resolve_files_to_check()
    if not files:
        logging.debug("SDL syntax check: no source files to scan")
        return 0

    sdl_files_set = set(CONFIG.sdl_files or ())
    cpp_global = not sdl_files_set  # if no explicit list, recognise ```cpp everywhere

    all_blocks: list[dict] = []
    for f in files:
        try:
            text = f.read_text(encoding="utf-8")
        except OSError as exc:
            logging.warning(f"SDL syntax check: cannot read {f}: {exc}")
            continue
        recognise_cpp = cpp_global or f.name in sdl_files_set
        all_blocks.extend(_extract_sdl_blocks(text, f.name, recognise_cpp=recognise_cpp))

    if not all_blocks:
        logging.debug("SDL syntax check: no SDL blocks found")
        return 0

    logging.info(
        f"SDL syntax check: validating {len(all_blocks)} block(s) across {len(files)} file(s)..."
    )

    results = _run_node_shim(all_blocks)
    if results is None:
        # Infrastructure problem already logged; treat as skip when not strict.
        return -1 if not strict else 1

    # Index blocks by id for line-offset lookup
    block_by_id = {b["id"]: b for b in all_blocks}

    total_errors = 0
    files_with_errors: set[str] = set()
    for entry in results:
        eid = entry.get("id", "<unknown>")
        errors = entry.get("errors", [])
        if not errors:
            continue
        block = block_by_id.get(eid, {})
        block_lineno = block.get("lineno", 0)
        files_with_errors.add(eid.split(":", 1)[0])

        log_fn = logging.error if strict else logging.warning
        log_fn(f"SDL syntax: {eid} — {len(errors)} error(s):")
        last_source_line: str | None = None
        for err in errors[:_MAX_ERRORS_PER_BLOCK]:
            offset = err.get("line")
            absolute = (block_lineno + offset - 1) if isinstance(offset, int) else None
            col = err.get("column")
            loc = f"line {absolute}" if absolute else f"block-line {offset}"
            if isinstance(col, int):
                loc += f", col {col}"
            # Strip the parser's redundant "SYNTAX ERROR: " prefix.
            msg = err.get("message", "<no message>")
            msg = re.sub(r"^SYNTAX ERROR:\s*", "", msg)
            log_fn(f"  {loc}: {msg}")
            # Show the source line under the error — only when it changes,
            # so two errors on the same line don't repeat the context.
            source_line = err.get("sourceLine")
            if source_line and source_line != last_source_line:
                log_fn(f"    │ {source_line}")
                last_source_line = source_line
            # Caret pointing at the offending column (best-effort).
            if source_line and isinstance(col, int) and col > 0:
                caret = " " * (col - 1) + "^"
                log_fn(f"    │ {caret}")
        if len(errors) > _MAX_ERRORS_PER_BLOCK:
            log_fn(f"  ... and {len(errors) - _MAX_ERRORS_PER_BLOCK} more")
        total_errors += len(errors)

    if total_errors:
        logging.warning(
            f"SDL syntax check: {total_errors} error(s) across {len(files_with_errors)} file(s)"
        )
    else:
        logging.info(f"SDL syntax check: all {len(all_blocks)} block(s) valid")

    return total_errors
