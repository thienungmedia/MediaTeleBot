#!/usr/bin/env python3
from __future__ import annotations
"""
gcal_bridge.py - Cầu nối tự động ghi & xem Google Calendar 100% không cần cài Antigravity.
Hỗ trợ 3 lớp đồng bộ tự động (ưu tiên từ cao xuống thấp):
1. gcalendar CLI (nếu máy có cài Antigravity).
2. Google Apps Script Bridge (Web App cá nhân 1 phút — cả Ghi & Đọc trực tiếp Google Calendar API).
3. macOS Calendar.app đồng bộ 2 chiều với tài khoản Google đã đăng nhập trên Mac (0 dòng code).
"""

import json
import os
import re
import ssl
import subprocess
import urllib.parse
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).parent.resolve()
CONFIG_PATH = BASE_DIR / "config.json"

APPS_SCRIPT_TEMPLATE = r"""function _parseYMD(s) {
  var p = String(s).split("-");
  return new Date(Number(p[0]), Number(p[1]) - 1, Number(p[2]));
}

function _handleReq(params) {
  var cal = CalendarApp.getDefaultCalendar();
  var tz = cal.getTimeZone() || Session.getScriptTimeZone();
  var act = (params.action || "ping").toLowerCase();

  if (act === "ping") {
    return { ok: true, calendar: cal.getName(), timezone: tz };
  }

  if (act === "create") {
    var summary = String(params.summary || "Lịch hẹn mới");
    var sd = _parseYMD(params.start);
    var ed = params.end ? _parseYMD(params.end) : null;
    if (ed && (ed.getTime() - sd.getTime() > 86400000)) {
      cal.createAllDayEvent(summary, sd, ed);
    } else {
      cal.createAllDayEvent(summary, sd);
    }
    return { ok: true, calendar: cal.getName(), summary: summary };
  }

  if (act === "list") {
    var startD = new Date(params.start);
    var endD = new Date(params.end);
    var evs = cal.getEvents(startD, endD);
    var list = evs.map(function(e) {
      if (e.isAllDayEvent()) {
        return {
          summary: e.getTitle(),
          start: { date: Utilities.formatDate(e.getAllDayStartDate(), tz, "yyyy-MM-dd") },
          end: { date: Utilities.formatDate(e.getAllDayEndDate(), tz, "yyyy-MM-dd") }
        };
      }
      return {
        summary: e.getTitle(),
        start: { dateTime: Utilities.formatDate(e.getStartTime(), tz, "yyyy-MM-dd'T'HH:mm:ssXXX") },
        end: { dateTime: Utilities.formatDate(e.getEndTime(), tz, "yyyy-MM-dd'T'HH:mm:ssXXX") }
      };
    });
    return { ok: true, calendar: cal.getName(), events: list };
  }

  return { ok: false, error: "Unknown action: " + act };
}

function doGet(e) {
  var res = _handleReq((e && e.parameter) ? e.parameter : {});
  return ContentService.createTextOutput(JSON.stringify(res)).setMimeType(ContentService.MimeType.JSON);
}

function doPost(e) {
  var body = {};
  try { body = JSON.parse(e.postData.contents || "{}"); } catch (err) {}
  var res = _handleReq(body);
  return ContentService.createTextOutput(JSON.stringify(res)).setMimeType(ContentService.MimeType.JSON);
}"""


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


def _urlopen_robust(req, timeout: int = 20):
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


def _read_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def get_webhook_url() -> str:
    env_url = os.environ.get("GCAL_WEBHOOK_URL", "").strip()
    if env_url:
        return env_url
    cfg = _read_config()
    return (cfg.get("gcal_webhook_url") or "").strip()


