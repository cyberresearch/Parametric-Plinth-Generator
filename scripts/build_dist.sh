#!/usr/bin/env bash
set -euo pipefail

# Build the shippable zip for the Parametric Plinth Generator.
# Reads the version from bl_info in the addon source so it cannot drift.

cd "$(dirname "$0")/.."

ADDON_FILE="addon/plinth_generator_v3_4.py"

# Extract the version tuple from bl_info: e.g. "(3, 4, 1)" -> "3.4.1"
VERSION=$(python3 -c "
import re, sys
src = open('$ADDON_FILE').read()
m = re.search(r'\"version\":\s*\((\d+),\s*(\d+),\s*(\d+)\)', src)
if not m:
    sys.exit('Could not parse bl_info version from $ADDON_FILE')
print('.'.join(m.groups()))
")

OUT_DIR="dist"
ZIP_NAME="plinth_generator_v${VERSION}.zip"
ZIP_PATH="${OUT_DIR}/${ZIP_NAME}"

mkdir -p "$OUT_DIR"
rm -f "$ZIP_PATH"

# Stage shippable files in a temp directory so the zip contains only what a
# buyer needs, no repo metadata.
STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT

cp "$ADDON_FILE" "$STAGE/"
cp README.md "$STAGE/"
cp LICENSE "$STAGE/"
cp CHANGELOG.md "$STAGE/"

(cd "$STAGE" && zip -q "$OLDPWD/$ZIP_PATH" \
    "$(basename "$ADDON_FILE")" \
    README.md \
    LICENSE \
    CHANGELOG.md)

echo "Built: $ZIP_PATH ($(du -h "$ZIP_PATH" | cut -f1))"
