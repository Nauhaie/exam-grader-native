#!/usr/bin/env bash
# convert-icon.sh – Convert icon.svg into the platform icon formats used by
# run.sh (window icon) and package-app.sh (PyInstaller --icon).
#
# Run this once whenever icon.svg changes, then commit the generated files.
#
# Outputs:
#   icon.png        256×256 PNG  – used by PyInstaller on Linux / Windows,
#                                  and as the base for macOS conversion
#   icon.icns       macOS icon bundle – produced only when running on macOS
#
# Conversion is attempted via (in order of preference):
#   1. cairosvg   (pip install cairosvg)
#   2. inkscape
#   3. rsvg-convert
#   4. convert    (ImageMagick)

set -euo pipefail
cd "$(dirname "$0")"

SVG="icon.svg"
PNG="icon.png"

if [ ! -f "$SVG" ]; then
  echo "Error: $SVG not found." >&2
  exit 1
fi

# ── Generate icon.png ────────────────────────────────────────────────────────

echo "==> Converting $SVG → $PNG …"

if python3 -c "import cairosvg" 2>/dev/null; then
  python3 -c "
import cairosvg
cairosvg.svg2png(url='$SVG', write_to='$PNG', output_width=256, output_height=256)
"
  echo "    Used cairosvg."

elif command -v inkscape >/dev/null 2>&1; then
  inkscape --export-type=png --export-filename="$PNG" --export-width=256 --export-height=256 "$SVG"
  echo "    Used inkscape."

elif command -v rsvg-convert >/dev/null 2>&1; then
  rsvg-convert -w 256 -h 256 "$SVG" -o "$PNG"
  echo "    Used rsvg-convert."

elif command -v convert >/dev/null 2>&1; then
  convert -background none -resize 256x256 "$SVG" "$PNG"
  echo "    Used ImageMagick convert."

else
  echo "Error: no SVG conversion tool found." >&2
  echo "Install one of: cairosvg (pip), inkscape, librsvg (rsvg-convert), or ImageMagick." >&2
  exit 1
fi

echo "    $PNG written."

# ── Generate icon.icns (macOS only) ─────────────────────────────────────────

if [[ "$(uname)" == "Darwin" ]]; then
  echo "==> Creating icon.icns …"
  ICONSET="icon.iconset"
  rm -rf "$ICONSET"
  mkdir "$ICONSET"

  # Generate all required sizes from the SVG (or fall back to scaling the PNG)
  for size in 16 32 64 128 256 512; do
    double=$((size * 2))
    if python3 -c "import cairosvg" 2>/dev/null; then
      python3 -c "import cairosvg; cairosvg.svg2png(url='$SVG', write_to='$ICONSET/icon_${size}x${size}.png', output_width=$size, output_height=$size)"
      python3 -c "import cairosvg; cairosvg.svg2png(url='$SVG', write_to='$ICONSET/icon_${size}x${size}@2x.png', output_width=$double, output_height=$double)"
    else
      sips -z $size $size "$PNG" --out "$ICONSET/icon_${size}x${size}.png" >/dev/null
      sips -z $double $double "$PNG" --out "$ICONSET/icon_${size}x${size}@2x.png" >/dev/null
    fi
  done

  iconutil -c icns "$ICONSET" -o icon.icns
  rm -rf "$ICONSET"
  echo "    icon.icns written."
fi

echo ""
echo "Done. Commit the generated file(s) so package-app.sh can use them without"
echo "requiring any conversion tools at build time."
