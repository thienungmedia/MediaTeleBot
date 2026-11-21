#!/usr/bin/env python3
from __future__ import annotations
"""
Trí tuệ nhân tạo Gemini tích hợp sẵn cho MacFileBot:
1. Hiểu mọi ngữ cảnh, phương ngữ, tiếng lóng, câu nối tiếp của người dùng -> Dịch chuẩn xác
   sang ngôn ngữ lệnh chuẩn mà nl_engine.py đã được huấn luyện (CMD: <lệnh chuẩn>).
2. Trò chuyện tự nhiên "trên trời dưới đất" (CHAT: <phản hồi>) khi người dùng muốn tâm sự,
   hỏi đáp kiến thức, viết caption trả khách, hỏi kỹ thuật quay dựng, tán gẫu...
3. Giữ nguyên chốt an toàn tuyệt đối 100%: Không bao giờ xoá hoặc ghi đè file.
"""

import base64
import datetime
import json
import os
import re
import ssl
import urllib.request
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


def _urlopen_robust(req, timeout=18):
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


CONFIG_PATH = Path(__file__).parent.resolve() / "config.json"
DEFAULT_MODEL = "gemini-2.5-flash"
FALLBACK_MODELS = [
    "gemini-2.5-flash",
    "gemini-flash-latest",
    "gemini-2.5-flash-lite",
    "gemini-flash-lite-latest",
    "gemini-2.0-flash",
]


# Lưu lịch sử hội thoại ngắn theo từng người dùng để hiểu ngữ cảnh nối tiếp
CHAT_HISTORY: dict[int, list[dict]] = {}
MAX_HISTORY_TURNS = 10


def record_history(chat_id: int, role: str, text: str) -> None:
    if not chat_id or not text:
        return
    hist = CHAT_HISTORY.setdefault(chat_id, [])
    hist.append({"role": role, "text": text[:600]})
    if len(hist) > MAX_HISTORY_TURNS:
        del hist[:-MAX_HISTORY_TURNS]


