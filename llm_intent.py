#!/usr/bin/env python3
from __future__ import annotations
"""
AI hiểu ngôn ngữ tự nhiên (Gemini API) -> dịch câu nói tuỳ ý thành MỘT lệnh chuẩn
mà nl_engine đã hỗ trợ. AI KHÔNG tự chạm vào file: mọi thao tác vẫn đi qua bộ công cụ
an toàn (không xoá, không ghi đè). Nếu chưa có API key thì module này im lặng bỏ qua.
"""

import datetime
import json
import os
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

def _urlopen_robust(req, timeout=15):
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
DEFAULT_MODEL = "gemini-3.1-flash-lite"
FALLBACK_MODELS = ["gemini-flash-latest", "gemini-flash-lite-latest", "gemini-3.5-flash-lite", "gemini-3.5-flash"]

SYSTEM_PROMPT = """Bạn là bộ phiên dịch lệnh cho trợ lý quản lý file & lịch trên máy Mac của một nhà quay phim.
Nhiệm vụ: đọc câu tiếng Việt tự nhiên của người dùng và viết lại thành ĐÚNG MỘT lệnh chuẩn (một dòng, không giải thích)
theo các mẫu sau. Hôm nay là {today} ({weekday}).

MẪU LỆNH CHUẨN:
1. Xem lịch:      "<mốc thời gian> có lịch gì"   (mốc: hôm nay | ngày mai | ngày mốt | hôm qua | tuần này | tuần sau | ngày DD/MM | ngày DD/MM âm | tháng M)
2. Note lịch:     "note lịch DDMM nội dung" hoặc "note lịch DD/MM âm nội dung" (nếu là Âm lịch). (vd: note lịch 1610 psc a Thăng, note lịch 25/11 âm cưới a Nam)
3. Tìm file/thư mục:
   - Tìm bình thường: "tìm thư mục <từ khoá>" hoặc "tìm file <từ khoá>"
   - Tìm trong Google Drive: "tìm thư mục <từ khoá> trong google drive"
4. Dung lượng:    "thư mục <tên> nặng bao nhiêu gb"   hoặc "ổ cứng còn trống bao nhiêu"
5. Chuyển/dời:    "chuyển thư mục <tên> qua <nơi đến>"   (nơi đến: film data | desktop | downloads | thư mục <tên> ngoài desktop)
                  Nếu nguồn nằm ở nơi cụ thể: "chuyển thư mục <tên> trong film data ra thư mục source ngoài desktop"
6. Sao chép:      "copy thư mục <tên> qua <nơi đến>"
7. Up Google Drive: "up file <tên> lên drive"   (mặc định vào THIEN UNG PRODUCTION; tự trả link)
8. Lấy link Drive (chỉ xin link không gửi ai): "lấy link file <tên> trong thư mục THIEN UNG PRODUCTION"
9. Xem thư mục:   "xem trong <nơi> có gì"
10. Gửi link cho ai đó (dù có chữ "zalo" hay không, vd "gửi link X qua cho Y", "bắn link X cho Y", "chia sẻ link X qua zalo cho Y"):
    -> "gửi link file <tên> cho <người nhận> qua zalo"
11. Up Drive rồi gửi link cho ai đó:
    -> "up file <tên> lên drive rồi gửi link cho <người nhận> qua zalo"

QUY TẮC:
- Chỉ trả về lệnh chuẩn, không thêm chữ nào khác.
- Giữ nguyên mã số ngày tháng và từ khoá chính (như 2510, huynh trung hiep, 2810, 2410).
- Tách bạch rõ ràng đâu là tên file/thư mục cần gửi và đâu là tên người nhận (ví dụ "Hoàng Dựng", "anh Thăng").
- Ngày trong "note lịch" viết DDMM (vd 16/10 -> 1610).
- Nếu người dùng nói ngày Âm lịch (có chữ "âm", "âm lịch", "al"), BẮT BUỘC giữ nguyên chữ "âm" trong lệnh chuẩn (ví dụ "note lịch 25/11 âm cưới a Nam").
- TUYỆT ĐỐI không tạo lệnh xoá. Nếu người dùng yêu cầu xoá/format/thao tác nguy hiểm, trả về: UNKNOWN
- Nếu không thể hiểu hoặc không thuộc các mẫu trên, trả về: UNKNOWN
"""


def _get_key_and_model() -> tuple[str | None, str]:
    key = os.environ.get("GEMINI_API_KEY")
    model = DEFAULT_MODEL
    try:
        cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        key = key or cfg.get("gemini_api_key")
        model = cfg.get("gemini_model", DEFAULT_MODEL)
    except Exception:
        pass
    return key, model


def rewrite_to_command(user_text: str) -> str | None:
    """Return a canonical command string, or None if no key / not understood / error."""
    key, model = _get_key_and_model()
    if not key:
        return None

    today = datetime.date.today()
    weekdays = ["Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy", "Chủ Nhật"]
    prompt = SYSTEM_PROMPT.format(today=today.strftime("%d/%m/%Y"), weekday=weekdays[today.weekday()])

    body = {
        "system_instruction": {"parts": [{"text": prompt}]},
        "contents": [{"role": "user", "parts": [{"text": user_text}]}],
        "generationConfig": {"temperature": 0, "maxOutputTokens": 400},
    }
    # Thử lần lượt các model (model bị quá tải/ngừng thì tự chuyển sang model kế tiếp)
    models = [model] + [m for m in FALLBACK_MODELS if m != model]
    text = ""
    for mdl in models:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{mdl}:generateContent"
        req = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json", "x-goog-api-key": key},
        )
        try:
            with _urlopen_robust(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
            break
        except Exception:
            continue
    if not text:
        return None

    text = text.strip("`\"' \n").splitlines()[0].strip() if text else ""
    if not text or text.upper().startswith("UNKNOWN"):
        return None
    # Chốt an toàn: không bao giờ chạy lệnh có ý xoá
    low = text.lower()
    if any(w in low for w in ("xoá", "xóa", "delete", "remove", " rm ", "format")):
        return None
    return text
