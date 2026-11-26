#!/usr/bin/env python3
"""Local setup and service controls for MediaTeleBot."""
from __future__ import annotations

import argparse
import getpass
import json
import os
import plistlib
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pairing
from runtime import BASE_DIR, IS_MAC, IS_WINDOWS, SOURCE_DIR, edit_config, lock_instance, open_https, read_config

PYTHON_MIN = (3, 10)
FILES = (
    "bot.py", "safe_fs.py", "gdrive_offload.py", "nl_engine.py", "mac_remote.py",
    "gcal_bridge.py", "llm_intent.py", "lunar_calendar.py", "updater.py",
    "runtime.py", "pairing.py", "install_core.py", "setup_gui.py",
)
LABEL = "com.macfilebot.telegrambot"
PLIST = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
STOP_REQUEST = BASE_DIR / "stop.request"
BOT_SCRIPT = BASE_DIR / "bot.py"
WIN_STARTUP = r"Software\Microsoft\Windows\CurrentVersion\Run"


def verify_telegram_token(token: str) -> str:
    if not re.fullmatch(r"[0-9]{6,16}:[A-Za-z0-9_-]{30,70}", token):
        raise ValueError("Bot token không đúng định dạng BotFather.")
    try:
        with open_https(f"https://api.telegram.org/bot{token}/getMe", timeout=15) as response:
            data = json.loads(response.read(65536))
        if data.get("ok") and data.get("result", {}).get("username"):
            return data["result"]["username"]
    except (OSError, ValueError):
        pass
    raise ValueError("Telegram không xác nhận bot token. Kiểm tra token và kết nối HTTPS.")


def is_running() -> bool:
    try:
        with lock_instance(BASE_DIR / "bot.lock"):
            return False
    except BlockingIOError:
        return True
    except OSError as exc:
        if IS_WINDOWS and exc.errno in (13, 36):
            return True
        raise


def _gui_domain() -> str:
    return f"gui/{os.getuid()}"


def stop_service() -> None:
    if IS_MAC:
        subprocess.run(["/bin/launchctl", "bootout", f"{_gui_domain()}/{LABEL}"], capture_output=True, timeout=12)
        # Stop the prior service label for upgrades where it is still loaded.
        subprocess.run(["/bin/launchctl", "bootout", f"{_gui_domain()}/com.thienung.telegramfilebot"], capture_output=True, timeout=12)
    elif IS_WINDOWS and is_running():
        STOP_REQUEST.touch(mode=0o600)
    if IS_MAC or IS_WINDOWS:
        end = time.monotonic() + 40
        while is_running() and time.monotonic() < end:
            time.sleep(0.25)
        if is_running():
            raise ValueError("Bot đang chạy trong một cửa sổ khác. Hãy đóng cửa sổ đó trước khi cài lại hoặc khởi động lại.")


def _windows_autostart(command: list[str] | None) -> None:
    import winreg
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, WIN_STARTUP) as key:
        if command:
            winreg.SetValueEx(key, "MediaTeleBot", 0, winreg.REG_SZ, subprocess.list2cmdline(command))
        else:
            try:
                winreg.DeleteValue(key, "MediaTeleBot")
            except FileNotFoundError:
                pass


def _python_path() -> str:
    return str(Path(sys.executable).resolve()) if not IS_WINDOWS else sys.executable


