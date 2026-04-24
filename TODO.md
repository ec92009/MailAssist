# TODO

## Core bot

- Add a shared `VERSION` source and wire it into both CLI output and the local UI.
- Extend the thread schema to include `cc`, `bcc`, reply-to metadata, and quoted-history markers.
- Add a first-class review action flow so drafts can move between `pending_review`, `accepted`, `rejected`, and `needs_revision`.
- Make Gmail draft creation preserve recipients and reply threading metadata from the source thread.
- Decide whether revision notes should trigger in-place editing or full draft regeneration.
- Add authenticated actions to the local GUI, starting with Gmail OAuth launch and connection-status checks.

## Gmail

- Validate Gmail OAuth in this repo with real credentials.
- Add inbox thread fetch so local JSON imports are optional rather than required.
- Decide how often local Gmail snapshots should be refreshed.
- Store provider-side draft IDs and thread references more completely.

## Outlook

- Implement an Outlook provider using Microsoft Graph draft creation.
- Define a provider-neutral thread model that can represent both Gmail and Outlook conversation data cleanly.
- Decide whether Outlook should ship only after Gmail review/revision is stable.
- Wire Outlook connection setup into the local config GUI once the provider exists.

## Local UI

- Add filtering by provider, status, and thread in the draft review panel.
- Add a one-click action to submit an accepted draft to the active provider.
- Add a draft-history view so revised versions can be compared locally.
