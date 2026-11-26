"""Release notifications. Installation is handled by the OS package installer."""
from __future__ import annotations

import json
import re
import urllib.error

from runtime import open_https

CURRENT_VERSION = "1.8.0"
RELEASES_URL = "https://github.com/thienungmedia/MediaTeleBot/releases"
RELEASE_API = "https://api.github.com/repos/thienungmedia/MediaTeleBot/releases/latest"


def _version(text: str) -> tuple[int, ...]:
    if not re.fullmatch(r"v?\d+\.\d+\.\d+", text):
        return ()
    return tuple(int(part) for part in text.removeprefix("v").split("."))


def check_for_updates() -> dict:
    try:
        with open_https(RELEASE_API, timeout=10) as response:
            data = json.loads(response.read(512 * 1024))
        tag = data.get("tag_name", "")
        return {"has_update": _version(tag) > _version(CURRENT_VERSION), "latest_version": tag}
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return {"has_update": False}
        return {"has_update": False, "error": True}
    except (ValueError, OSError):
        return {"has_update": False, "error": True}


def release_button() -> dict:
    return {"inline_keyboard": [[{"text": "Mở trang phát hành GitHub", "url": RELEASES_URL}]]}


def update_message() -> tuple[str, dict]:
    result = check_for_updates()
    if result.get("has_update"):
        text = f"Đã có MediaTeleBot {result['latest_version']}. Tải bộ cài từ trang phát hành."
    elif result.get("error"):
        text = f"Đang dùng MediaTeleBot v{CURRENT_VERSION}. Chưa kiểm tra được GitHub."
    else:
        text = f"Đang dùng MediaTeleBot v{CURRENT_VERSION}. GitHub chưa có bản phát hành mới hơn."
    return text, release_button()


if __name__ == "__main__":
    print(update_message()[0])
    print(RELEASES_URL)
