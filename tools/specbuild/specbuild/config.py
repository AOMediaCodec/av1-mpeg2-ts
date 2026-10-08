"""Specification build configuration."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, fields
from pathlib import Path


@dataclass
class SpecConfig:
    """Configuration for a specification build.

    Override the defaults to adapt the build pipeline for a different
    specification.  The current defaults are for the Bicycle Design &
    Assembly Specification (test/demo spec).

    To customise for your own spec, create a ``specbuild.toml`` file in the
    project root (or add a ``[tool.specbuild]`` section to ``pyproject.toml``).
    Only the fields you want to change need to be specified::

        # specbuild.toml
        spec_name = "AV2"
        spec_full_name = "AV2 Bitstream & Decoding Process Specification"
        repo_url = "https://gitlab.com/AOMediaCodec/av2-spec.git"
        repo_browse_url = "https://gitlab.com/AOMediaCodec/av2-spec/-/tree/"
        sdl_files = ["conventions.bs", "decoding_process.bs"]
    """

    # Spec identity
    spec_name: str = "Bicycle"
    spec_full_name: str = "Bicycle Design & Assembly Specification"

    # Directory and file structure
    bikeshed_dir: str = "bikeshed"
    main_bs_file: str = "index.bs"
    diff_bs_file: str = "index_diff_hack.bs"
    header_file: str = "header.bs"

    # Git / Repository
    # repo_url is intentionally empty by default.  Set it in specbuild.toml
    # to enable the clone-based diff strategy.  When empty, the diff pipeline
    # falls back to auto-detecting the remote URL from `git remote get-url origin`.
    repo_url: str = ""
    repo_browse_url: str = ""
    main_branch_clone_dir: str = "downloads/spec-main"
    main_branch: str = "main"

    # Version placeholders in the header file (replaced during build)
    version_url_placeholder: str = "VERSION_URL"
    version_text_placeholder: str = "VERSION_TEXT"

    # Output directory naming template ({date}, {sha}, {spec_name} are substituted)
    output_dir_template: str = "{spec_name}_Spec"

    # External tools
    htmldiff_url: str = "https://raw.githubusercontent.com/w3c/htmldiff-ui/main/htmldiff.pl"

    # Source files with special handling.  Defaults are intentionally empty
    # — the bicycle demo overrides them in its own specbuild.toml.  Other
    # specs opt in only if they actually use these features.
    symbols_file: str = ""
    sort_symbols_file: str = ""
    tables_file: str = ""
    sdl_files: tuple[str, ...] = ()
    # Path to SDL descriptor config, relative to the spec root.
    # When empty, uses the specbuild package's built-in config/sdl_descriptors.cfg.
    sdl_descriptors_file: str = ""

    # SDL indentation: how many source spaces equal one indent level (default 4).
    # When 0, indentation is inferred from brace/bracket depth in the source
    # (use this for specs whose SDL blocks have no leading whitespace).
    sdl_indent_spaces: int = 4

    # SDL indent step rendered in the HTML table (em units per level, default 1.0).
    sdl_indent_em: float = 1.0

    # Optional: path to an x86_64 Python for WeasyPrint on Apple Silicon
    x86_python_path: str = "venv_x86/bin/python"

    # When True, renumber the Introduction section as "0" and shift all
    # subsequent top-level clause numbers down by 1 (ISO/IEC convention).
    introduction_section_zero: bool = False

    # When True, post-process HEVC-style <div class='equation'>$$ ... $$</div>
    # blocks: pseudocode → <pre>, pure math → MathML via latex2mathml.
    hevc_equations: bool = False

    # Table of contents depth (1–6; controls DOCX toc-depth and CSS visibility)
    toc_depth: int = 3

    # Source format: "bikeshed" (default) or "asciidoc"
    source_format: str = "bikeshed"

    # AsciiDoc source directory (relative to project root)
    asciidoc_dir: str = "adoc"

    # Main AsciiDoc entry-point file (relative to asciidoc_dir)
    main_adoc_file: str = "document.adoc"

    # Asciidoctor binary path (override if asciidoctor is not on PATH)
    asciidoctor_bin: str = "asciidoctor"

    # Resolved source directory for AsciiDoc builds (set during detection)
    asciidoc_source_dir: str = ""


# Active configuration singleton.
CONFIG = SpecConfig()


@dataclass
class StandardsConfig:
    """Standards document configuration (populated from [standards] in TOML)."""

    flavor: str = ""
    docnumber: str = ""
    partnumber: str = ""
    edition: str = ""
    copyright_year: str = ""
    stage: str = ""
    doc_type: str = "standard"
    technical_committee: str = ""
    subcommittee: str = ""
    workgroup: str = ""
    language: str = "en"
    title_intro: str = ""
    title_main: str = ""
    title_part: str = ""
    secretariat: str = ""
    series: str = ""
    study_group: str = ""
    category: str = ""
    intended_status: str = ""
    custom_boilerplate_dir: str = ""
    base_document: str = ""
    amendment_number: str = "1"
    conformance_levels: tuple[str, ...] = ()


STANDARDS = StandardsConfig()

# Names of all valid SpecConfig fields (for validation).
_VALID_FIELDS = frozenset(f.name for f in fields(SpecConfig))
_VALID_STANDARDS_FIELDS = frozenset(f.name for f in fields(StandardsConfig))

# Track which fields were explicitly set via load_config / _apply_overrides.
# Lets autodetect distinguish "user-provided" from "still at default" without
# comparing values (which fails when the user happens to set a field to its
# default — e.g. spec_name = "Bicycle").
_LOADED_FIELDS: set[str] = set()


def _read_toml(path: Path) -> dict:
    """Read a TOML file and return its contents as a dict."""
    try:
        import tomllib
    except ModuleNotFoundError:
        try:
            import tomli as tomllib  # type: ignore[no-redef]
        except ModuleNotFoundError:
            raise RuntimeError(
                "TOML support requires Python 3.11+ or the 'tomli' package. "
                "Install it with: pip install tomli"
            ) from None
    return tomllib.loads(path.read_text(encoding="utf-8"))


def _apply_overrides(overrides: dict, source: str) -> int:
    """Apply a dict of overrides to the CONFIG singleton.

    Also handles a ``[theme]`` sub-table: any keys inside it are forwarded
    to the :data:`specbuild.theme.THEME` singleton.

    Returns the number of fields that were updated.
    """
    from dataclasses import fields as dc_fields

    from specbuild.theme import THEME, Theme

    _valid_theme_fields = frozenset(f.name for f in dc_fields(Theme))

    count = 0
    for key, value in overrides.items():
        # Handle [theme] sub-table
        if key == "theme" and isinstance(value, dict):
            for tkey, tval in value.items():
                if tkey not in _valid_theme_fields:
                    logging.warning(f"{source} [theme]: unknown field '{tkey}' (ignored)")
                    continue
                setattr(THEME, tkey, tval)
                count += 1
            continue

        # Handle [standards] sub-table
        if key == "standards" and isinstance(value, dict):
            for skey, sval in value.items():
                if skey == "multipart" and isinstance(sval, dict):
                    from specbuild.multipart import load_multipart_config

                    load_multipart_config(sval)
                    count += 1
                    continue
                if skey == "custom_references" and isinstance(sval, dict):
                    from specbuild.standards.customrefs import load_custom_references

                    count += load_custom_references(sval)
                    continue
                if skey == "custom_flavors" and isinstance(sval, dict):
                    from specbuild.standards.customflavors import load_custom_flavors

                    count += load_custom_flavors(sval)
                    continue
                if skey not in _VALID_STANDARDS_FIELDS:
                    logging.warning(f"{source} [standards]: unknown field '{skey}' (ignored)")
                    continue
                if isinstance(getattr(STANDARDS, skey), tuple) and isinstance(sval, list):
                    sval = tuple(sval)
                setattr(STANDARDS, skey, sval)
                count += 1
            continue

        if key not in _VALID_FIELDS:
            logging.warning(f"{source}: unknown config field '{key}' (ignored)")
            continue
        # Convert lists to tuples for tuple-typed fields (e.g. sdl_files)
        if isinstance(getattr(CONFIG, key), tuple) and isinstance(value, list):
            value = tuple(value)
        setattr(CONFIG, key, value)
        _LOADED_FIELDS.add(key)
        count += 1
    return count


def load_config(config_path: Path | None = None) -> int:
    """Load configuration from a TOML file into the CONFIG singleton.

    Resolution order (first found wins):

    1. Explicit *config_path* argument (e.g. from ``--config`` CLI flag).
    2. ``specbuild.toml`` in the current working directory.
    3. ``[tool.specbuild]`` section in ``pyproject.toml`` in the CWD.

    Returns the number of fields that were updated (0 if no config found).
    """
    # 1. Explicit path
    if config_path is not None:
        if not config_path.exists():
            logging.error(f"Config file not found: {config_path}")
            raise FileNotFoundError(f"Config file not found: {config_path}")
        data = _read_toml(config_path)
        n = _apply_overrides(data, str(config_path))
        logging.info(f"Loaded {n} config field(s) from {config_path}")
        return n

    # 2. specbuild.toml
    specbuild_toml = Path("specbuild.toml")
    if specbuild_toml.exists():
        data = _read_toml(specbuild_toml)
        n = _apply_overrides(data, "specbuild.toml")
        logging.info(f"Loaded {n} config field(s) from specbuild.toml")
        return n

    # 3. [tool.specbuild] in pyproject.toml
    pyproject = Path("pyproject.toml")
    if pyproject.exists():
        data = _read_toml(pyproject)
        section = data.get("tool", {}).get("specbuild", {})
        if section:
            n = _apply_overrides(section, "pyproject.toml [tool.specbuild]")
            logging.info(f"Loaded {n} config field(s) from pyproject.toml [tool.specbuild]")
            return n

    return 0


# Hidden filename used as the merge target when the configured
# main_bs_file would collide with a source file (single-file mode).
_SINGLE_FILE_MERGE_TARGET = ".specbuild_main.bs"

# Match the Bikeshed metadata block at the top of an .bs file.
_METADATA_BLOCK_RE = re.compile(
    r"<pre\s+class=['\"]metadata['\"][^>]*>(.*?)</pre>",
    re.DOTALL | re.IGNORECASE,
)


def _parse_bikeshed_metadata(source_file: Path) -> dict[str, str]:
    """Parse the ``<pre class='metadata'>`` block of a Bikeshed source file.

    Returns a dict of the simple ``Key: value`` lines inside the block.
    Last-occurrence wins on duplicate keys.  Returns an empty dict if
    the file is missing or has no metadata block.
    """
    if not source_file.exists():
        return {}
    try:
        text = source_file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    match = _METADATA_BLOCK_RE.search(text)
    if not match:
        return {}
    result: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            result[key.strip()] = value.strip()
    return result


def _derive_identity_from_source() -> None:
    """Fill in ``spec_name`` / ``spec_full_name`` from Bikeshed metadata.

    Only overrides fields the user did not set explicitly via TOML — so
    ``specbuild.toml`` always wins, even when its values happen to match
    the dataclass default.

    Tries the configured ``<bikeshed_dir>/<header_file>`` first.  If that
    file is missing or has no metadata block (e.g. specs that name their
    header ``00_Header.bs`` instead of the default ``header.bs``), scans
    every ``.bs`` file in the source directory and uses the first one
    that contains a ``<pre class='metadata'>`` block.
    """
    bs_dir = Path(CONFIG.bikeshed_dir)

    candidates: list[Path] = []
    explicit = bs_dir / CONFIG.header_file
    if explicit.exists():
        candidates.append(explicit)
    if bs_dir.exists():
        candidates.extend(sorted(p for p in bs_dir.glob("*.bs") if p != explicit))

    meta: dict[str, str] = {}
    for candidate in candidates:
        meta = _parse_bikeshed_metadata(candidate)
        if meta:
            break
    if not meta:
        return

    shortname = meta.get("Shortname")
    title = meta.get("Title")

    if "spec_name" not in _LOADED_FIELDS and shortname:
        CONFIG.spec_name = shortname
        logging.debug(f"spec_name derived from Bikeshed metadata: '{CONFIG.spec_name}'")

    if "spec_full_name" not in _LOADED_FIELDS and title:
        CONFIG.spec_full_name = title
        logging.debug(f"spec_full_name derived from Bikeshed metadata: '{CONFIG.spec_full_name}'")


def autodetect_layout() -> bool:
    """Adjust ``CONFIG`` for the current working directory's layout.

    Runs after :func:`load_config` and inspects the filesystem to bridge
    two common Bikeshed project shapes:

    1. **Multi-file** — ``CONFIG.bikeshed_dir`` exists (e.g. ``bikeshed/``)
       and contains the chapter ``.bs`` files plus an optional manifest.
       Nothing is changed.
    2. **Single-file** — ``CONFIG.bikeshed_dir`` does not exist but one or
       more ``.bs`` files live at CWD.  ``bikeshed_dir`` is rewritten to
       ``"."`` so the rest of the pipeline finds them.

    When source-and-output collide (the merge would read and write the
    same file), the merge target ``main_bs_file`` is rewritten to a
    hidden working file (``.specbuild_main.bs``) so the user's source
    file is left untouched.  If the user explicitly set ``header_file``
    to the original ``main_bs_file``, it follows the rewrite.

    Returns:
        ``True`` when single-file layout was detected and applied,
        ``False`` otherwise.
    """
    bs_dir = Path(CONFIG.bikeshed_dir)
    if bs_dir.exists():
        _derive_identity_from_source()
        return False  # multi-file layout already in place

    cwd_bs_files = list(Path(".").glob("*.bs"))
    if not cwd_bs_files:
        return False  # no Bikeshed source detected at CWD either

    logging.debug(
        f"Single-file layout detected: bikeshed_dir '{bs_dir}' missing, "
        f"using CWD with {len(cwd_bs_files)} .bs file(s)"
    )
    CONFIG.bikeshed_dir = "."

    # Detect source-vs-merge-target collision.  If main_bs_file points
    # to one of the source files in CWD, rewrite the merge target.
    original_main = CONFIG.main_bs_file
    if (Path(".") / original_main).exists():
        CONFIG.main_bs_file = _SINGLE_FILE_MERGE_TARGET
        logging.debug(
            f"Source file '{original_main}' would collide with merge target; "
            f"writing merged output to '{CONFIG.main_bs_file}' instead"
        )
        # If header_file was the (now-rewritten) main file, follow it.
        if CONFIG.header_file == original_main:
            CONFIG.header_file = CONFIG.main_bs_file

    # If header_file points at a file that doesn't exist (e.g. the
    # default 'header.bs' on a single-file spec), fall back to the
    # original source so date/SHA substitution still has a target.
    if not (Path(".") / CONFIG.header_file).exists():
        CONFIG.header_file = original_main
        logging.debug(f"header_file defaulted to '{original_main}' (no separate header file)")

    _derive_identity_from_source()
    return True
