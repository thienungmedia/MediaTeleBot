#!/usr/bin/env python3
from __future__ import annotations
"""
install_core.py - Trình cài đặt chuyên sâu MacFileBot vào hệ thống macOS.
Cài đặt trực tiếp vào: ~/Library/Application Support/MacFileBot
Đảm bảo 100% chạy ngầm native 24/7 không phụ thuộc Terminal hay thư mục Downloads.
"""

import json
import os
import shutil
import ssl
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

def get_ssl_context():
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

SOURCE_DIR = Path(__file__).parent.resolve()
TARGET_DIR = Path.home() / "Library" / "Application Support" / "MacFileBot"
LAUNCH_AGENTS_DIR = Path.home() / "Library" / "LaunchAgents"
PLIST_NAME = "com.macfilebot.telegrambot"
PLIST_PATH = LAUNCH_AGENTS_DIR / f"{PLIST_NAME}.plist"

REQUIRED_FILES = [
    "bot.py",
    "safe_fs.py",
    "nl_engine.py",
    "llm_intent.py",
    "zalo_sender.py",
    "updater.py",
    "version.json",
    "no_delete_guard.py",
    "KhoiDongLai.command",
    "DoiThuMucDrive.command",
    "CapNhat.command",
    "GoCaiDat.command",
    "KiemTraLoi.command",
]


def find_best_python() -> str:
    candidates = [
        "/Library/Frameworks/Python.framework/Versions/3.14/bin/python3",
        "/Library/Frameworks/Python.framework/Versions/3.13/bin/python3",
        "/Library/Frameworks/Python.framework/Versions/3.12/bin/python3",
        "/Library/Frameworks/Python.framework/Versions/3.11/bin/python3",
        "/Library/Frameworks/Python.framework/Versions/3.10/bin/python3",
        "/opt/homebrew/bin/python3",
        "/usr/local/bin/python3",
        "/usr/bin/python3",
        sys.executable,
    ]
    for p in candidates:
        if p and os.path.exists(p) and os.access(p, os.X_OK):
            return p
    return sys.executable or "/usr/bin/python3"


