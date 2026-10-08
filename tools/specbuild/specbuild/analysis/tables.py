"""Extract tables from specification source and create header files."""

from __future__ import annotations

import logging
import re
from pathlib import Path

from specbuild.config import CONFIG


def extract_tables_from_section9(
    section9_file: Path, attachments_dir: Path, content: str = None
) -> str:
    """Extract code blocks from the tables source file and write them to .h files.

    Args:
        section9_file (Path): Path to the tables .bs file.
        attachments_dir (Path): Directory where .h files will be written.
        content (str, optional): Pre-read file content.  If None the file is
            read from *section9_file*.

    Returns:
        str: Modified content with code blocks replaced by header file references.
    """
    attachments_dir.mkdir(parents=True, exist_ok=True)

    if content is None:
        with section9_file.open("r", encoding="utf8") as f:
            content = f.read()

    general_section_end = (
        "This section contains tables that do not naturally fit in the main "
        "sections of\nthe Specification."
    )
    if general_section_end in content:
        developer_note = (
            "\n\nNote: For developers: All tables in this section are available "
            "as individual header files\n(linked throughout) or as a single "
            "combined header file:\n"
            '<a href="./attachments/all_tables.h">all_tables.h</a>.'
        )
        content = content.replace(general_section_end, general_section_end + developer_note, 1)
        logging.debug("Injected developer note in Section 9.1")

    code_block_pattern = r"~~~~~(?:[ \t]*\w*)?[ \t]*\n(.*?)\n~~~~~"
    matches = list(re.finditer(code_block_pattern, content, re.DOTALL))
    logging.info(f"Found {len(matches)} code blocks in {section9_file.name}")

    for match in reversed(matches):
        code_block = match.group(1)

        array_matches = list(re.finditer(r"^(\w+)(?:\s*\n)?\s*\[", code_block, re.MULTILINE))

        if array_matches:
            replacements = []

            if len(array_matches) > 1:
                for i, array_match in enumerate(array_matches):
                    array_name = array_match.group(1)
                    header_filename = f"{array_name.lower()}.h"
                    header_path = attachments_dir / header_filename

                    start_pos = array_match.start()
                    end_pos = (
                        array_matches[i + 1].start()
                        if i + 1 < len(array_matches)
                        else len(code_block)
                    )
                    array_content = code_block[start_pos:end_pos].rstrip()

                    with header_path.open("w", encoding="utf8") as h_file:
                        h_file.write(f"{array_content}\n")

                    logging.debug(f"  {array_name} -> ./attachments/{header_filename}")
                    replacements.append(
                        f"`{array_name}` is defined in the "
                        f'<a href="./attachments/{header_filename}">'
                        f"{header_filename}</a> header file."
                    )

                replacement = "\n\n".join(replacements)
            else:
                array_name = array_matches[0].group(1)
                header_filename = f"{array_name.lower()}.h"
                header_path = attachments_dir / header_filename

                with header_path.open("w", encoding="utf8") as h_file:
                    h_file.write(f"{code_block}\n")

                logging.debug(f"  {array_name} -> ./attachments/{header_filename}")
                replacement = (
                    f"`{array_name}` is defined in the "
                    f'<a href="./attachments/{header_filename}">'
                    f"{header_filename}</a> header file."
                )

            content = content[: match.start()] + replacement + content[match.end() :]
        else:
            logging.warning(
                f"Could not extract array name from code block at position {match.start()}"
            )

    return content


def create_combined_header(attachments_dir: Path) -> None:
    """Combine all individual .h files into a single ``all_tables.h`` file.

    Args:
        attachments_dir (Path): Directory containing individual .h files.
    """
    combined_path = attachments_dir / "all_tables.h"
    h_files = sorted([f for f in attachments_dir.glob("*.h") if f.name != "all_tables.h"])

    logging.info(f"Creating combined header file: {combined_path.name} ({len(h_files)} tables)")

    with combined_path.open("w", encoding="utf8") as combined:
        combined.write("/*\n")
        combined.write(f" * {CONFIG.spec_full_name} - All Additional Tables (Section 9)\n")
        combined.write(" * Auto-generated combined header file\n")
        combined.write(" *\n")
        combined.write(
            f" * This file contains {len(h_files)} table definitions extracted from the\n"
        )
        combined.write(f" * {CONFIG.spec_full_name}.\n")
        combined.write(" */\n\n")

        for i, h_file in enumerate(h_files, 1):
            combined.write(f"/* {'-' * 76} */\n")
            combined.write(f"/* {h_file.name:<74} */\n")
            combined.write(f"/* {'-' * 76} */\n\n")

            content = h_file.read_text(encoding="utf8")
            combined.write(content)

            if i < len(h_files):
                combined.write("\n\n")

    size_kb = combined_path.stat().st_size / 1024
    logging.info(f"Combined header created: {size_kb:.1f} KB")
