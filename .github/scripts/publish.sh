#!/usr/bin/env bash
#
# publish.sh — publish spec builds to the gh-pages branch.
#
# The gh-pages branch hosts an additive file tree:
#
#   /                 root dashboard (index.html, regenerated every run)
#   /main/            latest build of the main branch
#   /pr/<n>/          preview + diff for open PR #<n>
#
# Each invocation only touches its own subfolder, then regenerates the root
# dashboard, then commits and pushes. Because pushes to gh-pages can race
# between concurrent runs, callers MUST serialize via a workflow `concurrency`
# group. As a second line of defence we retry the push with a rebase.
#
# Auth uses the built-in GITHUB_TOKEN (exposed as $GH_TOKEN for the `gh` CLI
# used by the dashboard generator, and via the checkout's credential helper for
# git push). No personal API key is involved.
#
# Usage:
#   publish.sh main               # copy ./av1-mpeg2-ts_Spec -> main/
#   publish.sh pr <number>        # copy ./av1-mpeg2-ts_Spec -> pr/<number>/
#   publish.sh pr-delete <number> # remove pr/<number>/
#
# Environment:
#   REPO        owner/name slug (e.g. AOMediaCodec/av1-mpeg2-ts)     [required]
#   GH_TOKEN    token for `gh` used by gen_dashboard.py             [required]
#   BUILD_DIR   source build dir (default: av1-mpeg2-ts_Spec)
#   PAGES_DIR   gh-pages worktree dir (default: .gh-pages)
#   PAGES_BRANCH branch name (default: gh-pages)

set -euo pipefail

MODE="${1:-}"
ARG="${2:-}"

BUILD_DIR="${BUILD_DIR:-av1-mpeg2-ts_Spec}"
PAGES_DIR="${PAGES_DIR:-.gh-pages}"
PAGES_BRANCH="${PAGES_BRANCH:-gh-pages}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

: "${REPO:?REPO must be set (owner/name)}"

git config --global user.name  "github-actions[bot]"
git config --global user.email "github-actions[bot]@users.noreply.github.com"

# Authenticated remote URL. A fresh `git clone` does NOT inherit the
# credentials actions/checkout configured for the main working copy, so we
# embed the built-in token directly. $GH_TOKEN is the ephemeral GITHUB_TOKEN.
: "${GH_TOKEN:?GH_TOKEN must be set}"
REMOTE_URL="https://x-access-token:${GH_TOKEN}@github.com/${REPO}.git"

# --- Clone (or create) the gh-pages branch into a fresh worktree ----------
rm -rf "$PAGES_DIR"
if git ls-remote --exit-code --heads "$REMOTE_URL" "$PAGES_BRANCH" >/dev/null 2>&1; then
  git clone --branch "$PAGES_BRANCH" --single-branch --depth 1 \
    "$REMOTE_URL" "$PAGES_DIR"
else
  echo "gh-pages branch does not exist yet — creating orphan branch."
  git clone --depth 1 "$REMOTE_URL" "$PAGES_DIR"
  ( cd "$PAGES_DIR"
    git checkout --orphan "$PAGES_BRANCH"
    git rm -rf . >/dev/null 2>&1 || true
    # .nojekyll: serve _-prefixed asset dirs and skip Jekyll processing.
    touch .nojekyll )
fi

# --- Apply the requested change to the tree -------------------------------
# UTC timestamp recorded in each published folder so the dashboard can show a
# reliable "last updated" per card (file mtimes reset on gh-pages clone).
PUBLISHED_AT="$(date -u '+%Y-%m-%d %H:%M UTC')"
case "$MODE" in
  main)
    echo "Publishing main build -> main/"
    rm -rf "$PAGES_DIR/main"
    mkdir -p "$PAGES_DIR/main"
    cp -R "$BUILD_DIR/." "$PAGES_DIR/main/"
    printf '%s' "$PUBLISHED_AT" > "$PAGES_DIR/main/.published-at"
    ;;
  pr)
    : "${ARG:?PR number required}"
    echo "Publishing PR #$ARG build -> pr/$ARG/"
    rm -rf "${PAGES_DIR:?}/pr/$ARG"
    mkdir -p "$PAGES_DIR/pr/$ARG"
    cp -R "$BUILD_DIR/." "$PAGES_DIR/pr/$ARG/"
    printf '%s' "$PUBLISHED_AT" > "$PAGES_DIR/pr/$ARG/.published-at"
    ;;
  pr-delete)
    : "${ARG:?PR number required}"
    echo "Removing preview for PR #$ARG"
    rm -rf "${PAGES_DIR:?}/pr/$ARG"
    ;;
  *)
    echo "usage: publish.sh {main|pr <n>|pr-delete <n>}" >&2
    exit 2
    ;;
esac

# --- Regenerate the root dashboard ----------------------------------------
touch "$PAGES_DIR/.nojekyll"
# Kill-switch service worker at the site root: evicts any stale spec worker a
# previous root-served deployment registered at scope "/". Served as sw.js.
cp "$SCRIPT_DIR/kill-sw.js" "$PAGES_DIR/sw.js"
REPO="$REPO" python3 "$SCRIPT_DIR/gen_dashboard.py" "$PAGES_DIR"

# --- Commit & push (with rebase-retry to survive races) -------------------
cd "$PAGES_DIR"
git add -A
if git diff --cached --quiet; then
  echo "No changes to publish."
  exit 0
fi

MSG="Update previews: ${MODE}${ARG:+ #$ARG} [skip ci]"
git commit -m "$MSG"

for attempt in 1 2 3 4 5; do
  if git push origin "HEAD:${PAGES_BRANCH}"; then
    echo "Pushed to ${PAGES_BRANCH} (attempt ${attempt})."
    exit 0
  fi
  echo "Push failed (attempt ${attempt}); refetching and retrying..."
  git fetch origin "$PAGES_BRANCH" || true
  git rebase "origin/${PAGES_BRANCH}" || git rebase --abort || true
done

echo "Failed to push after retries." >&2
exit 1
