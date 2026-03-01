#!/usr/bin/env bash
# package-app.sh – Build a standalone ExamGrader application bundle.
#
# Usage:
#   bash package-app.sh
#
# Requires:  pip install pyinstaller
# Output:    dist/ExamGrader/   (folder with executable)
#            dist/ExamGrader.app  (macOS only – drag to Applications)

set -euo pipefail
cd "$(dirname "$0")"

# Use the same virtual environment as run.sh so we don't touch the system Python.
if [ ! -d "venv" ]; then
  echo "==> Creating virtual environment…"
  python3 -m venv venv
fi

echo "==> Activating virtual environment…"
# shellcheck disable=SC1091
source venv/bin/activate

echo "==> Installing/updating dependencies…"
pip install --quiet -r requirements.txt

echo "==> Installing PyInstaller (if not already installed)…"
pip install --quiet pyinstaller

echo "==> Cleaning previous build artifacts…"
rm -rf build dist ExamGrader.spec

echo "==> Building…"
ICON_ARG=""
if [ -f "icon.png" ]; then
    ICON_ARG="--icon icon.png"
elif [ -f "icon.icns" ]; then
    ICON_ARG="--icon icon.icns"
fi
pyinstaller \
    --name "ExamGrader" \
    --windowed \
    --onedir \
    --add-data "sample_project:sample_project" \
    --add-data "icon.svg:." \
    $ICON_ARG \
    app/main.py

echo ""
echo "Done.  Output is in dist/ExamGrader/"
if [[ "$(uname)" == "Darwin" ]]; then
    echo "macOS app bundle: dist/ExamGrader.app"
fi
