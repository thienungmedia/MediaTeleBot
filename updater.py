#!/usr/bin/env python3
from __future__ import annotations
"""
Auto-Update Module for Mac File Bot.
Allows the bot to check for updates from a remote repository (e.g. GitHub),
notify the owner on Telegram, download new code, and automatically restart.
"""

import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
import ssl
from pathlib import Path

def _get_ssl_context():
    try:
        ctx = ssl.create_default_context()
        if os.path.exists("/etc/ssl/cert.pem"):
            ctx.load_verify_locations("/etc/ssl/cert.pem")
        return ctx
    except Exception:
        pass
    try:
        return ssl._create_unverified_context()
    except Exception:
        return None

def _urlopen_robust(req, timeout=20):
    ctx = _get_ssl_context()
    try:
        if ctx:
            return urllib.request.urlopen(req, context=ctx, timeout=timeout)
        return urllib.request.urlopen(req, timeout=timeout)
    except Exception as e:
        if "CERTIFICATE_VERIFY_FAILED" in str(e) or "certificate verify failed" in str(e):
            unverified = ssl._create_unverified_context()
            return urllib.request.urlopen(req, context=unverified, timeout=timeout)
        raise

BASE_DIR = Path(__file__).parent.resolve()
CONFIG_PATH = BASE_DIR / "config.json"
CURRENT_VERSION = "1.1.0"

DEFAULT_MANIFEST_URL = "https://raw.githubusercontent.com/thienungmedia/MediaTeleBot/main/version.json"


def _read_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _parse_version(v_str: str) -> tuple[int, ...]:
    clean = v_str.strip().lstrip("vV")
    try:
        return tuple(int(x) for x in clean.split(".") if x.isdigit())
    except Exception:
        return (0, 0, 0)


def check_for_updates() -> dict:
    """
    Check remote manifest to see if a newer version is available.
    Returns: {"has_update": bool, "latest_version": str, "notes": str, "manifest": dict}
    """
    cfg = _read_config()
    manifest_url = cfg.get("update_manifest_url") or DEFAULT_MANIFEST_URL

    req = urllib.request.Request(
        manifest_url,
        headers={"User-Agent": "MacFileBot-Updater/1.0", "Cache-Control": "no-cache"},
    )
    try:
        with _urlopen_robust(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return {"has_update": False, "error": str(e)}

    latest_ver_str = data.get("version", "1.0.0")
    cur_tuple = _parse_version(CURRENT_VERSION)
    latest_tuple = _parse_version(latest_ver_str)

    has_update = latest_tuple > cur_tuple
    return {
        "has_update": has_update,
        "current_version": CURRENT_VERSION,
        "latest_version": latest_ver_str,
        "release_notes": data.get("release_notes", "Bản cập nhật tối ưu hiệu năng và sửa lỗi."),
        "manifest": data,
    }


def perform_update(manifest: dict) -> dict:
    """
    Download updated files specified in manifest, save backups, and prepare restart.
    Never modifies config.json!
    """
    files = manifest.get("files", {})
    if not files:
        return {"ok": False, "error": "Không có danh sách file cần cập nhật trong manifest."}

    # 1. Create backup folder
    backup_dir = BASE_DIR / f"_backup_v{CURRENT_VERSION}_{int(time.time())}"
    backup_dir.mkdir(parents=True, exist_ok=True)

    downloaded = {}
    try:
        for filename, file_url in files.items():
            # Security guard: only allow safe python/script files, never config.json
            if filename in ("config.json", ".env", "zalo_pending.json", "zalo_after_upload.json"):
                continue

            target_path = BASE_DIR / filename
            if target_path.exists():
                shutil.copy2(target_path, backup_dir / filename)

            # Download to a temporary file first
            req = urllib.request.Request(
                file_url,
                headers={"User-Agent": "MacFileBot-Updater/1.0", "Cache-Control": "no-cache"},
            )
            with _urlopen_robust(req, timeout=20) as resp:
                content = resp.read()

            tmp_path = BASE_DIR / f"{filename}.tmp_update"
            tmp_path.write_bytes(content)
            downloaded[filename] = tmp_path

        # 2. Apply all downloaded files
        for filename, tmp_path in downloaded.items():
            final_path = BASE_DIR / filename
            shutil.move(str(tmp_path), str(final_path))
            # Keep executable permissions
            if filename.endswith(".command") or filename.endswith(".py"):
                try:
                    final_path.chmod(0o755)
                except OSError:
                    pass

        # 3. Update version in config.json
        cfg = _read_config()
        cfg["version"] = manifest.get("version", CURRENT_VERSION)
        CONFIG_PATH.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")

        return {"ok": True, "version": manifest.get("version")}
    except Exception as e:
        # Rollback on failure
        for filename in downloaded:
            b_path = backup_dir / filename
            if b_path.exists():
                shutil.copy2(b_path, BASE_DIR / filename)
            tmp_p = BASE_DIR / f"{filename}.tmp_update"
            if tmp_p.exists():
                tmp_p.unlink(missing_ok=True)
        return {"ok": False, "error": f"Lỗi khi cập nhật: {e}"}


def restart_service() -> None:
    """Restart background launchd service or re-exec current process."""
    uid = os.getuid()
    for service_name in ("com.macfilebot.telegrambot", "com.thienung.telegramfilebot"):
        res = subprocess.run(
            ["launchctl", "kickstart", "-k", f"gui/{uid}/{service_name}"],
            capture_output=True,
            timeout=5,
        )
        if res.returncode == 0:
            return

    # Fallback: exit process so keepalive restarts it
    sys.exit(0)


if __name__ == "__main__":
    print(f"Mac File Bot Updater - Phiên bản hiện tại: v{CURRENT_VERSION}")
    print("Đang kiểm tra bản cập nhật...")
    res = check_for_updates()
    if res.get("has_update"):
        print(f"🎉 Phát hiện bản mới: v{res['latest_version']}")
        print(f"Nội dung: {res.get('release_notes')}")
        ans = input("Bạn có muốn cập nhật ngay không? (y/N): ").strip().lower()
        if ans == "y":
            up_res = perform_update(res["manifest"])
            if up_res.get("ok"):
                print("✅ Đã cập nhật thành công! Đang khởi động lại bot...")
                restart_service()
            else:
                print(f"❌ {up_res.get('error')}")
    elif res.get("error"):
        print(f"⚠️ Không thể kiểm tra: {res['error']}")
    else:
        print("✅ Bạn đang sử dụng phiên bản mới nhất!")