def save_webhook_url(url: str) -> dict:
    """Xác thực URL Google Apps Script bằng ?action=ping rồi lưu vào config.json."""
    clean = (url or "").strip().strip("`'\"<> ")
    if not re.match(r"^https://script\.google\.com/(?:a/macros/[^/]+/)?macros/s/[A-Za-z0-9_\-]+/exec\b", clean):
        return {
            "ok": False,
            "error": (
                "❌ Đường dẫn Google Apps Script không hợp lệ.\n"
                "URL đúng phải có dạng: `https://script.google.com/macros/s/.../exec`"
            ),
        }

    clean = clean.split("?", 1)[0]
    ping_url = f"{clean}?action=ping"
    req = urllib.request.Request(ping_url, headers={"User-Agent": "MacFileBot-GCal/1.0"})
    try:
        with _urlopen_robust(req, timeout=20) as resp:
            raw = resp.read().decode("utf-8", "replace").strip()
        data = json.loads(raw)
        if not data.get("ok"):
            return {"ok": False, "error": f"❌ Apps Script báo lỗi: {data.get('error', 'Không rõ')}"}
    except Exception as e:
        return {
            "ok": False,
            "error": (
                f"❌ Không kết nối được tới Google Apps Script ({e}).\n"
                "👉 Hãy kiểm tra lúc Deploy đã chọn quyền truy cập **Anyone (Bất kỳ ai)** chưa nhé!"
            ),
        }

    cfg = _read_config()
    cfg["gcal_webhook_url"] = clean
    try:
        CONFIG_PATH.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        return {"ok": False, "error": f"❌ Lỗi lưu cấu hình: {e}"}

    cal_name = data.get("calendar") or "Google Calendar"
    return {
        "ok": True,
        "calendar": cal_name,
        "url": clean,
        "reply": (
            f"✅ ĐÃ KẾT NỐI TỰ ĐỘNG GOOGLE CALENDAR THÀNH CÔNG!\n"
            f"• 📅 Lịch đích: *{cal_name}*\n"
            f"• ⚡ Chế độ: Tự động 100% cả GHI & ĐỌC lịch trực tiếp từ Google (không cần Antigravity, không cần bấm xác nhận web)."
        ),
    }


def open_macos_internet_accounts() -> dict:
    """Mở thẳng màn hình Tài khoản Internet của macOS để người dùng bật Lịch Google."""
    try:
        r = subprocess.run(
            ["open", "x-apple.systempreferences:com.apple.Internet-Accounts-Settings.extension"],
            capture_output=True,
            text=True,
            timeout=6,
        )
        if r.returncode != 0:
            subprocess.run(["open", "-b", "com.apple.systempreferences"], capture_output=True, timeout=6)
        return {
            "ok": True,
            "reply": (
                "⚙️ Đã mở màn hình *Cài đặt hệ thống → Tài khoản Internet (Internet Accounts)* trên máy Mac!\n\n"
                "👉 Bạn chỉ cần chọn *Thêm tài khoản → Google* (hoặc bấm vào Gmail có sẵn) và gạt BẬT mục **Lịch (Calendars)** là xong — từ nay bot sẽ tự động đồng bộ lịch 2 chiều lên Google Calendar!"
            ),
        }
    except Exception as e:
        return {"ok": False, "error": f"❌ Không thể mở Cài đặt hệ thống: {e}"}


