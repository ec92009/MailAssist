# TODO

## Core bot

- Add a shared `VERSION` source and wire it into both CLI output and the local UI.
- Extend the thread schema to include `cc`, `bcc`, reply-to metadata, and quoted-history markers.
- Replace the mock review inbox with provider-backed thread ingestion once Gmail fetch is ready.
- Make Gmail draft creation preserve recipients and reply threading metadata from the source thread.
- Decide whether revision notes should trigger in-place editing or full draft regeneration.
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

- Extend queue filtering beyond the mock inbox so provider-fetched threads can be triaged the same way.
- Let the operator request another set of alternative drafts without losing the currently edited candidate.
- Add a draft-history view so revised versions can be compared locally.
- Replace the transitional browser-served UI once the PySide6 desktop workflow reaches feature parity.

## Packaging

- Build a true standalone macOS `.app` or `.pkg` rather than the current project-environment launcher bundle.
- Add a Windows `.exe` and `.msi` packaging path for the PySide6 desktop app.
- Add GitHub Actions release jobs to build and publish macOS and Windows desktop artifacts.