def start_service() -> None:
    if is_running():
        return
    if not read_config().get("bot_token") or not BOT_SCRIPT.is_file():
        raise ValueError("Hãy cài đặt MediaTeleBot và xác nhận token trước.")
    STOP_REQUEST.unlink(missing_ok=True)
    python = _python_path()
    command = [python, str(BOT_SCRIPT)]
    if IS_MAC:
        PLIST.parent.mkdir(parents=True, exist_ok=True)
        # Use plistlib so paths with spaces and XML characters remain valid.
        agent = {
            "Label": LABEL, "ProgramArguments": command, "WorkingDirectory": str(BASE_DIR),
            "RunAtLoad": True, "KeepAlive": True, "ThrottleInterval": 10,
            "StandardOutPath": str(BASE_DIR / "bot_service.log"),
            "StandardErrorPath": str(BASE_DIR / "bot_service.err.log"),
            "EnvironmentVariables": {"PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"},
        }
        with PLIST.open("wb") as fp:
            plistlib.dump(agent, fp)
        subprocess.run(["/bin/launchctl", "enable", f"{_gui_domain()}/{LABEL}"], capture_output=True, timeout=12)
        result = subprocess.run(["/bin/launchctl", "bootstrap", _gui_domain(), str(PLIST)], capture_output=True, timeout=12)
        if result.returncode:
            raise ValueError("macOS chưa khởi động được LaunchAgent. Bạn cần đăng nhập phiên đồ họa của tài khoản này.")
    elif IS_WINDOWS:
        pythonw = Path(python).with_name("pythonw.exe")
        if pythonw.is_file():
            _windows_autostart([str(pythonw), str(BOT_SCRIPT)])
        # STARTUPINFO flags hide the background console while keeping diagnostics.
        with (BASE_DIR / "bot_service.log").open("ab") as log:
            subprocess.Popen(command, cwd=BASE_DIR, stdin=subprocess.DEVNULL, stdout=log,
                             stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
    else:
        raise ValueError("Dùng 'python3 bot.py' để chạy ở foreground trên hệ điều hành này.")

    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if is_running():
            return
        time.sleep(0.2)
    raise ValueError("Bot chưa chạy. Xem nhật ký bot_service.log trong thư mục dữ liệu.")


def disable_service() -> None:
    stop_service()
    if IS_MAC:
        PLIST.unlink(missing_ok=True)
    elif IS_WINDOWS:
        _windows_autostart(None)


def validate_local_root(raw: str) -> str:
    path = Path(raw).expanduser().resolve()
    if not path.is_dir():
        raise ValueError("Chọn một thư mục có thật trên máy.")
    return str(path)


def install(bot_token: str = "", gemini_key: str = "", gdrive_folder: str = "",
            *, reset_owner: bool = False, start: bool = True) -> dict:
    cfg = read_config()
    token = bot_token.strip() or cfg.get("bot_token", "")
    username = verify_telegram_token(token)
    if gdrive_folder and (gdrive_folder in (".", "..") or any(c in gdrive_folder for c in "/\\:")):
        raise ValueError("Dùng tên một thư mục Drive. Để chọn chính xác thư mục, cấu hình Drive trên máy chủ.")
    BASE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not IS_WINDOWS:
        BASE_DIR.chmod(0o700)
    was_installed = BOT_SCRIPT.exists()
    if start and (was_installed or is_running()):
        stop_service()
    for filename in FILES:
        src, dst = SOURCE_DIR / filename, BASE_DIR / filename
        if src != dst:
            tmp = dst.with_suffix(".installing")
            shutil.copyfile(src, tmp)
            os.replace(tmp, dst)

    def apply(new):
        if reset_owner:
            new.pop("bot_token", None)
        pairing.configure_token(new, token)
        if gemini_key.strip():
            new["gemini_api_key"] = gemini_key.strip()
        if gdrive_folder:
            new.update(default_gdrive_folder=gdrive_folder, default_gdrive_folder_id=None,
                       default_gdrive_folder_url=None, default_gdrive_is_shared=False)
        return None if new.get("owner_id") else pairing.issue_code(new)

    code = edit_config(apply)
    if start and (IS_MAC or IS_WINDOWS):
        start_service()
    return {"username": username, "code": code}


def new_pairing_code() -> str:
    def apply(cfg):
        if not cfg.get("bot_token"):
            raise ValueError("Hãy nhập bot token trước.")
        if cfg.get("owner_id"):
            raise ValueError("Máy đã có chủ. Dùng chức năng đặt lại quyền chủ nếu muốn liên kết tài khoản khác.")
        return pairing.issue_code(cfg)
    return edit_config(apply)


def main() -> None:
    if sys.version_info < PYTHON_MIN:
        raise SystemExit("MediaTeleBot cần Python 3.10 trở lên.")
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--gui", action="store_true")
    mode.add_argument("--pairing-code", action="store_true")
    mode.add_argument("--start", action="store_true")
    mode.add_argument("--stop", "--uninstall", action="store_true")
    mode.add_argument("--restart", action="store_true")
    mode.add_argument("--status", action="store_true")
    mode.add_argument("--configure-calendar", action="store_true")
    mode.add_argument("--set-folder", metavar="NAME")
    mode.add_argument("--set-drive-root", metavar="DIRECTORY")
    mode.add_argument("--add-shared-root", metavar="DIRECTORY")
    mode.add_argument("--add-media-root", metavar="DIRECTORY")
    parser.add_argument("--reset-owner", action="store_true")
    parser.add_argument("--no-start", action="store_true")
    args = parser.parse_args()
    if args.gui:
        import setup_gui
        setup_gui.run()
    elif args.start or args.restart:
        if args.restart:
            stop_service()
        start_service()
    elif args.stop:
        disable_service()
    elif args.status:
        cfg = read_config()
        print(f"Thư mục dữ liệu: {BASE_DIR}\nBot: {'đang chạy' if is_running() else 'đã dừng'}\nChủ Telegram: {cfg.get('owner_id') or 'chưa ghép cặp'}")
    elif args.configure_calendar:
        import gcal_bridge
        url = input("URL Apps Script /exec: ").strip()
        secret = getpass.getpass("Khóa Apps Script: ")
        print("Đã cấu hình lịch:", gcal_bridge.configure_webhook(url, secret))
    elif args.set_folder is not None:
        import safe_fs
        res = safe_fs.set_default_gdrive_folder(args.set_folder)
        if not res["ok"]:
            raise ValueError(res["error"])
        print(res["folder_name"])
    elif args.set_drive_root:
        root = validate_local_root(args.set_drive_root)
        edit_config(lambda cfg: cfg.update(google_drive_root=root))
    elif args.add_shared_root or args.add_media_root:
        key = "shared_roots" if args.add_shared_root else "media_roots"
        root = validate_local_root(args.add_shared_root or args.add_media_root)
        edit_config(lambda cfg: cfg.update({key: list(dict.fromkeys([*(cfg.get(key) or []), root]))}))
    elif args.pairing_code:
        print("/pair", new_pairing_code())
    else:
        token = getpass.getpass("Telegram Bot Token (Enter để giữ cấu hình cũ): ")
        gemini = getpass.getpass("Gemini API key (tùy chọn): ")
        result = install(token, gemini, reset_owner=args.reset_owner, start=not args.no_start)
        print("Bot Telegram: @" + result["username"])
        if result["code"]:
            print("Gửi trong chat riêng trong vòng 15 phút: /pair", result["code"])
        else:
            print("Đã giữ quyền chủ Telegram hiện tại.")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        # Never print request URLs or config contents.
        print(str(exc) if isinstance(exc, ValueError) and not isinstance(exc, json.JSONDecodeError) else f"Cài đặt gặp lỗi ({type(exc).__name__}).", file=sys.stderr)
        sys.exit(1)
