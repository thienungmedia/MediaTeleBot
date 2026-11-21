#!/usr/bin/env python3
from __future__ import annotations
"""
Telegram Safe File Manager Bot & Antigravity Bridge for macOS.
- 100% No-Delete Architecture (only browse, search, copy, and non-overwriting move).
- Interactive Inline Keyboard buttons on Telegram for browsing drives & folders,
  plus 2-tap Copy / Move between drives!
- Also bridges natural language requests directly to Antigravity AI.
"""

import fcntl
import importlib
import json
import os
import re
import signal
import sys
import threading
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

import gcal_bridge
import mac_remote
import safe_fs
from safe_fs import (
    list_drives,
    list_directory,
    search_files,
    safe_copy,
    safe_move,
    get_folder_size,
    upload_to_google_drive,
    find_google_drive_root,
)
import nl_engine
from nl_engine import parse_and_execute_nl, find_best_matches

BASE_DIR = Path(__file__).parent.resolve()
CONFIG_PATH = BASE_DIR / "config.json"
INBOX_PATH = BASE_DIR / "inbox.jsonl"
OUTBOX_PATH = BASE_DIR / "outbox.jsonl"
OUTBOX_RESULT_PATH = BASE_DIR / "outbox_result.json"
SYSINFO_PATH = BASE_DIR / "system_info.json"


def load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_config(cfg: dict) -> None:
    current = load_config()
    current.update(cfg)
    CONFIG_PATH.write_text(json.dumps(current, indent=2, ensure_ascii=False), encoding="utf-8")


import ssl

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

def _urlopen_robust(req, timeout=35):
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


