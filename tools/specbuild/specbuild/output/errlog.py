"""Error HTML log export.

Captures WARNING+ log records emitted during a build and writes them to a
navigable HTML file — equivalent to Metanorma's ``.err.html`` output.

Usage (called from compile.py before the build starts)::

    from specbuild.output.errlog import install_handler
    install_handler()

Then, in the ``--error-log`` output task::

    from specbuild.output.errlog import export_error_log
    export_error_log(target_dir / "spec.err.html")
"""

from __future__ import annotations

import html
import logging
from datetime import datetime, timezone
from pathlib import Path

_handler: _ErrLogHandler | None = None


class _ErrLogHandler(logging.Handler):
    """Captures WARNING+ records into an in-memory list."""

    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def install_handler() -> None:
    """Install the capturing handler on the root logger.  Idempotent."""
    global _handler
    if _handler is None:
        _handler = _ErrLogHandler()
        logging.getLogger().addHandler(_handler)


def uninstall_handler() -> None:
    """Remove the capturing handler from the root logger."""
    global _handler
    if _handler is not None:
        logging.getLogger().removeHandler(_handler)
        _handler = None


def export_error_log(output_path: Path) -> Path:
    """Write captured warnings/errors to *output_path* as a styled HTML file.

    Returns the path that was written.  Writes an empty-log page even when
    there are no records so the file is always produced when requested.
    """
    records = list(_handler.records) if _handler else []
    _write_html(output_path, records)
    logging.info(f"Error log written to {output_path}")
    return output_path


# ---------------------------------------------------------------------------
# HTML generation
# ---------------------------------------------------------------------------


def _write_html(output_path: Path, records: list[logging.LogRecord]) -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    rows: list[str] = []
    for r in records:
        is_error = r.levelno >= logging.ERROR
        level_class = "error" if is_error else "warning"
        level_label = "ERROR" if is_error else "WARNING"
        ts = datetime.fromtimestamp(r.created, tz=timezone.utc).strftime("%H:%M:%S")
        rows.append(
            f'<tr class="{level_class}">'
            f'<td class="ts">{ts}</td>'
            f'<td class="lvl">{level_label}</td>'
            f'<td class="mod">{html.escape(r.name)}</td>'
            f'<td class="msg">{html.escape(r.getMessage())}</td>'
            "</tr>"
        )

    error_count = sum(1 for r in records if r.levelno >= logging.ERROR)
    warning_count = len(records) - error_count
    if error_count:
        status_class, status_text = (
            "has-errors",
            f"{error_count} error(s), {warning_count} warning(s)",
        )
    elif warning_count:
        status_class, status_text = "has-warnings", f"{warning_count} warning(s)"
    else:
        status_class, status_text = "clean", "No warnings or errors"

    rows_html = (
        "\n".join(rows)
        if rows
        else '<tr><td colspan="4" class="none">No warnings or errors recorded.</td></tr>'
    )

    html_content = f"""\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Build Error Log</title>
<style>
body{{font-family:monospace;font-size:13px;margin:0;padding:0;background:#fafafa}}
header{{background:#222;color:#fff;padding:12px 20px}}
header h1{{margin:0;font-size:16px;font-weight:normal}}
header .meta{{font-size:11px;color:#aaa;margin-top:4px}}
.summary{{padding:10px 20px;border-bottom:1px solid #ddd;background:#fff}}
.summary.has-errors{{background:#fff0f0;border-left:4px solid #c00}}
.summary.has-warnings{{background:#fffbe6;border-left:4px solid #e6a800}}
.summary.clean{{background:#f0fff0;border-left:4px solid #090}}
table{{width:100%;border-collapse:collapse}}
th{{background:#333;color:#fff;padding:6px 10px;text-align:left;font-size:11px}}
td{{padding:5px 10px;border-bottom:1px solid #eee;vertical-align:top;white-space:pre-wrap;word-break:break-word}}
tr.error td{{background:#fff8f8}}
tr.warning td{{background:#fffdf0}}
.ts{{width:70px;color:#888;font-size:11px;white-space:nowrap}}
.lvl{{width:70px;font-weight:bold;white-space:nowrap}}
tr.error .lvl{{color:#c00}}
tr.warning .lvl{{color:#b87000}}
.mod{{width:220px;color:#555;font-size:11px}}
.none{{text-align:center;color:#888;padding:20px}}
</style>
</head>
<body>
<header>
<h1>specbuild \u2014 Build Error Log</h1>
<div class="meta">Generated {now}</div>
</header>
<div class="summary {status_class}">{status_text}</div>
<table>
<thead><tr><th>Time</th><th>Level</th><th>Module</th><th>Message</th></tr></thead>
<tbody>
{rows_html}
</tbody>
</table>
</body>
</html>"""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html_content, encoding="utf-8")
