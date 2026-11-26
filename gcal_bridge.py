"""Calendar backends configured locally on the computer running the bot."""
from __future__ import annotations

import datetime as dt
import json
import re
import subprocess
import urllib.request

from runtime import IS_MAC, edit_config, open_https, read_config

PROTOCOL = "mediatelebot-calendar-v1"
URL_PATTERN = re.compile(r"https://script\.google\.com/(?:a/[^/]+/)?macros/s/[A-Za-z0-9_-]+/exec")

APPS_SCRIPT_TEMPLATE = r"""function response_(data) {
  return ContentService.createTextOutput(JSON.stringify(data))
    .setMimeType(ContentService.MimeType.JSON);
}

function doGet() {
  return response_({ok: false, error: 'POST required'});
}

function doPost(e) {
  try {
    const p = JSON.parse(e.postData.contents);
    const secret = PropertiesService.getScriptProperties().getProperty('MEDIATELEBOT_SECRET');
    if (!secret || secret.length < 32 || typeof p.secret !== 'string' || p.secret.length !== secret.length) {
      return response_({ok: false, error: 'Unauthorized'});
    }
    let diff = 0;
    for (let i = 0; i < secret.length; i++) diff |= secret.charCodeAt(i) ^ p.secret.charCodeAt(i);
    if (diff !== 0) return response_({ok: false, error: 'Unauthorized'});

    const cal = CalendarApp.getDefaultCalendar();
    const tz = cal.getTimeZone();
    if (p.action === 'ping') {
      return response_({ok: true, protocol: 'mediatelebot-calendar-v1', calendar: cal.getName()});
    }
    if (p.action === 'create') {
      if (!/^\d{4}-\d{2}-\d{2}$/.test(p.start) || !/^\d{4}-\d{2}-\d{2}$/.test(p.end) ||
          typeof p.summary !== 'string' || !p.summary.trim() || p.summary.length > 500) {
        return response_({ok: false, error: 'Invalid event'});
      }
      const start = Utilities.parseDate(p.start, tz, 'yyyy-MM-dd');
      const end = Utilities.parseDate(p.end, tz, 'yyyy-MM-dd');
      if (end <= start) return response_({ok: false, error: 'Invalid date range'});
      cal.createAllDayEvent(p.summary, start, end);
      return response_({ok: true, calendar: cal.getName()});
    }
    if (p.action === 'list') {
      const start = new Date(p.start);
      const end = new Date(p.end);
      if (!isFinite(+start) || !isFinite(+end) || end <= start || end - start > 90 * 86400000) {
        return response_({ok: false, error: 'Invalid date range'});
      }
      const date = (d) => Utilities.formatDate(d, tz, 'yyyy-MM-dd');
      const events = cal.getEvents(start, end, {max: 250}).map(function (event) {
        const allDay = event.isAllDayEvent();
        return {
          summary: event.getTitle(),
          start: allDay ? {date: date(event.getAllDayStartDate())} : {dateTime: event.getStartTime().toISOString()},
          end: allDay ? {date: date(event.getAllDayEndDate())} : {dateTime: event.getEndTime().toISOString()}
        };
      });
      return response_({ok: true, events: events});
    }
    return response_({ok: false, error: 'Unknown action'});
  } catch (_) {
    return response_({ok: false, error: 'Calendar request failed'});
  }
}"""

MAC_CALENDAR = r"""
function ymd(d) {
  return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
}
function localDate(s) {
  const p = s.split('-').map(Number);
  return new Date(p[0], p[1] - 1, p[2]);
}
function run(args) {
  const [operation, name, first, last, summary] = args;
  const app = Application('Calendar');
  const cals = app.calendars.whose({name: name})();
  if (cals.length !== 1) throw Error('Select a uniquely named calendar');
  const calendar = cals[0];
  if (operation === 'create') {
    calendar.events.push(app.Event({
      summary: summary, startDate: localDate(first), endDate: localDate(last), alldayEvent: true
    }));
    return JSON.stringify({ok: true, calendar: name});
  }
  const start = new Date(first);
  const end = new Date(last);
  const found = calendar.events.whose({_and: [
    {startDate: {_lessThan: end}},
    {endDate: {_greaterThan: start}}
  ]})();
  return JSON.stringify(found.slice(0, 250).map(function (event) {
    const allDay = event.alldayEvent();
    const a = event.startDate();
    const b = event.endDate();
    return {
      summary: event.summary(),
      start: allDay ? {date: ymd(a)} : {dateTime: a.toISOString()},
      end: allDay ? {date: ymd(b)} : {dateTime: b.toISOString()}
    };
  }));
}
"""


