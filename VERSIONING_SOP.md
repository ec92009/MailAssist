# Versioning SOP

- This versioning scheme is for the MailAssist bot and its static viewer.
- Apply it when either the drafting flow, provider integrations, review UX, or GitHub Pages viewer changes in a user-visible way.
- Do not treat local experiment runs, sample thread changes, or one-off generated draft/log files as automatic version bumps by themselves.
- Use visible app versions in the form `vX.Y`.
- Use bare `X.Y` in repo metadata such as a top-level `VERSION` file.
- `X` is the number of days since `2026-04-24`.
- `Y` increments with each user-visible build on that same day.
- The CLI and the viewer should read from the same shared version source once version wiring is added.
- At the end of each bot/viewer-facing cycle, report:
- localhost viewer URL
- LAN viewer URL
- GitHub Pages viewer URL
- the exact new version to expect on those surfaces
