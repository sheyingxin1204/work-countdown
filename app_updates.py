"""GitHub Release discovery and verified asset downloads.

Keeping release/network code out of the Tk window class makes it possible to
test update parsing and file replacement preparation without creating a GUI.
The caller still owns the background thread and the user-facing dialogs.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import urllib.request
from pathlib import Path
from typing import Any, Callable

MAX_DOWNLOAD_BYTES = 200 * 1024 * 1024


def version_tuple(value: Any) -> tuple[int, ...]:
    parts = re.findall(r"\d+", str(value))
    return tuple(int(part) for part in parts) or (0,)


def latest_release_url(repository: str) -> str:
    return f"https://github.com/{repository}/releases/latest"


def parse_release_payload(
    payload: Any,
    repository: str,
    current_version: str,
) -> tuple[dict[str, Any], bool]:
    """Extract the newest EXE asset and compare it with the running version."""

    if not isinstance(payload, dict):
        raise ValueError("Release 响应必须是 JSON 对象")
    latest_tag = str(payload.get("tag_name", "")).strip()
    if not latest_tag:
        raise ValueError("Release 没有可用的版本号")
    release_url = str(payload.get("html_url") or latest_release_url(repository))
    assets = payload.get("assets") or []
    asset = next(
        (
            item
            for item in assets
            if isinstance(item, dict) and str(item.get("name", "")).lower().endswith(".exe")
        ),
        None,
    )
    release_info = {
        "tag": latest_tag,
        "url": release_url,
        "asset_url": str(asset.get("browser_download_url")) if asset else None,
        "asset_name": str(asset.get("name")) if asset else None,
        "digest": str(asset.get("digest") or "") if asset else "",
    }
    return release_info, version_tuple(latest_tag) > version_tuple(current_version)


def fetch_latest_release(
    repository: str,
    current_version: str,
    app_name: str,
    timeout: float = 8,
    opener: Callable[..., Any] | None = None,
) -> tuple[dict[str, Any], bool]:
    """Fetch and parse the latest GitHub Release metadata."""

    api_url = f"https://api.github.com/repos/{repository}/releases/latest"
    request = urllib.request.Request(
        api_url,
        headers={"Accept": "application/vnd.github+json", "User-Agent": f"{app_name}/{current_version}"},
    )
    open_url = opener or urllib.request.urlopen
    with open_url(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return parse_release_payload(payload, repository, current_version)


def download_release_asset(
    release_info: dict[str, Any],
    update_dir: str | Path,
    app_name: str,
    app_version: str,
    timeout: float = 30,
    max_bytes: int = MAX_DOWNLOAD_BYTES,
    opener: Callable[..., Any] | None = None,
) -> tuple[Path, str]:
    """Download one EXE into a temporary file, verify SHA-256, then publish it."""

    asset_url = str(release_info.get("asset_url") or "").strip()
    if not asset_url:
        raise ValueError("Release 没有可下载的 EXE 文件")
    update_path = Path(update_dir)
    update_path.mkdir(parents=True, exist_ok=True)
    safe_tag = re.sub(r"[^A-Za-z0-9._-]+", "-", str(release_info.get("tag", "latest")))
    target_path = update_path / f"BanClock-{safe_tag}.exe"
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", suffix=".download", dir=update_path, delete=False
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            request = urllib.request.Request(
                asset_url,
                headers={
                    "Accept": "application/octet-stream",
                    "User-Agent": f"{app_name}/{app_version}",
                },
            )
            digest = hashlib.sha256()
            total_size = 0
            open_url = opener or urllib.request.urlopen
            with open_url(request, timeout=timeout) as response:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    total_size += len(chunk)
                    if total_size > max_bytes:
                        raise ValueError("更新文件超过 200 MB，已停止下载")
                    digest.update(chunk)
                    temporary_file.write(chunk)
        actual_digest = digest.hexdigest().lower()
        expected_digest = str(release_info.get("digest", "")).replace("sha256:", "").lower()
        if expected_digest and actual_digest != expected_digest:
            raise ValueError("下载文件校验失败，文件可能已损坏")
        os.replace(temporary_path, target_path)
        temporary_path = None
        return target_path, actual_digest
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass
