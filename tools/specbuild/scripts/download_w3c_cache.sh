#!/bin/bash
# Download external W3C resources needed for WeasyPrint PDF generation.
# Run this once when you have network access (e.g., off VPN).
#
# Usage: ./download_w3c_cache.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CACHE_DIR="$SCRIPT_DIR/css/w3c-cache"

mkdir -p "$CACHE_DIR"

echo "Downloading W3C resources to $CACHE_DIR ..."

# 1. W3C base stylesheet (imported by W3C-UD.css)
echo "  [1/6] base.css ..."
curl -sL -o "$CACHE_DIR/base.css" \
    "https://www.w3.org/StyleSheets/TR/2021/base.css"

# 2. W3C-UD stylesheet (Bikeshed "Unofficial Draft" boilerplate)
echo "  [2/6] W3C-UD.css ..."
curl -sL -o "$CACHE_DIR/W3C-UD.css" \
    "https://www.w3.org/StyleSheets/TR/2021/W3C-UD"

# 3. W3C logo (referenced in the stylesheet header)
echo "  [3/6] W3C logo ..."
curl -sL -o "$CACHE_DIR/W3C-logo.svg" \
    "https://www.w3.org/StyleSheets/TR/2021/logos/W3C"

# 4. UD watermark (background image referenced from W3C-UD.css)
echo "  [4/6] UD watermark ..."
curl -sL -o "$CACHE_DIR/UD-watermark.svg" \
    "https://www.w3.org/StyleSheets/TR/2016/logos/UD-watermark"

# 5. UD watermark light-draft (CSS variable in base.css)
echo "  [5/6] UD-watermark-light-draft.svg ..."
curl -sL -o "$CACHE_DIR/UD-watermark-light-draft.svg" \
    "https://www.w3.org/StyleSheets/TR/2021/logos/UD-watermark-light-draft.svg"

# 6. UD watermark light-unofficial (CSS variable in base.css)
echo "  [6/6] UD-watermark-light-unofficial.svg ..."
curl -sL -o "$CACHE_DIR/UD-watermark-light-unofficial.svg" \
    "https://www.w3.org/StyleSheets/TR/2021/logos/UD-watermark-light-unofficial.svg"

echo ""
echo "=== Done ==="
echo "Cached files:"
ls -lh "$CACHE_DIR"
echo ""
echo "The build will automatically use these cached files."
