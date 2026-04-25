#!/usr/bin/env python3

from __future__ import annotations

import os
import plistlib
import random
import shutil
import stat
import subprocess
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer


APP_NAME = "MailAssist"
BUNDLE_ID = "com.ecohen.mailassist"
SRC_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SRC_DIR.parent.parent
VERSION = (PROJECT_DIR / "VERSION").read_text(encoding="utf-8").strip()
ICON_SVG = PROJECT_DIR / "assets" / "brand" / "mailassist_icon.svg"
BUILD_DIR = PROJECT_DIR / "build" / "macos"
DIST_DIR = PROJECT_DIR / "dist"
ICONSET_DIR = BUILD_DIR / f"{APP_NAME}.iconset"
ICNS_PATH = BUILD_DIR / f"{APP_NAME}.icns"
APP_PATH = DIST_DIR / f"{APP_NAME}.app"
INSTALL_DIR = Path("/Applications")
INSTALL_APP_PATH = INSTALL_DIR / f"{APP_NAME}.app"
LSREGISTER_PATH = Path(
    "/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister"
)


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


def build_icns(iconset_dir: Path, icns_path: Path) -> None:
    subprocess.run(
        ["iconutil", "-c", "icns", str(iconset_dir), "-o", str(icns_path)],
        check=True,
    )


def write_info_plist(resources_dir: Path) -> None:
    info = {
        "CFBundleDevelopmentRegion": "en",
        "CFBundleDisplayName": APP_NAME,
        "CFBundleExecutable": APP_NAME,
        "CFBundleIconFile": ICNS_PATH.name,
        "CFBundleIdentifier": BUNDLE_ID,
        "CFBundleInfoDictionaryVersion": "6.0",
        "CFBundleName": APP_NAME,
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": VERSION,
        "CFBundleVersion": VERSION,
        "LSApplicationCategoryType": "public.app-category.productivity",
        "LSMinimumSystemVersion": "12.0",
        "NSHighResolutionCapable": True,
    }
    info_path = APP_PATH / "Contents" / "Info.plist"
    with info_path.open("wb") as handle:
        plistlib.dump(info, handle)
    shutil.copy2(ICNS_PATH, resources_dir / ICNS_PATH.name)


def write_launcher(macos_dir: Path) -> None:
    launcher = macos_dir / APP_NAME
    script = f"""#!/bin/zsh
set -euo pipefail

APP_NAME={APP_NAME!r}
PROJECT_DIR={str(PROJECT_DIR)!r}
PROJECT_PYTHON="$PROJECT_DIR/.venv/bin/python"
LOG_FILE="${{TMPDIR:-/tmp}}/mailassist_gui.log"

cd "$PROJECT_DIR"

if [[ -x "$PROJECT_PYTHON" ]]; then
  exec -a "$APP_NAME" "$PROJECT_PYTHON" -m mailassist.cli.main desktop-gui >>"$LOG_FILE" 2>&1
fi

UV_BIN="${{UV_BIN:-$(command -v uv || true)}}"
if [[ -n "$UV_BIN" ]]; then
  exec -a "$APP_NAME" "$UV_BIN" run --project "$PROJECT_DIR" python -m mailassist.cli.main desktop-gui >>"$LOG_FILE" 2>&1
fi

/usr/bin/osascript -e 'display alert "MailAssist could not start" message "No project Python or uv executable was found." as critical'
exit 1
"""
    launcher.write_text(script, encoding="utf-8")
    current_mode = launcher.stat().st_mode
    launcher.chmod(current_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def build_app() -> None:
    if APP_PATH.exists():
        shutil.rmtree(APP_PATH)
    resources_dir = APP_PATH / "Contents" / "Resources"
    macos_dir = APP_PATH / "Contents" / "MacOS"
    resources_dir.mkdir(parents=True, exist_ok=True)
    macos_dir.mkdir(parents=True, exist_ok=True)
    write_info_plist(resources_dir)
    write_launcher(macos_dir)
    (APP_PATH / "Contents" / "PkgInfo").write_text("APPL????", encoding="ascii")


def install_app() -> Path:
    if not os.access(INSTALL_DIR, os.W_OK):
        raise PermissionError(f"{INSTALL_DIR} is not writable by this shell.")
    if INSTALL_APP_PATH.exists():
        shutil.rmtree(INSTALL_APP_PATH)
    shutil.copytree(APP_PATH, INSTALL_APP_PATH)
    return INSTALL_APP_PATH


def register_app() -> None:
    if not LSREGISTER_PATH.exists():
        return
    subprocess.run(
        [str(LSREGISTER_PATH), "-f", str(INSTALL_APP_PATH)],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def sync_dock_entry() -> None:
    if os.uname().sysname != "Darwin":
        return

    dock_plist_path = Path.home() / "Library" / "Preferences" / "com.apple.dock.plist"
    if not dock_plist_path.exists():
        return

    with dock_plist_path.open("rb") as handle:
        dock_data = plistlib.load(handle)

    target_url = INSTALL_APP_PATH.resolve().as_uri() + "/"
    updated = False
    for item in dock_data.get("persistent-apps", []):
        tile_data = item.get("tile-data", {})
        file_data = tile_data.get("file-data", {})
        file_url = file_data.get("_CFURLString")
        if tile_data.get("file-label") != APP_NAME and not (
            isinstance(file_url, str) and f"{APP_NAME}.app" in file_url
        ):
            continue
        file_data["_CFURLString"] = target_url
        file_data["_CFURLStringType"] = 15
        tile_data["bundle-identifier"] = BUNDLE_ID
        tile_data["file-data"] = file_data
        tile_data["file-label"] = APP_NAME
        item["tile-data"] = tile_data
        updated = True

    if not updated:
        dock_data.setdefault("persistent-apps", []).append(
            {
                "GUID": random.randint(1, 2**32 - 1),
                "tile-data": {
                    "bundle-identifier": BUNDLE_ID,
                    "dock-extra": False,
                    "file-data": {
                        "_CFURLString": target_url,
                        "_CFURLStringType": 15,
                    },
                    "file-label": APP_NAME,
                    "file-type": 41,
                    "is-beta": False,
                },
                "tile-type": "file-tile",
            }
        )
        updated = True

    if updated:
        with dock_plist_path.open("wb") as handle:
            plistlib.dump(dock_data, handle)
        subprocess.run(["killall", "Dock"], check=False)


def main() -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QGuiApplication([])
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    DIST_DIR.mkdir(parents=True, exist_ok=True)

    render_icon(ICON_SVG, ICONSET_DIR)
    build_icns(ICONSET_DIR, ICNS_PATH)
    build_app()
    install_app()
    register_app()
    sync_dock_entry()

    print(INSTALL_APP_PATH)
    app.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
