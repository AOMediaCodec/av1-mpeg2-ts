#!/usr/bin/env python3
"""Generate the root index.html dashboard for the spec preview site.

The dashboard lists the live `main/` build plus one card per open PR that
currently has a preview folder on the gh-pages branch.

Inputs:
  * argv[1]  : path to the checked-out gh-pages worktree (root of the site).
               PR previews are expected under `<root>/pr/<n>/`, main under
               `<root>/main/`.
  * env REPO : "owner/name" slug (from ${{ github.repository }}), used to
               build absolute links and to query open PRs.

Open-PR metadata (title, author, base branch) is fetched with the GitHub CLI
(`gh pr list`), which authenticates using the built-in GITHUB_TOKEN — no
personal API key is required. If `gh` is unavailable or fails, we fall back to
listing whatever `pr/<n>/` folders exist on disk.
"""

from __future__ import annotations

import html
import json
import os
import subprocess
import sys
from pathlib import Path


def open_prs() -> dict[int, dict]:
    """Return {number: {title, author, base}} for open PRs via `gh`.

    Empty dict on any failure — callers fall back to the folder listing.
    """
    try:
        out = subprocess.run(
            [
                "gh", "pr", "list",
                "--state", "open",
                "--limit", "200",
                "--json", "number,title,author,baseRefName,headRefName,updatedAt",
            ],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        prs = json.loads(out)
    except (subprocess.CalledProcessError, FileNotFoundError, json.JSONDecodeError):
        return {}

    result: dict[int, dict] = {}
    for pr in prs:
        result[int(pr["number"])] = {
            "title": pr.get("title", ""),
            "author": (pr.get("author") or {}).get("login", ""),
            "base": pr.get("baseRefName", ""),
            "head": pr.get("headRefName", ""),
            "updated": pr.get("updatedAt", ""),
        }
    return result


def existing_pr_dirs(root: Path) -> list[int]:
    """PR numbers that currently have a preview folder on gh-pages."""
    pr_root = root / "pr"
    if not pr_root.is_dir():
        return []
    nums: list[int] = []
    for child in pr_root.iterdir():
        if child.is_dir() and child.name.isdigit():
            nums.append(int(child.name))
    return sorted(nums)


def render(root: Path, repo: str) -> str:
    meta = open_prs()
    dirs = set(existing_pr_dirs(root))

    # Show a card for every PR that has a folder. Enrich with `gh` metadata
    # where available; folders without metadata (e.g. gh failed) still render.
    pr_numbers = sorted(dirs, reverse=True)

    repo_url = f"https://github.com/{repo}"
    has_main = (root / "main" / "index.html").exists()
    main_pdf = "av1-mpeg2-ts_Spec.pdf"
    has_main_pdf = (root / "main" / main_pdf).exists()

    # GitHub mark (Octicons mark-github) — inline so it needs no external
    # asset; inherits the link colour via fill="currentColor".
    _gh_path = (
        "M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19"
        "-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-."
        "15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28"
        "-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1."
        "02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53"
        "-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1"
        ".87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46."
        "55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"
    )
    github_icon = (
        '<svg class="gh-icon" viewBox="0 0 16 16" width="14" height="14" '
        f'fill="currentColor" aria-hidden="true"><path d="{_gh_path}"></path></svg>'
    )

    def card_time(rel: str) -> str:
        """Render the last-published timestamp for a folder, if recorded.

        publish.sh writes ``<folder>/.published-at`` (UTC) when it publishes a
        build; file mtimes are unreliable because a fresh gh-pages clone resets
        them, so the persisted marker is the source of truth.
        """
        marker = root / rel / ".published-at"
        try:
            ts = marker.read_text(encoding="utf-8").strip() if marker.exists() else ""
        except OSError:
            ts = ""
        if not ts:
            return ""
        return f'<span class="card-time" title="Last updated">{html.escape(ts)}</span>'


    cards = []
    for n in pr_numbers:
        info = meta.get(n, {})
        title = html.escape(info.get("title") or f"Pull request #{n}")
        author = html.escape(info.get("author") or "")
        base = html.escape(info.get("base") or "main")
        head = html.escape(info.get("head") or "")
        stale = n not in meta  # folder exists but PR no longer open

        author_line = f"by @{author} · " if author else ""
        branch_line = f"{head} → {base}" if head else f"→ {base}"
        stale_badge = (
            '<span class="badge stale">merged/closed — pending cleanup</span>'
            if stale else ""
        )

        cards.append(f"""
      <article class="card">
        {card_time(f"pr/{n}")}
        <h3><a href="./pr/{n}/index.html">PR #{n}: {title}</a> {stale_badge}</h3>
        <p class="meta">{author_line}{branch_line}</p>
        <p class="links">
          <a href="./pr/{n}/index.html">Spec</a>
          <a href="./pr/{n}/diff_viewer.html">Diff viewer</a>
          <a href="{repo_url}/pull/{n}">{github_icon} PR #{n}</a>
        </p>
      </article>""")

    if not cards:
        cards.append('<p class="empty">No open pull requests with previews right now.</p>')

    pdf_link = (
        f'\n          <a href="./main/{main_pdf}">PDF</a>' if has_main_pdf else ""
    )
    main_card = (
        f"""
      <article class="card main">
        {card_time("main")}
        <h3><a href="./main/index.html">Main specification</a></h3>
        <p class="meta">Latest build of the <code>main</code> branch</p>
        <p class="links">
          <a href="./main/index.html">Spec</a>{pdf_link}
          <a href="{repo_url}">{github_icon} Repository</a>
        </p>
      </article>"""
        if has_main
        else '<p class="empty">Main build not available yet.</p>'
    )

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>AV1-MPEG2-TS — Spec Previews</title>
  <style>
    :root {{ color-scheme: light dark; }}
    body {{
      font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
      max-width: 860px; margin: 0 auto; padding: 2rem 1.25rem; line-height: 1.5;
    }}
    h1 {{ margin-bottom: 0.25rem; }}
    .subtitle {{ color: #666; margin-top: 0; }}
    h2 {{ margin-top: 2rem; border-bottom: 1px solid #ccc3; padding-bottom: 0.3rem; }}
    .card {{
      border: 1px solid #8884; border-radius: 10px; padding: 1rem 1.25rem;
      margin: 1rem 0; background: #8881; position: relative;
    }}
    .card.main {{ border-color: #3b82f6aa; background: #3b82f611; }}
    .card h3 {{ margin: 0 0 0.35rem; font-size: 1.1rem; }}
    .card-time {{
      position: absolute; top: 0.7rem; right: 1rem;
      color: #999; font-size: 0.72rem; white-space: nowrap;
    }}
    .gh-icon {{ vertical-align: -2px; color: #1f2328; }}
    @media (prefers-color-scheme: dark) {{ .gh-icon {{ color: #e6edf3; }} }}
    .meta {{ margin: 0.2rem 0 0.6rem; color: #777; font-size: 0.9rem; }}
    .links a {{ margin-right: 1rem; text-decoration: none; white-space: nowrap; }}
    .links a:hover {{ text-decoration: underline; }}
    .badge.stale {{
      font-size: 0.72rem; font-weight: 600; color: #b45309;
      background: #f59e0b22; border: 1px solid #f59e0b55;
      border-radius: 999px; padding: 0.1rem 0.55rem; vertical-align: middle;
    }}
    .empty {{ color: #888; font-style: italic; }}
    footer {{ margin-top: 3rem; color: #999; font-size: 0.82rem; }}
  </style>
</head>
<body>
  <h1>AV1-MPEG2-TS Specification Previews</h1>
  <p class="subtitle">Live builds of the specification and open pull requests.</p>

  <h2>Main</h2>
  {main_card}

  <h2>Open pull requests</h2>
  {"".join(cards)}

  <footer>
    Generated automatically by GitHub Actions ·
    <a href="{repo_url}">{html.escape(repo)}</a>
  </footer>

  <script>
    // Register the kill-switch worker to evict any stale spec service worker
    // that a previous (root-served) deployment left registered at scope "/".
    if ('serviceWorker' in navigator) {{
      navigator.serviceWorker.register('./sw.js').catch(function () {{}});
    }}
  </script>
</body>
</html>
"""


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: gen_dashboard.py <gh-pages-root>", file=sys.stderr)
        return 2
    root = Path(sys.argv[1])
    repo = os.environ.get("REPO", "AOMediaCodec/av1-mpeg2-ts")
    (root / "index.html").write_text(render(root, repo), encoding="utf-8")
    print(f"Wrote {root / 'index.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
