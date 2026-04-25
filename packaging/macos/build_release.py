#!/usr/bin/env python3

from __future__ import annotations

import os
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer


APP_NAME = "MailAssist"
BUNDLE_ID = "com.ecohen.mailassist"
SRC_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SRC_DIR.parent.parent
VERSION = (PROJECT_DIR / "VERSION").read_text(encoding="utf-8").strip()
ICON_SVG = PROJECT_DIR / "assets" / "brand" / "mailassist_icon.svg"
BUILD_DIR = PROJECT_DIR / "build" / "macos-release"
DIST_DIR = PROJECT_DIR / "dist"
APP_PATH = DIST_DIR / f"{APP_NAME}.app"
RELEASE_DIR = DIST_DIR / f"{APP_NAME}-v{VERSION}-mac-gmail"
DMG_PATH = DIST_DIR / f"{APP_NAME}-v{VERSION}-mac-gmail.dmg"
ICONSET_DIR = BUILD_DIR / f"{APP_NAME}.iconset"
ICNS_PATH = BUILD_DIR / f"{APP_NAME}.icns"
ENTRY_SCRIPT = SRC_DIR / "pyinstaller_entry.py"


def render_icon(source_svg: Path, iconset_dir: Path) -> None:
    renderer = QSvgRenderer(str(source_svg))
    if not renderer.isValid():
        raise RuntimeError(f"Could not render SVG icon: {source_svg}")
    if iconset_dir.exists():
        shutil.rmtree(iconset_dir)
    iconset_dir.mkdir(parents=True, exist_ok=True)
    for size in (16, 32, 128, 256, 512):
        for scale in (1, 2):
            actual_size = size * scale
            image = QImage(actual_size, actual_size, QImage.Format.Format_ARGB32)
            image.fill(QColor(0, 0, 0, 0))
            painter = QPainter(image)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            renderer.render(painter)
            painter.end()
            suffix = "" if scale == 1 else "@2x"
            target = iconset_dir / f"icon_{size}x{size}{suffix}.png"
            if not image.save(str(target)):
                raise RuntimeError(f"Could not write icon PNG: {target}")


def build_icns() -> None:
    subprocess.run(["iconutil", "-c", "icns", str(ICONSET_DIR), "-o", str(ICNS_PATH)], check=True)


def run_pyinstaller() -> None:
    if APP_PATH.exists():
        shutil.rmtree(APP_PATH)
    subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--windowed",
            "--name",
            APP_NAME,
            "--icon",
            str(ICNS_PATH),
            "--osx-bundle-identifier",
            BUNDLE_ID,
            "--add-data",
            f"{PROJECT_DIR / 'assets'}:assets",
            "--add-data",
            f"{PROJECT_DIR / 'docs'}:docs",
            "--collect-all",
            "googleapiclient",
            "--collect-all",
            "google_auth_oauthlib",
            "--collect-all",
            "google.oauth2",
            str(ENTRY_SCRIPT),
        ],
        cwd=PROJECT_DIR,
        check=True,
    )


def patch_info_plist() -> None:
    plist_path = APP_PATH / "Contents" / "Info.plist"
    with plist_path.open("rb") as handle:
        info = plistlib.load(handle)
    info.update(
        {
            "CFBundleDisplayName": APP_NAME,
            "CFBundleIdentifier": BUNDLE_ID,
            "CFBundleShortVersionString": VERSION,
            "CFBundleVersion": VERSION,
            "LSApplicationCategoryType": "public.app-category.productivity",
            "LSMinimumSystemVersion": "12.0",
            "NSHighResolutionCapable": True,
        }
    )
    with plist_path.open("wb") as handle:
        plistlib.dump(info, handle)


def sign_app() -> None:
    subprocess.run(
        ["codesign", "--force", "--deep", "--sign", "-", str(APP_PATH)],
        check=True,
    )


def write_release_readme(target: Path) -> None:
    text = f"""# MailAssist v{VERSION} for Mac/Gmail

This preview build is for macOS with Gmail. Outlook and Windows are not included yet.

## Install

1. Install and start Ollama from https://ollama.com.
2. In Terminal, install at least one local model, for example:

   ```bash
   ollama pull gemma4:31b
   ```

3. Drag `MailAssist.app` to your Applications folder.
4. Open `MailAssist.app`.
5. If macOS blocks the preview build because it is not notarized yet, try opening it once, then use Apple menu > System Settings > Privacy & Security. In the Security section, choose Open or Open Anyway for MailAssist, confirm again, and enter your Mac login password if prompted. Apple says this override is available for about an hour after the blocked open attempt.
6. Follow the setup wizard.
7. For Gmail, use `setting_up_gmail_connection_for_MailAssist.pdf` to create/download your Google OAuth Desktop client JSON.

## Gmail Files

MailAssist stores local configuration here:

```text
~/Library/Application Support/MailAssist/
```

By default, place the Gmail OAuth client file here:

```text
~/Library/Application Support/MailAssist/secrets/gmail-client-secret.json
```

MailAssist creates the Gmail token beside it after the first Google sign-in:

```text
~/Library/Application Support/MailAssist/secrets/gmail-token.json
```

## What MailAssist Does

- Watches Gmail for messages that appear to need a reply.
- Uses your local Ollama model to classify and draft.
- Creates Gmail drafts for you to review.
- Never sends email.

## Logs

Use `View logs` in the app. Logs stay local under:

```text
~/Library/Application Support/MailAssist/data/bot-logs/
```

"""
    target.write_text(text, encoding="utf-8")


def prepare_release_folder() -> None:
    if RELEASE_DIR.exists():
        shutil.rmtree(RELEASE_DIR)
    RELEASE_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copytree(APP_PATH, RELEASE_DIR / f"{APP_NAME}.app")
    write_release_readme(RELEASE_DIR / "README_FIRST.txt")
    for pdf_name in ("setting_up_gmail_connection_for_MailAssist.pdf", "gmail_oauth_advanced.pdf"):
        source = PROJECT_DIR / "docs" / pdf_name
        if source.exists():
            shutil.copy2(source, RELEASE_DIR / pdf_name)


def create_dmg() -> None:
    if DMG_PATH.exists():
        DMG_PATH.unlink()
    subprocess.run(
        [
            "hdiutil",
            "create",
            "-volname",
            f"{APP_NAME} v{VERSION}",
            "-srcfolder",
            str(RELEASE_DIR),
            "-ov",
            "-format",
            "UDZO",
            str(DMG_PATH),
        ],
        check=True,
    )


def main() -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QGuiApplication.instance() or QGuiApplication([])
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    DIST_DIR.mkdir(parents=True, exist_ok=True)
    render_icon(ICON_SVG, ICONSET_DIR)
    build_icns()
    run_pyinstaller()
    patch_info_plist()
    sign_app()
    prepare_release_folder()
    create_dmg()
    print(DMG_PATH)
    app.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
