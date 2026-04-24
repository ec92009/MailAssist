# Realism

## Non-negotiable constraints

- The model may draft messages, but it must not send them autonomously.
- Provider writes should default to draft creation, not delivery.
- Local artifacts can contain sensitive email content, so the repo should never commit private draft/log files by accident.
- Prompting must avoid inventing commitments, dates, facts, or attachments that do not exist in the source thread.

## Operational reality

- Ollama quality will vary by local model size and machine resources.
- Gmail and Outlook APIs will impose auth, token, and quota constraints that do not exist in local-only testing.
- Real inboxes include signatures, forwarded chains, formatting noise, and ambiguous requests; the normalized thread format needs to handle that cleanly.
- A useful audit trail matters as much as raw generation quality because the user needs to understand why a draft exists.

## Approval posture

- Draft locally first.
- Let the user review every proposed response.
- Record revision instructions explicitly so later draft iterations stay explainable.
- Treat acceptance as permission to create a provider draft, not permission to send.

## Privacy posture

- Assume local logs and drafts may contain personal or confidential information.
- Keep secrets under a non-committed path such as `secrets/`.
- Keep generated local content out of git unless the user explicitly wants to publish a sanitized snapshot.
- Prefer a future redaction layer before public GitHub Pages publishing if real email content will be displayed.
