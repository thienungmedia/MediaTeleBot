"""One-time owner pairing, issued only on the computer running the bot."""
from __future__ import annotations

import hashlib
import hmac
import secrets
import time

LIFETIME = 15 * 60


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def issue_code(config: dict, now: float | None = None) -> str:
    code = secrets.token_urlsafe(12)
    config["pairing_hash"] = _digest(code)
    config["pairing_expires"] = (time.time() if now is None else now) + LIFETIME
    return code


def private_sender(message: dict, user: dict | None = None) -> int | None:
    chat = message.get("chat") or {}
    sender = (message.get("from") or {}) if user is None else user
    uid = sender.get("id")
    if (
        type(uid) is int and uid > 0 and not sender.get("is_bot")
        and chat.get("type") == "private" and chat.get("id") == uid
    ):
        return uid
    return None


def claim(config: dict, code: str, user: dict, now: float | None = None) -> bool:
    if config.get("owner_id") or type(user.get("id")) is not int or user["id"] <= 0:
        return False
    expected = config.get("pairing_hash")
    clock = time.time() if now is None else now
    if not expected or clock >= config.get("pairing_expires", 0):
        return False
    if not hmac.compare_digest(expected, _digest(code)):
        return False
    config.pop("pairing_hash", None)
    config.pop("pairing_expires", None)
    config.update(owner_id=user["id"], chat_id=user["id"], username=user.get("username", ""))
    return True


def configure_token(config: dict, token: str) -> None:
    if config.get("bot_token") != token:
        config.update(owner_id=None, chat_id=None, username="", allowed_users=[], last_update_id=0)
        config.pop("pairing_hash", None)
        config.pop("pairing_expires", None)
    config["bot_token"] = token
    owner = config.get("owner_id")
    if type(owner) is not int or owner <= 0:
        owner = None
    config.update(owner_id=owner, chat_id=owner)
    config["allowed_users"] = sorted({uid for uid in (config.get("allowed_users") or []) if type(uid) is int and uid > 0 and uid != owner})
