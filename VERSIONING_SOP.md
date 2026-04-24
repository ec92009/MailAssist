# Versioning SOP

- This versioning scheme is for the MailAssist bot, local GUI, and any future packaged desktop build.
- Apply it when the drafting flow, provider integrations, review UX, or any other user-visible MailAssist surface changes.
- Do not treat local experiment runs, sample thread changes, or one-off generated draft/log files as automatic version bumps by themselves.
- Use visible app versions in the form `vX.Y`.
- Use bare `X.Y` in repo metadata such as a top-level `VERSION` file.
- `X` is the number of days since `2026-02-28`.
- `Y` increments with each user-visible build on that same day.
- The CLI and GUI should read from the same shared version source.
- At the end of each bot/viewer-facing cycle, report:
- localhost GUI URL
- LAN GUI URL when available
- GitHub Pages URL only if a live viewer is actually active
- the exact new version to expect on those active surfaces