SYSTEM_PROMPT = """Bạn là Trợ Lý AI Thông Minh (MacFileBot) chạy trên máy Mac của một ekip Quay Dựng Phim / Media Production, đồng thời là một người bạn trò chuyện cực kỳ nhạy bén, thân thiện, hiểu biết rộng ("trên trời dưới đất").

Hôm nay là {today} ({weekday}).
{context_block}

BẠN CÓ ĐÚNG 2 CHẾ ĐỘ PHẢN HỒI (BẮT BUỘC chọn 1 trong 2 tiền tố ở đầu câu trả lời: `CMD:` hoặc `CHAT:`):

======================================================================
CHẾ ĐỘ 1: `CMD: <lệnh chuẩn>`
Khi người dùng có ý định yêu cầu thao tác với File, Thư mục, Ổ cứng, Google Drive, Zalo, hoặc Lịch làm việc (dù họ nói bằng văn nói tự nhiên, tiếng lóng, viết tắt, sai chính tả, nói trống không, hoặc nhắc tiếp tới file vừa tìm ở câu trước).
Hãy dịch ý của họ thành ĐÚNG 1 DÒNG bắt đầu bằng `CMD: ` theo chuẩn ngôn ngữ máy đã huấn luyện dưới đây:

1. XEM LỊCH LÀM VIỆC:
   - `CMD: <mốc thời gian> có lịch gì`
   (trong đó `<mốc thời gian>` là: `hôm nay` | `ngày mai` | `ngày mốt` | `hôm qua` | `tuần này` | `tuần sau` | `ngày DD/MM` | `ngày DD/MM âm` | `tháng M`)
   Ví dụ: "bữa 20 tháng 12 có kèo nào không" -> `CMD: ngày 20/12 có lịch gì`

2. GHI / NOTE LỊCH LÀM VIỆC (DƯƠNG LỊCH & ÂM LỊCH):
   - Lịch Dương: `CMD: note lịch DD/MM <nội dung công việc>` (hoặc nhiều ngày: `CMD: note lịch DD-DD/MM <nội dung>`)
   - Lịch Âm:    `CMD: note lịch DD/MM âm <nội dung công việc>`
   *Lưu ý quan trọng*: Lọc bỏ các từ thừa như "vào google calendar", "lên lịch", "nhắc tôi", "ghi chú" khỏi `<nội dung công việc>`.
   Ví dụ:
   - "nhớ ghi lịch 20/12 vào google calender đi quay phóng sự cưới" -> `CMD: note lịch 20/12 đi quay phóng sự cưới`
   - "bữa mùng 5 tháng 11 âm chụp lễ đính hôn a Nam" -> `CMD: note lịch 05/11 âm chụp lễ đính hôn a Nam`

3. TÌM KIẾM FILE / THƯ MỤC DỰ ÁN:
   - Tìm chung trên cả máy Mac, ổ cứng & Google Drive: `CMD: tìm <từ khoá>`
   - Tìm riêng trên Google Drive: `CMD: tìm <từ khoá> trong google drive`
   - Tìm file do thợ/khách gửi (mục Được chia sẻ với tôi): `CMD: tìm <từ khoá> trong mục được chia sẻ`
   Ví dụ:
   - "ê lục coi có cái project psc hằng cần ở đâu không" -> `CMD: tìm psc hằng cần`
   - "coi thử trên drive có thư mục 2510 chưa" -> `CMD: tìm 2510 trong google drive`
   - "tìm cái file flycam thợ mới gửi" -> `CMD: tìm flycam trong mục được chia sẻ`

4. KIỂM TRA DUNG LƯỢNG (NẶNG BAO NHIÊU GB / Ổ CỨNG TRỐNG BAO NHIÊU):
   - Kiểm tra 1 file/thư mục: `CMD: kiểm tra file <tên> nặng bao nhiêu`
   - Kiểm tra dung lượng các ổ đĩa: `CMD: ổ cứng còn trống bao nhiêu`
   Ví dụ:
   - "coi giùm cái psc hằng cần nặng mấy mê / mấy ghi" -> `CMD: kiểm tra file psc hằng cần nặng bao nhiêu`
   - "check thử ổ cứng còn dư nhiều không" -> `CMD: ổ cứng còn trống bao nhiêu`

5. CHUYỂN (MOVE) HOẶC SAO CHÉP (COPY) FILE/THƯ MỤC GIỮA CÁC Ổ ĐĨA:
   - Chuyển (Move): `CMD: chuyển thư mục <tên> qua <nơi đến>`
     (Nếu có nói rõ nơi nguồn: `CMD: chuyển thư mục <tên> trong <nơi nguồn> ra <nơi đến>`)
   - Sao chép (Copy): `CMD: copy thư mục <tên> qua <nơi đến>`
   Ví dụ:
   - "quăng cái folder 2510 ngoài màn hình vô ổ film data giùm" -> `CMD: chuyển thư mục 2510 ngoài desktop qua film data`

6. UPLOAD LÊN GOOGLE DRIVE & LẤY LINK:
   - Upload vào thư mục mặc định: `CMD: up file <tên> lên drive`
   - Upload vào thư mục chỉ định: `CMD: up file <tên> lên drive vào thư mục <tên thư mục đích>`
   - Chỉ lấy link file/thư mục đã có sẵn trên Drive: `CMD: lấy link file <tên>`
   Ví dụ:
   - "đẩy cái psc hằng cần lên drive lấy link gửi khách" -> `CMD: up file psc hằng cần lên drive`
   - "cho xin cái link drive của bộ psc hằng cần" -> `CMD: lấy link file psc hằng cần`

7. GỬI LINK GOOGLE DRIVE QUA ZALO CHO KHÁCH / THỢ (MẶC ĐỊNH KHI BẢO GỬI FILE / FOLDER / LINK CHO AI ĐÓ):
   - Khi người dùng bảo "gửi file...", "gửi folder...", "gửi thư mục...", "gửi link..." cho một người nào đó (vd: Hoàng, Hoàng Dựng, anh Thăng...), MẶC ĐỊNH 100% là gửi link Google Drive qua Zalo (KHÔNG phải chuyển file nội bộ trong máy):
     `CMD: gửi link file <tên> cho <người nhận> qua zalo`
   - Up lên Drive xong tự gửi link:
     `CMD: up file <tên> lên drive rồi gửi link cho <người nhận> qua zalo`
   - LIÊN KẾT NGỮ CẢNH CÂU TRƯỚC (RẤT QUAN TRỌNG):
     Nếu câu trước vừa tìm/nhắc tới một file hoặc thư mục (có trong `File/thư mục vừa thao tác gần nhất` hoặc lịch sử hội thoại), và câu này người dùng nói ngắn gọn như:
     "gửi qua cho Hoàng", "gửi link đấy qua cho Hoàng Dựng", "gửi cái đó cho Hoàng", "bắn qua cho anh Thăng đi", "gửi folder đấy cho Hoàng":
     -> BẮT BUỘC thay thế đại từ ("đấy", "đó", "này", "nó", hoặc chỗ khuyết) bằng đúng tên file/thư mục vừa tìm được ở câu trước!
   Ví dụ:
   - "bắn cái link psc hằng cần qua zalo cho Hoàng Dựng đi" -> `CMD: gửi link file psc hằng cần cho Hoàng Dựng qua zalo`
   - (Câu trước vừa tìm `2810 HOÀNG DỰNG`) "gửi link đấy qua cho hoàng dựng" -> `CMD: gửi link file 2810 HOÀNG DỰNG cho hoàng dựng qua zalo`
   - (Câu trước vừa tìm `psc hằng cần`) "gửi qua cho Hoàng" -> `CMD: gửi link file psc hằng cần cho Hoàng qua zalo`

8. XOÁ BẢN TẢI VỀ TRÊN GOOGLE DRIVE (GIẢI PHÓNG Ổ CỨNG MÁY MAC AN TOÀN):
   - Xoá bản tải về của file/thư mục: `CMD: xoá bản tải về <tên>`
   - Kiểm tra tiến độ đồng bộ: `CMD: kiểm tra đồng bộ <tên>`
   - Bật tự động xoá bản tải về sau khi đồng bộ 100%: `CMD: bật tự động xoá bản tải về`
   - Tắt tự động xoá bản tải về: `CMD: tắt tự động xoá bản tải về`
   - Xem cài đặt: `CMD: cài đặt xoá bản tải về`
   *Lưu ý ngữ cảnh*: Nếu câu trước vừa up hoặc vừa tìm file X, và câu này người dùng bảo "xoá bản tải về đấy đi", "xoá bản tải về file đó", "gỡ bản tải về đi": hãy thay thế bằng `CMD: xoá bản tải về <tên file X>`.

9. MỞ ỨNG DỤNG / PHẦN MỀM TRÊN MÁY MAC:
   - Mở ứng dụng từ xa: `CMD: mở app <tên>` (vd: `CMD: mở app premiere`, `CMD: mở app capcut`, `CMD: mở app zalo`, `CMD: mở app photoshop`, `CMD: mở app davinci resolve`, `CMD: mở app brave`)
   - Xem danh sách ứng dụng trên máy: `CMD: xem danh sách app`

10. KIỂM TRA & KHÔI PHỤC FILE TRONG THÙNG RÁC (TRASH) TRÊN MÁY MAC:
   - Xem danh sách / dung lượng thùng rác: `CMD: kiểm tra thùng rác` (hoặc `CMD: thùng rác nặng bao nhiêu`)
   - Tìm file trong thùng rác: `CMD: tìm <tên> trong thùng rác` (vd: "tìm psc hằng cần trong thùng rác" -> `CMD: tìm psc hằng cần trong thùng rác`, "coi thùng rác có file cưới 2810 không" -> `CMD: tìm cưới 2810 trong thùng rác`)
   - Khôi phục file từ thùng rác về lại thư mục ban đầu (Đưa trở lại / Put Back): `CMD: khôi phục <tên> trong thùng rác`
     (Ví dụ: "chuyển file X trong thùng rác ra lại folder ban đầu", "đưa file cưới 2810 về chỗ cũ", "lấy lại file đó trong thùng rác", "khôi phục file vừa xoá" -> `CMD: khôi phục <tên> trong thùng rác`)
   - Lấy file từ thùng rác ra một thư mục cụ thể: `CMD: chuyển <tên> từ thùng rác ra <nơi đến>`

11. XEM BÊN TRONG THƯ MỤC / ĐỔI THƯ MỤC MẶC ĐỊNH / CẬP NHẬT BOT:
   - Mở xem thư mục/ổ đĩa: `CMD: xem trong <nơi> có gì` (vd: `CMD: xem trong desktop có gì`, `CMD: xem trong film data có gì`)
   - Xem thư mục upload Drive mặc định: `CMD: thư mục mặc định là gì`
   - Đổi thư mục upload Drive mặc định: `CMD: đặt thư mục mặc định là <tên thư mục>`
   - Cập nhật phần mềm bot: `CMD: cập nhật`

12. CHỤP ẢNH MÀN HÌNH & ĐIỀU KHIỂN MÁY MAC TỪ XA:
   - Chụp ảnh màn hình: `CMD: chụp màn hình` | Có lưới toạ độ A1-H6: `CMD: chụp màn hình có lưới` | Ảnh HD nét gốc: `CMD: chụp màn hình hd`
   - Hỏi AI đọc nội dung trên màn hình: `CMD: xem màn hình <câu hỏi>` (vd: "coi thử premiere render xong chưa" -> `CMD: xem màn hình premiere render xong chưa`)
   - Bảng điều khiển / Tình trạng máy: `CMD: bảng điều khiển` | `CMD: tình trạng máy`
   - Click chuột theo ô lưới hoặc toạ độ: `CMD: click <ô lưới hoặc toạ độ>` (vd: `CMD: click C3`, `CMD: double click D4`, `CMD: click phải B2`)
   - Click chuột thông minh bằng AI Vision: `CMD: click vào <mô tả nút trên màn hình>` (vd: "bấm vào nút Xuất video đi" -> `CMD: click vào nút Xuất video`)
   - Gõ văn bản / bấm phím / cuộn chuột: `CMD: gõ <nội dung>` | `CMD: gõ và enter <nội dung>` | `CMD: bấm phím <tên phím hoặc tổ hợp>` (vd: `CMD: bấm phím space`, `CMD: bấm phím cmd+s`, `CMD: bấm phím enter`) | `CMD: cuộn xuống` | `CMD: cuộn lên`
   - Chuyển hoặc thoát ứng dụng đang chạy: `CMD: chuyển sang <tên app>` | `CMD: tắt app <tên app>`
   - Âm lượng & Màn hình: `CMD: tăng âm lượng` | `CMD: giảm âm lượng` | `CMD: tắt tiếng` | `CMD: âm lượng <số>%` | `CMD: khoá màn hình` | `CMD: đánh thức màn hình` | `CMD: tắt màn hình`
   - Điều khiển full màn hình RustDesk / AnyDesk: `CMD: điều khiển rustdesk` | `CMD: điều khiển anydesk`

======================================================================
CHẾ ĐỘ 2: `CHAT: <câu trả lời tự nhiên>`
Khi người dùng KHÔNG yêu cầu các thao tác kỹ thuật ở Chế độ 1, mà muốn:
- Trò chuyện tự nhiên "trên trời dưới đất", chào hỏi, tâm sự buồn vui, xả stress sau ngày đi quay.
- Nhờ viết status/caption Facebook, TikTok, kịch bản quay phóng sự cưới, lời chúc, email, tin nhắn báo giá cho khách.
- Hỏi đáp kiến thức về máy ảnh (Sony, Canon...), ống kính (lens), thông số quay phim, ánh sáng, dựng phim (Premiere, DaVinci Resolve, CapCut, Final Cut), âm nhạc, đời sống, xã hội, ẩm thực, thời tiết, tính toán...
- Hoặc khi người dùng yêu cầu XOÁ file / format ổ đĩa: Hãy trả lời bằng `CHAT:` một cách lịch sự, vui vẻ rằng bot đang bật **Chế độ Bảo Vệ An Toàn 100% (Cấm Xoá File)** để bảo vệ tuyệt đối dữ liệu quay dựng nên sẽ không xoá bất kỳ file nào.

QUY TẮC TRẢ LỜI Ở CHẾ ĐỘ `CHAT:`:
- Bắt đầu bằng chữ `CHAT: ` rồi viết câu trả lời tự nhiên, gần gũi, thông minh, linh hoạt bằng tiếng Việt.
- Nếu ở Chế độ 1 (`CMD:`), CHỈ viết đúng 1 dòng `CMD: <lệnh chuẩn>`, tuyệt đối không giải thích thêm.
"""


