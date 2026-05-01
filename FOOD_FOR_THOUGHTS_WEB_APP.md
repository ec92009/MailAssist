# Food for Thoughts — Web App

*Saved 2026-04-30 against `main` at `146b8c9` (v61.10). Parked, not committed to.*

A future-self note. The user is keeping PySide6 for now; this file captures the analysis so it does not have to be rebuilt from scratch when the question returns.

---

## Question

Would there be benefit in replacing the PySide6 desktop GUI with a web app served on `127.0.0.1`?

---

## Short Answer

**Yes, but mostly because of Windows packaging.** If shipping to Magali on Windows continues to be gated on a Parallels VM and PyInstaller, a web GUI converts that blocker into a non-issue. Every other benefit (architecture cleanup, simpler tests, eliminated subprocess tax, faster iteration) has a cheaper alternative if pursued individually.

The decision pivots on one question: **is Windows distribution going to stay painful?** If yes, the web rewrite pays for itself on packaging alone. If a Windows VM is on the way and a `.exe` ships shortly, the web rewrite is mostly costs.

---

## PySide6 Desktop (Current State)

**Pros**
- Already built and working; v61.10 is shipping today
- Native feel: dock, system tray, OS dialogs, keyboard shortcuts
- No network surface — process isolation, no auth tokens, no CSRF
- System tray icon is a real "MailAssist is watching" indicator
- First-run UX is "double-click `.app`"
- Provider plumbing (Gmail, Outlook, Ollama) already wired through it

**Cons**
- Windows packaging blocked on Parallels VM (TODO item 7)
- `gui/desktop.py` is a 3085-line single class; growing and hard to maintain
- Per-action `QProcess` startup tax — every bot action re-imports `mailassist`, re-auths providers, re-loads `.env`
- `tests/test_desktop_layout.py` is 1527 lines of offscreen Qt — slow and brittle because there is no smaller seam
- Mac signing/notarization deferred but eventually mandatory
- Rich-text signature editor locked to `QTextEdit`

---

## Web App (FastAPI / Flask on `127.0.0.1`)

**Pros**
- **One package, all OSes.** `uv tool install mailassist && mailassist serve` works identically on Windows, macOS, and Linux. No PyInstaller, no signing, no notarization, no Windows VM.
- Magali install collapses to "install, run, open browser"; `tools/magali-bootstrap.ps1` shrinks dramatically
- Long-lived server process holds provider auth and Ollama clients in memory — eliminates the per-action startup tax
- Forces architectural cleanup of the 3085-line megaclass into per-panel components (Settings, Bot Control, Recent Activity, Tone editors)
- HTTP/JSON test surface is faster, parallelizable, less brittle than offscreen Qt
- Faster UI iteration during the long tail of polish (browser refresh vs. Qt rebuild)
- OAuth flows are already browser-shaped — Outlook device-code and Gmail OAuth feel more natural in a real browser

**Cons**
- 1–2 weeks rewrite for parity, longer for full polish
- Rich-text signature editor needs replacement (TipTap or Quill — days of work, not hours)
- New security surface: bind to `127.0.0.1`, generate a per-launch auth token, set strict CORS, gate writes with CSRF
- First-run UX degrades to "server running, click this URL" (a small launcher window or printed URL is the typical mitigation)
- Loses native polish: dock, system menu, system tray, OS-native dialogs
- Browser notifications are a weaker "MailAssist is watching" affordance than a system tray icon
- New bug class: CORS, CSP, token expiry, browser-tab lifecycle, multiple-window state sync

---

## What Triggers Reopening This

Reconsider when **either**:

1. Windows packaging actually blocks a planned ship date (i.e., a Magali deployment slips because of `.exe` builds), or
2. The desktop megaclass becomes unworkable enough that "rewrite" beats "extract panels" — concretely, when a feature change in one panel routinely breaks unrelated tests in `test_desktop_layout.py`, or when the file pushes past ~5000 lines.

Until one of those triggers fires, PySide6 is the right call.

---

## If You Pursue It — Open Questions for a Real Migration Plan

This file is parked analysis, not an implementation plan. A follow-up plan would need to decide:

- **Framework**: FastAPI + HTMX (least JS, server-side rendering) vs. FastAPI + a JS framework (React/Vue) vs. Flask vs. Tauri-as-shell (web tech inside a native window — keeps dock/tray)
- **Bot action transport**: subprocess + SSE (preserve current isolation) vs. in-process + WebSocket (lower latency, harder to recover from a stuck Ollama)
- **Auth**: per-launch token + cookie vs. localhost-trust + CSRF only
- **Rich-text editor**: TipTap vs. Quill vs. ProseMirror — each has trade-offs around HTML output cleanliness
- **Migration sequencing**: ship web GUI alongside desktop for one release as opt-in, then deprecate
- **Fate of `tests/test_desktop_layout.py`**: delete with the desktop, or keep until the desktop is fully retired

---

## Cross-References

- `2026.04.30_Claude_Critique_2.md` (merged current critique: 3085-line megaclass, per-action `QProcess` tax, and architecture cleanup pointers)
- `TODO.md` item 7 (Windows packaging blocked on Parallels VM)
- `docs/magali-zoom-operator-script.md` (current install path that would simplify)
