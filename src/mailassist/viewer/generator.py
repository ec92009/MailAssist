from __future__ import annotations

import json
from pathlib import Path


HTML_TEMPLATE = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>MailAssist Viewer</title>
    <style>
      :root {
        --bg: #f2eee7;
        --panel: #fffaf4;
        --ink: #1e2430;
        --muted: #5c6677;
        --accent: #c95c3d;
        --border: #d7cabb;
      }
      * { box-sizing: border-box; }
      body {
        margin: 0;
        font-family: Georgia, "Iowan Old Style", serif;
        background:
          radial-gradient(circle at top left, rgba(201, 92, 61, 0.16), transparent 32%),
          linear-gradient(180deg, #f7f2ea, #efe7db);
        color: var(--ink);
      }
      header {
        padding: 48px 20px 24px;
        max-width: 1100px;
        margin: 0 auto;
      }
      h1 {
        margin: 0;
        font-size: clamp(2.2rem, 5vw, 4rem);
        line-height: 0.95;
      }
      p {
        color: var(--muted);
        max-width: 720px;
        font-size: 1.05rem;
      }
      main {
        max-width: 1100px;
        margin: 0 auto;
        padding: 0 20px 40px;
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
        gap: 20px;
      }
      section {
        background: var(--panel);
        border: 1px solid var(--border);
        border-radius: 18px;
        padding: 20px;
        box-shadow: 0 10px 30px rgba(30, 36, 48, 0.08);
      }
      h2 {
        margin-top: 0;
        font-size: 1.3rem;
      }
      article {
        border-top: 1px solid var(--border);
        padding-top: 14px;
        margin-top: 14px;
      }
      article:first-of-type {
        border-top: 0;
        padding-top: 0;
        margin-top: 0;
      }
      .meta {
        color: var(--muted);
        font-size: 0.92rem;
      }
      pre {
        white-space: pre-wrap;
        background: #fff;
        border: 1px solid var(--border);
        border-radius: 12px;
        padding: 12px;
        overflow-x: auto;
      }
      .badge {
        display: inline-block;
        padding: 4px 8px;
        border-radius: 999px;
        background: rgba(201, 92, 61, 0.12);
        color: var(--accent);
        font-size: 0.82rem;
        margin-right: 8px;
      }
    </style>
  </head>
  <body>
    <header>
      <h1>MailAssist Viewer</h1>
      <p>Static snapshot of locally generated drafts and execution logs. Commit the generated files to publish them through GitHub Pages.</p>
    </header>
    <main>
      <section>
        <h2>Drafts</h2>
        __DRAFTS__
      </section>
      <section>
        <h2>Logs</h2>
        __LOGS__
      </section>
    </main>
  </body>
</html>
"""


def _render_drafts(drafts: list[dict]) -> str:
    if not drafts:
        return "<p>No drafts yet.</p>"

    items = []
    for draft in reversed(drafts):
        provider_id = draft.get("provider_draft_id") or "local-only"
        items.append(
            f"""
            <article>
              <div><span class="badge">{draft["provider"]}</span><span class="badge">{draft["status"]}</span></div>
              <h3>{draft["subject"]}</h3>
              <div class="meta">Thread {draft["thread_id"]} • Model {draft["model"]} • Provider draft {provider_id}</div>
              <pre>{draft["body"]}</pre>
            </article>
            """
        )
    return "\n".join(items)


def _render_logs(logs: list[dict]) -> str:
    if not logs:
        return "<p>No logs yet.</p>"

    items = []
    for log in reversed(logs):
        error_block = f"<pre>{log['error']}</pre>" if log.get("error") else ""
        items.append(
            f"""
            <article>
              <div><span class="badge">{log["status"]}</span><span class="badge">{log["provider"]}</span></div>
              <div class="meta">Run {log["run_id"]} • Thread {log["thread_id"]} • Started {log["started_at"]}</div>
              <p>{log["prompt_preview"]}</p>
              <p>{log["response_preview"]}</p>
              {error_block}
            </article>
            """
        )
    return "\n".join(items)


def build_site(site_dir: Path, drafts: list[dict], logs: list[dict]) -> Path:
    site_dir.mkdir(parents=True, exist_ok=True)
    (site_dir / ".gitkeep").write_text("", encoding="utf-8")
    (site_dir / "data.json").write_text(
        json.dumps({"drafts": drafts, "logs": logs}, indent=2), encoding="utf-8"
    )
    html = HTML_TEMPLATE.replace("__DRAFTS__", _render_drafts(drafts)).replace(
        "__LOGS__", _render_logs(logs)
    )
    output = site_dir / "index.html"
    output.write_text(html, encoding="utf-8")
    return output
