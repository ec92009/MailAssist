# Research

## Provider research

- Decide how thread ingestion should work for Gmail:
- direct API fetch
- IMAP fallback
- exported JSON/import pipeline
- Decide whether Outlook support should target Microsoft Graph draft creation first or a more generic IMAP/SMTP compatibility layer.
- Confirm what metadata must be preserved for provider-native drafts:
- recipients
- cc/bcc
- thread references
- quoted history
- labels or categories

## Prompting research

- Compare prompt formats for short transactional replies versus longer relationship-heavy email.
- Evaluate whether the local model should return plain body text only or a structured JSON output with subject/body/reasoning fields.
- Test whether revision instructions work better as an appended note or as a separate system-style section.

## Review-flow research

- Define the minimal local state machine for draft review:
- pending_review
- accepted
- rejected
- needs_revision
- Decide whether revisions create a new sibling draft or overwrite the previous draft record.
- Decide what the static viewer should show for rejected or superseded drafts.

## Publishing research

- Decide whether GitHub Pages should publish sanitized summaries only or full draft text.
- Evaluate adding a build-time redaction pass for emails, names, phone numbers, and signatures.
- Decide whether generated site artifacts should be committed manually or built automatically in CI from sanitized source bundles.
