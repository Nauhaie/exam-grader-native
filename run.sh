#!/bin/bash
set -e

cd "$(dirname "$0")"

if [ ! -d "venv" ]; then
  echo "Creating virtual environment..."
  python3 -m venv venv
fi

echo "Activating virtual environment..."
source venv/bin/activate

# Reinstall only when requirements.txt has changed (works on macOS and Linux)
REQ_HASH_FILE="venv/.requirements_hash"
if command -v md5 >/dev/null 2>&1; then
  CURRENT_HASH=$(md5 -q requirements.txt)
else
  CURRENT_HASH=$(md5sum requirements.txt | awk '{print $1}')
fi

if [ ! -f "$REQ_HASH_FILE" ] || [ "$(cat "$REQ_HASH_FILE")" != "$CURRENT_HASH" ]; then
  echo "Installing/updating dependencies..."
  pip install -r requirements.txt --quiet
  echo "$CURRENT_HASH" > "$REQ_HASH_FILE"
else
  echo "Dependencies up to date, skipping install."
fi

echo "Launching Exam Grader..."
python app/main.py