def verify_telegram_token(token: str) -> dict:
    token = token.strip()
    if not token:
        return {"ok": False, "error": "Token đang để trống"}
    url = f"https://api.telegram.org/bot{token}/getMe"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "MacFileBot-Installer/1.0"})
        ctx = get_ssl_context()
        opener = urllib.request.urlopen(req, context=ctx, timeout=10) if ctx else urllib.request.urlopen(req, timeout=10)
        with opener as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data.get("ok"):
                return {"ok": True, "result": data.get("result", {})}
            return {"ok": False, "error": data.get("description", "Token không hợp lệ")}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def install(bot_token: str, gemini_key: str = "", gdrive_folder: str = "PRODUCTION") -> dict:
    bot_token = bot_token.strip()
    gemini_key = gemini_key.strip()
    gdrive_folder = gdrive_folder.strip() or "PRODUCTION"

    # 1. Kiểm tra Token
    token_check = verify_telegram_token(bot_token)
    if not token_check["ok"]:
        return {"ok": False, "error": f"Lỗi xác thực Bot Token: {token_check['error']}"}

    bot_info = token_check["result"]
    bot_username = bot_info.get("username", "")

    # 2. Tạo thư mục đích an toàn sâu trong máy (~/Library/Application Support/MacFileBot)
    TARGET_DIR.mkdir(parents=True, exist_ok=True)
    LAUNCH_AGENTS_DIR.mkdir(parents=True, exist_ok=True)

    # 3. Sao chép toàn bộ code và tài nguyên vào TARGET_DIR
    for fname in REQUIRED_FILES:
        src = SOURCE_DIR / fname
        if src.exists():
            dst = TARGET_DIR / fname
            shutil.copy2(src, dst)
            try:
                os.chmod(dst, 0o755)
            except Exception:
                pass

    # Xoá cờ kiểm duyệt bảo mật của macOS tại thư mục đích
    subprocess.run(["/usr/bin/xattr", "-dr", "com.apple.quarantine", str(TARGET_DIR)], capture_output=True)

    # 4. Ghi file config.json tại TARGET_DIR
    sys.path.insert(0, str(TARGET_DIR))
    try:
        import safe_fs
        cfg = safe_fs._read_json(TARGET_DIR / "config.json")
    except Exception:
        cfg = {}

    cfg["bot_token"] = bot_token
    cfg["gemini_api_key"] = gemini_key
    cfg["gemini_model"] = "gemini-3.1-flash-lite"
    cfg["owner_id"] = None
    cfg["chat_id"] = None
    cfg["username"] = ""
    if "last_update_id" not in cfg:
        cfg["last_update_id"] = 0

    try:
        with open(TARGET_DIR / "config.json", "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
        os.chmod(TARGET_DIR / "config.json", 0o600)
    except Exception as e:
        return {"ok": False, "error": f"Không thể ghi config.json: {e}"}

    # Cập nhật thư mục upload mặc định qua safe_fs
    try:
        import safe_fs
        safe_fs.CONFIG_PATH = TARGET_DIR / "config.json"
        safe_fs.BASE_DIR = TARGET_DIR
        res_folder = safe_fs.set_default_gdrive_folder(gdrive_folder)
        folder_display = res_folder.get("folder_name", gdrive_folder)
    except Exception:
        folder_display = gdrive_folder

    # 5. Tạo LaunchAgent plist
    python_bin = find_best_python()
    plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{PLIST_NAME}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{python_bin}</string>
        <string>{TARGET_DIR}/bot.py</string>
    </array>
    <key>WorkingDirectory</key>
    <string>{TARGET_DIR}</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>{TARGET_DIR}/bot_service.log</string>
    <key>StandardErrorPath</key>
    <string>{TARGET_DIR}/bot_service.err.log</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/Library/Frameworks/Python.framework/Versions/Current/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
        <key>HOME</key>
        <string>{Path.home()}</string>
        <key>PYTHONUNBUFFERED</key>
        <string>1</string>
    </dict>
</dict>
</plist>
"""
    try:
        PLIST_PATH.write_text(plist_content, encoding="utf-8")
        os.chmod(PLIST_PATH, 0o644)
    except Exception as e:
        return {"ok": False, "error": f"Không thể tạo LaunchAgent plist: {e}"}

    # 6. Kích hoạt dịch vụ chạy ngầm
    uid = os.getuid()
    # Dừng tiến trình cũ
    subprocess.run(["launchctl", "bootout", f"gui/{uid}/{PLIST_NAME}"], capture_output=True)
    subprocess.run(["launchctl", "bootout", f"gui/{uid}", str(PLIST_PATH)], capture_output=True)
    subprocess.run(["launchctl", "unload", "-w", str(PLIST_PATH)], capture_output=True)
    subprocess.run(["pkill", "-f", f"{TARGET_DIR}/bot.py"], capture_output=True)
    time.sleep(0.5)

    # Nạp và khởi chạy mới bằng cả API modern lẫn legacy
    subprocess.run(["launchctl", "load", "-w", str(PLIST_PATH)], capture_output=True)
    subprocess.run(["launchctl", "bootstrap", f"gui/{uid}", str(PLIST_PATH)], capture_output=True)
    subprocess.run(["launchctl", "enable", f"gui/{uid}/{PLIST_NAME}"], capture_output=True)
    subprocess.run(["launchctl", "kickstart", "-k", "-p", f"gui/{uid}/{PLIST_NAME}"], capture_output=True)

    # Chờ 1.5 giây và kiểm tra xem bot đã thực sự chạy chưa
    time.sleep(1.5)
    is_running = False
    chk = subprocess.run(["launchctl", "print", f"gui/{uid}/{PLIST_NAME}"], capture_output=True, text=True)
    if "state = running" in chk.stdout or "pid = " in chk.stdout:
        is_running = True

    return {
        "ok": True,
        "bot_username": bot_username,
        "bot_name": bot_info.get("first_name", ""),
        "target_dir": str(TARGET_DIR),
        "is_running": is_running,
        "folder": folder_display,
        "python": python_bin,
    }


def get_status() -> dict:
    uid = os.getuid()
    chk = subprocess.run(["launchctl", "print", f"gui/{uid}/{PLIST_NAME}"], capture_output=True, text=True)
    is_running = "state = running" in chk.stdout or "pid = " in chk.stdout
    pid = ""
    for line in chk.stdout.splitlines():
        if "pid = " in line:
            pid = line.split("=")[-1].strip()
            break

    cfg = {}
    cfg_file = TARGET_DIR / "config.json"
    if cfg_file.exists():
        try:
            cfg = json.loads(cfg_file.read_text(encoding="utf-8"))
        except Exception:
            pass

    return {
        "installed": TARGET_DIR.exists() and (TARGET_DIR / "bot.py").exists(),
        "is_running": is_running,
        "pid": pid,
        "bot_token": cfg.get("bot_token", ""),
        "owner_id": cfg.get("owner_id"),
        "folder": cfg.get("default_gdrive_folder", "PRODUCTION"),
        "target_dir": str(TARGET_DIR),
    }


def uninstall() -> dict:
    uid = os.getuid()
    subprocess.run(["launchctl", "bootout", f"gui/{uid}/{PLIST_NAME}"], capture_output=True)
    subprocess.run(["launchctl", "bootout", f"gui/{uid}", str(PLIST_PATH)], capture_output=True)
    subprocess.run(["launchctl", "unload", "-w", str(PLIST_PATH)], capture_output=True)
    subprocess.run(["pkill", "-f", f"{TARGET_DIR}/bot.py"], capture_output=True)
    if PLIST_PATH.exists():
        try:
            PLIST_PATH.unlink()
        except Exception:
            pass
    return {"ok": True}


def restart() -> dict:
    uid = os.getuid()
    subprocess.run(["launchctl", "kickstart", "-k", "-p", f"gui/{uid}/{PLIST_NAME}"], capture_output=True)
    time.sleep(1)
    return get_status()


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "--status":
        print(json.dumps(get_status(), indent=2, ensure_ascii=False))
        sys.exit(0)

    if len(sys.argv) >= 2 and sys.argv[1] == "--restart":
        print(json.dumps(restart(), indent=2, ensure_ascii=False))
        sys.exit(0)

    if len(sys.argv) >= 2 and sys.argv[1] == "--uninstall":
        print(json.dumps(uninstall(), indent=2, ensure_ascii=False))
        sys.exit(0)

    if len(sys.argv) >= 2 and sys.argv[1] == "--verify-token":
        t = sys.argv[2] if len(sys.argv) >= 3 else ""
        print(json.dumps(verify_telegram_token(t), ensure_ascii=False))
        sys.exit(0)

    # CLI mode: install_core.py <token> [gemini_key] [folder]
    if len(sys.argv) >= 2 and not sys.argv[1].startswith("--"):
        tok = sys.argv[1]
        gem = sys.argv[2] if len(sys.argv) >= 3 else ""
        fol = sys.argv[3] if len(sys.argv) >= 4 else "PRODUCTION"
        res = install(tok, gem, fol)
        print(json.dumps(res, indent=2, ensure_ascii=False))
        sys.exit(0 if res.get("ok") else 1)

    print("Cách dùng: install_core.py <token> [gemini_key] [folder]")
