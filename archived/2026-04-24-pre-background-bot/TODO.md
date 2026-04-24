# TODO

## Core bot

- Extend the thread schema to include `cc`, `bcc`, reply-to metadata, and quoted-history markers.
- Move the desktop GUI from `data/review-inbox.json` to the folder-based queue lifecycle:
  `bot_processed`, `gui_acquired`, `user_reviewed`, `provider_drafted`, `user_replied`.
- Define the per-email JSON contract for that lifecycle, including review outcome, selected candidate, edited body, provider IDs, and archive state.
- Add bot processing for `user_reviewed` items so selected drafts become provider drafts and move into `provider_drafted`.
- Replace the mock review inbox with provider-backed thread ingestion once Gmail fetch is ready.
- Make Gmail draft creation preserve recipients and reply threading metadata from the source thread.
- Add authenticated actions to the local GUI, starting with Gmail OAuth launch and connection-status checks.

## Gmail

- Validate Gmail OAuth in this repo with real credentials.
- Add inbox thread fetch so local JSON imports are optional rather than required.
- Decide how often local Gmail snapshots should be refreshed.

## Outlook

- Implement an Outlook provider using Microsoft Graph draft creation.
- Define a provider-neutral thread model that can represent both Gmail and Outlook conversation data cleanly.
- Decide whether Outlook should ship only after Gmail review/revision is stable.
- Wire Outlook connection setup into the local config GUI once the provider exists.

## Local UI

- Verify live incremental streaming behavior across the local Ollama models we expect to support, and add lightweight instrumentation if a model still flushes in one chunk.
- Add a clearer in-app status/state explanation for `urgent` vs `reply_needed`, since triage meaning now matters in the inbox table.
- Add a real archive/hidden-items workflow around checked rows so ignored and user-replied mail can be cleared efficiently without losing auditability.
- Add a draft-history view so revised versions can be compared locally.
- Decide whether the browser-served UI should stay as a fallback or be removed entirely now that the native desktop path is the main surface.

## Packaging

- Build a true standalone macOS `.app` or `.pkg` rather than the current project-environment launcher bundle.
- Add a Windows `.exe` and `.msi` packaging path for the PySide6 desktop app.
- Add GitHub Actions release jobs to build and publish macOS and Windows desktop artifacts.
