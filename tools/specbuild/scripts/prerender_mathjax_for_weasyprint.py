#!/usr/bin/env python3

"""
Pre-render MathJax equations for WeasyPrint.

WeasyPrint doesn't execute JavaScript, so it can't render MathJax equations.
This script uses Puppeteer (Node.js) to pre-render the MathJax equations, then
saves the rendered HTML for WeasyPrint to process.

For WeasyPrint compatibility the script switches MathJax from its default CHTML
output (which requires web fonts) to SVG output (fully self-contained vector
paths).
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import uuid
from pathlib import Path

# Route logging through the shared colored formatter when this script is
# invoked as a subprocess of compile.py.
_repo_root = str(Path(__file__).resolve().parent.parent)
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)
from specbuild.logsetup import setup_logging  # noqa: E402

setup_logging("INFO")


def _build_node_env() -> dict:
    """Build a subprocess env with NODE_PATH pointing at PROJECT_ROOT/node_modules."""
    from specbuild import PROJECT_ROOT

    node_env = dict(os.environ)
    node_modules = PROJECT_ROOT / "node_modules"
    if node_modules.exists():
        existing = node_env.get("NODE_PATH", "")
        node_env["NODE_PATH"] = (
            str(node_modules) + os.pathsep + existing if existing else str(node_modules)
        )
    return node_env


def check_node_and_puppeteer() -> bool:
    """Check if Node.js and puppeteer-core are available."""
    try:
        result = subprocess.run(["node", "--version"], capture_output=True, text=True)
        node_version = result.stdout.strip()
        logging.info(f"Node.js version: {node_version}")
    except FileNotFoundError:
        logging.error("Node.js not found. Please install Node.js first.")
        return False

    try:
        result = subprocess.run(
            ["node", "-e", 'require("puppeteer-core"); console.log("ok")'],
            capture_output=True,
            text=True,
            env=_build_node_env(),
        )
        if "ok" in result.stdout:
            logging.info("puppeteer-core is installed")
            return True
        else:
            logging.error("puppeteer-core not installed. Run: npm install puppeteer-core")
            return False
    except Exception as e:
        logging.error(f"Failed to check puppeteer-core: {e}")
        return False


def _switch_mathjax_to_svg(html_path: Path) -> bool:
    """Rewrite the MathJax config/script tags in *html_path* to use SVG output.

    Returns True if any replacement was made.
    """
    text = html_path.read_text(encoding="utf-8")
    changed = False

    # Replace the MathJax loader: tex-chtml.js -> tex-svg.js
    new_text = text.replace("tex-chtml.js", "tex-svg.js")
    if new_text != text:
        changed = True
        text = new_text

    # Replace config key: chtml: { ... } -> svg: { ... }
    # This handles the MathJax = { ... chtml: { scale: 1.2 } ... } block
    new_text = re.sub(
        r"chtml\s*:\s*\{([^}]*)\}",
        r"svg: {\1}",
        text,
    )
    if new_text != text:
        changed = True
        text = new_text

    if changed:
        html_path.write_text(text, encoding="utf-8")
        logging.info("Switched MathJax config from CHTML to SVG output")

    return changed


def prerender_mathjax(html_path: Path, chrome_path: str) -> bool:
    """
    Pre-render MathJax equations using Puppeteer.

    This switches the MathJax config to SVG output, loads the HTML in Chrome
    via Puppeteer, waits for MathJax to render, then saves the rendered HTML
    (with equations as inline SVG elements).

    Args:
        html_path: Path to HTML file to process
        chrome_path: Path to Chrome executable

    Returns:
        True if successful, False otherwise
    """
    logging.info(f"Pre-rendering MathJax for WeasyPrint: {html_path}")

    if not check_node_and_puppeteer():
        logging.error("Cannot pre-render MathJax without Node.js and puppeteer-core")
        return False

    # Switch MathJax from CHTML (needs web fonts) to SVG (self-contained)
    _switch_mathjax_to_svg(html_path)

    # Safely encode paths for embedding in JS string literals
    chrome_path_js = json.dumps(str(chrome_path))
    html_path_js = json.dumps(str(html_path))

    # Create a Node.js script to prerender using Puppeteer
    node_script = f"""
const puppeteer = require('puppeteer-core');
const fs = require('fs');
const path = require('path');

(async () => {{
    const browser = await puppeteer.launch({{
        executablePath: {chrome_path_js},
        headless: true,
        args: ['--no-sandbox', '--disable-setuid-sandbox']
    }});

    const page = await browser.newPage();

    // Load the HTML file
    await page.goto('file://' + path.resolve({html_path_js}), {{
        waitUntil: 'networkidle0',
        timeout: 45000
    }});

    // Wait for MathJax to finish rendering
    await page.evaluate(async () => {{
        if (window.MathJax) {{
            if (window.MathJax.Hub) {{
                // MathJax 2.x
                await new Promise(resolve => {{
                    window.MathJax.Hub.Queue(() => resolve());
                }});
            }} else if (window.MathJax.startup) {{
                // MathJax 3.x
                await window.MathJax.startup.promise;
            }}
        }}
        // Small delay for any async rendering to finish
        await new Promise(r => setTimeout(r, 500));
    }});

    // Get the fully rendered HTML
    const html = await page.content();

    // Write back to file
    fs.writeFileSync({html_path_js}, html, 'utf8');

    await browser.close();

    console.log('MathJax pre-rendering complete');
}})().catch(err => {{
    console.error('Error:', err);
    process.exit(1);
}});
"""

    # Write the Node.js script to a uniquely-named temporary file to avoid
    # race conditions when multiple processes run concurrently.
    temp_script = html_path.parent / f"_mathjax_tmp_{uuid.uuid4().hex}.js"
    try:
        with open(temp_script, "w", encoding="utf-8") as f:
            f.write(node_script)

        # Execute the Node.js script.
        # Set NODE_PATH to the build system's node_modules so that
        # `require('puppeteer-core')` resolves correctly regardless of
        # where the temp script was written (e.g. the output directory).
        logging.info("Running Puppeteer to render MathJax...")
        result = subprocess.run(
            ["node", str(temp_script)],
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
            cwd=html_path.parent.parent,
            env=_build_node_env(),
        )
        if result.stderr:
            for line in result.stderr.strip().split("\n"):
                if line.strip():
                    logging.warning(f"Puppeteer: {line.strip()}")

        logging.info("Successfully pre-rendered MathJax equations")
        return True

    except subprocess.TimeoutExpired:
        logging.error("Puppeteer timed out while rendering MathJax")
        return False
    except subprocess.CalledProcessError as e:
        logging.error(f"Puppeteer failed: {e}")
        if e.stdout:
            logging.error(f"Stdout: {e.stdout}")
        if e.stderr:
            logging.error(f"Stderr: {e.stderr}")
        return False
    except Exception as e:
        logging.error(f"Failed to pre-render MathJax: {e}")
        return False
    finally:
        # Clean up temporary script
        if temp_script.exists():
            temp_script.unlink()


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <html_file> <chrome_path>")
        sys.exit(1)

    html_path = Path(sys.argv[1])
    chrome_path = sys.argv[2]

    if not html_path.exists():
        logging.error(f"HTML file not found: {html_path}")
        sys.exit(1)

    if not Path(chrome_path).exists():
        logging.error(f"Chrome not found at: {chrome_path}")
        sys.exit(1)

    success = prerender_mathjax(html_path, chrome_path)
    sys.exit(0 if success else 1)