def _get_keys_and_model() -> tuple[list[str], str]:
    keys = []
    env_k = os.environ.get("GEMINI_API_KEY", "").strip()
    if env_k:
        keys.append(env_k)
    model = DEFAULT_MODEL
    try:
        if CONFIG_PATH.exists():
            cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            cfg_k = (cfg.get("gemini_api_key") or "").strip()
            if cfg_k and cfg_k not in keys:
                keys.append(cfg_k)
            model = cfg.get("gemini_model") or DEFAULT_MODEL
            if model == "gemini-3.1-flash-lite":
                model = DEFAULT_MODEL
    except Exception:
        pass
    return keys, model


def process_with_gemini(
    user_text: str,
    chat_id: int = 0,
    last_item: str | None = None,
    default_folder: str | None = None,
) -> dict | None:
    """
    Analyze user_text with Gemini and return either:
      {"mode": "cmd", "command": "<canonical_command>"}
    or:
      {"mode": "chat", "reply": "<natural_conversation_reply>"}
    or None if API is unreachable.
    """
    keys, model = _get_keys_and_model()
    if not keys:
        return None

    today = datetime.date.today()
    weekdays = ["Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy", "Chủ Nhật"]

    ctx_lines = []
    if last_item:
        ctx_lines.append(f"- File/Thư mục người dùng vừa thao tác gần nhất: {last_item}")
    if default_folder:
        ctx_lines.append(f"- Thư mục Google Drive mặc định hiện tại: {default_folder}")
    context_block = "NGỮ CẢNH HIỆN TẠI:\n" + "\n".join(ctx_lines) if ctx_lines else ""

    prompt = SYSTEM_PROMPT.format(
        today=today.strftime("%d/%m/%Y"),
        weekday=weekdays[today.weekday()],
        context_block=context_block,
    )

    contents = []
    if chat_id and chat_id in CHAT_HISTORY:
        for turn in CHAT_HISTORY[chat_id][-8:]:
            role = "user" if turn["role"] == "user" else "model"
            contents.append({"role": role, "parts": [{"text": turn["text"]}]})
    contents.append({"role": "user", "parts": [{"text": user_text}]})

    body = {
        "system_instruction": {"parts": [{"text": prompt}]},
        "contents": contents,
        "generationConfig": {"temperature": 0.3, "maxOutputTokens": 800},
    }

    models = [model] + [m for m in FALLBACK_MODELS if m != model]
    raw_resp = ""
    for api_key in keys:
        for mdl in models:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{mdl}:generateContent"
            req = urllib.request.Request(
                url,
                data=json.dumps(body).encode("utf-8"),
                headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
            )
            try:
                with _urlopen_robust(req, timeout=15) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                raw_resp = data["candidates"][0]["content"]["parts"][0]["text"].strip()
                if raw_resp:
                    break
            except Exception:
                continue
        if raw_resp:
            break

    if not raw_resp:
        return None

    cleaned = raw_resp.strip()
    first_line = cleaned.splitlines()[0].strip().strip("`\"'")

    if first_line.upper().startswith("CMD:"):
        cmd_str = first_line[4:].strip().strip("`\"'")
        low = cmd_str.lower()
        if any(w in low for w in ("xoá", "xóa", "delete", "remove", " rm ", "format")):
            return {
                "mode": "chat",
                "reply": "🔒 Chế độ Bảo Vệ An Toàn 100% đang bật để giữ an toàn tuyệt đối cho dữ liệu quay dựng của bạn, vì vậy tôi không thực hiện thao tác xoá file nhé!",
            }
        if cmd_str and not cmd_str.upper().startswith("UNKNOWN"):
            record_history(chat_id, "user", user_text)
            record_history(chat_id, "model", f"CMD: {cmd_str}")
            return {"mode": "cmd", "command": cmd_str}

    if cleaned.upper().startswith("CHAT:"):
        chat_reply = cleaned[5:].strip()
    else:
        chat_reply = cleaned

    if chat_reply:
        record_history(chat_id, "user", user_text)
        record_history(chat_id, "model", f"CHAT: {chat_reply}")
        return {"mode": "chat", "reply": chat_reply}

    return None


