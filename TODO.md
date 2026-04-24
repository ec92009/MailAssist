# TODO

## Core bot

- Add a shared `VERSION` source and wire it into both CLI output and the static viewer.
- Extend the thread schema to include `cc`, `bcc`, reply-to metadata, and quoted-history markers.
- Add a first-class review action flow so drafts can move between `pending_review`, `accepted`, `rejected`, and `needs_revision`.
- Make Gmail draft creation preserve recipients and reply threading metadata from the source thread.
- Add a redact-before-publish mode for the static viewer.

## Gmail

- Validate Gmail OAuth in this repo with real credentials.
- Add inbox thread fetch so local JSON imports are optional rather than required.
- Decide how often local Gmail snapshots should be refreshed.
- Store provider-side draft IDs and thread references more completely.

## Outlook

- Implement an Outlook provider using Microsoft Graph draft creation.
- Define a provider-neutral thread model that can represent both Gmail and Outlook conversation data cleanly.
- Decide whether Outlook should ship only after Gmail review/revision is stable.

## Viewer

- Add filtering by provider, status, and thread.
- Add a detail page or expandable cards for draft history.
- Publish sanitized bundles that are safe for GitHub Pages.
- Decide whether the viewer should read a single snapshot file or versioned historical bundles.
