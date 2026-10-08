#!/usr/bin/env bash
#
# reconcile_previews.sh — remove pr/<n>/ preview folders on gh-pages whose PR
# is no longer open, independent of any single event.
#
# preview-pr.yml's `cleanup` job removes a preview when it observes that
# specific PR's `closed` event. That is a single point of failure: if the
# webhook delivery for one PR's close is ever dropped or never sent, its
# folder orphans on gh-pages with nothing to notice or fix it (observed for
# PR #34 — closed without merging, and no `closed`-triggered workflow run
# for it exists at all in the Actions history). This script re-derives the
# truth directly from the GitHub API, so it fixes the problem regardless of
# whether any particular webhook fired.
#
# Safe to run at any time: a folder is only ever deleted after confirming via
# `gh pr list` that its PR is not open. If nothing is stale, it's a no-op.
#
# Usage:
#   reconcile_previews.sh
#
# Environment:
#   REPO         owner/name slug (e.g. AOMediaCodec/av1-mpeg2-ts)   [required]
#   GH_TOKEN     token for `gh` and for publish.sh's git push      [required]
#   PAGES_BRANCH branch name (default: gh-pages)

set -euo pipefail

: "${REPO:?REPO must be set (owner/name)}"
: "${GH_TOKEN:?GH_TOKEN must be set}"

PAGES_BRANCH="${PAGES_BRANCH:-gh-pages}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

SCAN_DIR="$(mktemp -d)"
trap 'rm -rf "$SCAN_DIR"' EXIT

echo "Scanning '$PAGES_BRANCH' for pr/<n>/ preview folders..."
git clone --branch "$PAGES_BRANCH" --single-branch --depth 1 \
  "https://x-access-token:${GH_TOKEN}@github.com/${REPO}.git" "$SCAN_DIR" >/dev/null 2>&1

mapfile -t PREVIEW_NUMS < <(
  find "$SCAN_DIR/pr" -mindepth 1 -maxdepth 1 -type d -exec basename {} \; 2>/dev/null \
    | grep -E '^[0-9]+$' | sort -n
)

if [ ${#PREVIEW_NUMS[@]} -eq 0 ]; then
  echo "No pr/<n>/ folders on '$PAGES_BRANCH'. Nothing to reconcile."
  exit 0
fi
echo "Found ${#PREVIEW_NUMS[@]} preview folder(s): ${PREVIEW_NUMS[*]}"

mapfile -t OPEN_PRS < <(
  gh pr list --repo "$REPO" --state open --limit 500 --json number --jq '.[].number'
)
echo "Currently open PR(s): ${OPEN_PRS[*]:-(none)}"

is_open() {
  local n="$1" open
  for open in "${OPEN_PRS[@]:-}"; do
    [ "$open" = "$n" ] && return 0
  done
  return 1
}

STALE=()
for n in "${PREVIEW_NUMS[@]}"; do
  is_open "$n" || STALE+=("$n")
done

if [ ${#STALE[@]} -eq 0 ]; then
  echo "Every preview folder corresponds to an open PR. Nothing to reconcile."
  exit 0
fi

echo "Stale preview folder(s) to remove: ${STALE[*]}"
for n in "${STALE[@]}"; do
  echo "--- Removing orphaned preview for closed/merged PR #$n ---"
  REPO="$REPO" GH_TOKEN="$GH_TOKEN" PAGES_BRANCH="$PAGES_BRANCH" \
    bash "$SCRIPT_DIR/publish.sh" pr-delete "$n"
done
