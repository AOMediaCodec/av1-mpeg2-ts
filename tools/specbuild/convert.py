"""specbuild format converter.

Converts documents from other formats into Bikeshed source trees
suitable for use with the specbuild pipeline.

Supported sources
-----------------
- ``metanorma`` — Metanorma/AsciiDoc ISO standard projects
- ``iso-docx``  — ISO publication Word (.docx) files

Usage::

    python convert.py --from metanorma /path/to/project
    python convert.py --from metanorma /path/to/project --output /path/to/output
    python convert.py --from metanorma doc.adoc --output ./heif-bikeshed
    python convert.py --from metanorma doc.adoc --output ./heif --overwrite

    python convert.py --from iso-docx spec.docx --output ./spec-bikeshed
    python convert.py --from iso-docx spec.docx --to metanorma --output ./spec-mn
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="convert.py",
        description="Convert documents to a specbuild Bikeshed project.",
    )
    p.add_argument(
        "--from",
        "-f",
        dest="source_format",
        default="metanorma",
        choices=["metanorma", "iso-docx"],
        metavar="FORMAT",
        help="Source format: metanorma, iso-docx.",
    )
    p.add_argument(
        "--to",
        "-t",
        dest="target_format",
        default="bikeshed",
        choices=["bikeshed", "metanorma"],
        metavar="FORMAT",
        help="Target format: bikeshed (default) or metanorma.",
    )
    p.add_argument(
        "input",
        help="Path to source project directory or main document file.",
    )
    p.add_argument(
        "--output",
        "-o",
        metavar="DIR",
        help="Output directory (default: <input-stem>-bikeshed/ or <input-stem>-metanorma/ depending on --to).",
    )
    p.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite files in an existing output directory.",
    )
    p.add_argument(
        "--no-scaffold",
        action="store_true",
        help="Do not copy the specbuild pipeline into the output directory.",
    )
    p.add_argument(
        "--single-file",
        action="store_true",
        help="Merge all sections into a single index.bs file.",
    )
    p.add_argument(
        "--flavor",
        default="auto",
        choices=["auto", "h265", "cmaf"],
        metavar="FLAVOR",
        help="Document flavor for iso-docx: auto (default), h265, or cmaf.",
    )
    p.add_argument(
        "--converter",
        default="docximport",
        choices=["docximport", "legacy"],
        metavar="CONVERTER",
        help=(
            "Bikeshed converter for iso-docx: "
            "docximport (default, flavor-aware, generates specbuild.toml) or "
            "legacy (simpler, better inline cross-ref resolution)."
        ),
    )
    p.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging.",
    )
    return p


def _print_conversion_report(
    source_fmt: str,
    target_fmt: str,
    inp: Path,
    output_dir: Path,
    section_count: int,
    warnings: list,
    next_steps: list[str],
    extra_fields: dict | None = None,
) -> None:
    print("\nConversion complete:")
    print(f"  Source format : {source_fmt}")
    print(f"  Target format : {target_fmt}")
    if extra_fields:
        for k, v in extra_fields.items():
            print(f"  {k:<13} : {v}")
    print(f"  Input         : {inp}")
    print(f"  Output        : {output_dir}")
    print(f"  Sections      : {section_count}")
    if warnings:
        print(f"  Warnings      : {len(warnings)}")
        for w in warnings[:10]:
            print(f"    - {w}")
        if len(warnings) > 10:
            print(f"    ... and {len(warnings) - 10} more")
    print()
    print("Next steps:")
    for step in next_steps:
        print(step)
    print()


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    inp = Path(args.input)
    if not inp.exists():
        logging.error(f"Input path does not exist: {inp}")
        return 1

    # Default output directory
    if args.output:
        out = Path(args.output)
    else:
        stem = inp.stem if inp.is_file() else inp.name
        out = Path(f"{stem}-metanorma" if args.target_format == "metanorma" else f"{stem}-bikeshed")

    if args.source_format == "metanorma":
        from specbuild.convert.metanorma import convert_project

        try:
            result = convert_project(
                inp,
                out,
                overwrite=args.overwrite,
                single_file=args.single_file,
                scaffold=not args.no_scaffold,
            )
        except FileExistsError as exc:
            logging.error(str(exc))
            return 1
        except FileNotFoundError as exc:
            logging.error(str(exc))
            return 1

        sections = result["sections"]
        warnings = result["warnings"]
        output_dir = result["output_dir"]

        _print_conversion_report(
            "Metanorma/AsciiDoc",
            "Bikeshed",
            inp,
            output_dir,
            len(sections),
            warnings,
            next_steps=[
                f"  1. Build spec:  cd {output_dir} && python compile.py",
                f"  2. Build PDF:   cd {output_dir} && python compile.py --pdf",
            ],
        )

    elif args.source_format == "iso-docx":
        if not inp.is_file() or inp.suffix.lower() != ".docx":
            logging.error(f"iso-docx requires a .docx file as input: {inp}")
            return 1

        fmt = args.target_format  # "bikeshed" or "metanorma"

        if fmt == "bikeshed" and args.converter == "docximport":
            from specbuild.convert.metanorma import _scaffold_specbuild
            from specbuild.input.docximport import convert_docx as _import_docx

            if out.exists() and not args.overwrite:
                logging.error(
                    f"Output directory already exists: {out}. Use --overwrite to overwrite."
                )
                return 1
            out.mkdir(parents=True, exist_ok=True)
            try:
                result = _import_docx(inp, out, flavor=args.flavor)
            except FileNotFoundError as exc:
                logging.error(str(exc))
                return 1
            except Exception as exc:  # noqa: BLE001
                logging.error(str(exc))
                return 1
            report = result["report"]
            output_dir = out

            if not args.no_scaffold:
                _scaffold_specbuild(out, overwrite=args.overwrite)

            _print_conversion_report(
                "ISO Word (.docx)",
                "Bikeshed",
                inp,
                output_dir,
                section_count=report.sections_generated,
                warnings=[],
                next_steps=[
                    f"  1. Build spec:  cd {out} && python compile.py",
                ],
                extra_fields={
                    "Converter": "docximport (flavor-aware)",
                    "Flavor": args.flavor,
                    "Tables": report.total_tables,
                    "SDL tables": report.sdl_tables_detected,
                },
            )

        elif fmt == "bikeshed" and args.converter == "legacy":
            from specbuild.convert.iso_docx import convert_docx as _legacy_docx

            try:
                result = _legacy_docx(inp, out, fmt="bikeshed", overwrite=args.overwrite)
            except FileExistsError as exc:
                logging.error(str(exc))
                return 1

            sections = result["sections"]
            warnings = result["warnings"]
            output_dir = result["output_dir"]

            _print_conversion_report(
                "ISO Word (.docx)",
                "Bikeshed",
                inp,
                output_dir,
                len(sections),
                warnings,
                next_steps=[
                    f"  1. Build spec:  cd {output_dir} && python compile.py",
                ],
                extra_fields={"Converter": "legacy"},
            )

        else:  # metanorma
            from specbuild.convert.iso_docx import convert_docx

            try:
                result = convert_docx(inp, out, fmt=fmt, overwrite=args.overwrite)
            except FileExistsError as exc:
                logging.error(str(exc))
                return 1
            except Exception as exc:
                logging.error(str(exc))
                return 1

            sections = result["sections"]
            warnings = result["warnings"]
            output_dir = result["output_dir"]

            _print_conversion_report(
                "ISO Word (.docx)",
                "Metanorma/AsciiDoc",
                inp,
                output_dir,
                len(sections),
                warnings,
                next_steps=[
                    "  1. Install Metanorma (https://www.metanorma.org/install/)",
                    f"  2. Build:  cd {output_dir} && metanorma compile document.adoc",
                ],
            )

    return 0


if __name__ == "__main__":
    sys.exit(main())