def rewrite_to_command(user_text: str) -> str | None:
    """Backward-compatible helper returning only a canonical command string or None."""
    res = process_with_gemini(user_text)
    if res and res.get("mode") == "cmd":
        return res.get("command")
    return None


def _call_gemini_vision(image_path: str, prompt_text: str, max_tokens: int = 500) -> str | None:
    """Gọi Gemini Vision với ảnh JPEG local và prompt text."""
    keys, model = _get_keys_and_model()
    if not keys or not image_path or not os.path.exists(image_path):
        return None
    try:
        with open(image_path, "rb") as fp:
            b64_data = base64.b64encode(fp.read()).decode("ascii")
    except Exception:
        return None

    body = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"inline_data": {"mime_type": "image/jpeg", "data": b64_data}},
                    {"text": prompt_text},
                ],
            }
        ],
        "generationConfig": {"temperature": 0.1, "maxOutputTokens": max_tokens},
    }
    models = [model] + [m for m in FALLBACK_MODELS if m != model]
    for api_key in keys:
        for mdl in models:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{mdl}:generateContent"
            req = urllib.request.Request(
                url,
                data=json.dumps(body).encode("utf-8"),
                headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
            )
            try:
                with _urlopen_robust(req, timeout=22) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                txt = data["candidates"][0]["content"]["parts"][0]["text"].strip()
                if txt:
                    return txt
            except Exception:
                continue
    return None


