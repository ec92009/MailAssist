from __future__ import annotations

from pathlib import Path


def load_visible_version(root_dir: Path) -> str:
    version_file = root_dir / "VERSION"
    if version_file.exists():
        return version_file.read_text(encoding="utf-8").strip()
    try:
        from mailassist import __version__
    except ImportError:
        return "0.0"
    return __version__.removesuffix(".0")
