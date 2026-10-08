#!/bin/bash
# Setup script for WeasyPrint PDF generation on Apple Silicon with x86_64 Homebrew.
#
# Problem: Your Homebrew (at /usr/local) installs x86_64 libraries (glib, pango,
# harfbuzz, etc.) via Rosetta, but the main venv has arm64 pip packages.
# WeasyPrint needs both the C libraries and Python packages to match architecture.
#
# Solution: Create a dedicated x86_64 Python venv where pip installs x86_64
# wheels, matching the x86_64 Homebrew C libraries. The build system will use
# this venv (via arch -x86_64) only for the WeasyPrint PDF step.
#
# Usage:
#   ./setup_weasyprint.sh
#
# After running this script, rebuild with:
#   python compile.py --pdf --weasyprint

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$SCRIPT_DIR/venv_x86"
PYTHON_X86="/usr/local/bin/python3.13"

echo "============================================================"
echo "WeasyPrint Setup for Apple Silicon + x86_64 Homebrew"
echo "============================================================"
echo ""

# --- Step 0: Check prerequisites ---
echo "[1/5] Checking prerequisites..."

if [ "$(uname -m)" != "arm64" ]; then
    echo "  WARNING: This script is designed for Apple Silicon (arm64)."
    echo "  Your machine reports: $(uname -m)"
fi

if ! command -v brew &>/dev/null; then
    echo "  ERROR: Homebrew not found. Install from https://brew.sh"
    exit 1
fi

BREW_PREFIX="$(brew --prefix)"
echo "  Homebrew prefix: $BREW_PREFIX"

# --- Step 1: Install Homebrew C dependencies ---
echo ""
echo "[2/5] Installing Homebrew C dependencies for WeasyPrint..."

BREW_DEPS="glib pango harfbuzz fontconfig libffi gobject-introspection"
for dep in $BREW_DEPS; do
    if brew list "$dep" &>/dev/null; then
        echo "  $dep: already installed"
    else
        echo "  Installing $dep..."
        brew install "$dep"
    fi
done

# Verify glib architecture matches what we expect
GLIB_LIB="$BREW_PREFIX/lib/libgobject-2.0.0.dylib"
if [ -f "$GLIB_LIB" ]; then
    GLIB_ARCH=$(file "$GLIB_LIB" | grep -o 'x86_64\|arm64' | head -1)
    echo "  glib architecture: $GLIB_ARCH"
else
    echo "  WARNING: glib library not found at $GLIB_LIB"
fi

# --- Step 2: Locate or verify x86_64 Python ---
echo ""
echo "[3/5] Locating x86_64 Python..."

if [ ! -f "$PYTHON_X86" ]; then
    # Try alternatives
    for candidate in /usr/local/bin/python3.14 /usr/local/bin/python3.12 /usr/local/bin/python3.11 /usr/local/bin/python3; do
        if [ -f "$candidate" ]; then
            # Check it can run as x86_64
            if arch -x86_64 "$candidate" -c "pass" 2>/dev/null; then
                PYTHON_X86="$candidate"
                break
            fi
        fi
    done
fi

if [ ! -f "$PYTHON_X86" ]; then
    echo "  ERROR: No x86_64-compatible Python found."
    echo "  Install one via Homebrew: brew install python@3.13"
    exit 1
fi

# Verify it runs under x86_64
if ! arch -x86_64 "$PYTHON_X86" -c "import platform; assert platform.machine() == 'x86_64'" 2>/dev/null; then
    echo "  ERROR: $PYTHON_X86 cannot run as x86_64"
    exit 1
fi

PY_VERSION=$(arch -x86_64 "$PYTHON_X86" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "  Using: $PYTHON_X86 (Python $PY_VERSION, x86_64)"

# --- Step 3: Create x86_64 venv ---
echo ""
echo "[4/5] Creating x86_64 virtual environment at $VENV_DIR..."

if [ -d "$VENV_DIR" ]; then
    echo "  Removing existing venv_x86..."
    rm -rf "$VENV_DIR"
fi

arch -x86_64 "$PYTHON_X86" -m venv "$VENV_DIR"

# Verify the venv Python runs as x86_64
VENV_PYTHON="$VENV_DIR/bin/python"
VENV_ARCH=$(arch -x86_64 "$VENV_PYTHON" -c "import platform; print(platform.machine())")
echo "  venv Python architecture: $VENV_ARCH"

if [ "$VENV_ARCH" != "x86_64" ]; then
    echo "  ERROR: venv Python is not x86_64. Aborting."
    exit 1
fi

# --- Step 4: Install Python packages ---
echo ""
echo "[5/5] Installing WeasyPrint and dependencies (x86_64)..."

# Upgrade pip first
arch -x86_64 "$VENV_PYTHON" -m pip install --upgrade pip 2>&1 | tail -1

# Install WeasyPrint and all its dependencies
# Using the same versions as requirements.txt where possible
arch -x86_64 "$VENV_PYTHON" -m pip install \
    "weasyprint==68.1" \
    "beautifulsoup4==4.14.3" \
    "Pillow==11.1.0" \
    "lxml==5.3.0" \
    "cffi==2.0.0" \
    "pypdf==5.3.0" \
    "fonttools==4.61.1" \
    2>&1 | grep -E "^(Successfully|ERROR|WARNING)" || true

# Verify WeasyPrint imports
echo ""
echo "Verifying WeasyPrint installation..."
if arch -x86_64 "$VENV_PYTHON" -c "from weasyprint import HTML; print('  WeasyPrint OK')" 2>&1; then
    echo ""
else
    echo ""
    echo "  ERROR: WeasyPrint import failed. Check the error above."
    echo "  You may need to: brew reinstall glib pango harfbuzz"
    exit 1
fi

# Also verify specbuild imports work (needs bikeshed deps too)
echo "Verifying specbuild compatibility..."
if arch -x86_64 "$VENV_PYTHON" -c "
import sys; sys.path.insert(0, '$SCRIPT_DIR')
from specbuild.pagenumbers import to_roman, has_dual_numbering, collect_body_ids
print('  specbuild imports OK')
" 2>&1; then
    echo ""
else
    echo "  WARNING: specbuild imports failed (non-critical — only needed for shared helpers)"
fi

# --- Step 5: Update config ---
echo "============================================================"
echo "Setup complete!"
echo "============================================================"
echo ""
echo "venv location:  $VENV_DIR"
echo "Python:         $VENV_PYTHON ($VENV_ARCH)"
echo ""

# Check if config already has x86_python_path set
CONFIG_FILE="$SCRIPT_DIR/specbuild/config.py"
if grep -q 'x86_python_path.*=.*None' "$CONFIG_FILE" 2>/dev/null; then
    echo "ACTION REQUIRED: Update specbuild/config.py to use the x86_64 venv:"
    echo ""
    echo "  Change:"
    echo "    x86_python_path: str = None"
    echo "  To:"
    echo "    x86_python_path: str = \"venv_x86/bin/python\""
    echo ""
    echo "Or I can do it for you — just say the word."
fi

echo ""
echo "Then rebuild with:"
echo "  python compile.py --pdf --weasyprint --log_level DEBUG"