def locate_ui_element_on_screen(image_path: str, target_desc: str) -> dict:
    """Dùng Gemini Vision tìm toạ độ (0..1000) của phần tử UI trên ảnh màn hình."""
    if not _get_keys_and_model()[0]:
        return {
            "found": False,
            "reason": (
                "Chưa cài Gemini API Key miễn phí. "
                "Lấy key tại https://aistudio.google.com/apikey rồi dán trực tiếp vào chat Telegram này để bật AI Vision!"
            ),
        }
    prompt = (
        "Bạn là hệ thống AI Computer Use chuyên xác định toạ độ trên ảnh màn hình macOS.\n"
        f"Hãy tìm phần tử giao diện khớp nhất với yêu cầu của người dùng: \"{target_desc}\".\n"
        "Quy ước hệ toạ độ chuẩn hoá từ 0 đến 1000:\n"
        "- x = 0 là mép trái ngoài cùng, x = 1000 là mép phải ngoài cùng.\n"
        "- y = 0 là mép trên ngoài cùng, y = 1000 là mép dưới ngoài cùng.\n"
        "Hãy trả về DUY NHẤT 1 đối tượng JSON hợp lệ (không giải thích thêm):\n"
        "- Nếu tìm thấy tâm chính xác của nút/mục/vùng đó: "
        "{\"found\": true, \"x\": <số nguyên 0..1000>, \"y\": <số nguyên 0..1000>, \"label\": \"<tên ngắn gọn của mục>\"}\n"
        "- Nếu không nhìn thấy trên màn hình hiện tại: "
        "{\"found\": false, \"reason\": \"<lý do ngắn gọn bằng tiếng Việt>\"}"
    )
    raw = _call_gemini_vision(image_path, prompt, max_tokens=250)
    if not raw:
        return {"found": False, "reason": "Không thể kết nối AI Vision để phân tích màn hình."}

    cleaned = raw.strip()
    m_code = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, flags=re.DOTALL)
    if m_code:
        cleaned = m_code.group(1)
    else:
        m_brace = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
        if m_brace:
            cleaned = m_brace.group(0)

    try:
        obj = json.loads(cleaned)
    except Exception:
        return {"found": False, "reason": "AI không trả về được toạ độ JSON hợp lệ."}

    if not obj.get("found"):
        return {"found": False, "reason": obj.get("reason") or "Không thấy phần tử này trên màn hình."}

    try:
        x = float(obj["x"])
        y = float(obj["y"])
        if 0 <= x <= 1000 and 0 <= y <= 1000:
            return {
                "found": True,
                "x": x,
                "y": y,
                "label": str(obj.get("label") or target_desc)[:60],
            }
    except Exception:
        pass
    return {"found": False, "reason": "Toạ độ AI trả về vượt phạm vi màn hình."}


def analyze_screen_with_gemini(image_path: str, question: str) -> str | None:
    """Dùng Gemini Vision đọc và tóm tắt nội dung hiển thị trên màn hình theo câu hỏi."""
    if not _get_keys_and_model()[0]:
        return (
            "💡 Chưa cài Gemini API Key miễn phí để AI đọc màn hình.\n"
            "👉 Bạn lấy key tại https://aistudio.google.com/apikey rồi dán trực tiếp vào chat Telegram này để bật tính năng phân tích màn hình thông minh!"
        )
    q = (question or "").strip() or "Màn hình máy Mac hiện đang hiển thị gì?"
    prompt = (
        "Bạn là trợ lý AI đang nhìn ảnh chụp màn hình máy Mac của người dùng.\n"
        f"Yêu cầu / câu hỏi của người dùng: \"{q}\"\n"
        "Hãy trả lời ngắn gọn, súc tích, chính xác bằng tiếng Việt (3-6 dòng) về những gì thực tế đang hiển thị trên màn hình "
        "(tên app đang mở, tiến độ render/tải lên nếu có, thông báo lỗi, nội dung chính)."
    )
    return _call_gemini_vision(image_path, prompt, max_tokens=500)
