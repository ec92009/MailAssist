# Summary

MailAssist is now framed as a local-first drafting assistant rather than an autonomous email bot. The current repo already has the basic skeleton for thread ingestion from disk, prompt generation through Ollama, local draft/log persistence, optional Gmail draft submission, and a local GUI for configuration and review.

This conversation established the first repo operating shape and then revised the product direction in an important way:

- the project docs were adapted from `~/Dev/trading` into MailAssist-specific docs for strategy, realism, research, results, todo tracking, environment setup, versioning, and local UI workflow
- Markdown links were normalized to `~`-style home-relative paths instead of explicit `/Users/ecohen/...` paths
- `rscp` is now a documented project shorthand meaning: refresh docs, summarize the current conversation to `SUMMARY.md`, commit, and push
- the local GUI now includes provider setup, Ollama checks, and draft review actions
- the old GitHub Pages/static viewer direction was intentionally scrapped because approvals need to happen in the local app
- draft green-light, red-light, needs-revision, and reset actions now live in the local UI rather than a public static site

The important constraints are now clear:

- draft, do not send
- keep the human approval loop explicit
- preserve a local audit trail
- prepare for Gmail first and Outlook second
- avoid publishing sensitive content blindly

Current repo status:

- local package scaffold is in place and installs cleanly
- the CLI works
- tests pass
- the local UI runs locally and is now the intended approval surface
- the old `build-site`/GitHub Pages path has been removed from the codebase
- the repo already has a configured GitHub remote at `ec92009/MailAssist`
- the repo now contains a local draft review panel backed by saved draft JSON records

The next practical milestone is a Gmail-first review workflow with better provider metadata, plus wiring accepted drafts cleanly into provider-native draft creation from the local UI.

Project workflow shorthand:

- `rscp` means: refresh docs, summarize the current conversation to `SUMMARY.md`, commit, and push.