def create_via_webhook(summary: str, start_iso: str, end_iso: str) -> dict:
    """Tạo sự kiện trực tiếp lên Google Calendar qua Google Apps Script Web App."""
    url = get_webhook_url()
    if not url:
        return {"ok": False, "error": "Chưa cấu hình gcal_webhook_url"}

    payload = json.dumps({
        "action": "create",
        "summary": summary,
        "start": start_iso,
        "end": end_iso,
    }).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "MacFileBot-GCal/1.0"},
        method="POST",
    )
    try:
        with _urlopen_robust(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
        if data.get("ok"):
            return {"ok": True, "calendar": data.get("calendar") or "Google Calendar", "method": "apps_script"}
        return {"ok": False, "error": data.get("error") or "Apps Script không trả về ok"}
    except Exception:
        # Dự phòng qua GET query params (phòng trường hợp redirect 302 đổi POST)
        try:
            qs = urllib.parse.urlencode({
                "action": "create",
                "summary": summary,
                "start": start_iso,
                "end": end_iso,
            })
            req_g = urllib.request.Request(f"{url}?{qs}", headers={"User-Agent": "MacFileBot-GCal/1.0"})
            with _urlopen_robust(req_g, timeout=20) as resp2:
                data2 = json.loads(resp2.read().decode("utf-8", "replace"))
            if data2.get("ok"):
                return {"ok": True, "calendar": data2.get("calendar") or "Google Calendar", "method": "apps_script"}
            return {"ok": False, "error": data2.get("error") or "Lỗi Apps Script"}
        except Exception as e2:
            return {"ok": False, "error": str(e2)}


def list_via_webhook(start_iso: str, end_iso: str) -> list[dict]:
    """Đọc danh sách sự kiện trực tiếp từ Google Calendar qua Google Apps Script Web App."""
    url = get_webhook_url()
    if not url:
        return []
    try:
        qs = urllib.parse.urlencode({"action": "list", "start": start_iso, "end": end_iso})
        req = urllib.request.Request(f"{url}?{qs}", headers={"User-Agent": "MacFileBot-GCal/1.0"})
        with _urlopen_robust(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
        if data.get("ok") and isinstance(data.get("events"), list):
            return data["events"]
    except Exception:
        pass
    return []


def create_via_macos_calendar(summary: str, d_start, d_end_inclusive) -> dict:
    """
    Tạo sự kiện cả ngày trong Calendar.app bản địa của macOS.
    Nếu máy đã đăng nhập tài khoản Google trong Internet Accounts và bật Lịch (is_google_sync=True),
    Calendar.app sẽ tự động đồng bộ 2 chiều lên Google Calendar ngay lập tức.
    """
    safe_summary = summary.replace("\\", "\\\\").replace('"', '\\"')
    script = f'''
    try
        set startDate to current date
        set time of startDate to 0
        set day of startDate to 1
        set year of startDate to {d_start.year}
        set month of startDate to {d_start.month}
        set day of startDate to {d_start.day}

        set endDate to current date
        set time of endDate to 0
        set day of endDate to 1
        set year of endDate to {d_end_inclusive.year}
        set month of endDate to {d_end_inclusive.month}
        set day of endDate to {d_end_inclusive.day}

        tell application "Calendar"
            set targetCal to missing value
            set isGoogleSync to false
            set calList to every calendar whose writable is true
            repeat with c in calList
                set cName to name of c
                if cName contains "@" or cName contains "Google" or cName contains "Gmail" then
                    set targetCal to c
                    set isGoogleSync to true
                    exit repeat
                end if
            end repeat
            if targetCal is missing value then
                repeat with c in calList
                    set cName to name of c
                    if cName contains "Lịch" or cName contains "Calendar" or cName contains "Work" or cName contains "Công việc" or cName contains "Home" or cName contains "Cá nhân" then
                        set targetCal to c
                        exit repeat
                    end if
                end repeat
            end if
            if targetCal is missing value and (count of calList) > 0 then
                set targetCal to item 1 of calList
            end if
            if targetCal is not missing value then
                tell targetCal
                    make new event at end with properties {{summary:"{safe_summary}", start date:startDate, end date:endDate, allday event:true}}
                end tell
                set calOutName to name of targetCal
                if isGoogleSync then
                    try
                        reload calendars
                    end try
                    return "GOOGLE|" & calOutName
                else
                    return "LOCAL|" & calOutName
                end if
            end if
        end tell
    end try
    return ""
    '''
    try:
        res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=10)
        raw_out = (res.stdout or "").strip()
        if res.returncode == 0 and "|" in raw_out:
            tag, cal_name = raw_out.split("|", 1)
            return {
                "ok": True,
                "calendar": cal_name.strip(),
                "is_google_sync": (tag == "GOOGLE"),
            }
    except Exception:
        pass
    return {"ok": False, "calendar": None, "is_google_sync": False}


def get_calendar_sync_status(gcalendar_bin: str = "") -> dict:
    """Kiểm tra tất cả các kênh đồng bộ Google Calendar tự động hiện có trên máy."""
    has_cli = bool(gcalendar_bin and Path(gcalendar_bin).exists())
    webhook_url = get_webhook_url()
    has_webhook = bool(webhook_url)

    macos_google_cals = []
    macos_other_cals = []
    try:
        r = subprocess.run(
            [
                "osascript",
                "-e",
                'tell application "Calendar"\nset out to {}\nrepeat with c in (every calendar whose writable is true)\nset end of out to name of c\nend repeat\nreturn out\nend tell',
            ],
            capture_output=True,
            text=True,
            timeout=6,
        )
        if r.returncode == 0 and r.stdout.strip():
            for item in r.stdout.strip().split(", "):
                cn = item.strip()
                if not cn:
                    continue
                if "@" in cn or "Google" in cn or "Gmail" in cn:
                    macos_google_cals.append(cn)
                else:
                    macos_other_cals.append(cn)
    except Exception:
        pass

    return {
        "has_cli": has_cli,
        "has_webhook": has_webhook,
        "webhook_url": webhook_url,
        "macos_google_cals": macos_google_cals,
        "macos_other_cals": macos_other_cals,
        "auto_ready": has_cli or has_webhook or bool(macos_google_cals),
    }


def create_google_calendar_event(
    summary: str,
    d_start,
    d_end_inclusive,
    gcalendar_bin: str = "",
) -> dict:
    """
    Tự động ghi sự kiện vào Google Calendar theo thứ tự ưu tiên:
    1) gcalendar CLI (Antigravity)
    2) Google Apps Script Bridge (Web App cá nhân)
    3) macOS Calendar.app đồng bộ 2 chiều với Google
    4) fallback chỉ lưu cục bộ (local_only)
    """
    import datetime

    start_iso = d_start.isoformat()
    end_iso = (d_end_inclusive + datetime.timedelta(days=1)).isoformat()

    # 1. Antigravity gcalendar CLI
    if gcalendar_bin and Path(gcalendar_bin).exists():
        try:
            res = subprocess.run(
                [gcalendar_bin, "mutate", "create", "--summary", summary, "--start", start_iso, "--end", end_iso, "--all-day"],
                capture_output=True,
                text=True,
                timeout=60,
            )
            out = (res.stdout or "") + (res.stderr or "")
            if res.returncode == 0:
                link_m = re.search(r"Link:\s*(\S+)", out)
                return {
                    "ok": True,
                    "synced_google": True,
                    "method": "antigravity_cli",
                    "calendar": "Google Calendar (Antigravity)",
                    "link": link_m.group(1) if link_m else None,
                }
        except Exception:
            pass

    # 2. Google Apps Script Bridge
    if get_webhook_url():
        wh_res = create_via_webhook(summary, start_iso, end_iso)
        if wh_res.get("ok"):
            return {
                "ok": True,
                "synced_google": True,
                "method": "apps_script",
                "calendar": wh_res.get("calendar") or "Google Calendar",
                "link": None,
            }

    # 3. macOS Calendar.app (đồng bộ Google 2 chiều hoặc Lịch nội bộ)
    mac_res = create_via_macos_calendar(summary, d_start, d_end_inclusive)
    if mac_res.get("ok"):
        is_gsync = bool(mac_res.get("is_google_sync"))
        return {
            "ok": True,
            "synced_google": is_gsync,
            "method": "macos_google_sync" if is_gsync else "macos_local",
            "calendar": mac_res.get("calendar"),
            "link": None,
        }

    # 4. Chỉ mới lưu cục bộ
    return {
        "ok": False,
        "synced_google": False,
        "method": "local_only",
        "calendar": None,
        "link": None,
    }
