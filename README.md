# MailAssist

Local AI-assisted email drafting bot using Ollama and local models. `MailAssist` ingests email threads, composes proposed replies, saves drafts and execution logs locally, can optionally submit drafts to Gmail, and keeps approval decisions inside the local desktop UI.

## Current docs

- [STRATEGY.md](~/Dev/MailAssist/STRATEGY.md): current product shape, workflow, and architecture
- [RESULTS.md](~/Dev/MailAssist/RESULTS.md): current implementation status, known gaps, and short-term conclusions
- [TODO.md](~/Dev/MailAssist/TODO.md): active follow-up work
- [REALISM.md](~/Dev/MailAssist/REALISM.md): safety, privacy, and provider-reality constraints
- [RESEARCH.md](~/Dev/MailAssist/RESEARCH.md): integration and product research backlog
- [SUMMARY.md](~/Dev/MailAssist/SUMMARY.md): high-level snapshot of where the project stands
- [ENVIRONMENT_SOP.md](~/Dev/MailAssist/ENVIRONMENT_SOP.md): workspace Python and package-management preferences
- [VERSIONING_SOP.md](~/Dev/MailAssist/VERSIONING_SOP.md): bot/local-UI visible versioning rules
- [SHOW_ME_SOP.md](~/Dev/MailAssist/SHOW_ME_SOP.md): local UI show-and-report workflow

Use this `README` for setup and operational scripts. For decisions about workflow, safety, rollout, and product direction, prefer the docs above.

Project shorthand:

- `rscp` means: refresh docs, summarize the current conversation to `SUMMARY.md`, commit, and push.

---

## What this project does

- Accepts a normalized email thread payload from a local file or future provider sync
- Builds a response prompt for a local model running through Ollama
- Saves generated reply drafts to `data/drafts/`
- Saves execution logs to `data/logs/`
- Keeps the human in control of every draft: compare options, edit them locally, then green-light or red-light one
- Optionally submits approved drafts to Gmail from the CLI or the local UI
- Includes a native `PySide6` desktop app for provider settings, Ollama configuration, mock inbox review, and bot log inspection

---

## Project structure

```text
MailAssist/
├── .env.example                  # Local config template
├── AGENTS.md                     # Repo working preferences
├── STRATEGY.md                   # Product and architecture strategy
├── REALISM.md                    # Constraints and safety guardrails
├── RESULTS.md                    # Current implementation state
├── RESEARCH.md                   # Open research questions
├── TODO.md                       # Near-term work list
├── SUMMARY.md                    # Executive snapshot
├── VERSIONING_SOP.md             # Visible versioning guidance
├── SHOW_ME_SOP.md                # Local UI show/share workflow
├── data/
│   ├── threads/                  # Source email thread JSON files
│   ├── drafts/                   # Saved generated draft JSON files
│   └── logs/                     # Saved execution log JSON files
├── src/mailassist/               # Bot package
```

---

## Setup

### 1. Clone and create the repo environment

```bash
cd ~/Dev/MailAssist
uv venv .venv
source .venv/bin/activate
uv pip install --python .venv/bin/python -e .
```

### 2. Configure local settings

```bash
cp .env.example .env
```

Set the Ollama endpoint and model you want to use. Add Gmail OAuth paths when you are ready to enable Gmail drafts.

You can also configure the app through the native desktop GUI:

```bash
./.venv/bin/mailassist desktop-gui
```

### 3. Create a sample draft locally

```bash
./.venv/bin/mailassist draft-thread --thread-file data/threads/sample-thread.json
```

### 4. Open the local UI

```bash
./.venv/bin/mailassist desktop-gui
```

The desktop app is the preferred review surface going forward.

The local GUI now opens into a review-first workspace with:

- a sortable inbox table with classification, received date, and sender
- side-by-side thread review and candidate drafting
- explicit `Use this`, `Ignore`, and `Close` actions in the detail view
- Ollama-generated classifications so urgent mail can be surfaced and automated or spammy threads can be set aside
- a modal settings dialog for Ollama, provider config, and the user signature
- a separate logs window for bot stdout and saved JSONL logs

For a macOS app bundle in the current LeadLight-style launcher pattern:

```bash
./build_mailassist_app.sh
```

---

## Gmail draft support

Gmail is the first provider target. The integration is optional until you install the Gmail extras and set up OAuth credentials.

```bash
uv pip install --python .venv/bin/python -e ".[gmail]"
./.venv/bin/mailassist gmail-auth
```

Once authenticated, you can ask the bot to submit the draft upstream while still saving the local copy:

```bash
./.venv/bin/mailassist draft-thread \
  --thread-file data/threads/sample-thread.json \
  --submit-provider-draft
```

The local desktop UI is now the place where draft approvals happen, and accepted Gmail drafts can be created upstream with one click from that review panel. GitHub remains useful for source control, but not as the approval surface for live drafts.
