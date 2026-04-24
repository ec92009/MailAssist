# MailAssist

Local AI-assisted email drafting bot using Ollama and local models. `MailAssist` ingests email threads, composes proposed replies, saves drafts and execution logs locally, and can optionally submit drafts to Gmail. The generated artifacts can then be published through a static GitHub Pages viewer.

## Current docs

- [STRATEGY.md](~/Dev/MailAssist/STRATEGY.md): current product shape, workflow, and architecture
- [RESULTS.md](~/Dev/MailAssist/RESULTS.md): current implementation status, known gaps, and short-term conclusions
- [TODO.md](~/Dev/MailAssist/TODO.md): active follow-up work
- [REALISM.md](~/Dev/MailAssist/REALISM.md): safety, privacy, and provider-reality constraints
- [RESEARCH.md](~/Dev/MailAssist/RESEARCH.md): integration and product research backlog
- [SUMMARY.md](~/Dev/MailAssist/SUMMARY.md): high-level snapshot of where the project stands
- [ENVIRONMENT_SOP.md](~/Dev/MailAssist/ENVIRONMENT_SOP.md): workspace Python and package-management preferences
- [VERSIONING_SOP.md](~/Dev/MailAssist/VERSIONING_SOP.md): bot/viewer visible versioning rules
- [SHOW_ME_SOP.md](~/Dev/MailAssist/SHOW_ME_SOP.md): local/public viewer show-and-report workflow
- [docs/README.md](~/Dev/MailAssist/docs/README.md): static viewer notes

Use this `README` for setup and operational scripts. For decisions about workflow, safety, rollout, and product direction, prefer the docs above.

Project shorthand:

- `rscp` means: refresh docs, summarize the current conversation to `SUMMARY.md`, commit, and push.

---

## What this project does

- Accepts a normalized email thread payload from a local file or future provider sync
- Builds a response prompt for a local model running through Ollama
- Saves generated reply drafts to `data/drafts/`
- Saves execution logs to `data/logs/`
- Keeps the human in control of every draft: accept, reject, or revise
- Optionally submits approved drafts to Gmail
- Generates a static site snapshot in `site/` for GitHub Pages publishing

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
├── SHOW_ME_SOP.md                # Viewer show/share workflow
├── data/
│   ├── threads/                  # Source email thread JSON files
│   ├── drafts/                   # Saved generated draft JSON files
│   └── logs/                     # Saved execution log JSON files
├── site/                         # Generated static viewer output
├── docs/                         # Viewer documentation
├── src/mailassist/               # Bot package
└── .github/workflows/pages.yml   # GitHub Pages deployment
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

### 3. Create a sample draft locally

```bash
./.venv/bin/mailassist draft-thread --thread-file data/threads/sample-thread.json
```

### 4. Build the static viewer

```bash
./.venv/bin/mailassist build-site
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

---

## GitHub setup

When you are ready to sync with GitHub:

```bash
git remote add origin git@github.com:ec92009/MailAssist.git
git branch -M main
git add .
git commit -m "Initial MailAssist scaffold"
git push -u origin main
```

The Pages workflow publishes the generated `site/` directory once the repository exists and GitHub Pages is enabled for Actions.
