#!/usr/bin/env python3

from __future__ import annotations

import plistlib
import shutil
import stat
from pathlib import Path

APP_NAME = "MailAssist"
BUNDLE_ID = "com.ecohen.mailassist"
SRC_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SRC_DIR.parent.parent
DIST_DIR = PROJECT_DIR / "dist"
APP_PATH = DIST_DIR / f"{APP_NAME}.app"
INSTALL_DIR = Path.home() / "Applications"
INSTALL_APP_PATH = INSTALL_DIR / f"{APP_NAME}.app"
ENTRY_MODULE = "mailassist.cli.main"
ICNS_PATH = PROJECT_DIR / "build" / "macos-release" / f"{APP_NAME}.icns"


def package_version() -> str:
    version_file = PROJECT_DIR / "VERSION"
    if not version_file.exists():
        return "0.0"
    return version_file.read_text(encoding="utf-8").strip()


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
        "CFBundleShortVersionString": package_version(),
        "CFBundleVersion": package_version(),
        "LSApplicationCategoryType": "public.app-category.productivity",
        "NSHighResolutionCapable": True,
    }
    info_path = APP_PATH / "Contents" / "Info.plist"
    with info_path.open("wb") as handle:
        plistlib.dump(info, handle)
    resources_dir.mkdir(parents=True, exist_ok=True)
    if ICNS_PATH.exists():
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
  exec -a "$APP_NAME" "$PROJECT_PYTHON" -m {ENTRY_MODULE} desktop-gui >>"$LOG_FILE" 2>&1
fi

UV_BIN="${{UV_BIN:-$(command -v uv || true)}}"
if [[ -n "$UV_BIN" ]]; then
  exec -a "$APP_NAME" "$UV_BIN" run --project "$PROJECT_DIR" python -m {ENTRY_MODULE} desktop-gui >>"$LOG_FILE" 2>&1
fi

/usr/bin/osascript -e 'display alert "MailAssist could not start" message "No project Python or uv executable was found." as critical'
exit 1
"""
    launcher.write_text(script, encoding="utf-8")
    current_mode = launcher.stat().st_mode
    launcher.chmod(current_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def build_app() -> Path:
    if APP_PATH.exists():
        shutil.rmtree(APP_PATH)
    resources_dir = APP_PATH / "Contents" / "Resources"
    macos_dir = APP_PATH / "Contents" / "MacOS"
    resources_dir.mkdir(parents=True, exist_ok=True)
    macos_dir.mkdir(parents=True, exist_ok=True)
    write_info_plist(resources_dir)
    write_launcher(macos_dir)
    (APP_PATH / "Contents" / "PkgInfo").write_text("APPL????", encoding="ascii")
    return APP_PATH


def install_app() -> Path:
    INSTALL_DIR.mkdir(parents=True, exist_ok=True)
    if INSTALL_APP_PATH.exists():
        shutil.rmtree(INSTALL_APP_PATH)
    shutil.copytree(APP_PATH, INSTALL_APP_PATH)
    return INSTALL_APP_PATH


def main() -> int:
    DIST_DIR.mkdir(parents=True, exist_ok=True)
    build_app()
    installed = install_app()
    print(installed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