def _post_webhook(url: str, secret: str, action: str, **fields) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(dict(fields, action=action, secret=secret)).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with open_https(req, timeout=20) as response:
        data = json.loads(response.read(1024 * 1024))
    if not isinstance(data, dict) or not data.get("ok"):
        raise ValueError("Apps Script từ chối yêu cầu.")
    return data


def configure_webhook(url: str, secret: str) -> str:
    url = url.strip()
    if not URL_PATTERN.fullmatch(url) or len(secret) < 32:
        raise ValueError("Cần URL /exec chính thức và khóa ít nhất 32 ký tự.")
    try:
        result = _post_webhook(url, secret, "ping")
        if result.get("protocol") != PROTOCOL:
            raise ValueError("Phiên bản Apps Script không tương thích.")
        try:
            _post_webhook(url, "0" * len(secret), "ping")
        except ValueError:
            pass
        else:
            raise ValueError("Deployment vẫn cho phép truy cập khi thiếu khóa hợp lệ.")
    except (OSError, ValueError):
        raise ValueError("Không xác nhận được bản Apps Script có khóa bảo vệ. Kiểm tra URL, deployment và Script Property.") from None
    edit_config(lambda cfg: cfg.update(gcal_webhook_url=url, gcal_webhook_secret=secret))
    return result.get("calendar") or "Google Calendar"


def _webhook(config: dict) -> tuple[str, str] | None:
    url = config.get("gcal_webhook_url") or ""
    secret = config.get("gcal_webhook_secret") or ""
    if URL_PATTERN.fullmatch(url) and len(secret) >= 32:
        return url, secret
    return None


def _mac_calendar(action: str, name: str, start_iso: str, end_iso: str, summary: str = ""):
    result = subprocess.run(
        ["/usr/bin/osascript", "-l", "JavaScript", "-e", MAC_CALENDAR, action, name, start_iso, end_iso, summary],
        capture_output=True, text=True, timeout=25, check=True,
    )
    return json.loads(result.stdout)


def get_calendar_sync_status() -> dict:
    config = read_config()
    return {
        "has_webhook": bool(_webhook(config)),
        "legacy_webhook": bool(config.get("gcal_webhook_url") and not _webhook(config)),
        "macos_calendar": config.get("macos_calendar") if IS_MAC else None,
    }


def open_macos_internet_accounts() -> dict:
    if not IS_MAC:
        return {"ok": False, "error": "Cài đặt này dành cho macOS."}
    subprocess.run(["/usr/bin/open", "x-apple.systempreferences:com.apple.Internet-Accounts"], check=True, timeout=10)
    return {"ok": True, "reply": "Đã mở Tài khoản Internet trên Mac. Sau khi đăng nhập, nhập chính xác tên lịch trong trình cấu hình MediaTeleBot."}


def create_google_calendar_event(summary: str, start, end_inclusive) -> dict:
    cfg = read_config()
    start_iso = start.isoformat()
    end_iso = (end_inclusive + dt.timedelta(days=1)).isoformat()
    webhook = _webhook(cfg)
    calendar = cfg.get("macos_calendar") if IS_MAC else None
    if not (webhook or calendar):
        return {"method": "local"}
    try:
        if webhook:
            res = _post_webhook(*webhook, "create", summary=summary, start=start_iso, end=end_iso)
            return {"method": "apps_script", "calendar": res.get("calendar"), "synced_google": True}
        _mac_calendar("create", calendar, start_iso, end_iso, summary)
        return {"method": "macos_calendar", "calendar": calendar}
    except (OSError, ValueError, subprocess.SubprocessError):
        return {"method": "uncertain"}


def list_events(start_iso: str, end_iso: str) -> list[dict]:
    cfg = read_config()
    webhook = _webhook(cfg)
    calendar = cfg.get("macos_calendar") if IS_MAC else None
    if not (webhook or calendar):
        return []
    if webhook:
        events = _post_webhook(*webhook, "list", start=start_iso, end=end_iso).get("events")
    else:
        events = _mac_calendar("list", calendar, start_iso, end_iso)
    if not isinstance(events, list):
        raise ValueError("Phản hồi lịch không hợp lệ.")
    return events