class TelegramClient:
    def __init__(self, token: str):
        self.token = token.strip()
        self.base_url = f"https://api.telegram.org/bot{self.token}"

    def call(self, method: str, payload: dict | None = None, timeout: int = 35) -> dict:
        url = f"{self.base_url}/{method}"
        data = None
        headers = {}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers)
        with _urlopen_robust(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def send_message(self, chat_id: int, text: str, reply_markup: dict | None = None) -> dict:
        payload = {
            "chat_id": chat_id,
            "text": text[:4000],
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup
        return self.call("sendMessage", payload)

    @staticmethod
    def _build_multipart(fields: dict, files: dict) -> tuple[bytes, str]:
        boundary = f"----MacFileBotBoundary{uuid.uuid4().hex}"
        chunks: list[bytes] = []
        for k, v in fields.items():
            if v is None:
                continue
            chunks.append(f"--{boundary}\r\n".encode("utf-8"))
            chunks.append(f'Content-Disposition: form-data; name="{k}"\r\n\r\n'.encode("utf-8"))
            chunks.append(str(v).encode("utf-8") + b"\r\n")
        for field_name, file_tuple in files.items():
            filename, raw_bytes, ctype = file_tuple
            chunks.append(f"--{boundary}\r\n".encode("utf-8"))
            chunks.append(
                f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"\r\n'.encode("utf-8")
            )
            chunks.append(f"Content-Type: {ctype}\r\n\r\n".encode("utf-8"))
            chunks.append(raw_bytes + b"\r\n")
        chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
        return b"".join(chunks), f"multipart/form-data; boundary={boundary}"

    def send_photo(
        self,
        chat_id: int,
        photo_path: str,
        caption: str = "",
        reply_markup: dict | None = None,
    ) -> dict:
        p = Path(photo_path)
        fields: dict = {"chat_id": str(chat_id)}
        if caption:
            fields["caption"] = caption[:1020]
        if reply_markup:
            fields["reply_markup"] = json.dumps(reply_markup, ensure_ascii=False)
        body, ctype_header = self._build_multipart(
            fields,
            {"photo": (p.name, p.read_bytes(), "image/jpeg")},
        )
        req = urllib.request.Request(
            f"{self.base_url}/sendPhoto",
            data=body,
            headers={"Content-Type": ctype_header},
        )
        with _urlopen_robust(req, timeout=45) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def send_document(
        self,
        chat_id: int,
        file_path: str,
        caption: str = "",
        reply_markup: dict | None = None,
    ) -> dict:
        p = Path(file_path)
        fields: dict = {"chat_id": str(chat_id)}
        if caption:
            fields["caption"] = caption[:1020]
        if reply_markup:
            fields["reply_markup"] = json.dumps(reply_markup, ensure_ascii=False)
        ctype = "image/jpeg" if p.suffix.lower() in (".jpg", ".jpeg") else "application/octet-stream"
        body, ctype_header = self._build_multipart(
            fields,
            {"document": (p.name, p.read_bytes(), ctype)},
        )
        req = urllib.request.Request(
            f"{self.base_url}/sendDocument",
            data=body,
            headers={"Content-Type": ctype_header},
        )
        with _urlopen_robust(req, timeout=45) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def answer_callback(self, callback_id: str, text: str = "") -> None:
        try:
            self.call("answerCallbackQuery", {"callback_query_id": callback_id, "text": text})
        except Exception:
            pass


# Short path registry in memory so callback_data stays within Telegram's 64-byte limit
PATH_MAP: dict[str, str] = {}
PATH_REV: dict[str, str] = {}
NEXT_ID = 1


def register_path(path_str: str) -> str:
    global NEXT_ID
    resolved = str(Path(path_str).expanduser().resolve())
    if resolved in PATH_REV:
        return PATH_REV[resolved]
    pid = f"p{NEXT_ID}"
    NEXT_ID += 1
    PATH_MAP[pid] = resolved
    PATH_REV[resolved] = pid
    return pid


def get_registered_path(pid: str) -> str | None:
    return PATH_MAP.get(pid)


RC_APP_MAP: dict[str, str] = {}
RC_APP_REV: dict[str, str] = {}
NEXT_APP_ID = 1


def register_rc_app(app_name: str) -> str:
    global NEXT_APP_ID
    if app_name in RC_APP_REV:
        return RC_APP_REV[app_name]
    aid = f"a{NEXT_APP_ID}"
    NEXT_APP_ID += 1
    RC_APP_MAP[aid] = app_name
    RC_APP_REV[app_name] = aid
    return aid


def get_rc_app(aid: str) -> str | None:
    return RC_APP_MAP.get(aid)


def send_nl_response(client: TelegramClient, chat_id: int, nl_res: dict) -> None:
    if nl_res.get("open_dir"):
        view_text, kb = format_dir_view(nl_res["open_dir"], chat_id)
        client.send_message(chat_id, view_text, reply_markup=kb)
        return
    if nl_res.get("document_path") and os.path.exists(nl_res["document_path"]):
        reply_txt = nl_res.get("reply") or ""
        client.send_document(
            chat_id,
            nl_res["document_path"],
            caption=reply_txt[:1020],
            reply_markup=nl_res.get("reply_markup"),
        )
        return
    if nl_res.get("photo_path") and os.path.exists(nl_res["photo_path"]):
        reply_txt = nl_res.get("reply") or ""
        if len(reply_txt) <= 950:
            client.send_photo(
                chat_id,
                nl_res["photo_path"],
                caption=reply_txt,
                reply_markup=nl_res.get("reply_markup"),
            )
        else:
            client.send_photo(
                chat_id,
                nl_res["photo_path"],
                caption=reply_txt[:220] + "...",
            )
            client.send_message(
                chat_id,
                reply_txt,
                reply_markup=nl_res.get("reply_markup"),
            )
        return
    if nl_res.get("reply_markup"):
        client.send_message(chat_id, nl_res["reply"], reply_markup=nl_res["reply_markup"])
        return
    kb_rows = []
    quick_dst = nl_res.get("quick_move_dst")
    quick_is_copy = nl_res.get("quick_is_copy", False)
    quick_is_gdrive = nl_res.get("quick_is_gdrive", False)
    dst_pid = register_path(quick_dst) if quick_dst else None
    matches = nl_res.get("matches", [])

    for idx, m in enumerate(matches, 1):
        pid = register_path(m["path"])
        icon = "📁" if m["is_dir"] else "📄"
        if dst_pid:
            dst_name = Path(quick_dst).name
            if quick_is_gdrive:
                btn_text = (
                    f"✅ Xác nhận Up: {m['name']} -> {dst_name}"
                    if len(matches) == 1
                    else f"☁️ Chọn Up #{idx}: {m['name']} -> {dst_name}"
                )
                kb_rows.append([{"text": btn_text[:60], "callback_data": f"qgd:{pid}:{dst_pid}"}])
            else:
                act_verb = "Copy" if quick_is_copy else "Chuyển"
                op_code = "qcp" if quick_is_copy else "qmv"
                btn_text = (
                    f"✅ Xác nhận {act_verb}: {m['name']} -> {dst_name}"
                    if len(matches) == 1
                    else f"✅ Chọn {act_verb} #{idx}: {m['name']} -> {dst_name}"
                )
                kb_rows.append([{"text": btn_text[:60], "callback_data": f"{op_code}:{pid}:{dst_pid}"}])
                # If single match and move requested, also offer an option to Copy instead of Move
                if len(matches) == 1 and not quick_is_copy:
                    kb_rows.append([
                        {
                            "text": f"📋 Chỉ Sao chép (giữ file gốc) -> {dst_name}"[:60],
                            "callback_data": f"qcp:{pid}:{dst_pid}",
                        }
                    ])
        else:
            kb_rows.append([{"text": f"{icon} Mở: {m['name']}", "callback_data": f"open:{pid}"}])

    if dst_pid and matches:
        kb_rows.append([{"text": "❌ Huỷ bỏ", "callback_data": "cancel_nl"}])

    markup = {"inline_keyboard": kb_rows} if kb_rows else None
    client.send_message(chat_id, nl_res["reply"], reply_markup=markup)


def write_system_snapshot() -> None:
    try:
        home = Path.home()
        gdrive_root = find_google_drive_root(auto_launch=False)
        snap = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "drives": list_drives(),
            "google_drive_root": str(gdrive_root) if gdrive_root else None,
            "desktop": list_directory(str(home / "Desktop"), limit=50),
            "downloads": list_directory(str(home / "Downloads"), limit=50),
            "cloud_storage": list_directory(str(home / "Library" / "CloudStorage"), limit=20),
        }
        SYSINFO_PATH.write_text(json.dumps(snap, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        print(f"[Snapshot error]: {e}", file=sys.stderr, flush=True)


def outbox_worker(client: TelegramClient, cfg: dict) -> None:
    """Background thread watching outbox.jsonl for commands from Antigravity."""
    while True:
        try:
            if OUTBOX_PATH.exists():
                content = OUTBOX_PATH.read_text(encoding="utf-8").strip()
                if content:
                    OUTBOX_PATH.write_text("", encoding="utf-8")
                    results = []
                    for line in content.splitlines():
                        if not line.strip():
                            continue
                        cmd = json.loads(line)
                        act = cmd.get("action")
                        cid = cmd.get("chat_id") or cfg.get("chat_id")
                        if act == "send" and cid:
                            client.send_message(cid, cmd.get("text", ""))
                            results.append({"ok": True, "action": "send"})
                        elif act == "ls":
                            results.append(list_directory(cmd.get("path", "~"), limit=100))
                        elif act == "find":
                            results.append({"ok": True, "matches": find_best_matches(cmd.get("query", ""))})
                        elif act == "size":
                            results.append(get_folder_size(cmd.get("path", "~")))
                        elif act == "copy":
                            res = safe_copy(cmd["src"], cmd["dst"])
                            results.append(res)
                            if cmd.get("notify") and cid:
                                client.send_message(cid, f"✅ Đã sao chép:\n• Từ: {res.get('src')}\n• Sang: {res.get('dst')}")
                        elif act == "move":
                            res = safe_move(cmd["src"], cmd["dst"])
                            results.append(res)
                            if cmd.get("notify") and cid:
                                client.send_message(cid, f"✅ Đã chuyển:\n• Từ: {res.get('src')}\n• Sang: {res.get('dst')}")
                        elif act == "gdrive":
                            res = upload_to_google_drive(cmd["src"], cmd.get("subfolder", ""))
                            results.append(res)
                            if cmd.get("notify") and cid:
                                if res.get("ok"):
                                    client.send_message(cid, f"☁️ Đã đưa lên Google Drive:\n• Nguồn: {res.get('src')}\n• Đích: {res.get('dst')}")
                                else:
                                    client.send_message(cid, f"❌ {res.get('error')}")
                    OUTBOX_RESULT_PATH.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            print(f"[Outbox error]: {e}", file=sys.stderr, flush=True)
        time.sleep(0.4)


def update_checker_worker(client: TelegramClient, cfg: dict) -> None:
    """Check for new versions 30s after startup and once every 24 hours."""
    time.sleep(30)
    while True:
        try:
            import updater
            chat_id = cfg.get("chat_id")
            if chat_id:
                res = updater.check_for_updates()
                if res.get("has_update"):
                    markup = {"inline_keyboard": [
                        [{"text": f"🚀 Cập nhật lên v{res['latest_version']}", "callback_data": "do_update"}],
                        [{"text": "❌ Để sau", "callback_data": "cancel_nl"}]
                    ]}
                    client.send_message(
                        chat_id,
                        f"🔔 THÔNG BÁO BẢN CẬP NHẬT MỚI: v{res['latest_version']}!\n\n"
                        f"📝 Nội dung:\n{res.get('release_notes')}\n\n"
                        f"👉 Bấm nút bên dưới để cập nhật tự động:",
                        reply_markup=markup,
                    )
        except Exception:
            pass
        time.sleep(86400)


USER_STATE: dict[int, dict] = {}


def build_home_keyboard() -> dict:
    home = Path.home()
    buttons = [
        [
            {"text": "💽 Danh sách Ổ đĩa (/Volumes)", "callback_data": "drives"},
            {"text": "☁️ Google Drive", "callback_data": "gdrive_home"},
        ],
        [
            {"text": "📥 Downloads", "callback_data": f"open:{register_path(str(home / 'Downloads'))}"},
            {"text": "🖥 Desktop", "callback_data": f"open:{register_path(str(home / 'Desktop'))}"},
        ],
        [
            {"text": "📄 Documents", "callback_data": f"open:{register_path(str(home / 'Documents'))}"},
            {"text": "🏠 Thư mục gốc (~)", "callback_data": f"open:{register_path(str(home))}"},
        ],
        [
            {"text": "🗑 Thùng rác (Trash)", "callback_data": "trash_view"},
            {"text": "🚀 Mở Ứng dụng (Apps)", "callback_data": "apps_view"},
        ],
        [
            {"text": "📸 Chụp Màn Hình", "callback_data": "rc_snap"},
            {"text": "🎛 Điều Khiển Máy", "callback_data": "rc_panel"},
        ],
    ]
    return {"inline_keyboard": buttons}


def format_drives_view() -> tuple[str, dict]:
    drives = list_drives()
    lines = ["💽 DANH SÁCH Ổ ĐĨA TRÊN MÁY MAC:\n"]
    kb = []
    for d in drives:
        lines.append(
            f"• {d['name']}\n"
            f"  Đường dẫn: {d['mount']}\n"
            f"  Trống: {d['free']} / Tổng: {d['total']}"
        )
        pid = register_path(d["mount"])
        kb.append([{"text": f"📂 Mở ổ đĩa: {d['name']} (Trống {d['free']})", "callback_data": f"open:{pid}"}])
    kb.append([{"text": "🏠 Về Menu chính", "callback_data": "home"}])
    return "\n".join(lines), {"inline_keyboard": kb}


def format_dir_view(path_str: str, chat_id: int) -> tuple[str, dict]:
    info = list_directory(path_str, limit=25)
    if not info.get("ok"):
        return f"❌ {info.get('error')}", build_home_keyboard()

    if info.get("is_file"):
        f_pid = register_path(info["path"])
        text = (
            f"📄 CHI TIẾT FILE:\n"
            f"Tên: {Path(info['path']).name}\n"
            f"Đường dẫn: {info['path']}\n"
            f"Kích thước: {info['size']}\n"
            f"Sửa đổi: {info['modified']}\n\n"
            f"🔒 Chế độ an toàn: Chỉ cho phép Sao chép hoặc Dời file (Không xoá)."
        )
        parent_pid = register_path(str(Path(info["path"]).parent))
        row1 = [
            {"text": "📋 Sao chép (Copy) file này", "callback_data": f"pick_cp:{f_pid}"},
            {"text": "📦 Dời (Move) file này", "callback_data": f"pick_mv:{f_pid}"},
        ]
        try:
            import gdrive_offload
            if gdrive_offload.is_inside_google_drive(info["path"]):
                row1.append({"text": "🧹 Xoá bản tải về", "callback_data": f"evict:{f_pid}"})
        except Exception:
            pass
        kb = [
            row1,
            [{"text": "⬅️ Quay lại thư mục cha", "callback_data": f"open:{parent_pid}"}],
        ]
        return text, {"inline_keyboard": kb}

    cur_path = info["path"]
    cur_pid = register_path(cur_path)
    state = USER_STATE.get(chat_id, {})
    pending_action = state.get("action")
    pending_src = state.get("src")

    header = [f"📂 THƯ MỤC: {cur_path}"]
    if pending_action and pending_src:
        act_label = "SAO CHÉP (COPY)" if pending_action == "cp" else "DỜI (MOVE)"
        header.append(
            f"\n⚡ ĐANG CHỌN NƠI ĐẾN ĐỂ {act_label}:\n"
            f"Nguồn: {pending_src}\n"
            f"👉 Hãy mở thư mục/ổ đĩa đích rồi bấm nút [Dán vào thư mục này] bên dưới!"
        )

    items = info.get("items", [])
    if not items:
        header.append("\n(Thư mục trống)")
    else:
        header.append(f"\nHiển thị {len(items)}/{info['total_count']} mục:")

    kb = []
    # If user is in Copy/Move mode, show big Paste button at the top
    if pending_action and pending_src:
        act_label = "📋 DÁN (SAO CHÉP) VÀO ĐÂY" if pending_action == "cp" else "📦 CHUYỂN (MOVE) VÀO ĐÂY"
        kb.append([{"text": act_label, "callback_data": f"paste:{cur_pid}"}])
        kb.append([{"text": "❌ Huỷ thao tác Copy/Move", "callback_data": f"cancel:{cur_pid}"}])
    else:
        folder_row = [
            {"text": "📋 Copy cả thư mục này", "callback_data": f"pick_cp:{cur_pid}"},
            {"text": "📦 Dời cả thư mục này", "callback_data": f"pick_mv:{cur_pid}"},
        ]
        try:
            import gdrive_offload
            if gdrive_offload.is_inside_google_drive(cur_path):
                folder_row.append({"text": "🧹 Xoá bản tải về", "callback_data": f"evict:{cur_pid}"})
        except Exception:
            pass
        kb.append(folder_row)

    # Navigation row
    nav_row = []
    if info.get("parent"):
        nav_row.append({"text": "⬆️ Thư mục cha", "callback_data": f"open:{register_path(info['parent'])}"})
    nav_row.append({"text": "💽 Đổi Ổ đĩa", "callback_data": "drives"})
    nav_row.append({"text": "🏠 Menu", "callback_data": "home"})
    kb.append(nav_row)

    # Item buttons
    for item in items:
        pid = register_path(item["path"])
        icon = "📁" if item["is_dir"] else "📄"
        size_str = "" if item["is_dir"] else f" ({item['size']})"
        label = f"{icon} {item['name']}{size_str}"
        kb.append([{"text": label[:60], "callback_data": f"open:{pid}"}])

    return "\n".join(header), {"inline_keyboard": kb}


def _send_gcal_setup_guide(client: TelegramClient, chat_id: int, include_status: bool = False) -> None:
    """Hiển thị trạng thái & 2 cách bật tự động lưu Google Calendar không cần Antigravity."""
    lines: list[str] = []
    if include_status:
        st = gcal_bridge.get_calendar_sync_status(nl_engine.GCALENDAR_BIN)
        lines.append("📅 TRẠNG THÁI ĐỒNG BỘ GOOGLE CALENDAR:\n")
        if st.get("has_webhook"):
            lines.append("• ☁️ Google Apps Script Bridge: ✅ *ĐÃ KẾT NỐI* (Tự động cả GHI & ĐỌC trực tiếp)")
        else:
            lines.append("• ☁️ Google Apps Script Bridge: ⚪ Chưa cài")
        if st.get("macos_google_cals"):
            lines.append("• 🔄 Lịch Google trên macOS: ✅ *ĐÃ BẬT* (`" + "`, `".join(st["macos_google_cals"]) + "`)")
        else:
            lines.append("• 🔄 Lịch Google trên macOS: ⚪ Chưa bật đồng bộ")
        if st.get("has_cli"):
            lines.append("• 🤖 Antigravity gcalendar CLI: ✅ Đã cài")
        lines.append("")

    lines.extend([
        "⚡ *2 CÁCH TỰ ĐỘNG GHI LỊCH GOOGLE 100% KHÔNG CẦN ANTIGRAVITY:*\n",
        "1️⃣ **Cách 1 — Nhanh nhất (20 giây, 0 dòng code):**",
        "   Mở *Cài đặt hệ thống → Tài khoản Internet → Google → Gạt BẬT mục Lịch (Calendars)*.",
        "   Từ đó mỗi khi bạn nhắn `note lịch 20/12 ...`, bot tự ghi vào Lịch Mac và macOS tự đồng bộ 2 chiều lên Google Calendar ngay lập tức!\n",
        "2️⃣ **Cách 2 — Dùng Google Apps Script (1 phút, Đọc & Ghi trực tiếp không cần Apple Calendar):**",
        "   Bấm nút *Lấy mã Google Apps Script* bên dưới, deploy Web App tại `script.google.com` rồi dán đường dẫn `/exec` thẳng vào chat Telegram này.",
    ])
    kb = [
        [{"text": "⚙️ Mở Cài đặt Tài khoản Google trên Mac", "callback_data": "gcal_open_mac_accounts"}],
        [{"text": "📋 Lấy mã Google Apps Script", "callback_data": "gcal_show_script"}],
        [{"text": "🏠 Về Menu chính", "callback_data": "home"}],
    ]
    client.send_message(chat_id, "\n".join(lines), reply_markup={"inline_keyboard": kb})


def handle_message(client: TelegramClient, cfg: dict, msg: dict) -> bool:
    """
    Process an incoming Telegram text message.
    Returns True if a natural-language request was queued for Antigravity AI.
    """
    chat_id = msg["chat"]["id"]
    user_id = msg.get("from", {}).get("id")
    username = msg.get("from", {}).get("username", "")
    text = (msg.get("text") or "").strip()

    if not text:
        return False

    # Bind owner on first /start if not configured yet
    owner_id = cfg.get("owner_id")
    if owner_id is None:
        cfg["owner_id"] = user_id
        cfg["chat_id"] = chat_id
        cfg["username"] = username
        save_config(cfg)
        owner_id = user_id
        print(f"[🔒 Bảo mật] Đã khoá quyền điều khiển cho chủ nhân Telegram ID: {owner_id} (@{username})", flush=True)

    allowed_users = set()
    if owner_id:
        allowed_users.add(owner_id)
    for u in cfg.get("allowed_users", []):
        try:
            allowed_users.add(int(u))
        except Exception:
            pass

    if user_id not in allowed_users:
        print(f"[🚫 Người chưa được phân quyền] id={user_id} @{username}: {text[:80]}", flush=True)
        # Phản hồi lịch sự và rõ ràng khi người lạ hoặc thợ bấm /start
        if text.startswith("/start"):
            owner_name = f"@{cfg.get('username')}" if cfg.get('username') else "chủ nhân"
            alert_reply = (
                "⛔ BẠN CHƯA ĐƯỢC PHÂN QUYỀN ĐIỀU KHIỂN MÁY MAC NÀY!\n\n"
                f"• Con bot này đang liên kết với máy Mac của {owner_name}.\n"
                f"• Telegram ID của bạn là: `{user_id}`\n\n"
                "💡 ĐỂ SỬ DỤNG BOT NÀY:\n"
                "1. Nếu đây là máy Mac của bạn: Hãy tạo Bot Token riêng bằng @BotFather và mở app 'Cài Đặt MacFileBot' trên máy của bạn để thiết lập.\n"
                f"2. Nếu bạn là thợ/cộng sự muốn điều khiển máy Mac của {owner_name}: Hãy nhờ chủ nhân nhắn cho bot câu lệnh:\n"
                f"   `thêm thợ {user_id}` để cấp quyền cho bạn."
            )
            client.send_message(chat_id, alert_reply)
            # Thông báo cho chủ nhân
            if cfg.get("chat_id"):
                try:
                    client.send_message(
                        cfg["chat_id"],
                        f"🚨 Thợ/Người dùng @{username or 'chưa đặt username'} (ID: `{user_id}`) vừa gửi /start vào bot của bạn.\n"
                        f"👉 Nếu muốn cấp quyền cho người này cùng điều khiển máy, bạn hãy nhắn:\n`thêm thợ {user_id}`",
                    )
                except Exception:
                    pass
        return False

    # Lệnh cấp quyền thêm thợ dành riêng cho chủ nhân
    t_lower = text.lower().strip()
    if user_id == owner_id and (t_lower.startswith("thêm thợ ") or t_lower.startswith("them tho ") or t_lower.startswith("cấp quyền ") or t_lower.startswith("cap quyen ")):
        parts = t_lower.split()
        cand_id = parts[-1].strip("`'\" ")
        if cand_id.isdigit():
            new_uid = int(cand_id)
            cur_allowed = cfg.get("allowed_users", [])
            if new_uid not in cur_allowed:
                cur_allowed.append(new_uid)
                cfg["allowed_users"] = cur_allowed
                save_config(cfg)
                client.send_message(chat_id, f"✅ ĐÃ CẤP QUYỀN ĐIỀU KHIỂN CHO THỢ CÓ TELEGRAM ID: `{new_uid}`!\nBây giờ người này có thể gửi /start và tra cứu file trên máy Mac của bạn.")
                try:
                    client.send_message(new_uid, f"🎉 BẠN ĐÃ ĐƯỢC CHỦ NHÂN MÁY MAC CẤP QUYỀN ĐIỀU KHIỂN!\nHãy gửi lệnh /start để bắt đầu sử dụng.")
                except Exception:
                    pass
            else:
                client.send_message(chat_id, f"ℹ️ Thợ có Telegram ID `{new_uid}` đã có trong danh sách phân quyền từ trước.")
            return False

    # Always keep latest chat_id updated
    if cfg.get("chat_id") != chat_id:
        cfg["chat_id"] = chat_id
        save_config(cfg)

    if text.startswith("/start") or text.startswith("/help"):
        welcome = (
            "✅ ĐÃ KẾT NỐI VỚI MÁY MAC CỦA BẠN!\n"
            "🔒 Chế độ bảo vệ: BẬT (CẤM XOÁ FILE 100%).\n\n"
            "💬 NHẮN TIẾNG VIỆT TỰ NHIÊN HOẶC BẤM NÚT BÊN DƯỚI:\n"
            "• 📁 File & Drive: \"tìm dự án 2510\", \"up file lên drive\", \"xoá bản tải về 2510\"\n"
            "• 💬 Gửi link Zalo: \"gửi link 2510 cho Anh Nam qua zalo\"\n"
            "• 📸 Màn hình & Điều khiển: \"chụp màn hình\", \"bấm vào nút Xuất\", \"tình trạng máy\"\n"
            "• 🚀 App & Thùng rác: \"mở premiere\", \"kiểm tra thùng rác\", \"khôi phục file X\"\n"
            "• 📅 Lịch làm việc: \"note lịch 20/12 quay sự kiện\", \"tuần này có lịch gì\"\n"
        )
        if not (cfg.get("gemini_api_key") or os.environ.get("GEMINI_API_KEY")):
            welcome += "\n💡 Mẹo: Lấy Gemini API Key miễn phí tại https://aistudio.google.com/apikey rồi dán thẳng vào đây để mở khoá AI trò chuyện & AI Vision Click!"
        client.send_message(chat_id, welcome, reply_markup=build_home_keyboard())
        return False

    if text.strip().lower() in ("/update", "/version", "/capnhat", "cập nhật", "update", "kiểm tra cập nhật", "update bot", "cập nhật bot"):
        import updater
        client.send_message(chat_id, f"🔍 Đang kiểm tra bản cập nhật (Bản hiện tại: v{updater.CURRENT_VERSION})...")
        res = updater.check_for_updates()
        if res.get("has_update"):
            markup = {"inline_keyboard": [
                [{"text": f"🚀 Cập nhật lên v{res['latest_version']}", "callback_data": "do_update"}],
                [{"text": "❌ Để sau", "callback_data": "cancel_nl"}]
            ]}
            client.send_message(
                chat_id,
                f"🎉 PHÁT HIỆN BẢN CẬP NHẬT MỚI: v{res['latest_version']}!\n\n"
                f"📝 Chi tiết nâng cấp:\n{res.get('release_notes')}\n\n"
                f"👉 Bấm nút bên dưới để cập nhật tự động:",
                reply_markup=markup
            )
        elif res.get("error"):
            client.send_message(chat_id, f"⚠️ Không thể kiểm tra máy chủ cập nhật: {res['error']}")
        else:
            client.send_message(chat_id, f"✅ Bạn đang sử dụng phiên bản mới nhất (v{updater.CURRENT_VERSION})!")
        return False

    if text.startswith("/drives"):
        view_text, kb = format_drives_view()
        client.send_message(chat_id, view_text, reply_markup=kb)
        return False

    # Cho phép người dùng dán trực tiếp Gemini API Key trên Telegram (nếu muốn dùng key riêng)
    m_gem = re.match(r"^(?:/gemini|gemini|cài\s+gemini|set\s+gemini)\s+(\S+)$", text.strip(), flags=re.IGNORECASE)
    if m_gem or (text.strip().startswith("AIzaSy") and len(text.strip().split()) == 1 and len(text.strip()) >= 35):
        new_key = m_gem.group(1).strip() if m_gem else text.strip()
        cfg["gemini_api_key"] = new_key
        save_config(cfg)
        client.send_message(
            chat_id,
            "✅ ĐÃ CẬP NHẬT MÃ GEMINI API KEY THÀNH CÔNG!\n"
            "🤖 Bây giờ tôi có thể hiểu mọi ngữ cảnh câu lệnh tự nhiên và trò chuyện mọi chủ đề cùng bạn."
        )
        return False

    # Kết nối trực tiếp Google Calendar qua Apps Script Webhook URL hoặc xem cài đặt /gcal
    m_gcal_url = re.match(
        r"^(?:/gcal\s+)?(https://script\.google\.com/(?:a/macros/[^/]+/)?macros/s/[A-Za-z0-9_\-]+/exec\S*)$",
        text.strip(),
        flags=re.IGNORECASE,
    )
    if m_gcal_url:
        raw_url = m_gcal_url.group(1).strip()
        client.send_message(chat_id, "⏳ Đang kiểm tra kết nối tới Google Apps Script của bạn...")
        res = gcal_bridge.save_webhook_url(raw_url)
        if res.get("ok"):
            cfg["gcal_webhook_url"] = res["url"]
            client.send_message(chat_id, res["reply"])
        else:
            client.send_message(chat_id, res.get("error", "❌ Không kết nối được Google Calendar."))
        return False

    if text.strip().lower() in (
        "/gcal", "cài đặt lịch google", "cai dat lich google",
        "kết nối lịch google", "ket noi lich google", "cài lịch google", "cai lich google"
    ):
        _send_gcal_setup_guide(client, chat_id, include_status=True)
        return False

    if text.startswith("/ls"):
        arg = text[3:].strip() or "~"
        view_text, kb = format_dir_view(arg, chat_id)
        client.send_message(chat_id, view_text, reply_markup=kb)
        return False

    if text.startswith("/find"):
        parts = text[5:].strip().split(" in ", 1)
        kw = parts[0].strip()
        root = parts[1].strip() if len(parts) > 1 else "~"
        if not kw:
            client.send_message(chat_id, "ℹ️ Cú pháp: /find <từ_khoá> hoặc /find <từ_khoá> in <thư_mục>")
            return False
        res = search_files(kw, root)
        if not res.get("ok"):
            client.send_message(chat_id, f"❌ {res.get('error')}")
            return False
        matches = res.get("matches", [])
        if not matches:
            client.send_message(chat_id, f"🔍 Không tìm thấy file nào khớp '{kw}' trong {res['root']}.")
            return False
        lines = [f"🔍 Tìm thấy {len(matches)} kết quả cho '{kw}':\n"]
        kb = []
        for m in matches[:15]:
            icon = "📁" if m["is_dir"] else "📄"
            lines.append(f"{icon} {m['path']} ({m['size']})")
            pid = register_path(m["path"])
            kb.append([{"text": f"{icon} {Path(m['path']).name}", "callback_data": f"open:{pid}"}])
        client.send_message(chat_id, "\n".join(lines), reply_markup={"inline_keyboard": kb})
        return False

    if text.startswith("/cp ") or text.startswith("/mv "):
        is_copy = text.startswith("/cp ")
        body = text[4:].strip()
        if "->" not in body:
            cmd = "/cp" if is_copy else "/mv"
            client.send_message(chat_id, f"ℹ️ Cú pháp: {cmd} <đường_dẫn_nguồn> -> <đường_dẫn_đích>")
            return False
        src_str, dst_str = [p.strip() for p in body.split("->", 1)]
        res = safe_copy(src_str, dst_str) if is_copy else safe_move(src_str, dst_str)
        if res.get("ok"):
            action_vn = "Sao chép" if is_copy else "Dời"
            client.send_message(
                chat_id,
                f"✅ {action_vn} thành công!\n• Nguồn: {res['src']}\n• Đích: {res['dst']}"
            )
        else:
            client.send_message(chat_id, f"❌ {res.get('error')}")
        return False

    # Hot-reload safe_fs and nl_engine while preserving PENDING_CONFIRM and LAST_CONTEXT state
    print(f"[📩 Yêu cầu từ Telegram]: {text}", flush=True)
    saved_pending = dict(getattr(nl_engine, "PENDING_CONFIRM", {}))
    saved_context = dict(getattr(nl_engine, "LAST_CONTEXT", {}))
    importlib.reload(safe_fs)
    importlib.reload(nl_engine)
    nl_engine.PENDING_CONFIRM.update(saved_pending)
    nl_engine.LAST_CONTEXT.update(saved_context)

    nl_res = nl_engine.parse_and_execute_nl(text, chat_id=chat_id)
    if nl_res.get("handled"):
        send_nl_response(client, chat_id, nl_res)
        print(f"[✅ Đã xử lý tự động]: {nl_res.get('reply', '')[:120]}...", flush=True)
        return False

    # Unrecognized complex request -> Queue for Antigravity AI Assistant!
    entry = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "chat_id": chat_id,
        "user_id": user_id,
        "text": text,
    }
    with open(INBOX_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    client.send_message(
        chat_id,
        f"🤖 Đã chuyển yêu cầu nâng cao cho Antigravity xử lý:\n\"{text}\"\n⏳ Đang thực hiện trên máy Mac..."
    )
    return True


def handle_callback(client: TelegramClient, cfg: dict, cb: dict) -> None:
    cb_id = cb["id"]
    user_id = cb.get("from", {}).get("id")
    msg = cb.get("message", {})
    chat_id = msg.get("chat", {}).get("id")
    data = cb.get("data", "")

    owner_id = cfg.get("owner_id")
    if owner_id is not None and user_id != owner_id:
        client.answer_callback(cb_id, "⛔ Không có quyền.")
        return

    client.answer_callback(cb_id)

    if data == "cancel_nl":
        nl_engine.PENDING_CONFIRM.pop(chat_id, None)
        safe_fs.pop_zalo_pending()
        client.send_message(chat_id, "✅ Đã huỷ thao tác.")
        return

    if data == "do_update":
        import updater
        client.send_message(chat_id, "⏳ Đang tải và áp dụng bản cập nhật từ máy chủ...")
        res = updater.check_for_updates()
        if not res.get("has_update") or not res.get("manifest"):
            client.send_message(chat_id, "⚠️ Không tìm thấy gói cập nhật hợp lệ.")
            return
        up_res = updater.perform_update(res["manifest"])
        if up_res.get("ok"):
            client.send_message(
                chat_id,
                f"🎉 ĐÃ CẬP NHẬT THÀNH CÔNG LÊN v{up_res.get('version')}!\n🔄 Đang khởi động lại trợ lý..."
            )
            time.sleep(1)
            updater.restart_service()
        else:
            client.send_message(chat_id, f"❌ Lỗi cập nhật: {up_res.get('error')}")
        return

    if data == "zalo_send":
        pending = safe_fs.pop_zalo_pending()
        if not pending:
            client.send_message(chat_id, "⚠️ Không có tin nhắn Zalo nào đang chờ gửi hoặc tin nhắn đã hết hạn (quá 1 giờ).")
            return

        to = pending.get("to", "")
        text_to_send = pending.get("text", "")
        client.send_message(chat_id, f"🚀 Đang mở Zalo trên máy Mac và gửi tin nhắn cho: {to}...")

        try:
            import zalo_sender
            result = zalo_sender.send_zalo_message(to, text_to_send, really_send=True)
            if result.get("ok"):
                client.send_message(
                    chat_id,
                    f"✅ ĐÃ GỬI ZALO THÀNH CÔNG CHO: {to}\n\n📝 Nội dung đã gửi:\n{text_to_send}"
                )
            else:
                err = result.get("error", "Lỗi không xác định")
                client.send_message(
                    chat_id,
                    f"❌ KHÔNG THỂ GỬI QUA ZALO:\n{err}\n\n"
                    f"💡 Mẹo khắc phục:\n"
                    f"1. Đảm bảo app Zalo trên máy Mac đang mở và đã đăng nhập.\n"
                    f"2. Đảm bảo màn hình không bị khóa.\n"
                    f"3. Cấp quyền Trợ năng (Accessibility) cho Python tại:\n"
                    f"   Cài đặt hệ thống ➔ Quyền riêng tư & Bảo mật ➔ Trợ năng (Accessibility) ➔ Bật Python."
                )
        except Exception as e:
            client.send_message(chat_id, f"❌ Lỗi khi thực hiện gửi Zalo: {e}")
        return

    if data == "home":
        client.send_message(chat_id, "🏠 MENU QUẢN LÝ FILE AN TOÀN:", reply_markup=build_home_keyboard())
        return

    if data == "drives":
        view_text, kb = format_drives_view()
        client.send_message(chat_id, view_text, reply_markup=kb)
        return

    if data == "gdrive_home":
        gd_root = find_google_drive_root(auto_launch=True)
        if gd_root and gd_root.exists():
            view_text, kb = format_dir_view(str(gd_root), chat_id)
            client.send_message(chat_id, view_text, reply_markup=kb)
        else:
            client.send_message(
                chat_id,
                "⚠️ Chưa tìm thấy thư mục Google Drive trên máy Mac này.\n\n"
                "💡 Để bot tìm và mở file trên Google Drive:\n"
                "1. Hãy cài đặt và đăng nhập ứng dụng **Google Drive for Desktop** trên máy Mac.\n"
                "2. Đảm bảo ứng dụng Google Drive đang chạy trên thanh menu góc trên màn hình.",
                reply_markup=build_home_keyboard(),
            )
        return

    if data == "trash_view":
        summary = safe_fs.get_trash_summary()
        kb = []
        for it in summary.get("items", [])[:6]:
            pid = register_path(it["name"])
            short_name = it["name"] if len(it["name"]) <= 28 else it["name"][:25] + "..."
            kb.append([{"text": f"♻️ Khôi phục: {short_name}", "callback_data": f"restore_trash:{pid}"}])
        kb.append([{"text": "🏠 Về Menu chính", "callback_data": "home"}])
        client.send_message(chat_id, summary.get("reply", ""), reply_markup={"inline_keyboard": kb})
        return

    if data.startswith("restore_trash:"):
        pid = data.split(":", 1)[1]
        item_name = get_registered_path(pid)
        if not item_name:
            summary = safe_fs.get_trash_summary()
            kb = []
            for it in summary.get("items", [])[:6]:
                npid = register_path(it["name"])
                sn = it["name"] if len(it["name"]) <= 28 else it["name"][:25] + "..."
                kb.append([{"text": f"♻️ Khôi phục: {sn}", "callback_data": f"restore_trash:{npid}"}])
            kb.append([{"text": "🏠 Về Menu chính", "callback_data": "home"}])
            client.send_message(
                chat_id,
                "⚠️ Phiên nút bấm đã hết hạn. Danh sách Thùng rác mới nhất:\n\n" + summary.get("reply", ""),
                reply_markup={"inline_keyboard": kb},
            )
            return
        client.send_message(chat_id, f"♻️ Đang khôi phục '{item_name}' từ Thùng rác về lại thư mục ban đầu...")
        res = safe_fs.restore_from_trash(item_name)
        kb = [
            [{"text": "🗑 Xem lại Thùng rác", "callback_data": "trash_view"}],
            [{"text": "🏠 Về Menu chính", "callback_data": "home"}],
        ]
        client.send_message(
            chat_id,
            res.get("reply") or res.get("error", "❌ Không thể khôi phục mục này."),
            reply_markup={"inline_keyboard": kb},
        )
        return

    if data == "apps_view":
        categories = safe_fs.list_popular_apps()
        lines = ["🚀 MỞ ỨNG DỤNG TỪ XA TRÊN MÁY MAC:\nBấm nút bên dưới để khởi chạy nhanh ứng dụng:\n"]
        kb = []
        for cat in categories:
            row = []
            for name, path in cat["apps"][:4]:
                short_name = name.replace("Adobe ", "").replace(" 2027", "").replace(" 2026", "").replace(" Browser", "")
                row.append({"text": f"🚀 {short_name}", "callback_data": f"launch_app:{name}"})
                if len(row) == 2:
                    kb.append(row)
                    row = []
            if row:
                kb.append(row)
        kb.append([{"text": "🏠 Về Menu chính", "callback_data": "home"}])
        client.send_message(chat_id, "\n".join(lines), reply_markup={"inline_keyboard": kb})
        return

    if data.startswith("launch_app:"):
        app_name = data.split(":", 1)[1]
        res = safe_fs.open_application(app_name)
        client.send_message(chat_id, res.get("reply") or res.get("error", "Không thể mở ứng dụng."))
        return

    def _send_rc_capture(caption_text: str, with_grid: bool = False, hd: bool = False) -> None:
        cap = mac_remote.capture_screen(with_grid=with_grid, hd=hd)
        if not cap.get("ok"):
            markup = None
            if cap.get("permission_error"):
                markup = {
                    "inline_keyboard": [
                        [{"text": "⚙️ Mở Cài đặt Ghi màn hình", "callback_data": "rc_open_screen_perm"}],
                        [{"text": "🏠 Về Menu chính", "callback_data": "home"}],
                    ]
                }
            client.send_message(chat_id, cap.get("error", "❌ Không thể chụp màn hình."), reply_markup=markup)
            return
        if hd:
            client.send_document(
                chat_id,
                cap["path"],
                caption=caption_text[:1020],
                reply_markup=mac_remote.build_remote_keyboard(grid_mode=False),
            )
            return
        client.send_photo(
            chat_id,
            cap["path"],
            caption=caption_text[:1020],
            reply_markup=mac_remote.build_remote_keyboard(grid_mode=with_grid),
        )

    if data == "rc_snap":
        front = mac_remote.get_running_apps().get("front") or "macOS"
        _send_rc_capture(f"📸 ẢNH MÀN HÌNH THỰC TẾ\n• App đang mở chính: *{front}*", with_grid=False)
        return

    if data == "rc_grid":
        _send_rc_capture(
            "🎯 ẢNH MÀN HÌNH KÈM LƯỚI TOẠ ĐỘ (A1–H6)\n👉 Nhắn `click C3` (hoặc `double click D4`, `click phải B2`) để bấm!",
            with_grid=True,
        )
        return

    if data == "rc_hd":
        front = mac_remote.get_running_apps().get("front") or "macOS"
        _send_rc_capture(f"🔍 ẢNH MÀN HÌNH GỐC HD KHÔNG NÉN\n• App đang mở chính: *{front}*", hd=True)
        return

    if data == "rc_panel":
        _send_rc_capture(
            "🎛 TRUNG TÂM ĐIỀU KHIỂN MÁY MAC TỪ XA:\n"
            "• Click ô lưới: `click C3`, `double click D4`, `click phải B2`\n"
            "• AI Vision Click: `bấm vào nút Xuất video`, `click vào Zalo`\n"
            "• Gõ chữ & phím: `gõ Xin chào rồi enter`, `bấm cmd+s`\n"
            "• Hoặc chạm trực tiếp vào bảng nút bấm bên dưới!",
            with_grid=True,
        )
        return

    if data.startswith("rc_key:"):
        kspec = data.split(":", 1)[1]
        res = mac_remote.press_key(kspec)
        if not res.get("ok"):
            client.send_message(chat_id, res.get("error", "❌ Không thể bấm phím."))
            return
        time.sleep(0.6)
        _send_rc_capture(res.get("reply", f"⌨️ Đã bấm phím `{kspec}`"), with_grid=False)
        return

    if data.startswith("rc_scroll:"):
        direction = data.split(":", 1)[1]
        res = mac_remote.mouse_scroll(direction)
        if not res.get("ok"):
            client.send_message(chat_id, res.get("error", "❌ Không thể cuộn chuột."))
            return
        time.sleep(0.5)
        _send_rc_capture(res.get("reply", "🖱 Đã cuộn màn hình."), with_grid=False)
        return

    if data.startswith("rc_vol:"):
        act = data.split(":", 1)[1]
        res = mac_remote.set_volume(act)
        client.send_message(
            chat_id,
            res.get("reply") or res.get("error", "❌ Lỗi âm lượng."),
            reply_markup=mac_remote.build_remote_keyboard(grid_mode=False),
        )
        return

    if data == "rc_lock":
        res = mac_remote.lock_screen()
        client.send_message(
            chat_id,
            res.get("reply") or res.get("error", "❌ Không thể khoá màn hình."),
            reply_markup=mac_remote.build_remote_keyboard(grid_mode=False),
        )
        return

    if data == "rc_status":
        st = mac_remote.get_system_status()
        kb = [
            [
                {"text": "📸 Chụp Màn Hình", "callback_data": "rc_snap"},
                {"text": "📱 App đang chạy", "callback_data": "rc_apps"},
            ],
            [{"text": "🏠 Về Menu chính", "callback_data": "home"}],
        ]
        client.send_message(chat_id, st.get("reply", ""), reply_markup={"inline_keyboard": kb})
        return

    if data == "rc_apps":
        info = mac_remote.get_running_apps()
        front = info.get("front") or "Không rõ"
        apps = info.get("apps", [])[:8]
        kb = []
        for app_name in apps:
            aid = register_rc_app(app_name)
            short_n = app_name[:22] + "..." if len(app_name) > 24 else app_name
            kb.append([
                {"text": f"🪟 Mở: {short_n}", "callback_data": f"rc_focus:{aid}"},
                {"text": "❌ Đóng", "callback_data": f"rc_quit:{aid}"},
            ])
        kb.append([
            {"text": "📸 Chụp Màn Hình", "callback_data": "rc_snap"},
            {"text": "🏠 Về Menu chính", "callback_data": "home"},
        ])
        client.send_message(
            chat_id,
            f"📱 CÁC ỨNG DỤNG ĐANG CHẠY TRÊN MÁY MAC:\n• Đang mở phía trước: *{front}*\n👉 Bấm *Mở* để chuyển cửa sổ ngay và chụp ảnh màn hình, hoặc *Đóng* để thoát nhẹ nhàng:",
            reply_markup={"inline_keyboard": kb},
        )
        return

    if data.startswith("rc_focus:"):
        aid = data.split(":", 1)[1]
        app_name = get_rc_app(aid)
        if not app_name:
            client.send_message(chat_id, "⚠️ Phiên nút bấm đã hết hạn, vui lòng bấm lại [📱 App đang chạy].")
            return
        res = mac_remote.focus_app(app_name)
        if not res.get("ok"):
            client.send_message(chat_id, res.get("error", "❌ Không thể chuyển ứng dụng."))
            return
        time.sleep(0.5)
        _send_rc_capture(res.get("reply", f"🪟 Đã chuyển sang *{app_name}*."), with_grid=False)
        return

    if data.startswith("rc_quit:"):
        aid = data.split(":", 1)[1]
        app_name = get_rc_app(aid)
        if not app_name:
            client.send_message(chat_id, "⚠️ Phiên nút bấm đã hết hạn, vui lòng bấm lại [📱 App đang chạy].")
            return
        res = mac_remote.quit_app(app_name)
        client.send_message(
            chat_id,
            res.get("reply") or res.get("error", "❌ Không thể thoát ứng dụng."),
            reply_markup=mac_remote.build_remote_keyboard(grid_mode=False),
        )
        return

    if data.startswith("rc_remote:"):
        tool = data.split(":", 1)[1]
        client.send_message(chat_id, f"⏳ Đang mở {tool.capitalize()} và chụp màn hình chứa mã kết nối...")
        res = mac_remote.launch_remote_desktop(tool)
        if res.get("photo_path") and os.path.exists(res["photo_path"]):
            client.send_photo(
                chat_id,
                res["photo_path"],
                caption=(res.get("reply") or "")[:1020],
                reply_markup=mac_remote.build_remote_keyboard(grid_mode=False),
            )
        else:
            client.send_message(chat_id, res.get("reply") or res.get("error", "❌ Không thể mở Remote Desktop."))
        return

    if data == "rc_open_screen_perm":
        res = mac_remote.open_screen_recording_settings()
        kb = [[{"text": "🔄 Thử chụp lại ngay", "callback_data": "rc_snap"}], [{"text": "🏠 Về Menu chính", "callback_data": "home"}]]
        client.send_message(
            chat_id,
            res.get("reply") or res.get("error", ""),
            reply_markup={"inline_keyboard": kb},
        )
        return

    if data == "gcal_setup_guide":
        _send_gcal_setup_guide(client, chat_id, include_status=True)
        return

    if data == "gcal_open_mac_accounts":
        res = gcal_bridge.open_macos_internet_accounts()
        kb = [
            [{"text": "📋 Lấy mã Google Apps Script", "callback_data": "gcal_show_script"}],
            [{"text": "🏠 Về Menu chính", "callback_data": "home"}],
        ]
        client.send_message(
            chat_id,
            res.get("reply") or res.get("error", ""),
            reply_markup={"inline_keyboard": kb},
        )
        return

    if data == "gcal_show_script":
        guide = (
            "📋 CÁCH CÀI GOOGLE APPS SCRIPT (1 PHÚT — GHI & ĐỌC LỊCH TRỰC TIẾP):\n\n"
            "1. Mở https://script.google.com → Bấm 'Dự án mới' (New project).\n"
            "2. Xoá hết code mẫu và dán toàn bộ đoạn code ở tin nhắn ngay dưới vào.\n"
            "3. Bấm 'Triển khai' (Deploy) → 'Tạo mục triển khai mới' (New deployment) → Loại: 'Ứng dụng web' (Web app):\n"
            "   • Thực thi dưới danh nghĩa (Execute as): Tôi (Me)\n"
            "   • Ai có quyền truy cập (Who has access): Bất kỳ ai (Anyone)\n"
            "4. Bấm Triển khai → Cấp quyền Google Calendar → Copy đường dẫn Web app (/exec) và DÁN THẲNG VÀO CHAT NÀY là xong!"
        )
        client.send_message(chat_id, guide)
        client.send_message(chat_id, gcal_bridge.APPS_SCRIPT_TEMPLATE)
        return

    if data.startswith("qcp:") or data.startswith("qmv:") or data.startswith("qgd:"):
        parts = data.split(":")
        if len(parts) == 3:
            op, src_pid, dst_pid = parts
            src_path = get_registered_path(src_pid)
            dst_path = get_registered_path(dst_pid)
            nl_engine.PENDING_CONFIRM.pop(chat_id, None)
            if src_path and dst_path:
                is_copy = op in ("qcp", "qgd")
                sz_info = safe_fs.get_folder_size(src_path)
                sz_str = sz_info.get("size_human", "?") if sz_info.get("ok") else "?"
                res = safe_fs.safe_copy(src_path, dst_path) if is_copy else safe_fs.safe_move(src_path, dst_path)
                if res.get("ok"):
                    if op == "qgd":
                        client.send_message(
                            chat_id,
                            f"☁️ ĐÃ UPLOAD LÊN GOOGLE DRIVE THÀNH CÔNG!\n"
                            f"• Tên: {Path(src_path).name} ({sz_str})\n"
                            f"• Nguồn: {res['src']}\n"
                            f"• Đích Google Drive: {res['dst']}\n"
                            f"🔄 Google Drive trên máy Mac đang tự động đồng bộ lên mây!"
                        )
                    else:
                        act_vn = "SAO CHÉP" if is_copy else "CHUYỂN (DỜI)"
                        client.send_message(
                            chat_id,
                            f"✅ ĐÃ {act_vn} THÀNH CÔNG!\n"
                            f"• Tên: {Path(src_path).name} ({sz_str})\n"
                            f"• Nguồn: {res['src']}\n"
                            f"• Đích: {res['dst']}"
                        )
                else:
                    client.send_message(chat_id, f"❌ Lỗi: {res.get('error')}")
                return

    if data.startswith("evict:"):
        pid = data.split(":", 1)[1]
        path_str = get_registered_path(pid)
        if not path_str or not Path(path_str).exists():
            client.send_message(chat_id, "⚠️ Phiên đường dẫn đã hết hạn hoặc mục không còn tồn tại.", reply_markup=build_home_keyboard())
            return
        import gdrive_offload
        if not gdrive_offload.is_inside_google_drive(path_str):
            client.send_message(chat_id, "❌ Mục này không nằm trong Google Drive. Không thể xoá bản tải về.")
            return
        st = gdrive_offload.check_sync_status(path_str)
        if st["ok_100"]:
            client.send_message(chat_id, f"🧹 Đang thực hiện 'Xoá bản tải về' cho '{st['name']}'...")
            res = gdrive_offload.offload_local_copy(path_str, require_stable=False)
            client.send_message(chat_id, gdrive_offload.format_offload_result(res))
        else:
            pct = (st["uploaded"] * 100 // st["total"]) if st["total"] else 0
            gdrive_offload.schedule_offload_when_synced(path_str, notify=True)
            client.send_message(
                chat_id,
                f"⏳ CHƯA THỂ XOÁ BẢN TẢI VỀ NGAY LÚC NÀY ĐỂ BẢO VỆ DỮ LIỆU:\n\n"
                f"• Mục: {st['name']}\n"
                f"• Tiến độ: {st['uploaded']}/{st['total']} file đã lên đám mây ({pct}%)\n"
                f"• Dung lượng: {safe_fs.format_size(st['logical_bytes'])}\n\n"
                f"🛡️ QUY TẮC AN TOÀN TUYỆT ĐỐI:\n"
                f"Bot chỉ xoá bản tải về khi 100% file đã đồng bộ thành công lên Google Drive để tránh thiếu file!\n\n"
                f"✅ Bot đã lên lịch tự động: Ngay khi đồng bộ đủ 100%, bot sẽ tự động xoá bản tải về và thông báo cho bạn."
            )
        return

    if data.startswith("open:"):
        pid = data.split(":", 1)[1]
        path_str = get_registered_path(pid)
        if not path_str:
            client.send_message(chat_id, "⚠️ Phiên đường dẫn đã hết hạn, vui lòng chọn lại từ Menu.", reply_markup=build_home_keyboard())
            return
        view_text, kb = format_dir_view(path_str, chat_id)
        client.send_message(chat_id, view_text, reply_markup=kb)
        return

    if data.startswith("pick_cp:") or data.startswith("pick_mv:"):
        action, pid = data.split(":", 1)
        src_path = get_registered_path(pid)
        if not src_path:
            client.send_message(chat_id, "⚠️ Phiên đường dẫn đã hết hạn.", reply_markup=build_home_keyboard())
            return
        mode = "cp" if action == "pick_cp" else "mv"
        USER_STATE[chat_id] = {"action": mode, "src": src_path}
        parent_dir = str(Path(src_path).parent)
        view_text, kb = format_dir_view(parent_dir, chat_id)
        client.send_message(chat_id, view_text, reply_markup=kb)
        return

    if data.startswith("cancel:"):
        pid = data.split(":", 1)[1]
        USER_STATE.pop(chat_id, None)
        path_str = get_registered_path(pid) or "~"
        view_text, kb = format_dir_view(path_str, chat_id)
        client.send_message(chat_id, "✅ Đã huỷ thao tác Copy/Move.\n\n" + view_text, reply_markup=kb)
        return

    if data.startswith("paste:"):
        pid = data.split(":", 1)[1]
        dst_dir = get_registered_path(pid)
        state = USER_STATE.pop(chat_id, None)
        if not dst_dir or not state:
            client.send_message(chat_id, "⚠️ Không có thao tác Copy/Move nào đang chờ.", reply_markup=build_home_keyboard())
            return
        src_path = state["src"]
        is_copy = state["action"] == "cp"
        res = safe_copy(src_path, dst_dir) if is_copy else safe_move(src_path, dst_dir)
        if res.get("ok"):
            act_vn = "SAO CHÉP (COPY)" if is_copy else "DỜI (MOVE)"
            client.send_message(
                chat_id,
                f"✅ ĐÃ {act_vn} THÀNH CÔNG!\n• Nguồn: {res['src']}\n• Đích: {res['dst']}"
            )
        else:
            client.send_message(chat_id, f"❌ Lỗi: {res.get('error')}")
        view_text, kb = format_dir_view(dst_dir, chat_id)
        client.send_message(chat_id, view_text, reply_markup=kb)


def main():
    args = sys.argv[1:]
    cfg = load_config()

    # Subcommand: send a message back to the owner on Telegram
    if len(args) >= 2 and args[0] == "--send":
        token = cfg.get("bot_token")
        chat_id = cfg.get("chat_id")
        if not token or not chat_id:
            print("Chưa có bot_token hoặc chat_id trong config.json", file=sys.stderr)
            sys.exit(1)
        client = TelegramClient(token)
        client.send_message(chat_id, args[1])
        print("Đã gửi phản hồi tới Telegram.")
        return

    if len(args) >= 2 and args[0] == "--find":
        kw = args[1]
        roots = [args[2]] if len(args) >= 3 else ["~", "/Volumes"]
        all_matches = []
        for r in roots:
            res = search_files(kw, r, max_results=30)
            if res.get("ok"):
                all_matches.extend(res.get("matches", []))
        print(json.dumps(all_matches, indent=2, ensure_ascii=False))
        return

    if len(args) >= 2 and args[0] == "--ls":
        res = list_directory(args[1], limit=100)
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return

    if len(args) >= 2 and args[0] == "--size":
        res = get_folder_size(args[1])
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return

    if len(args) >= 3 and args[0] == "--copy":
        res = safe_copy(args[1], args[2])
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return

    if len(args) >= 3 and args[0] == "--move":
        res = safe_move(args[1], args[2])
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return

    if len(args) >= 2 and args[0] == "--gdrive":
        sub = args[2] if len(args) >= 3 else ""
        res = upload_to_google_drive(args[1], sub)
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return

    if len(args) >= 1 and args[0] == "--install-service":
        import shutil
        import subprocess
        plist_src = BASE_DIR / "com.thienung.telegramfilebot.plist"
        launch_agents_dir = Path.home() / "Library" / "LaunchAgents"
        launch_agents_dir.mkdir(parents=True, exist_ok=True)
        plist_dst = launch_agents_dir / "com.thienung.telegramfilebot.plist"
        shutil.copy2(plist_src, plist_dst)
        uid = os.getuid()
        subprocess.run(["launchctl", "bootout", f"gui/{uid}", str(plist_dst)], capture_output=True)
        res = subprocess.run(["launchctl", "bootstrap", f"gui/{uid}", str(plist_dst)], capture_output=True, text=True)
        if res.returncode != 0:
            subprocess.run(["launchctl", "unload", str(plist_dst)], capture_output=True)
            subprocess.run(["launchctl", "load", "-w", str(plist_dst)], check=True)
        print(f"✅ Đã cài đặt và khởi chạy dịch vụ chạy ngầm 24/7 tại: {plist_dst}")
        return

    if len(args) >= 1 and args[0] == "--enable-clamshell":
        import subprocess
        apple_script = (
            'do shell script "/usr/bin/pmset -a disablesleep 1 && '
            '/usr/bin/pmset -a sleep 0 && '
            '/usr/bin/pmset -a tcpkeepalive 1 && '
            '/usr/bin/pmset -a womp 1" with administrator privileges'
        )
        res = subprocess.run(["/usr/bin/osascript", "-e", apple_script], capture_output=True, text=True)
        if res.returncode == 0:
            print("✅ Đã bật chế độ CHỐNG NGỦ KHI GẬP NẮP (disablesleep = 1)!")
        else:
            print(f"❌ Không thể bật (cần xác nhận mật khẩu máy Mac): {res.stderr.strip()}", file=sys.stderr)
            sys.exit(1)
        return

    if len(args) >= 1 and args[0] == "--disable-clamshell":
        import subprocess
        apple_script = 'do shell script "/usr/bin/pmset -a disablesleep 0" with administrator privileges'
        res = subprocess.run(["/usr/bin/osascript", "-e", apple_script], capture_output=True, text=True)
        if res.returncode == 0:
            print("✅ Đã tắt chế độ chống ngủ khi gập nắp (trở về mặc định)!")
        else:
            print(f"❌ Lỗi: {res.stderr.strip()}", file=sys.stderr)
            sys.exit(1)
        return

    # Mode: exit after receiving 1 natural-language task so Antigravity wakes up
    exit_on_nl_task = "--listen-for-ai" in args

    try:
        signal.signal(signal.SIGHUP, signal.SIG_IGN)
    except Exception:
        pass

    lock_file_path = BASE_DIR / "bot.lock"
    lock_fp = None
    try:
        lock_fp = open(lock_file_path, "a+", encoding="utf-8")
        fcntl.flock(lock_fp.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        lock_fp.seek(0)
        lock_fp.truncate()
        lock_fp.write(str(os.getpid()))
        lock_fp.flush()
    except OSError:
        print("ℹ️ Một tiến trình bot.py khác đang chạy (đã giữ bot.lock). Thoát để tránh trùng lặp 409.", flush=True)
        sys.exit(0)

    token = os.environ.get("TELEGRAM_BOT_TOKEN") or cfg.get("bot_token")
    if not token:
        print("Chưa cấu hình TELEGRAM_BOT_TOKEN trong config.json", file=sys.stderr)
        sys.exit(1)

    if cfg.get("bot_token") != token:
        cfg["bot_token"] = token
        save_config(cfg)

    client = TelegramClient(token)
    try:
        client.call("deleteWebhook", {"drop_pending_updates": False}, timeout=10)
    except Exception:
        pass

    me = client.call("getMe")
    bot_username = me.get("result", {}).get("username", "Bot")
    print(f"🚀 Telegram Bot @{bot_username} đang hoạt động! (Chế độ cấm xoá file: BẬT)", flush=True)

    threading.Thread(target=write_system_snapshot, daemon=True).start()
    try:
        import gdrive_offload
        resumed = gdrive_offload.resume_pending_jobs()
        if resumed > 0:
            print(f"🔄 Đã khôi phục {resumed} tác vụ tự động xoá bản tải về Google Drive.", flush=True)
    except Exception as e:
        print(f"⚠️ Lỗi khôi phục tác vụ xoá bản tải về: {e}", flush=True)
    t_outbox = threading.Thread(target=outbox_worker, args=(client, cfg), daemon=True)
    t_outbox.start()
    t_update = threading.Thread(target=update_checker_worker, args=(client, cfg), daemon=True)
    t_update.start()

    # (Đã bỏ phát lại inbox.jsonl khi khởi động: trước đây nó gửi lại các lệnh cũ mỗi lần restart.)
    try:
        INBOX_PATH.write_text("", encoding="utf-8")
    except Exception:
        pass

    offset = cfg.get("last_update_id", 0)
    while True:
        try:
            cfg_latest = load_config()
            if cfg_latest:
                for k in ("owner_id", "chat_id", "username", "allowed_users", "default_gdrive_folder"):
                    if k in cfg_latest:
                        cfg[k] = cfg_latest[k]
            resp = client.call("getUpdates", {"offset": offset, "timeout": 25}, timeout=35)
            updates = resp.get("result", [])
            for upd in updates:
                offset = upd["update_id"] + 1
                cfg["last_update_id"] = offset
                save_config(cfg)

                if "message" in upd:
                    handle_message(client, cfg, upd["message"])
                elif "callback_query" in upd:
                    handle_callback(client, cfg, upd["callback_query"])
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"[Cảnh báo kết nối]: {e}", file=sys.stderr, flush=True)
            time.sleep(3)


if __name__ == "__main__":
    main()
