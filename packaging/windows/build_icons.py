#!/usr/bin/env python3

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer


SRC_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SRC_DIR.parent.parent
ICON_SVG = PROJECT_DIR / "assets" / "brand" / "mailassist_icon.svg"
ICON_PNG = PROJECT_DIR / "assets" / "brand" / "mailassist_icon_256.png"
ICON_ICO = PROJECT_DIR / "assets" / "brand" / "mailassist_icon.ico"


def render_icon(source_svg: Path, target_png: Path, target_ico: Path, *, size: int = 256) -> None:
    renderer = QSvgRenderer(str(source_svg))
    if not renderer.isValid():
        raise RuntimeError(f"Could not render SVG icon: {source_svg}")

    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(QColor(0, 0, 0, 0))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    renderer.render(painter)
    painter.end()

    target_png.parent.mkdir(parents=True, exist_ok=True)
    if not image.save(str(target_png)):
        raise RuntimeError(f"Could not write icon PNG: {target_png}")
    if not image.save(str(target_ico)):
        raise RuntimeError(f"Could not write icon ICO: {target_ico}")


def main() -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QGuiApplication([])
    render_icon(ICON_SVG, ICON_PNG, ICON_ICO)
    print(ICON_PNG)
    print(ICON_ICO)
    app.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
