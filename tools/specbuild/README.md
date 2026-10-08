# specbuild

A tool for building [Bikeshed](https://speced.github.io/bikeshed/) specifications with PDF generation, HTML diffing, multipage output, standards document support (24 SDO flavors plus custom via TOML), quality assurance, and 90+ configurable features.

Designed to work with any Bikeshed-based spec. Ships with a demo *Bicycle Design & Assembly Specification* for testing and development.

## Quick Start

```bash
# Clone the repository
git clone <SpecBuild-repo-url>
cd SpecBuild

# Create and activate a virtual environment
python3 -m venv venv
source venv/bin/activate        # macOS / Linux
# venv\Scripts\activate         # Windows

# Install dependencies
pip install -e ".[dev]"

# Build the specification
python compile.py
# or, after pip install:
specbuild
```

The output is written to a directory named `YYYYMMDD_<sha>_<SpecName>_Spec_Draft/` containing the compiled `index.html` and all assets.

## Requirements

- **Python 3.10+**
- **Bikeshed** (installed automatically via `pip install -e .`)
- **Git** (required for branch/SHA detection and diff features)
- **Google Chrome** (optional, for `--pdf` via headless Chrome)
- **WeasyPrint** (optional, for `--weasyprint` PDF generation)
- **Pandoc** (optional, for `--docx` Word export)

## Project Structure

```
compile.py              # Main build entry point
specbuild/              # Core package (100+ modules)
  cli.py                #   Argument parsing and CLI builder
  config.py             #   SpecConfig dataclass + CONFIG singleton
  builder.py            #   Bikeshed compilation driver
  merge.py              #   .bs file merging (manifest-ordered)
  git.py                #   Branch/SHA/date extraction
  plugins.py            #   Plugin registry and decorator API
  plugin_registry.py    #   Declarative registration of all 80 built-in features
  profiles.py           #   Build profiles (18 built-in + TOML custom profiles)
  theme.py              #   Visual theming (fonts, colors, sizes)
  context.py            #   BuildContext dataclass shared across plugins
  multipart.py          #   Multi-part standard orchestration
  standards/            #   Standards document framework (11 modules)
    flavors.py, registry.py, metadata.py, boilerplate.py, ...
  checks/               #   Quality checks (read-only, concurrent, 16 modules)
    accessibility.py, editorial.py, linkcheck.py, refvalidate.py, standardsvalidate.py, ...
  enhancements/         #   DOM mutations (sequential, 23 modules)
    equations.py, changebars.py, watermark.py, boilerplate.py, isonumbering.py, ...
  output/               #   Output format generation (15 modules)
    pdf.py, docxexport.py, standalone.py, diff.py, amendment.py, isodocxml.py, ...
  analysis/             #   Reporting and analysis (18 modules)
    compliance.py, regression.py, buildreport.py, conformancelevels.py, ...
bikeshed/               # Specification source files
  manifest.txt          #   Build order and front-matter config
  header.bs             #   Metadata, title, abstract
  *.bs                  #   Specification content (merged in order)
  footer.include        #   Custom footer
scripts/                # Utility scripts (PDF, math, syntax, etc.)
tests/                  # Test suite (pytest, 3201 tests)
```

## Build Pipeline

```
 .bs source files          specbuild.toml / pyproject.toml
       │                              │
       ▼                              ▼
 ┌───────────┐    manifest.txt   ┌─────────┐
 │   Merge   │◄──────────────────│ Config  │
 └─────┬─────┘                   └─────────┘
       │  index.bs
       ▼
 ┌───────────┐
 │ Bikeshed  │  compile → index.html
 └─────┬─────┘
       │
       ▼
 ┌───────────────┐
 │ Post-process  │  copy assets, renumber annexes, code-block tables
 └─────┬─────────┘
       │
       ├──────────────────┐
       ▼                  ▼
 ┌─────────────┐   ┌──────────────┐
 │ Enhancements│   │Quality Checks│  (concurrent)
 │ (sequential)│   │  validation  │
 │ equations,  │   │  links, a11y │
 │ change bars,│   │  spelling,   │
 │ cover page, │   │  terminology │
 │ tooltips... │   └──────────────┘
 └─────┬───────┘
       │
       ▼
 ┌──────────────────────────────────────────┐
 │            Output Tasks                  │
 │  (parallelizable with --parallel-outputs)│
 ├──────┬───────┬──────┬─────┬─────┬───────┤
 │ PDF  │ DOCX  │LaTeX │HTML │Multi│Search │
 │      │       │      │alone│page │Index  │
 └──────┴───────┴──────┴─────┴─────┴───────┘
```

Detailed architecture diagrams are available in [`images/diagrams/`](images/diagrams/).

## Configuration

specbuild loads configuration from (in priority order):

1. **CLI flags** (highest priority)
2. **`specbuild.toml`** in the project root
3. **`[tool.specbuild]`** section in `pyproject.toml`

### Adapting for Your Specification

Create a `specbuild.toml` in your project root. Only override the fields you need:

```toml
spec_name = "MySpec"
spec_full_name = "My Specification Title"
repo_url = "https://github.com/example/my-spec.git"
repo_browse_url = "https://github.com/example/my-spec/tree/"
main_branch = "main"
sdl_files = ["conventions.bs", "decoding_process.bs"]
```

### Source Manifest

The `bikeshed/manifest.txt` file controls chapter ordering and front-matter:

```ini
[front-matter]
toc
lof
lot

[files]
header.bs
scope.bs
terms.bs
conventions.bs
# ...
bibliography.bs
```

Files are merged in the order listed. The `[front-matter]` section controls which auto-generated lists appear (Table of Contents, List of Figures, List of Tables).

## Build Commands

### Basic Builds

```bash
# Standard build
python compile.py

# Fast HTML-only build (no enhancements)
python compile.py --profile quick

# Working draft with equations and highlighting
python compile.py --profile draft

# Full review build with all quality checks
python compile.py --profile review

# Publication build with PDF and all features
python compile.py --profile publication

# Debug logging
python compile.py --log_level DEBUG
```

### Build Profiles

Profiles are predefined flag combinations. Use `--list-profiles` to see all available profiles and `--profile NAME` to apply one. CLI flags always override profile settings.

| Profile       | Description                                      |
|---------------|--------------------------------------------------|
| `quick`       | Fast HTML-only build, no enhancements            |
| `draft`       | Equations, keyword highlighting, basic validation |
| `review`      | All quality checks, change bars, tooltips        |
| `publication` | Full build with PDF, LOF, LOT, PWA               |
| `pdf-draft`   | Quick PDF with equations only                    |
| `pdf-final`   | Full PDF with all enhancements                   |
| `iso-draft`   | ISO working draft with structure validation      |
| `iso-publication` | ISO publication-ready with all checks, PDF, DOCX, XML |
| `iso-dis`     | ISO Draft International Standard submission      |
| `itu-draft`   | ITU-T working draft with structure validation    |
| `ietf-draft`  | IETF Internet-Draft build                        |
| `ieee-draft`  | IEEE working draft with structure validation     |
| `3gpp-draft`  | 3GPP working draft with structure validation     |
| `iso-video-draft` | ISO/IEC video codec working draft             |
| `iso-video-publication` | ISO/IEC video codec publication-ready build |
| `aom-draft`   | Alliance for Open Media spec draft (AV1/AV2)    |
| `iso-amendment` | ISO/IEC amendment document                     |
| `itu-amendment` | ITU-T amendment/corrigendum document           |

Custom profiles can be loaded from a TOML file with `--profiles-file PATH`.

### PDF Generation

```bash
# PDF via headless Google Chrome (default)
python compile.py --pdf

# PDF via WeasyPrint
python compile.py --weasyprint

# PDF customization
python compile.py --pdf --page-size letter --page-numbers \
    --lof --lot --toc-leaders css --cover-page

# Apple Silicon: use x86_64 Python for WeasyPrint
python compile.py --weasyprint --x86-python venv_x86/bin/python
```

### HTML Diffing

```bash
# Diff against main branch
python compile.py --diff

# Diff against specific commit
python compile.py --diff --diff_sha abc1234

# Skip re-cloning (if already cloned)
python compile.py --diff --no_clone

# Interactive diff viewer
python compile.py --diff_viewer

# Side-by-side diff explorer
python compile.py --diff_explorer
```

### Multipage Output

```bash
# Generate multipage HTML with navigation
python compile.py --multipage

# Customize sidebar
python compile.py --multipage --sidebar_position right
python compile.py --multipage --no_sidebar --no_breadcrumb
```

### Conditional Compilation

Build variant documents from the same source by including or excluding sections:

```bash
# Build only the core normative sections
specbuild --include-sections "header,scope,terms,conventions,frame_*,drivetrain_*,braking_*"

# Exclude informative annexes
specbuild --exclude-sections "annex_*,bibliography"

# Combine with other flags for targeted builds
specbuild --include-sections "header,scope,terms" --profile quick
```

Patterns use shell-style globs matched against ``.bs`` file stems (without the extension). The header file is always included to ensure valid Bikeshed output. Both ``--include-sections`` and ``--exclude-sections`` can be used together — include is applied first, then exclude.

### Alternative Export Formats

```bash
# Word document
python compile.py --docx

# ISO-styled Word document
python compile.py --iso-docx

# LaTeX
python compile.py --latex

# IsoDoc XML
python compile.py --isodoc-xml

# NISO STS XML
python compile.py --sts-xml

# Standalone HTML (all resources inlined)
python compile.py --standalone
```

## Standards Document Support

specbuild supports 24 standards body flavors (plus custom flavors via TOML), with dedicated profiles, validation, boilerplate injection, reference databases, and export formats for each organization.

### Supported SDO Flavors

`iso`, `itu-t`, `itu`, `ietf`, `iec`, `nist`, `ogc`, `cc`, `bipm`, `bsi`, `cen`, `cenelec`, `ieee`, `jis`, `unece`, `un`, `3gpp`, `jvet`, `mpeg`, `iso-video`, `itu-video`, `aom`, `av1`, `av2`, plus custom flavors via TOML inheritance.

### Standards Workflows

```bash
# ISO-flavored working draft
python compile.py --standards-flavor iso --profile iso-draft

# ISO publication-ready build with all checks, PDF, DOCX, and XML
python compile.py --profile iso-publication

# ISO DIS submission
python compile.py --profile iso-dis --standards-stage DIS

# Validate document structure per standards flavor
python compile.py --validate-standards --standards-flavor iso

# Validate bibliography references against standards database
python compile.py --validate-references
python compile.py --validate-references --online-refs   # live API validation

# Amendment/corrigendum document
python compile.py --amendment --base-document "ISO/IEC 14496-10:2022"

# Multi-part standard features
python compile.py --collection-toc --cross-part-links

# Standards enhancements
python compile.py --inject-boilerplate --iso-numbering --format-bibliography
python compile.py --auto-expand-refs --import-terms
python compile.py --structured-requirements --conformance-requirements
python compile.py --reviewer-notes
python compile.py --conformance-levels "Main,Main 10,High Tier"
```

## Quality Assurance

```bash
# Run ALL quality checks at once
python compile.py --all-checks

# Run all checks with a build report
python compile.py --all-checks --build-report html

# Or run individual checks:

# Cross-reference validation
python compile.py --validate-refs
python compile.py --validate-refs-strict    # Exit with error on broken refs

# RFC 2119 compliance matrix
python compile.py --compliance-matrix

# Editorial consistency check
python compile.py --editorial
python compile.py --editorial-strict

# Accessibility audit (WCAG)
python compile.py --accessibility-audit

# Check broken images and external links
python compile.py --check-images --check-links

# Table structure validation
python compile.py --check-tables

# Referenceable table/figure check
python compile.py --check-referenceable

# Spelling and terminology
python compile.py --spellcheck --check-terminology

# Duplicate paragraph detection
python compile.py --check-duplicates --duplicate-threshold 0.7

# Definition consistency
python compile.py --check-dfn

# Uncited bibliography entries
python compile.py --check-orphan-refs
```

## Analysis and Reports

```bash
# Build report (HTML or JSON)
python compile.py --build-report html
python compile.py --build-report json
python compile.py --build-report both

# Definition cross-reference index
python compile.py --dfn-index

# Spec metrics (word count, sections, tables, etc.)
python compile.py --spec-metrics

# Cross-reference report
python compile.py --xref-report

# PR summary from git diff
python compile.py --pr-summary

# Normative dependency graph
python compile.py --normative-deps

# Spec version comparison dashboard
python compile.py --spec-compare path/to/baseline.html
```

## Build Regression Checking

Track structural changes across builds to catch unintended regressions:

```bash
# Save a baseline snapshot of the current build
python compile.py --save-baseline

# Check current build against saved baseline
python compile.py --regression

# Check against a specific HTML file
python compile.py --regression path/to/baseline.html

# Strict mode: exit with error on regressions
python compile.py --regression --regression-strict
```

The baseline is saved as `.specbuild_baseline.json` — a JSON snapshot of headings, element counts, and git metadata.

## Content Enhancements

```bash
# Equation numbering (enabled by default)
python compile.py --number-equations
python compile.py --no-number-equations

# RFC 2119 keyword highlighting
python compile.py --highlight-keywords

# Change bars marking modified text
python compile.py --change-bars
python compile.py --change-bars v1.0    # Since specific ref

# Table of changes
python compile.py --table-of-changes

# Revision history from git tags
python compile.py --revision-history

# Tooltips (enabled by default; use --no-* to disable)
python compile.py --no-figure-table-tooltips
python compile.py --no-syntax-tooltips

# Cover page
python compile.py --cover-page --cover-title "My Spec" \
    --cover-organization "ACME" --cover-doc-number "ACME-001"

# Watermark
python compile.py --watermark draft
python compile.py --watermark confidential

# Search index (Ctrl+K / Cmd+K)
python compile.py --search-index

# Progressive Web App (offline viewing)
python compile.py --pwa

# Content width (default: 60em from theme; 'none' to disable)
python compile.py --content-width 80ch
python compile.py --content-width 900px
python compile.py --content-width none    # full browser width
```

### Figure and Table Alignment

Figures and tables are centered by default in both HTML and PDF. Override per-element in `.bs` source with Bikeshed attribute syntax:

```
<figure class="align-left">...</figure>
<table class="full-width">...</table>
```

Available classes:
- `.align-left` — left-align
- `.align-right` — right-align
- `.align-center` — explicit center (same as default)
- `.full-width` — table spans 100% width (no centering)

## Output Options

```bash
# ZIP archive
python compile.py --zip

# Minify HTML
python compile.py --minify

# Externalize CSS/JS to separate files
python compile.py --externalize_resources

# Mobile-optimized (collapsible sections)
python compile.py --mobile_optimized

# Parallel output generation
python compile.py --parallel-outputs --pdf --standalone --zip
```

## Diagnostics & Provenance

```bash
# System diagnostic report — checks Python, Bikeshed, Chrome,
# WeasyPrint, Pandoc, Ghostscript, python-docx/pptx, openpyxl, Git,
# project root, active flavor, cache dir, and agent worktrees.
# Critical-deps failure (Python / Bikeshed / Git) gates exit code 1;
# optional deps don't.
python compile.py --diagnose

# Build provenance manifest — emits provenance.json next to the
# build output with sha256 of every .bs source + assets, tool
# versions (bikeshed, pandoc, git), build identity (branch / SHA /
# date / spec_name), and final-output hash. Same inputs produce
# byte-identical output.
python compile.py --provenance
```

## AI-Assisted Review

```bash
# OPT-IN: per-clause change-summary via the Anthropic API,
# emits ai_review.md alongside the build. Strictly local-files-only,
# never modifies anything. Cached on disk so repeated CI runs are
# deterministic and don't re-bill.
python compile.py --ai-review

# Custom baseline ref (default: latest tag → origin/main → main → HEAD~1)
python compile.py --ai-review --ai-review-baseline v1.0

# Print the prompt without calling the LLM (for inspection)
python compile.py --ai-review --ai-review-dry-run
```

Requires `ANTHROPIC_API_KEY` env var. Default model `claude-sonnet-4.6`; override via `SPECBUILD_AI_MODEL`. Cache: `~/.specbuild_cache/aireview/`.

## Math / Equation Lint

```bash
# Lint <math>, <span class="math">, and math-like <code> for:
# - Unbalanced (), [], {}
# - Inconsistent identifier casing (MaxCuSize vs maxCuSize)
# - Identifiers used in math context without a corresponding <dfn>
python compile.py --math-lint
python compile.py --math-lint-strict   # exit 1 on any finding
```

The math-like-code heuristic skips prose `<code>foo()</code>` (only triggers on real math markers like `_`, `^`, `\`, Unicode operators).

## Bibliography Auto-Enrichment

```bash
# One-shot tool: read a TOML/YAML bibliography file, look up DOI /
# arXiv / ISBN identifiers via Crossref + arXiv APIs, fill in missing
# titles / authors / year / publisher. Existing fields are NEVER
# overwritten.
python compile.py --bib-enrich path/to/biblio.toml
```

Cache: `~/.specbuild_cache/bibenrich/` (DOI / arXiv responses keyed by SHA-256). Polite User-Agent. Tolerates network failures gracefully.

## Test-Vector / Conformance-Bitstream Tracking

```bash
# Validate a TOML manifest of conformance bitstreams (file existence
# + sha256) and emit a clause→bitstream coverage matrix HTML report.
python compile.py --testvector-manifest vectors.toml

# Skip sha256 verification (fast file-existence-only check)
python compile.py --testvector-manifest vectors.toml --testvector-no-hashes

# Cross-spec coverage migration (HEVC → VVC, etc.)
python compile.py --testvector-crosswalk old_vectors.toml new_vectors.toml
# Reports: vectors that survive unchanged, vectors that need
# re-targeting (clause renamed), vectors retired (clause removed).
```

Sample manifest:

```toml
[[vectors]]
name = "AVC_intra_8bit_001"
path = "vectors/AVC/intra/AVC_intra_8bit_001.h264"
sha256 = "abcdef..."
clauses = ["7.3.2.1", "8.5.3"]
description = "8-bit intra-only stream exercising slice_header()"
profile = "Main"
```

## Cross-Spec Migration & Code-Sync Tools

For editors maintaining sister specs (HEVC ↔ VVC ↔ AV1 ↔ AV2):

```bash
# Compare a VTM/HM/JM C++ syntax function against the spec's SDL
# table; report added / removed / descriptor-changed / reordered
# fields. Recognized macros: READ_FLAG → u(1), READ_CODE(N,…) →
# u(N), READ_UVLC → ue(v), READ_SVLC → se(v), READ_UE_LIMITED,
# READ_SVLC_LIMITED. if(...) blocks attach a condition to subsequent
# rows.
python compile.py --codesync VTM/Source/Lib/DecoderLib/VLCReader.cpp output_dir/diff.html

# Mirror direction: extract <table class="sdl-syntax-table"> rows
# from the compiled HTML and emit C++ skeleton headers + per-syntax-
# element decoder stubs.
python compile.py --export-sdl output_dir/

# Diff two SDL-tagged spec versions by syntax-element name +
# descriptor + bit-width. Reports renamed (similarity heuristic),
# added, removed, descriptor-changed fields. HTML + JSON output.
python compile.py --syntax-diff path/to/hevc.bs path/to/vvc.bs
```

## Profile / Level / Tier Validation

```bash
# TOML-driven cross-check between profile/level/tier definitions and
# data-conformance-profile markers / Annex A tables in the spec.
python compile.py --profiles-spec profiles.toml
```

Reports missing profiles, orphan profile markers, and levels referenced in body but not defined in tables.

## Authoring Scaffolding

```bash
# Clause-level template: scaffolds a Bikeshed snippet for a new
# section. TYPE ∈ {syntax, process, profile, sei, annex}.
python compile.py --new-clause syntax "Picture parameter set RBSP semantics"
```

The output is printed to stdout (redirect into your `.bs` file as needed). Skeleton includes heading, syntax table, semantics block, decoding process — whichever apply for the chosen TYPE.

## Errata Backporting

```bash
# Generate per-erratum .patch files (via git format-patch) from a
# TOML errata manifest, plus a Markdown change-impact note.
python compile.py --backport-errata errata.toml --target-branch release/1.2
```

Pairs naturally with `analysis/errata.py` which catalogs errata in the source.

## Standards Meeting Contribution Tools

Specbuild includes a set of tools specifically designed for standards meetings (JVET, MPEG, AOM, ISO):

### NISO STS XML Export (Complete)

The `--sts-xml` output now produces fully conformant NISO STS 1.2 XML:

```bash
python compile.py --sts-xml
# Validates against NISO-STS-interchange-1-2-MathML3.dtd
```

**New in STS XML export:**
- Display equations → `<disp-formula><tex-math>` (TeX source recovered from `data-tex` attributes set during equation numbering)
- Inline math → `<inline-formula><tex-math>`
- Notes → `<non-normative-note>` with ISO-style numbered labels (NOTE, NOTE 2, NOTE 3 …)
- Examples → `<non-normative-example>` with numbered labels (EXAMPLE, EXAMPLE 2 …)
- Code blocks → `<code preformat-type="computer" language="...">` with language detection
- Internal links → `<xref ref-type="sec|table|fig|disp-formula" rid="...">` (full inline markup preserved)
- Tables → complete `<thead>`/`<tbody>`/`<tr>`/`<th>`/`<td>` with colspan/rowspan
- Bibliography → structured `<std><std-id><std-ref><title><pub-date>` for ISO/IEC/ITU/IEEE/RFC entries
- Requirements → `<named-content content-type="requirement">` when `--requirements-json` is also active

### Requirement ID System

```bash
# Assign REQ-<section>-NNN IDs to RFC 2119 normative statements
python compile.py --requirement-ids

# Also assign global sequential REQ-NNNN IDs and export manifest JSON
python compile.py --requirement-ids --requirements-json
# Outputs: requirements.json, requirements.csv, requirements.html,
#          requirements_manifest.json (for build-to-build diffing)
```

The `--requirements-json` flag also injects `data-req-id` and `data-req-global` HTML attributes, which are picked up by `--sts-xml` to emit `<named-content content-type="requirement">` wrappers.

### Relaton Bibliography Enrichment

```bash
# Enrich bibliography with structured metadata from the Relaton REST API
python compile.py --relaton-enrich

# Use a local relaton-data checkout (offline)
python compile.py --relaton-enrich --relaton-data-dir ~/relaton-data-iso

# Combined with STS XML for structured <std> elements
python compile.py --relaton-enrich --sts-xml
```

Adds `data-relaton-*` attributes to bibliography `<li>` elements: `data-relaton-title`, `data-relaton-publisher`, `data-relaton-year`, `data-relaton-status`, `data-relaton-url`. Results are cached in `~/.specbuild_cache/relaton/` for 30 days.

### Unified Numbering Engine

Equations, notes, and examples are numbered consistently with ISO rules:

```bash
# Standard build with equation numbering (enabled by default)
python compile.py --number-equations

# Extended numbering for notes and examples (via renumber_all)
python scripts/renumber_annexes.py --renumber-all output/*/index.html
```

- **Equations**: `(5.1)`, `(A.2)` — annex letters applied automatically
- **Notes**: NOTE, NOTE 2, NOTE 3 … per top-level clause (reset per h2)
- **Examples**: EXAMPLE, EXAMPLE 2, EXAMPLE 3 … per top-level clause

### Cross-Document Clause References

```bash
# Resolve [[xpart:N/id]] placeholders to cross-part links
# and write xpart_refs.json for incoming reference tracking
python compile.py --xpart-manifest
```

Write `[[xpart:2/clause-7-3-2]]` in your `.bs` source to link to Part 2, clause `clause-7-3-2`. The resulting HTML link carries `class="cross-part-ref" data-part="2" data-target="clause-7-3-2"`.

Configure cross-part targets in `specbuild.toml`:

```toml
[standards.multipart]
base_docnumber = "ISO/IEC 14496"
[[standards.multipart.parts]]
part_number = "2"
title = "Visual"
path = "../iso14496-2"
```

### Ballot Comment Tracker

```bash
# Load SC29/JVET ballot comment spreadsheet and generate interactive HTML tracker
python compile.py --ballot-comments comments.xlsx
python compile.py --ballot-comments comments.csv

# Outputs: ballot_comments.html (filterable table), ballot_comments.json
```

Supports the standard SC29/JVET/MPEG comment spreadsheet format. Column headers are auto-detected (flexible mapping). Requires `pip install specbuild[ballot]` for XLSX support.

Each comment links to the corresponding spec clause. The HTML tracker supports filtering by country, type, and resolution status.

### Contribution Cover Page

```bash
# Inject a standards contribution cover page
python compile.py --contribution-cover
```

Configure the cover page in `specbuild.toml`:

```toml
[standards.contribution]
input_doc = "JVET-AJ0123"
meeting = "123rd JVET Meeting, Geneva, January 2026"
title = "On improving prediction efficiency for complex textures"
authors = ["Alexis Tourapis", "Jens-Rainer Ohm"]
affiliation = "Apple Inc."
status = "Input"
abstract = "This contribution proposes..."
date = "2026-01-15"
```

Three SDO-flavored templates are available via `--standards-flavor`: `jvet` (default, dark-blue header), `mpeg` (ISO/IEC JTC 1/SC 29 branding), `aom` (green AOM branding).

### Meeting Slides Generator

```bash
# Generate a PPTX presentation from the built spec
python compile.py --slides

# Include only specific sections
python compile.py --slides --slides-sections "scope,s5,s6,s7"
```

Produces a dark-blue AOM/JVET-themed PPTX with:
- Title slide
- Agenda slide with all included section headings
- One content slide per section with bullet points extracted from body text

### Live Preview Server

```bash
# Build, serve on localhost, and watch for changes
python compile.py --serve
python compile.py --serve --serve-port 9000

# implies --watch
```

### Change Impact Analysis

```bash
# Compare current build against previous and classify changed sections
python compile.py --impact

# Compare against a specific baseline
python compile.py --impact --impact-base path/to/old/index.html
# Outputs: impact_report.html, impact_report.json
```

Sections are classified as `normative`, `conformance`, or `informative` based on content keywords.

### Spec Completeness Check

```bash
# Find TODO/TBD markers, empty sections, unfilled editor notes
python compile.py --completeness
python compile.py --completeness --completeness-strict   # exit 1 on errors
# Output: completeness_report.html
```

---

## Release Automation

```bash
# Full release workflow: validate clean tree, save baseline,
# generate changelog, create git tag
python compile.py --release v1.0
```

## Watch Mode

```bash
# Auto-rebuild on source file changes
python compile.py --watch
python compile.py --watch --watch-interval 2.0
```

## Feature Discovery

```bash
# List all available features grouped by pipeline phase
python compile.py --help-features

# List available build profiles
python compile.py --list-profiles

# Full CLI help
python compile.py --help
```

## Plugin System

specbuild includes a decorator-based plugin registry. All 90+ built-in features are registered as plugins, and `--help-features` displays them grouped by pipeline phase:

- **Quality Checks** — read-only analysis (run concurrently)
- **Enhancements** — DOM mutations applied sequentially
- **Output Tasks** — independent outputs (parallelizable with `--parallel-outputs`)

See `specbuild/plugins.py` for the registration API.

## Theming

Visual styling defaults (fonts, colors, sizes, page setup, watermarks, cover page) are defined in `specbuild/theme.py`. To customize, add a `[theme]` section to `specbuild.toml` with only the fields you want to change — you should never need to edit `theme.py` directly.

```toml
[theme]
content_width = "80ch"
font_sans = "Helvetica Neue, Arial, sans-serif"
color_accent = "#0055aa"
annex_heading_format = "letter"
```

A complete `specbuild.toml` with all defaults is included in the repository for reference. See [`docs/THEMING.md`](docs/THEMING.md) for the full field reference.

## Development

### Running Tests

```bash
# Full test suite
pytest

# Specific test file
pytest tests/test_regression.py -v

# Run with coverage (if installed)
pytest --cov=specbuild
```

### Linting

```bash
# Check formatting
ruff format --check specbuild/ tests/

# Check lint rules
ruff check specbuild/ tests/

# Auto-fix
ruff check --fix specbuild/ tests/
ruff format specbuild/ tests/
```

### CI

GitHub Actions runs on every push and PR to `main`:

- **Tests**: Python 3.10, 3.12, 3.13 matrix
- **Lint**: ruff format + lint checks
- **Build smoke test**: Full build with debug logging, artifact upload

## Dependencies

### Core (installed with `pip install -e .`)

| Package        | Purpose                              |
|----------------|--------------------------------------|
| beautifulsoup4 | HTML parsing and analysis            |
| bikeshed       | Specification preprocessor           |
| lxml           | Fast HTML/XML parser                 |
| Pygments       | Syntax highlighting                  |
| requests       | HTTP client (htmldiff download, etc.)|

### Optional Extras

```bash
pip install -e ".[pdf]"     # weasyprint, pypdf, pillow
pip install -e ".[ballot]"  # openpyxl (ballot comment XLSX loading)
pip install -e ".[test]"    # pytest
pip install -e ".[dev]"     # all above + ruff
```

## License

BSD-3-Clause
