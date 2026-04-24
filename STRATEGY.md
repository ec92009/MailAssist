# Strategy

## Product goal

Build a local-first email drafting assistant that helps the user respond faster without giving the model autonomous send authority.

## Core workflow

1. Ingest an email thread from a provider sync or a normalized local JSON file.
2. Build a drafting prompt that includes the latest thread context and any user revision guidance.
3. Ask a local model through Ollama to compose the reply.
4. Save the proposed draft and the execution log locally.
5. Let the user accept, reject, or request revisions.
6. On approval, create a provider-native draft in Gmail first and Outlook later.
7. Publish local artifacts to a static viewer for auditability and remote visibility.

## Architecture direction

### Local-first orchestration

- Keep the orchestration process local.
- Treat Ollama as the default model gateway.
- Preserve thread payloads, prompts, draft bodies, and run metadata on disk in a simple inspectable format.

### Provider boundary

- Use a provider interface so Gmail and Outlook can share the same orchestration flow.
- Keep provider-specific auth and draft-write logic out of the core drafting path.
- Start with Gmail draft creation only; do not send messages automatically.

### Human review loop

- The assistant proposes drafts.
- The user decides whether to accept, reject, or revise.
- Revision requests should become first-class inputs, not ad hoc prompt edits.

### Static visibility

- The bot should publish snapshots of local drafts and logs into a static site.
- GitHub Pages is the simplest first public viewer because it keeps hosting cheap and versioned.
- The viewer is a reporting surface, not a control plane.

## Near-term implementation posture

- Normalize around JSON input/output before adding provider-sync complexity.
- Keep dependencies light while the architecture is still moving.
- Prefer explicit files and small modules over framework-heavy abstractions.
- Delay Outlook implementation until the Gmail draft path is stable.
