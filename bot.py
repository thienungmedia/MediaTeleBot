#!/usr/bin/env python3
from __future__ import annotations
"""MediaTeleBot Telegram polling and command routing."""

import json
import os
import re
import signal
import sys
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from runtime import BASE_DIR, CONFIG_PATH, IS_MAC, edit_config, lock_instance, read_config
from runtime import open_https as _urlopen_robust

import pairing
import updater

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

def load_config() -> dict:
    return read_config(CONFIG_PATH)


def update_config(change):
    return edit_config(change, CONFIG_PATH)


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


USER_STATE: dict[int, dict] = {}


def build_home_keyboard() -> dict:
    home = Path.home()
    buttons = [
        [
            {"text": "💽 Danh sách ổ đĩa", "callback_data": "drives"},
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
    return {"inline_keyboard": buttons if IS_MAC else buttons[:3]}


def format_drives_view() -> tuple[str, dict]:
    drives = list_drives()
    lines = ["💽 DANH SÁCH Ổ ĐĨA:\n"]
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


def _send_gcal_setup_guide(client: TelegramClient, chat_id: int) -> None:
    status = gcal_bridge.get_calendar_sync_status()
    lines = ["Cấu hình lịch trên máy chạy MediaTeleBot."]
    if status["legacy_webhook"]:
        lines.append("Phát hiện URL Apps Script kiểu cũ. Hãy vô hiệu hóa deployment đó trong Google Apps Script.")
    if status["has_webhook"]:
        lines.append("Đã cấu hình kết nối Google Apps Script có khóa.")
    elif status["macos_calendar"]:
        lines.append(f"Lịch trên macOS đã chọn: {status['macos_calendar']}")
    else:
        lines.append("Đang dùng lịch lưu cục bộ.")
    kb = [[{"text": "Lấy mã Google Apps Script", "callback_data": "gcal_show_script"}]]
    if IS_MAC:
        kb.append([{"text": "Mở Tài khoản Internet trên Mac", "callback_data": "gcal_open_mac_accounts"}])
    client.send_message(chat_id, "\n".join(lines), reply_markup={"inline_keyboard": kb})


def handle_message(client: TelegramClient, cfg: dict, msg: dict) -> None:
    user_id = pairing.private_sender(msg)
    if user_id is None:
        return
    chat_id = user_id
    text = (msg.get("text") or "").strip()
    if not text:
        return

    owner_id = cfg.get("owner_id")
    if not owner_id:
        parts = text.split()
        paired = len(parts) == 2 and parts[0].lower() == "/pair" and update_config(
            lambda current: current.get("bot_token") == cfg.get("bot_token") and pairing.claim(current, parts[1], msg["from"])
        )
        if paired:
            client.send_message(chat_id, "✅ Đã ghép cặp máy này với tài khoản Telegram của bạn.", build_home_keyboard())
        else:
            client.send_message(chat_id, "Mở MediaTeleBot trên máy cần điều khiển để lấy mã. Sau đó nhắn /pair kèm mã trong chat riêng này.")
        return

    if user_id != owner_id:
        allowed = cfg.get("allowed_users") or []
        if user_id in allowed:
            handle_collaborator(client, cfg, user_id, text)
        elif text.split()[0].lower() == "/start":
            client.send_message(chat_id, f"Bạn chưa có quyền. Telegram ID của bạn là {user_id}.")
        return

    match = re.fullmatch(r"(thêm thợ|them tho|/allow|/revoke)\s+([0-9]{1,16})", text, re.IGNORECASE)
    if match:
        target = int(match[2])
        allowed = set(cfg.get("allowed_users") or [])
        if match[1].lower() == "/revoke":
            allowed.discard(target)
        elif target > 0 and target != owner_id:
            allowed.add(target)
        update_config(lambda current: current.update(allowed_users=sorted(allowed)) if current.get("owner_id") == user_id else None)
        client.send_message(chat_id, "Đã cập nhật danh sách cộng tác viên. Họ chỉ dùng được /find trong các thư mục bạn chia sẻ từ máy chủ.")
        return

    if text.lower().startswith("/pair"):
        client.send_message(chat_id, "Máy này đã gắn với tài khoản Telegram của bạn.")
        return

    if text.startswith("/start") or text.startswith("/help"):
        welcome = (
            "✅ ĐÃ KẾT NỐI VỚI MÁY MAC CỦA BẠN!\n"
            "🔒 Chat riêng đã ghép cặp.\n\n"
            "💬 NHẮN TIẾNG VIỆT TỰ NHIÊN HOẶC BẤM NÚT BÊN DƯỚI:\n"
            "• 📁 File & Drive: \"tìm dự án 2510\", \"up file lên drive\", \"xoá bản tải về 2510\"\n"
            "• 💬 Gửi link Zalo: \"gửi link 2510 cho Anh Nam qua zalo\"\n"
            "• 📸 Màn hình & Điều khiển: \"chụp màn hình\", \"bấm vào nút Xuất\", \"tình trạng máy\"\n"
            "• 🚀 App & Thùng rác: \"mở premiere\", \"kiểm tra thùng rác\", \"khôi phục file X\"\n"
            "• 📅 Lịch làm việc: \"note lịch 20/12 quay sự kiện\", \"tuần này có lịch gì\"\n"
        )
        if not (cfg.get("gemini_api_key") or os.environ.get("GEMINI_API_KEY")):
            welcome += "\nCấu hình Gemini từ MediaTeleBot trên máy chủ."
        if not IS_MAC:
            welcome = ("✅ MediaTeleBot đã kết nối.\nDùng /ls, /find, /cp, /mv, /drives, /gcal hoặc nhắn lệnh quản lý file và lịch. "
                       "Điều khiển màn hình, Finder và Zalo cần macOS.")
        client.send_message(chat_id, welcome, reply_markup=build_home_keyboard())
        return

    if text.lower() in ("/update", "/version", "/capnhat"):
        reply, markup = updater.update_message()
        client.send_message(chat_id, reply, reply_markup=markup)
        return

    if text.startswith("/drives"):
        view_text, kb = format_drives_view()
        client.send_message(chat_id, view_text, reply_markup=kb)
        return

    if re.search(r"(?:^/(?:gemini|gcal)\s+|AIza[0-9A-Za-z_-]{35}|https://script\.google\.com/)", text, re.IGNORECASE):
        client.send_message(chat_id, "Hãy nhập khóa Gemini và thông tin kết nối lịch trực tiếp trên máy chủ. Nếu đã dán khóa vào Telegram, hãy thu hồi khóa đó.")
        return

    if text.strip().lower() in (
        "/gcal", "cài đặt lịch google", "cai dat lich google",
        "kết nối lịch google", "ket noi lich google", "cài lịch google", "cai lich google"
    ):
        _send_gcal_setup_guide(client, chat_id)
        return

    if text.startswith("/ls"):
        arg = text[3:].strip() or "~"
        view_text, kb = format_dir_view(arg, chat_id)
        client.send_message(chat_id, view_text, reply_markup=kb)
        return

    if text == "/size" or text.startswith("/size "):
        target = text[5:].strip() or "~"
        result = safe_fs.get_folder_size(target)
        reply = f"{result['path']} — {result['size_human']}" if result.get("ok") else result["error"]
        client.send_message(chat_id, reply)
        return

    if text.startswith("/find"):
        parts = text[5:].strip().split(" in ", 1)
        kw = parts[0].strip()
        root = parts[1].strip() if len(parts) > 1 else "~"
        if not kw:
            client.send_message(chat_id, "ℹ️ Cú pháp: /find <từ_khoá> hoặc /find <từ_khoá> in <thư_mục>")
            return
        res = search_files(kw, root)
        if not res.get("ok"):
            client.send_message(chat_id, f"❌ {res.get('error')}")
            return
        matches = res.get("matches", [])
        if not matches:
            client.send_message(chat_id, f"🔍 Không tìm thấy file nào khớp '{kw}' trong {res['root']}.")
            return
        lines = [f"🔍 Tìm thấy {len(matches)} kết quả cho '{kw}':\n"]
        kb = []
        for m in matches[:15]:
            icon = "📁" if m["is_dir"] else "📄"
            lines.append(f"{icon} {m['path']} ({m['size']})")
            pid = register_path(m["path"])
            kb.append([{"text": f"{icon} {Path(m['path']).name}", "callback_data": f"open:{pid}"}])
        client.send_message(chat_id, "\n".join(lines), reply_markup={"inline_keyboard": kb})
        return

    if text.startswith("/cp ") or text.startswith("/mv "):
        is_copy = text.startswith("/cp ")
        body = text[4:].strip()
        if "->" not in body:
            cmd = "/cp" if is_copy else "/mv"
            client.send_message(chat_id, f"ℹ️ Cú pháp: {cmd} <đường_dẫn_nguồn> -> <đường_dẫn_đích>")
            return
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
        return

    nl_res = nl_engine.parse_and_execute_nl(text, chat_id=chat_id)
    if nl_res.get("handled"):
        send_nl_response(client, chat_id, nl_res)
    else:
        client.send_message(chat_id, "Tôi chưa nhận ra lệnh này. Nhắn /help để xem các lệnh có sẵn.")
    return


def handle_collaborator(client: TelegramClient, cfg: dict, chat_id: int, text: str) -> None:
    keyword = text[6:].strip() if text.startswith("/find ") else ""
    roots = cfg.get("shared_roots") or []
    if not keyword or not roots:
        client.send_message(chat_id, "Cộng tác viên có thể dùng /find <từ khóa> trong các thư mục chủ máy đã chia sẻ.")
        return
    results = []
    for root in roots:
        results.extend(safe_fs.search_shared(keyword, root, limit=15 - len(results)))
        if len(results) >= 15:
            break
    client.send_message(chat_id, "\n".join(results)[:3500] or "Không tìm thấy trong các thư mục được chia sẻ.")


def handle_callback(client: TelegramClient, cfg: dict, cb: dict) -> None:
    cb_id = cb["id"]
    user_id = pairing.private_sender(cb.get("message") or {}, cb.get("from") or {})
    chat_id = user_id
    data = cb.get("data") or ""
    if user_id is None or user_id != cfg.get("owner_id"):
        client.answer_callback(cb_id, "⛔ Không có quyền.")
        return
    if not IS_MAC and data.startswith(("rc_", "trash_", "restore_trash:", "zalo_", "apps_", "launch_app:", "evict:", "gcal_open_mac")):
        client.answer_callback(cb_id, "Tính năng này cần macOS.")
        return
    client.answer_callback(cb_id)

    if data == "cancel_nl":
        nl_engine.PENDING_CONFIRM.pop(chat_id, None)
        safe_fs.pop_zalo_pending()
        client.send_message(chat_id, "✅ Đã huỷ thao tác.")
        return

    if data == "do_update":
        client.send_message(chat_id, "Mở trang phát hành để tải bản cập nhật.", reply_markup=updater.release_button())
        return

    if data == "zalo_send":
        pending = safe_fs.pop_zalo_pending()
        if pending:
            client.send_message(chat_id, f"Bản nháp cho {pending['to']} (kiểm tra người nhận trong Zalo trước khi gửi):\n\n{pending['text']}")
        else:
            client.send_message(chat_id, "Không còn bản nháp Zalo. Hãy tạo lại từ link Drive.")
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
        _send_gcal_setup_guide(client, chat_id)
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
            "Bật Google Calendar bằng Apps Script:\n"
            "1. Tạo dự án mới trong script.google.com và dán mã bên dưới.\n"
            "2. Trong Project Settings → Script Properties, thêm MEDIATELEBOT_SECRET với một khóa ngẫu nhiên ít nhất 32 ký tự.\n"
            "3. Triển khai Web App bằng tài khoản chủ lịch.\n"
            "4. Nhập URL /exec và khóa trực tiếp trong MediaTeleBot trên máy chủ."
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
                if op == "qgd":
                    res = safe_fs.copy_to_drive_path(src_path, dst_path)
                else:
                    res = safe_fs.safe_copy(src_path, dst_path) if is_copy else safe_fs.safe_move(src_path, dst_path)
                if res.get("ok"):
                    if op == "qgd":
                        client.send_message(
                            chat_id,
                            f"☁️ Đã chép vào thư mục đồng bộ Google Drive.\n"
                            f"• Tên: {Path(src_path).name} ({sz_str})\n"
                            f"• Nguồn: {res['src']}\n"
                            f"• Đích Google Drive: {res['dst']}\n"
                            f"🔄 Kiểm tra trạng thái đồng bộ trong Google Drive."
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
        chat_id = cfg.get("owner_id")
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

    try:
        signal.signal(signal.SIGHUP, signal.SIG_IGN)
    except AttributeError:
        pass

    try:
        with lock_instance(BASE_DIR / "bot.lock"):
            run_polling()
    except OSError:
        print("Không thể chạy bot. Kiểm tra quyền thư mục dữ liệu hoặc tiến trình đang chạy.", file=sys.stderr)
        sys.exit(1)


def run_polling() -> None:
    cfg = load_config()
    token = os.environ.get("TELEGRAM_BOT_TOKEN") or cfg.get("bot_token")
    if not token:
        print("Mở trình cài đặt MediaTeleBot để nhập bot token.", file=sys.stderr)
        return
    if cfg.get("bot_token") != token:
        print("Token môi trường khác token cài đặt. Hãy cấu hình token mới từ trình cài đặt trước.", file=sys.stderr)
        return

    update_config(lambda current: pairing.configure_token(current, token) if current.get("bot_token") == token else None)
    client = TelegramClient(token)
    if not client.call("getMe").get("ok"):
        raise RuntimeError("Telegram không xác nhận bot token.")
    print("MediaTeleBot đang chạy.", flush=True)
    while not (BASE_DIR / "stop.request").exists():
        try:
            cfg = load_config()
            if cfg.get("bot_token") != token:
                print("Token đã thay đổi. Hãy mở lại MediaTeleBot.", flush=True)
                return
            response = client.call("getUpdates", {
                "offset": cfg.get("last_update_id", 0), "timeout": 25,
                "allowed_updates": ["message", "callback_query"],
            })
            for update in response.get("result", []):
                cfg = load_config()
                if cfg.get("bot_token") != token:
                    return
                def record_offset(current):
                    if current.get("bot_token") != token:
                        return False
                    current["last_update_id"] = update["update_id"] + 1
                    return True

                if not update_config(record_offset):
                    return
                try:
                    if "message" in update:
                        handle_message(client, cfg, update["message"])
                    elif "callback_query" in update:
                        handle_callback(client, cfg, update["callback_query"])
                finally:
                    mac_remote.clear_capture()
        except KeyboardInterrupt:
            break
        except Exception as exc:
            # Errors may contain URLs with bot tokens or private calendar links.
            print(f"Lỗi khi xử lý Telegram ({type(exc).__name__}).", file=sys.stderr, flush=True)
            time.sleep(3)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"MediaTeleBot không khởi động được ({type(exc).__name__}).", file=sys.stderr)
        sys.exit(1)
