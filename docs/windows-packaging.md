# Windows Packaging Notes

Magali is the north-star user, so Windows packaging matters more than polishing the Mac/Gmail sandbox once Outlook is proven.

## Recommended Path

Use a Windows build machine or Parallels VM for the first real package.

Initial pragmatic path:

1. Build a Windows executable from the Python/PySide app with PyInstaller.
2. Test the app locally on Windows with Ollama installed and Microsoft Graph auth configured.
3. Package the executable for install.
4. Sign the installer/package before handing it to a non-technical user.

## Package Format

MSIX is the preferred Windows packaging direction once the app is stable enough for distribution. Microsoft positions MSIX as the modern package format for desktop apps, with clean install/uninstall, app identity, update support, and enterprise deployment compatibility.

For very early internal testing, a zipped PyInstaller folder or unsigned installer can be acceptable only for the developer/operator. Do not hand an unsigned build to Magali as the normal path.

## Signing

Before sharing a Windows build outside the developer machine, decide how to sign it:

- Commercial code-signing certificate for a conventional installer.
- Azure Trusted Signing or another Microsoft-supported signing flow for MSIX/package signing.
- Self-signed certificate only for local VM testing, not for Magali.

Signing needs to match the package publisher identity. Timestamping should be enabled for signed packages so signatures survive certificate expiry.

## Parallels / VM Checklist

When a Windows VM is available:

1. Install Python supported by the project.
2. Install `uv`.
3. Clone `ec92009/MailAssist`.
4. Run `uv sync`.
5. Confirm `./.venv/Scripts/mailassist.exe desktop-gui` launches.
6. Install and validate Ollama for Windows.
7. Configure `.env` for Outlook/Microsoft 365.
8. Run `mailassist outlook-auth`.
9. Run `mailassist review-bot --action outlook-smoke-test --limit 5`.
10. Only after choosing a thread id, run the controlled draft smoke:

```powershell
mailassist review-bot --action outlook-smoke-test --thread-id <conversation-id> --create-draft
```

## Current Blocker

Windows packaging cannot be completed on the current Mac workspace alone. The next real step needs a Windows environment, likely Parallels, or another Windows build machine.

Primary Microsoft references:

- https://learn.microsoft.com/en-us/windows/msix/overview
- https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/packaging/
- https://learn.microsoft.com/en-us/windows/msix/package/sign-app-package-using-signtool
- https://learn.microsoft.com/en-us/windows/msix/package/signing-package-device-guard-signing
