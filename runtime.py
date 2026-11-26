"""Shared platform, private storage and verified HTTPS helpers."""
from __future__ import annotations

import json
import os
import ssl
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

IS_MAC = sys.platform == "darwin"
IS_WINDOWS = sys.platform == "win32"
SOURCE_DIR = Path(__file__).resolve().parent
if IS_MAC:
    USER_DIR = Path.home() / "Library" / "Application Support" / "MacFileBot"
elif IS_WINDOWS:
    USER_DIR = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local")) / "MediaTeleBot"
else:
    USER_DIR = Path(os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share")) / "MediaTeleBot"

# Installed code and its existing state share USER_DIR. Source runs use the same
# per-user state, so credentials never need to live in the Git checkout.
BASE_DIR = Path(os.environ.get("MEDIATELEBOT_DATA_DIR") or USER_DIR).expanduser().resolve()
CONFIG_PATH = BASE_DIR / "config.json"


def read_config(path: Path = CONFIG_PATH) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    if not isinstance(data, dict):
        raise ValueError("config.json phải chứa một đối tượng JSON.")
    return data


def write_private_json(path: Path, data: dict) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as f:
        tmp = Path(f.name)
        try:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
            f.close()
            os.replace(tmp, path)
        finally:
            tmp.unlink(missing_ok=True)


class HTTPSRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urlsplit(newurl).scheme.lower() != "https":
            raise ValueError("Chuyển hướng sang kết nối không phải HTTPS.")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def open_https(req, timeout=20):
    url = req.full_url if isinstance(req, urllib.request.Request) else req
    if urlsplit(url).scheme.lower() != "https":
        raise ValueError("Chỉ hỗ trợ kết nối HTTPS.")
    ctx = ssl.create_default_context()
    if IS_MAC and Path("/etc/ssl/cert.pem").is_file():
        ctx.load_verify_locations("/etc/ssl/cert.pem")
    opener = urllib.request.build_opener(
        HTTPSRedirectHandler(), urllib.request.HTTPSHandler(context=ctx)
    )
    return opener.open(req, timeout=timeout)


def mounted_roots() -> list[Path]:
    if IS_WINDOWS:
        import ctypes
        mask = ctypes.windll.kernel32.GetLogicalDrives()
        return [Path(chr(65 + i) + ":\\") for i in range(26) if mask & (1 << i)]
    volumes = Path("/Volumes")
    try:
        return sorted(volumes.iterdir())
    except OSError:
        return []


def lock_instance(path: Path):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    handle = path.open("a+b")
    try:
        if IS_WINDOWS:
            import msvcrt
            if handle.seek(0, os.SEEK_END) == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        raise
    return handle


def edit_config(change, path: Path = CONFIG_PATH):
    """Serialize updates from the bot and local setup without clobbering other fields."""
    for attempt in range(50):
        try:
            handle = lock_instance(path.with_suffix(".lock"))
        except OSError:
            if attempt == 49:
                raise
            time.sleep(0.02)
        else:
            with handle:
                cfg = read_config(path)
                result = change(cfg)
                write_private_json(path, cfg)
                return result
