from __future__ import annotations

import html
import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from mailassist.config import load_settings, read_env_file, write_env_file
from mailassist.llm.ollama import OllamaClient
from mailassist.storage.filesystem import FileStorage


def render_page(
    message: str = "",
    level: str = "info",
    ollama_prompt: str = "",
    ollama_result: str = "",
    ollama_result_level: str = "info",
) -> str:
    settings = load_settings()
    storage = FileStorage(settings.drafts_dir, settings.logs_dir)
    drafts = storage.list_draft_records()
    gmail_connected = settings.gmail_token_file.exists()
    models = []
    model_error = ""
    try:
        models = OllamaClient(settings.ollama_url, settings.ollama_model).list_models()
    except RuntimeError as exc:
        model_error = str(exc)

    options = []
    seen_selected = False
    for model_name in models:
        selected = " selected" if model_name == settings.ollama_model else ""
        if selected:
            seen_selected = True
        options.append(
            f'<option value="{html.escape(model_name)}"{selected}>{html.escape(model_name)}</option>'
        )
    if settings.ollama_model and not seen_selected:
        options.append(
            f'<option value="{html.escape(settings.ollama_model)}" selected>{html.escape(settings.ollama_model)} (current)</option>'
        )

    message_block = ""
    if message:
        message_block = f'<div class="banner {level}">{html.escape(message)}</div>'

    model_error_block = ""
    if model_error:
        model_error_block = f'<p class="hint error-text">{html.escape(model_error)}</p>'

    gmail_checked = "checked" if settings.gmail_enabled else ""
    outlook_checked = "checked" if settings.outlook_enabled else ""
    gmail_selected = "selected" if settings.default_provider == "gmail" else ""
    outlook_selected = "selected" if settings.default_provider == "outlook" else ""
    gmail_status = "Connected" if gmail_connected else "Not connected"
    gmail_open = " open" if settings.gmail_enabled else ""
    outlook_open = " open" if settings.outlook_enabled else ""

    ollama_result_block = ""
    if ollama_result:
        ollama_result_block = (
            f'<div class="test-result {ollama_result_level}"><pre>{html.escape(ollama_result)}</pre></div>'
        )

    draft_cards = []
    for draft in drafts:
        draft_cards.append(
            f"""
            <article class="draft-card">
              <div class="draft-header">
                <div>
                  <h3>{html.escape(draft.subject)}</h3>
                  <p class="meta">Thread {html.escape(draft.thread_id)} • {html.escape(draft.provider)} • {html.escape(draft.model)} • {html.escape(draft.created_at)}</p>
                </div>
                <span class="pill">{html.escape(draft.status)}</span>
              </div>
              <pre class="draft-body">{html.escape(draft.body)}</pre>
              <form class="revision-form" method="post" action="/draft-action">
                <input type="hidden" name="draft_id" value="{html.escape(draft.draft_id)}" />
                <label for="revision_notes_{html.escape(draft.draft_id)}">Revision notes</label>
                <textarea id="revision_notes_{html.escape(draft.draft_id)}" name="revision_notes" placeholder="What should change before we regenerate or edit this reply?">{html.escape(draft.revision_notes or "")}</textarea>
                <div class="actions">
                  <button type="submit" name="action" value="accepted">Green light</button>
                  <button type="submit" name="action" value="rejected" class="button warn">Red light</button>
                  <button type="submit" name="action" value="needs_revision" class="button secondary">Needs revision</button>
                  <button type="submit" name="action" value="pending_review" class="button secondary">Reset</button>
                </div>
              </form>
            </article>
            """
        )
    drafts_block = "\n".join(draft_cards) if draft_cards else '<p class="hint">No drafts yet. Generate one from the CLI, then review it here.</p>'

    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>MailAssist Config</title>
    <style>
      :root {{
        --bg: #f7f2ea;
        --panel: #fffaf4;
        --ink: #1e2430;
        --muted: #5c6677;
        --accent: #c95c3d;
        --border: #d9cbbb;
        --ok: #246a4f;
        --warn: #8c5122;
      }}
      * {{ box-sizing: border-box; }}
      body {{
        margin: 0;
        font-family: Georgia, "Iowan Old Style", serif;
        color: var(--ink);
        background:
          radial-gradient(circle at top left, rgba(201, 92, 61, 0.16), transparent 30%),
          linear-gradient(180deg, #faf5ee, #efe6db);
      }}
      .shell {{
        max-width: 1080px;
        margin: 0 auto;
        padding: 28px 18px 48px;
      }}
      .hero {{
        padding: 18px 4px 24px;
      }}
      .hero h1 {{
        margin: 0;
        font-size: clamp(2.2rem, 5vw, 4rem);
        line-height: 0.95;
      }}
      .hero p {{
        max-width: 760px;
        color: var(--muted);
        font-size: 1.05rem;
      }}
      .grid {{
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
        gap: 18px;
      }}
      .stack {{
        display: grid;
        gap: 18px;
      }}
      .panel {{
        background: var(--panel);
        border: 1px solid var(--border);
        border-radius: 18px;
        padding: 18px;
        box-shadow: 0 10px 28px rgba(30, 36, 48, 0.08);
      }}
      h2 {{
        margin-top: 0;
        margin-bottom: 10px;
        font-size: 1.35rem;
      }}
      label {{
        display: block;
        font-size: 0.95rem;
        margin: 14px 0 6px;
      }}
      input, select {{
        width: 100%;
        padding: 11px 12px;
        border: 1px solid var(--border);
        border-radius: 12px;
        background: #fff;
        font: inherit;
        color: var(--ink);
      }}
      textarea {{
        width: 100%;
        min-height: 120px;
        padding: 11px 12px;
        border: 1px solid var(--border);
        border-radius: 12px;
        background: #fff;
        font: inherit;
        color: var(--ink);
        resize: vertical;
      }}
      input[type="checkbox"] {{
        width: auto;
        margin-right: 8px;
      }}
      .check-row {{
        display: flex;
        align-items: center;
        margin-top: 12px;
      }}
      .actions {{
        display: flex;
        gap: 10px;
        flex-wrap: wrap;
        margin-top: 18px;
      }}
      button, .button {{
        display: inline-block;
        border: 0;
        border-radius: 999px;
        padding: 11px 16px;
        background: var(--accent);
        color: #fffaf4;
        text-decoration: none;
        font: inherit;
        cursor: pointer;
      }}
      .button.secondary {{
        background: #f0e3d2;
        color: var(--ink);
      }}
      .button.warn {{
        background: #a84b2f;
      }}
      .hint {{
        color: var(--muted);
        font-size: 0.92rem;
      }}
      .banner {{
        margin-bottom: 18px;
        padding: 12px 14px;
        border-radius: 14px;
      }}
      .banner.info {{
        background: rgba(36, 106, 79, 0.12);
        color: var(--ok);
      }}
      .banner.error {{
        background: rgba(140, 81, 34, 0.12);
        color: var(--warn);
      }}
      .pill {{
        display: inline-block;
        padding: 4px 9px;
        border-radius: 999px;
        background: rgba(201, 92, 61, 0.12);
        color: var(--accent);
        font-size: 0.82rem;
      }}
      .status {{
        margin-top: 10px;
        color: var(--muted);
      }}
      .error-text {{
        color: var(--warn);
      }}
      details {{
        margin-top: 16px;
        border: 1px solid var(--border);
        border-radius: 14px;
        background: rgba(255, 255, 255, 0.5);
        overflow: hidden;
      }}
      summary {{
        cursor: pointer;
        list-style: none;
        padding: 14px 16px;
        font-weight: 600;
        display: flex;
        align-items: center;
        justify-content: space-between;
      }}
      summary::-webkit-details-marker {{
        display: none;
      }}
      .details-body {{
        padding: 0 16px 16px;
        border-top: 1px solid var(--border);
      }}
      .summary-meta {{
        color: var(--muted);
        font-size: 0.9rem;
        font-weight: 400;
      }}
      .test-result {{
        margin-top: 14px;
        border-radius: 14px;
        padding: 12px;
      }}
      .test-result.info {{
        background: rgba(36, 106, 79, 0.08);
      }}
      .test-result.error {{
        background: rgba(140, 81, 34, 0.1);
      }}
      pre {{
        margin: 0;
        white-space: pre-wrap;
        word-break: break-word;
        font-family: "SFMono-Regular", Menlo, monospace;
      }}
      .draft-card {{
        border: 1px solid var(--border);
        border-radius: 14px;
        padding: 16px;
        background: rgba(255, 255, 255, 0.65);
        margin-top: 16px;
      }}
      .draft-card:first-of-type {{
        margin-top: 0;
      }}
      .draft-header {{
        display: flex;
        gap: 12px;
        align-items: flex-start;
        justify-content: space-between;
      }}
      h3 {{
        margin: 0;
        font-size: 1.1rem;
      }}
      .meta {{
        margin: 6px 0 0;
        color: var(--muted);
        font-size: 0.9rem;
      }}
      .draft-body {{
        margin-top: 14px;
        padding: 12px;
        border-radius: 12px;
        background: #fff;
        border: 1px solid var(--border);
      }}
      .revision-form {{
        margin-top: 14px;
      }}
      code {{
        font-family: "SFMono-Regular", Menlo, monospace;
      }}
    </style>
  </head>
  <body>
    <div class="shell">
      <div class="hero">
        <h1>MailAssist Config</h1>
        <p>Local operator UI for provider setup and Ollama model selection. Settings are saved to <code>.env</code> in this repo and used by the CLI.</p>
      </div>
      {message_block}
      <div class="grid">
        <div class="stack">
          <form class="panel" method="post" action="/save">
            <h2>Ollama</h2>
            <label for="ollama_url">Ollama URL</label>
            <input id="ollama_url" name="MAILASSIST_OLLAMA_URL" value="{html.escape(settings.ollama_url)}" />
            <label for="ollama_model">Chosen model</label>
            <select id="ollama_model" name="MAILASSIST_OLLAMA_MODEL">
              {''.join(options) or '<option value="">No models found</option>'}
            </select>
            {model_error_block}
            <p class="hint">Model options come from Ollama's local <code>/api/tags</code> endpoint.</p>
            <div class="actions">
              <button type="submit">Save Ollama settings</button>
              <a class="button secondary" href="/">Refresh model list</a>
            </div>
          </form>

          <form class="panel" method="post" action="/test-ollama">
            <h2>Ollama Check</h2>
            <label for="ollama_test_prompt">Test prompt</label>
            <textarea id="ollama_test_prompt" name="prompt" placeholder="Say hello and confirm which model answered.">{html.escape(ollama_prompt)}</textarea>
            <p class="hint">Use this to confirm the selected Ollama model is reachable and responding.</p>
            <div class="actions">
              <button type="submit">Send test prompt</button>
            </div>
            {ollama_result_block}
          </form>

          <form class="panel" method="post" action="/save">
            <h2>Providers</h2>
            <label for="default_provider">Default provider</label>
            <select id="default_provider" name="MAILASSIST_DEFAULT_PROVIDER">
              <option value="gmail" {gmail_selected}>Gmail</option>
              <option value="outlook" {outlook_selected}>Outlook</option>
            </select>
            <label class="check-row"><input type="checkbox" name="MAILASSIST_GMAIL_ENABLED" value="true" {gmail_checked} />Enable Gmail</label>
            <label class="check-row"><input type="checkbox" name="MAILASSIST_OUTLOOK_ENABLED" value="true" {outlook_checked} />Enable Outlook</label>
            <details{gmail_open}>
              <summary>
                <span>Gmail</span>
                <span class="summary-meta">{gmail_status if settings.gmail_enabled else "Disabled"}</span>
              </summary>
              <div class="details-body">
                <label for="gmail_credentials_file">Credentials file</label>
                <input id="gmail_credentials_file" name="MAILASSIST_GMAIL_CREDENTIALS_FILE" value="{html.escape(str(settings.gmail_credentials_file))}" />
                <label for="gmail_token_file">Token file</label>
                <input id="gmail_token_file" name="MAILASSIST_GMAIL_TOKEN_FILE" value="{html.escape(str(settings.gmail_token_file))}" />
                <p class="status">Token present: {"yes" if gmail_connected else "no"}</p>
              </div>
            </details>
            <details{outlook_open}>
              <summary>
                <span>Outlook</span>
                <span class="summary-meta">{"Enabled" if settings.outlook_enabled else "Disabled"}</span>
              </summary>
              <div class="details-body">
                <label for="outlook_client_id">Client ID</label>
                <input id="outlook_client_id" name="MAILASSIST_OUTLOOK_CLIENT_ID" value="{html.escape(settings.outlook_client_id)}" />
                <label for="outlook_tenant_id">Tenant ID</label>
                <input id="outlook_tenant_id" name="MAILASSIST_OUTLOOK_TENANT_ID" value="{html.escape(settings.outlook_tenant_id)}" />
                <label for="outlook_redirect_uri">Redirect URI</label>
                <input id="outlook_redirect_uri" name="MAILASSIST_OUTLOOK_REDIRECT_URI" value="{html.escape(settings.outlook_redirect_uri)}" />
                <p class="hint">Outlook draft creation is not implemented yet, but the local UI already preserves its connection settings.</p>
              </div>
            </details>
            <div class="actions">
              <button type="submit">Save provider settings</button>
            </div>
          </form>
        </div>

        <div class="panel">
          <h2>Draft Review</h2>
          <p class="hint">Green light and red light decisions now live here in the local UI.</p>
          {drafts_block}
        </div>
      </div>
    </div>
  </body>
</html>
"""


class ConfigRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            params = parse_qs(parsed.query)
            message = params.get("message", [""])[0]
            level = params.get("level", ["info"])[0]
            self._send_html(render_page(message=message, level=level))
            return

        if parsed.path == "/api/ollama/models":
            settings = load_settings()
            try:
                models = OllamaClient(settings.ollama_url, settings.ollama_model).list_models()
                self._send_json({"models": models})
            except RuntimeError as exc:
                self._send_json({"models": [], "error": str(exc)}, status=HTTPStatus.BAD_GATEWAY)
            return

        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        if self.path == "/draft-action":
            self._handle_draft_action()
            return

        if self.path == "/test-ollama":
            self._handle_test_ollama()
            return

        if self.path != "/save":
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8")
        form = parse_qs(body)

        env_file = load_settings().root_dir / ".env"
        current = read_env_file(env_file)
        updates = {
            "MAILASSIST_OLLAMA_URL": form.get("MAILASSIST_OLLAMA_URL", [current.get("MAILASSIST_OLLAMA_URL", "http://localhost:11434")])[0],
            "MAILASSIST_OLLAMA_MODEL": form.get("MAILASSIST_OLLAMA_MODEL", [current.get("MAILASSIST_OLLAMA_MODEL", "llama3.1:8b")])[0],
            "MAILASSIST_DEFAULT_PROVIDER": form.get("MAILASSIST_DEFAULT_PROVIDER", [current.get("MAILASSIST_DEFAULT_PROVIDER", "gmail")])[0],
            "MAILASSIST_GMAIL_ENABLED": "true" if "MAILASSIST_GMAIL_ENABLED" in form else "false",
            "MAILASSIST_OUTLOOK_ENABLED": "true" if "MAILASSIST_OUTLOOK_ENABLED" in form else "false",
            "MAILASSIST_GMAIL_CREDENTIALS_FILE": form.get(
                "MAILASSIST_GMAIL_CREDENTIALS_FILE",
                [current.get("MAILASSIST_GMAIL_CREDENTIALS_FILE", "secrets/gmail-client-secret.json")],
            )[0],
            "MAILASSIST_GMAIL_TOKEN_FILE": form.get(
                "MAILASSIST_GMAIL_TOKEN_FILE",
                [current.get("MAILASSIST_GMAIL_TOKEN_FILE", "secrets/gmail-token.json")],
            )[0],
            "MAILASSIST_OUTLOOK_CLIENT_ID": form.get(
                "MAILASSIST_OUTLOOK_CLIENT_ID",
                [current.get("MAILASSIST_OUTLOOK_CLIENT_ID", "")],
            )[0],
            "MAILASSIST_OUTLOOK_TENANT_ID": form.get(
                "MAILASSIST_OUTLOOK_TENANT_ID",
                [current.get("MAILASSIST_OUTLOOK_TENANT_ID", "")],
            )[0],
            "MAILASSIST_OUTLOOK_REDIRECT_URI": form.get(
                "MAILASSIST_OUTLOOK_REDIRECT_URI",
                [current.get("MAILASSIST_OUTLOOK_REDIRECT_URI", "http://localhost:8765/outlook/callback")],
            )[0],
        }
        current.update(updates)
        write_env_file(env_file, current)

        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", "/?message=Settings+saved&level=info")
        self.end_headers()

    def _handle_test_ollama(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8")
        form = parse_qs(body)
        prompt = form.get("prompt", [""])[0].strip()
        settings = load_settings()

        if not prompt:
            self._send_html(
                render_page(
                    message="Enter a prompt before testing Ollama.",
                    level="error",
                    ollama_prompt="",
                    ollama_result="",
                ),
                status=HTTPStatus.BAD_REQUEST,
            )
            return

        try:
            result = OllamaClient(settings.ollama_url, settings.ollama_model).compose_reply(prompt)
            if not result:
                result = "Ollama responded, but the model returned an empty body."
            self._send_html(
                render_page(
                    message="Ollama test completed.",
                    level="info",
                    ollama_prompt=prompt,
                    ollama_result=result,
                    ollama_result_level="info",
                )
            )
        except RuntimeError as exc:
            self._send_html(
                render_page(
                    message="Ollama test failed.",
                    level="error",
                    ollama_prompt=prompt,
                    ollama_result=str(exc),
                    ollama_result_level="error",
                ),
                status=HTTPStatus.BAD_GATEWAY,
            )

    def _handle_draft_action(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8")
        form = parse_qs(body)
        draft_id = form.get("draft_id", [""])[0].strip()
        action = form.get("action", [""])[0].strip()
        revision_notes = form.get("revision_notes", [""])[0].strip()

        if not draft_id or action not in {"accepted", "rejected", "needs_revision", "pending_review"}:
            self._send_html(
                render_page(message="Invalid draft action.", level="error"),
                status=HTTPStatus.BAD_REQUEST,
            )
            return

        settings = load_settings()
        storage = FileStorage(settings.drafts_dir, settings.logs_dir)
        storage.update_draft(
            draft_id,
            status=action,
            revision_notes=revision_notes or None,
        )
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", "/?message=Draft+updated&level=info")
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        return

    def _send_html(self, content: str, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = content.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def serve_config_gui(host: str = "127.0.0.1", port: int = 8765) -> None:
    server = ThreadingHTTPServer((host, port), ConfigRequestHandler)
    print(f"MailAssist config GUI available at http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
