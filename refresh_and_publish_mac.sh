#!/bin/zsh
set -euo pipefail

# macOS launchd has a minimal PATH. Include both Apple Silicon and Intel
# Homebrew locations before the system paths.
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$REPO_DIR"

LOCK_DIR="$REPO_DIR/.refresh-lock"
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  echo "[$(date)] Another class-availability refresh is already running; exiting."
  exit 0
fi
trap 'rmdir "$LOCK_DIR" 2>/dev/null || true' EXIT

echo
echo "============================================================"
echo "[$(date)] Starting Fall 2026 class-availability refresh"
echo "Repository: $REPO_DIR"

# Never overwrite uncommitted local work.
if [[ -n "$(git status --porcelain)" ]]; then
  echo "Local repository has uncommitted changes. Refresh aborted for safety."
  git status --short
  exit 1
fi

echo "Updating local repository from GitHub..."
git pull --ff-only origin main

PYTHON="$(command -v python3 || true)"
if [[ -z "$PYTHON" ]]; then
  echo "python3 was not found in PATH."
  exit 1
fi

if [[ ! -x "$REPO_DIR/.venv/bin/python" ]]; then
  echo "Creating local Python virtual environment..."
  "$PYTHON" -m venv "$REPO_DIR/.venv"
fi

echo "Checking Python dependencies..."
"$REPO_DIR/.venv/bin/python" -m pip install --disable-pip-version-check --quiet -r requirements.txt

echo "Checking Playwright Chromium..."
"$REPO_DIR/.venv/bin/python" -m playwright install chromium

echo "Collecting current UH Fall 2026 data..."
if ! "$REPO_DIR/.venv/bin/python" update_fall_2026.py; then
  echo "First refresh attempt failed. Waiting 60 seconds and trying once more..."
  sleep 60
  "$REPO_DIR/.venv/bin/python" update_fall_2026.py
fi

git add index.html course_browser_fall_2026_current.json

if git diff --cached --quiet; then
  echo "No publishable changes were produced."
  exit 0
fi

STAMP="$(TZ=Pacific/Honolulu date '+%Y-%m-%d %H:%M HST')"
git commit -m "Refresh Fall 2026 course availability — $STAMP"
git push origin main

echo "[$(date)] Refresh complete. GitHub Pages deployment will start automatically."
