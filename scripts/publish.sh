#!/bin/bash
# publish.sh — commit changed plant GLB files and push to main.
# The deploy workflow is dispatched explicitly afterwards (GITHUB_TOKEN
# pushes do not trigger workflows).
#
# Usage: bash scripts/publish.sh [--dry-run]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$SCRIPT_DIR")"

# CI auth: GITHUB_TOKEN available inside the workflow job
if [ -n "${GITHUB_TOKEN:-}" ] && [ -n "${GITHUB_REPOSITORY:-}" ]; then
    git remote set-url origin \
        "https://x-access-token:${GITHUB_TOKEN}@github.com/${GITHUB_REPOSITORY}.git"
fi

PLANTS_DIR="$ROOT/digital-garden-AR/src/assets/plants"

DRY_RUN=false
if [[ "${1:-}" == "--dry-run" ]]; then
    DRY_RUN=true
    echo "[publish] DRY RUN — no commits will be made"
fi

cd "$ROOT"

if [[ ! -d "$PLANTS_DIR" ]]; then
    echo "[publish] No plants directory found, nothing to publish."
    exit 0
fi

# Check if any GLB files exist
GLB_COUNT=$(find "$PLANTS_DIR" -name "*.glb" -type f 2>/dev/null | wc -l)
if [[ "$GLB_COUNT" -eq 0 ]]; then
    echo "[publish] No GLB files in plants directory, nothing to publish."
    exit 0
fi

# Stage only GLB files
git add "$PLANTS_DIR"/*.glb 2>/dev/null || true

# Check if there are staged changes
if git diff --cached --quiet; then
    echo "[publish] No changes to publish."
    exit 0
fi

# Get a summary for the commit message
TODAY=$(date +%Y-%m-%d)
CHANGED=$(git diff --cached --name-only | wc -l)

COMMIT_MSG="grow: $TODAY — $CHANGED plant(s) updated"

echo "[publish] Staged $CHANGED GLB file(s)"
echo "[publish] Commit message: $COMMIT_MSG"

if $DRY_RUN; then
    echo "[publish] DRY RUN — would commit and push. Exiting."
    exit 0
fi

# Configure git for CI bot
git config user.name "github-actions[bot]"
git config user.email "github-actions[bot]@users.noreply.github.com"

git commit -m "$COMMIT_MSG"

# Push, retry once on conflict
if ! git push origin main; then
    echo "[publish] Push failed, attempting pull --rebase and retry..."
    git pull --rebase origin main
    git push origin main
fi

echo "[publish] Done. Deploy workflow should be dispatched by the caller."
