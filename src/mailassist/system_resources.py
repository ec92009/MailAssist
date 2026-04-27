from __future__ import annotations

import ctypes
import os
import subprocess
import sys
from typing import Any


def format_size(size_value: object) -> str:
    try:
        size = float(size_value)
    except (TypeError, ValueError):
        return ""
    if size <= 0:
        return ""
    units = ("B", "KB", "MB", "GB", "TB")
    unit_index = 0
    while size >= 1000 and unit_index < len(units) - 1:
        size /= 1000
        unit_index += 1
    if unit_index == 0:
        return f"{int(size)} {units[unit_index]}"
    return f"{size:.1f} {units[unit_index]}"


def model_size_bytes(model_detail: dict[str, Any]) -> int | None:
    try:
        size = int(float(model_detail.get("size")))
    except (TypeError, ValueError):
        return None
    if size <= 0:
        return None
    return size


def model_name(model_detail: dict[str, Any]) -> str:
    return str(model_detail.get("name") or model_detail.get("model") or "").strip()


def loaded_model_memory_bytes(
    loaded_model_details: list[dict[str, Any]],
    installed_model_details: list[dict[str, Any]] | None = None,
) -> int:
    installed_sizes = {
        name: size
        for item in installed_model_details or []
        if (name := model_name(item)) and (size := model_size_bytes(item)) is not None
    }
    total = 0
    for item in loaded_model_details:
        name = model_name(item)
        size = model_size_bytes(item)
        if size is None and name:
            size = installed_sizes.get(name)
        if size:
            total += size
    return total


def effective_available_memory_bytes(
    available_memory_bytes: int | None,
    loaded_model_details: list[dict[str, Any]] | None = None,
    installed_model_details: list[dict[str, Any]] | None = None,
    total_memory_bytes: int | None = None,
) -> int | None:
    if not available_memory_bytes or available_memory_bytes <= 0:
        return None
    effective = available_memory_bytes + loaded_model_memory_bytes(
        loaded_model_details or [],
        installed_model_details,
    )
    if total_memory_bytes and total_memory_bytes > 0:
        effective = min(effective, total_memory_bytes)
    return effective


def _memory_from_sysconf() -> tuple[int | None, int | None]:
    if not hasattr(os, "sysconf"):
        return None, None
    try:
        page_size = int(os.sysconf("SC_PAGE_SIZE"))
    except (OSError, ValueError):
        return None, None
    total = None
    available = None
    for key, target in (("SC_PHYS_PAGES", "total"), ("SC_AVPHYS_PAGES", "available")):
        try:
            pages = int(os.sysconf(key))
        except (OSError, ValueError):
            continue
        if pages <= 0:
            continue
        value = pages * page_size
        if target == "total":
            total = value
        else:
            available = value
    return available, total


def _memory_from_windows_api() -> tuple[int | None, int | None]:
    class MemoryStatusEx(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    status = MemoryStatusEx()
    status.dwLength = ctypes.sizeof(status)
    try:
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):  # type: ignore[attr-defined]
            return None, None
    except (AttributeError, OSError):
        return None, None
    return int(status.ullAvailPhys), int(status.ullTotalPhys)


def _memory_from_macos_vm_stat() -> tuple[int | None, int | None]:
    try:
        total_output = subprocess.run(
            ["sysctl", "-n", "hw.memsize"],
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        )
        total = int(total_output.stdout.strip())
    except (OSError, subprocess.SubprocessError, ValueError):
        total = None
    try:
        vm_output = subprocess.run(
            ["vm_stat"],
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return None, total

    page_size = 4096
    pages: dict[str, int] = {}
    for line in vm_output.stdout.splitlines():
        if "page size of" in line:
            parts = [part for part in line.replace(".", "").split() if part.isdigit()]
            if parts:
                page_size = int(parts[0])
            continue
        if ":" not in line:
            continue
        label, value = line.split(":", 1)
        try:
            pages[label.strip()] = int(value.strip().strip("."))
        except ValueError:
            continue
    available_pages = (
        pages.get("Pages free", 0)
        + pages.get("Pages inactive", 0)
        + pages.get("Pages speculative", 0)
    )
    available = available_pages * page_size if available_pages > 0 else None
    return available, total


def system_memory_snapshot() -> tuple[int | None, int | None]:
    if sys.platform == "win32":
        return _memory_from_windows_api()
    if sys.platform == "darwin":
        available, total = _memory_from_macos_vm_stat()
        if available or total:
            return available, total
    return _memory_from_sysconf()


def recommended_model_names(
    model_details: list[dict[str, Any]],
    available_memory_bytes: int | None,
    loaded_model_details: list[dict[str, Any]] | None = None,
) -> tuple[list[str], list[str]]:
    if not available_memory_bytes or available_memory_bytes <= 0:
        return [], []
    effective_memory_bytes = effective_available_memory_bytes(
        available_memory_bytes,
        loaded_model_details,
        model_details,
    )
    if not effective_memory_bytes:
        return [], []
    safe_model_bytes = effective_memory_bytes * 0.75
    loaded_names = {
        name
        for item in loaded_model_details or []
        if (name := model_name(item))
    }
    known_models = [
        (str(item.get("name", "")).strip(), size)
        for item in model_details
        if (size := model_size_bytes(item)) is not None
    ]
    recommended = [name for name, size in known_models if name and (name in loaded_names or size <= safe_model_bytes)]
    oversized = [name for name, size in known_models if name and name not in loaded_names and size > safe_model_bytes]
    return recommended, oversized


def _format_model_name_list(names: list[str], *, limit: int = 3) -> str:
    visible = names[:limit]
    hidden_count = max(0, len(names) - len(visible))
    if hidden_count:
        visible.append(f"{hidden_count} more")
    return ", ".join(visible)


def memory_recommendation_message(
    model_details: list[dict[str, Any]],
    available_memory_bytes: int | None,
    total_memory_bytes: int | None,
    loaded_model_details: list[dict[str, Any]] | None = None,
) -> str:
    if not available_memory_bytes:
        return ""
    memory_text = format_size(available_memory_bytes)
    total_text = format_size(total_memory_bytes)
    memory_part = f"{memory_text} available"
    if total_text:
        memory_part = f"{memory_part} of {total_text} RAM"
    loaded_bytes = loaded_model_memory_bytes(loaded_model_details or [], model_details)
    if loaded_bytes:
        effective_memory = effective_available_memory_bytes(
            available_memory_bytes,
            loaded_model_details,
            model_details,
            total_memory_bytes,
        )
        loaded_part = f", including {format_size(loaded_bytes)} already used by loaded Ollama model(s)"
        if effective_memory:
            loaded_part = f"{loaded_part}; effective model budget starts from {format_size(effective_memory)}"
        memory_part = f"{memory_part}{loaded_part}"
    recommended, oversized = recommended_model_names(
        model_details,
        available_memory_bytes,
        loaded_model_details,
    )
    if recommended:
        return (
            f"System memory: {memory_part}. Recommended installed model(s): "
            f"{_format_model_name_list(recommended)}."
        )
    if oversized:
        return (
            f"System memory: {memory_part}. None of the installed models look small enough for "
            "the RAM currently available."
        )
    return f"System memory: {memory_part}. Install a small local model before drafting."
