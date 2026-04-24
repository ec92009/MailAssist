# Show Me SOP

- When the user asks to "show me" the web app, default to building the local static viewer from `site/`.
- If needed, serve the generated `site/` directory locally with a simple static server.
- If the user also wants the public site updated, push the committed `main` branch to GitHub so GitHub Pages can deploy the latest published snapshot.
- Report all three viewer URLs in the handoff:
- localhost URL
- LAN URL
- public GitHub Pages URL
- Also report the exact visible UI version the user should expect on those surfaces once version wiring is in place.
- Be explicit about scope: uncommitted local changes are not part of the GitHub Pages deploy unless they are committed first.
