#!/usr/bin/env python3
from __future__ import annotations
"""
Gửi tin nhắn Zalo bằng cách điều khiển ứng dụng Zalo trên Mac (giống người dùng thật).
Cần: Zalo đang mở & đã đăng nhập, màn hình không bị khoá, và đã cấp quyền
"Trợ năng" (Accessibility) cho Python trong System Settings.
"""

import subprocess
import time

APPLESCRIPT = r'''
on run argv
    set contactName to item 1 of argv
    set messageText to item 2 of argv
    set doSend to item 3 of argv
    tell application "Zalo" to activate
    delay 1.0
    tell application "System Events"
        tell process "Zalo"
            set frontmost to true
            delay 0.4
            keystroke "f" using command down
            delay 0.6
            set the clipboard to contactName
            keystroke "v" using command down
            delay 1.8
            key code 36
            delay 1.2
            set the clipboard to messageText
            keystroke "v" using command down
            delay 0.5
            if doSend is "yes" then key code 36
        end tell
    end tell
end run
'''


def check_accessibility() -> tuple[bool, str]:
    """Return (ok, message) telling whether this process may control the UI."""
    r = subprocess.run(
        ["/usr/bin/osascript", "-e", 'tell application "System Events" to tell process "Zalo" to count windows'],
        capture_output=True, text=True, timeout=30,
    )
    if r.returncode == 0:
        return True, "ok"
    return False, (r.stderr or r.stdout).strip()


def _get_clipboard() -> bytes | None:
    try:
        return subprocess.run(["/usr/bin/pbpaste"], capture_output=True, timeout=5).stdout
    except Exception:
        return None


def _set_clipboard(data: bytes) -> None:
    try:
        subprocess.run(["/usr/bin/pbcopy"], input=data, timeout=5)
    except Exception:
        pass


def send_zalo_message(contact: str, text: str, really_send: bool = True) -> dict:
    ok, msg = check_accessibility()
    if not ok:
        return {
            "ok": False,
            "error": (
                "Chưa có quyền điều khiển máy (Trợ năng). Hãy vào System Settings → Privacy & Security → "
                f"Accessibility và bật cho Python. Chi tiết: {msg[:200]}"
            ),
        }
    saved = _get_clipboard()
    try:
        r = subprocess.run(
            ["/usr/bin/osascript", "-e", APPLESCRIPT, contact, text, "yes" if really_send else "no"],
            capture_output=True, text=True, timeout=60,
        )
        if r.returncode != 0:
            return {"ok": False, "error": (r.stderr or r.stdout).strip()[:400]}
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        time.sleep(0.3)
        if saved is not None:
            _set_clipboard(saved)
