#!/usr/bin/env python3
from __future__ import annotations
"""
mac_remote.py - Chụp ảnh màn hình thực tế & Điều khiển máy Mac từ xa cho MacFileBot.
- 100% macOS native (screencapture, sips, osascript Cocoa/System Events, CoreGraphics ctypes).
- Không dùng thư viện ngoài, không xoá file (ghi đè đường dẫn cố định trong /tmp).
"""

import ctypes
import ctypes.util
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

import safe_fs

SCREEN_RAW = "/tmp/macfilebot_screen_raw.jpg"
SCREEN_VIEW = "/tmp/macfilebot_screen_view.jpg"
SCREEN_GRID = "/tmp/macfilebot_screen_grid.jpg"

GRID_COLS = 8
GRID_ROWS = 6
COL_LABELS = "ABCDEFGH"

# Các ứng dụng lõi tuyệt đối không thoát từ xa
PROTECTED_APPS = {
    "finder",
    "python",
    "python3",
    "antigravity",
    "terminal",
    "iterm2",
    "loginwindow",
    "system events",
}


class _CGPoint(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]


_CG_LIB = None


def _get_cg():
    """Khởi tạo và cache CoreGraphics qua ctypes."""
    global _CG_LIB
    if _CG_LIB is not None:
        return _CG_LIB
    cg_path = ctypes.util.find_library("CoreGraphics")
    if not cg_path:
        return None
    cg = ctypes.CDLL(cg_path)
    cg.CGMainDisplayID.restype = ctypes.c_uint32
    cg.CGDisplayPixelsWide.argtypes = [ctypes.c_uint32]
    cg.CGDisplayPixelsWide.restype = ctypes.c_size_t
    cg.CGDisplayPixelsHigh.argtypes = [ctypes.c_uint32]
    cg.CGDisplayPixelsHigh.restype = ctypes.c_size_t

    cg.CGEventCreate.argtypes = [ctypes.c_void_p]
    cg.CGEventCreate.restype = ctypes.c_void_p
    cg.CGEventGetLocation.argtypes = [ctypes.c_void_p]
    cg.CGEventGetLocation.restype = _CGPoint
    cg.CGEventCreateMouseEvent.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint32,
        _CGPoint,
        ctypes.c_uint32,
    ]
    cg.CGEventCreateMouseEvent.restype = ctypes.c_void_p
    cg.CGEventCreateScrollWheelEvent.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_int32,
    ]
    cg.CGEventCreateScrollWheelEvent.restype = ctypes.c_void_p
    cg.CGEventSetIntegerValueField.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int64]
    cg.CGEventPost.argtypes = [ctypes.c_uint32, ctypes.c_void_p]
    cg.CFRelease.argtypes = [ctypes.c_void_p]
    _CG_LIB = cg
    return cg


def get_screen_size() -> tuple[int, int]:
    """Lấy kích thước logic màn hình chính (vd 2560 x 1440), fallback (1920, 1080)."""
    try:
        cg = _get_cg()
        if cg:
            did = cg.CGMainDisplayID()
            w = int(cg.CGDisplayPixelsWide(did))
            h = int(cg.CGDisplayPixelsHigh(did))
            if w > 0 and h > 0:
                return w, h
    except Exception:
        pass
    return 1920, 1080


def wake_display() -> None:
    """Đánh thức màn hình máy Mac nếu đang ở chế độ ngủ."""
    try:
        subprocess.run(
            ["/usr/bin/caffeinate", "-u", "-t", "2"],
            capture_output=True,
            timeout=3,
        )
    except Exception:
        pass


def _render_overlay_jxa(
    in_path: str,
    out_path: str,
    draw_grid: bool,
    mark_xy: tuple[float, float] | None,
) -> bool:
    """Vẽ lưới toạ độ A1-H6 và/hoặc dấu tròn đỏ vị trí vừa click lên ảnh JPEG bằng Cocoa native."""
    jxa = r"""
ObjC.import("Cocoa");
function run(argv) {
    var inPath = argv[0];
    var outPath = argv[1];
    var drawGrid = (argv[2] === "1");
    var hasMark = (argv[3] === "1");
    var markNx = parseFloat(argv[4] || "0.5");
    var markNy = parseFloat(argv[5] || "0.5");

    var cols = 8;
    var rows = 6;
    var colLabels = ["A","B","C","D","E","F","G","H"];

    var img = $.NSImage.alloc.initWithContentsOfFile(inPath);
    if (!img) return "LOAD_FAILED";
    var rep = img.representations.objectAtIndex(0);
    var w = rep.pixelsWide;
    var h = rep.pixelsHigh;

    var bmp = $.NSBitmapImageRep.alloc.initWithBitmapDataPlanesPixelsWidePixelsHighBitsPerSampleSamplesPerPixelHasAlphaIsPlanarColorSpaceNameBytesPerRowBitsPerPixel(
        null, w, h, 8, 4, true, false, $.NSCalibratedRGBColorSpace, 0, 0
    );
    var ctx = $.NSGraphicsContext.graphicsContextWithBitmapImageRep(bmp);
    $.NSGraphicsContext.saveGraphicsState;
    $.NSGraphicsContext.setCurrentContext(ctx);

    img.drawInRectFromRectOperationFraction(
        $.NSMakeRect(0, 0, w, h),
        $.NSMakeRect(0, 0, img.size.width, img.size.height),
        $.NSCompositingOperationCopy,
        1.0
    );

    if (drawGrid) {
        var cellW = w / cols;
        var cellH = h / rows;

        $.NSColor.colorWithCalibratedRedGreenBlueAlpha(0.0, 0.9, 1.0, 0.5).setStroke;
        var path = $.NSBezierPath.bezierPath;
        path.setLineWidth(2.0);
        for (var c = 1; c < cols; c++) {
            var x = c * cellW;
            path.moveToPoint($.NSMakePoint(x, 0));
            path.lineToPoint($.NSMakePoint(x, h));
        }
        for (var r = 1; r < rows; r++) {
            var y = r * cellH;
            path.moveToPoint($.NSMakePoint(0, y));
            path.lineToPoint($.NSMakePoint(w, y));
        }
        path.stroke;

        var font = $.NSFont.boldSystemFontOfSize(Math.max(16, Math.round(w / 72)));
        var attrs = $.NSMutableDictionary.dictionary;
        attrs.setObjectForKey(font, $("NSFont"));
        attrs.setObjectForKey($.NSColor.colorWithCalibratedRedGreenBlueAlpha(1.0, 0.95, 0.2, 0.95), $("NSColor"));

        for (var r = 0; r < rows; r++) {
            for (var c = 0; c < cols; c++) {
                var label = $(colLabels[c] + String(r + 1));
                var sz = label.sizeWithAttributes(attrs);
                var padX = 6, padY = 3;
                var bx = c * cellW + 8;
                var topY = h - r * cellH;
                var by = topY - sz.height - padY * 2 - 8;
                var bgRect = $.NSMakeRect(bx, by, sz.width + padX * 2, sz.height + padY * 2);
                $.NSColor.colorWithCalibratedRedGreenBlueAlpha(0.0, 0.0, 0.0, 0.62).setFill;
                $.NSBezierPath.bezierPathWithRoundedRectXRadiusYRadius(bgRect, 5, 5).fill;
                label.drawAtPointWithAttributes($.NSMakePoint(bx + padX, by + padY), attrs);

                // Chấm tròn nhỏ mờ ở tâm ô
                var cx = c * cellW + cellW / 2;
                var cy = h - (r * cellH + cellH / 2);
                $.NSColor.colorWithCalibratedRedGreenBlueAlpha(0.0, 0.9, 1.0, 0.35).setFill;
                $.NSBezierPath.bezierPathWithOvalInRect($.NSMakeRect(cx - 3.5, cy - 3.5, 7, 7)).fill;
            }
        }
    }

    if (hasMark) {
        var mx = Math.max(4, Math.min(w - 4, markNx * w));
        var my = Math.max(4, Math.min(h - 4, h - markNy * h));
        var radius = Math.max(18, Math.round(w / 85));

        // Nền sáng nhẹ
        $.NSColor.colorWithCalibratedRedGreenBlueAlpha(1.0, 0.2, 0.2, 0.25).setFill;
        $.NSBezierPath.bezierPathWithOvalInRect($.NSMakeRect(mx - radius, my - radius, radius * 2, radius * 2)).fill;

        // Vòng tròn đỏ
        $.NSColor.colorWithCalibratedRedGreenBlueAlpha(1.0, 0.12, 0.12, 0.96).setStroke;
        var ring = $.NSBezierPath.bezierPathWithOvalInRect($.NSMakeRect(mx - radius, my - radius, radius * 2, radius * 2));
        ring.setLineWidth(4.0);
        ring.stroke;

        // Dấu chữ thập ở tâm
        var cross = $.NSBezierPath.bezierPath;
        cross.setLineWidth(3.0);
        cross.moveToPoint($.NSMakePoint(mx - radius - 8, my));
        cross.lineToPoint($.NSMakePoint(mx + radius + 8, my));
        cross.moveToPoint($.NSMakePoint(mx, my - radius - 8));
        cross.lineToPoint($.NSMakePoint(mx, my + radius + 8));
        cross.stroke;
    }

    $.NSGraphicsContext.restoreGraphicsState;
    var props = $.NSDictionary.dictionaryWithObjectForKey($(0.82), $("NSImageCompressionFactor"));
    var jpgData = bmp.representationUsingTypeProperties($.NSBitmapImageFileTypeJPEG, props);
    var ok = jpgData.writeToFileAtomically(outPath, true);
    return ok ? "OK" : "WRITE_FAILED";
}
"""
    has_mark = "1" if mark_xy else "0"
    nx_str = f"{mark_xy[0]:.6f}" if mark_xy else "0.5"
    ny_str = f"{mark_xy[1]:.6f}" if mark_xy else "0.5"
    try:
        res = subprocess.run(
            [
                "osascript",
                "-l",
                "JavaScript",
                "-e",
                jxa,
                in_path,
                out_path,
                "1" if draw_grid else "0",
                has_mark,
                nx_str,
                ny_str,
            ],
            capture_output=True,
            text=True,
            timeout=12,
        )
        return res.returncode == 0 and res.stdout.strip() == "OK" and os.path.exists(out_path)
    except Exception:
        return False


def capture_screen(
    with_grid: bool = False,
    mark_xy: tuple[float, float] | None = None,
    hd: bool = False,
) -> dict:
    """Chụp màn hình thực tế máy Mac; hỗ trợ ảnh thường gọn nhẹ, ảnh HD gốc, lưới A1-H6 hoặc chấm đỏ đánh dấu."""
    wake_display()
    try:
        res = subprocess.run(
            ["/usr/sbin/screencapture", "-x", "-t", "jpg", SCREEN_RAW],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception as e:
        return {
            "ok": False,
            "permission_error": True,
            "error": (
                f"⚠️ Không thể chụp màn hình ({e}).\n"
                "👉 Bấm nút [⚙️ Mở Cài đặt Ghi màn hình] bên dưới để bật quyền cho Python/MacFileBot rồi thử lại nhé!"
            ),
        }

    if res.returncode != 0 or not os.path.exists(SCREEN_RAW) or os.path.getsize(SCREEN_RAW) == 0:
        return {
            "ok": False,
            "permission_error": True,
            "error": (
                "⚠️ Không thể chụp màn hình (macOS có thể chưa cấp quyền 'Ghi màn hình / Screen Recording' cho Python).\n"
                "👉 Bấm nút [⚙️ Mở Cài đặt Ghi màn hình] bên dưới để bật quyền cho Python/MacFileBot rồi thử lại nhé!"
            ),
        }

    lw, lh = get_screen_size()
    if hd and not with_grid and not mark_xy:
        return {
            "ok": True,
            "path": SCREEN_RAW,
            "raw_path": SCREEN_RAW,
            "logical_w": lw,
            "logical_h": lh,
        }

    try:
        subprocess.run(
            [
                "/usr/bin/sips",
                "-Z",
                "1920",
                "-s",
                "format",
                "jpeg",
                "-s",
                "formatOptions",
                "80",
                SCREEN_RAW,
                "--out",
                SCREEN_VIEW,
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception:
        pass

    base_img = SCREEN_VIEW if (os.path.exists(SCREEN_VIEW) and os.path.getsize(SCREEN_VIEW) > 0) else SCREEN_RAW

    if with_grid or mark_xy:
        if _render_overlay_jxa(base_img, SCREEN_GRID, with_grid, mark_xy):
            return {
                "ok": True,
                "path": SCREEN_GRID,
                "raw_path": SCREEN_RAW,
                "logical_w": lw,
                "logical_h": lh,
            }

    return {
        "ok": True,
        "path": base_img,
        "raw_path": SCREEN_RAW,
        "logical_w": lw,
        "logical_h": lh,
    }


def get_running_apps() -> dict:
    """Lấy danh sách các ứng dụng GUI đang chạy và ứng dụng đang hiển thị phía trước."""
    jxa = r"""
var se = Application("System Events");
var procs = se.applicationProcesses.whose({backgroundOnly: false})();
var names = [];
var front = "";
for (var i = 0; i < procs.length; i++) {
    try {
        var n = procs[i].name();
        if (n) {
            names.push(n);
            if (procs[i].frontmost()) front = n;
        }
    } catch(e) {}
}
JSON.stringify({front: front, apps: names});
"""
    try:
        res = subprocess.run(
            ["osascript", "-l", "JavaScript", "-e", jxa],
            capture_output=True,
            text=True,
            timeout=8,
        )
        if res.returncode == 0 and res.stdout.strip():
            data = json.loads(res.stdout.strip())
            seen = set()
            unique = []
            for n in data.get("apps", []):
                if n and n not in seen:
                    seen.add(n)
                    unique.append(n)
            return {"front": data.get("front", ""), "apps": unique}
    except Exception:
        pass
    return {"front": "", "apps": []}


def get_system_status() -> dict:
    """Thu thập báo cáo tình trạng thực tế của máy Mac: App đang mở, CPU, Pin, Âm lượng, Ổ đĩa."""
    app_info = get_running_apps()
    front_app = app_info.get("front") or "Không rõ"
    running_apps = app_info.get("apps", [])

    # Top 5 tiến trình ăn CPU cao nhất
    top_procs = []
    try:
        ps_res = subprocess.run(
            ["ps", "-Arcwwwxo", "%cpu,%mem,comm"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if ps_res.returncode == 0:
            lines = ps_res.stdout.strip().splitlines()[1:6]
            for ln in lines:
                parts = ln.strip().split(None, 2)
                if len(parts) == 3:
                    cpu_p, mem_p, comm = parts
                    comm_short = Path(comm).name
                    top_procs.append(f"{comm_short} (CPU {cpu_p}%, RAM {mem_p}%)")
    except Exception:
        pass

    # Pin / Nguồn điện
    batt_str = "Không rõ"
    try:
        pm_res = subprocess.run(["pmset", "-g", "batt"], capture_output=True, text=True, timeout=4)
        if pm_res.returncode == 0 and pm_res.stdout.strip():
            lines = [l.strip() for l in pm_res.stdout.strip().splitlines() if l.strip()]
            src = lines[0].replace("Now drawing from ", "") if lines else ""
            pct = ""
            if len(lines) > 1:
                m = re.search(r"(\d+%);\s*([^;]+)", lines[1])
                if m:
                    pct = f"{m.group(1)} ({m.group(2).strip()})"
            batt_str = f"{pct} — {src}".strip(" —") if (pct or src) else "Đang cắm nguồn"
    except Exception:
        pass

    # Âm lượng hiện tại
    vol_str = "Không rõ"
    try:
        v_res = subprocess.run(
            ["osascript", "-e", "get volume settings"],
            capture_output=True,
            text=True,
            timeout=4,
        )
        if v_res.returncode == 0:
            out_v = v_res.stdout.strip()
            m_vol = re.search(r"output volume:(\d+)", out_v)
            m_mute = re.search(r"output muted:(true|false)", out_v)
            if m_vol:
                muted = (m_mute and m_mute.group(1) == "true")
                vol_str = f"{m_vol.group(1)}%" + (" (Đang tắt tiếng)" if muted else "")
    except Exception:
        pass

    # Load average & dung lượng ổ đĩa
    load_str = "?"
    try:
        l1, l5, l15 = os.getloadavg()
        load_str = f"{l1:.2f} / {l5:.2f} / {l15:.2f}"
    except Exception:
        pass

    disk_str = "?"
    try:
        du = shutil.disk_usage("/")
        free_gb = du.free / (1024 ** 3)
        total_gb = du.total / (1024 ** 3)
        disk_str = f"Còn trống {free_gb:.1f} GB / {total_gb:.1f} GB"
    except Exception:
        pass

    lines = [
        "📊 TÌNH TRẠNG THỰC TẾ MÁY MAC HIỆN TẠI:",
        f"• 🪟 Ứng dụng đang mở chính: *{front_app}*",
        f"• 📱 Các app đang chạy ({len(running_apps)}): " + (", ".join(running_apps[:10]) if running_apps else "Không có"),
        f"• ⚡ Tải CPU (1/5/15 phút): `{load_str}`",
        f"• 🔋 Pin / Nguồn: {batt_str}",
        f"• 🔊 Âm lượng: {vol_str}",
        f"• 💾 Ổ đĩa chính: {disk_str}",
    ]
    if top_procs:
        lines.append("\n🔥 Top 5 tiến trình tốn tài nguyên nhất:")
        for idx, tp in enumerate(top_procs, 1):
            lines.append(f"  {idx}. {tp}")

    return {
        "ok": True,
        "front_app": front_app,
        "apps": running_apps,
        "reply": "\n".join(lines),
    }


def grid_cell_to_logical_xy(spec: str) -> tuple[float, float] | None:
    """Quy đổi mã ô lưới (A1..H6, có thể kèm trên/dưới/trái/phải) hoặc toạ độ pixel (x y) sang toạ độ logic."""
    if not spec:
        return None
    s = safe_fs.strip_accents(spec.strip()).lower()
    w, h = get_screen_size()

    # 1. Ô lưới A1..H6
    m_cell = re.search(r"\b([a-h])\s*([1-6])\b", s)
    if m_cell:
        col_ch = m_cell.group(1).upper()
        row_idx = int(m_cell.group(2)) - 1
        col_idx = COL_LABELS.index(col_ch)
        cell_w = w / GRID_COLS
        cell_h = h / GRID_ROWS

        cx = col_idx * cell_w + cell_w / 2.0
        cy = row_idx * cell_h + cell_h / 2.0

        if "trai" in s or "left" in s:
            cx -= cell_w * 0.25
        elif "phai" in s or "right" in s:
            cx += cell_w * 0.25
        if "tren" in s or "top" in s:
            cy -= cell_h * 0.25
        elif "duoi" in s or "bottom" in s:
            cy += cell_h * 0.25

        return cx, cy

    # 2. Toạ độ pixel trực tiếp "1280 720" hoặc "1280,720"
    m_px = re.search(r"\b(\d{1,5})\s*[,x\s]\s*(\d{1,5})\b", s)
    if m_px:
        x = float(m_px.group(1))
        y = float(m_px.group(2))
        return max(1.0, min(w - 1.0, x)), max(1.0, min(h - 1.0, y))

    return None


def mouse_click(x: float, y: float, button: str = "left", clicks: int = 1) -> dict:
    """Thực hiện click chuột tại toạ độ logic (x, y) bằng CoreGraphics CGEvent."""
    cg = _get_cg()
    if not cg:
        return {"ok": False, "error": "❌ Không thể tải thư viện CoreGraphics để điều khiển chuột."}

    w, h = get_screen_size()
    cx = max(1.0, min(float(w - 1), float(x)))
    cy = max(1.0, min(float(h - 1), float(y)))
    pt = _CGPoint(cx, cy)

    # kCGEventMouseMoved = 5
    mv_ev = cg.CGEventCreateMouseEvent(None, 5, pt, 0)
    if mv_ev:
        cg.CGEventPost(0, mv_ev)
        cg.CFRelease(mv_ev)
    time.sleep(0.05)

    is_right = (button == "right")
    down_type = 3 if is_right else 1
    up_type = 4 if is_right else 2
    btn_code = 1 if is_right else 0

    total_clicks = max(1, min(2, int(clicks)))
    for c_state in range(1, total_clicks + 1):
        d_ev = cg.CGEventCreateMouseEvent(None, down_type, pt, btn_code)
        u_ev = cg.CGEventCreateMouseEvent(None, up_type, pt, btn_code)
        if d_ev and u_ev:
            if total_clicks == 2:
                # kCGMouseEventClickState = 1
                cg.CGEventSetIntegerValueField(d_ev, 1, c_state)
                cg.CGEventSetIntegerValueField(u_ev, 1, c_state)
            cg.CGEventPost(0, d_ev)
            time.sleep(0.03)
            cg.CGEventPost(0, u_ev)
        if d_ev:
            cg.CFRelease(d_ev)
        if u_ev:
            cg.CFRelease(u_ev)
        if c_state < total_clicks:
            time.sleep(0.06)

    return {
        "ok": True,
        "x": round(cx, 1),
        "y": round(cy, 1),
        "norm_x": cx / float(w),
        "norm_y": cy / float(h),
    }


def mouse_scroll(direction: str = "down", steps: int = 6) -> dict:
    """Cuộn chuột lên hoặc xuống bằng CoreGraphics CGEventCreateScrollWheelEvent."""
    cg = _get_cg()
    if not cg:
        return {"ok": False, "error": "❌ Không thể tải thư viện CoreGraphics để cuộn chuột."}

    d_low = (direction or "down").lower().strip()
    delta = 5 if d_low in ("up", "len", "lên") else -5
    for _ in range(max(1, steps)):
        ev = cg.CGEventCreateScrollWheelEvent(None, 0, 1, delta)
        if ev:
            cg.CGEventPost(0, ev)
            cg.CFRelease(ev)
        time.sleep(0.04)
    label = "Lên" if delta > 0 else "Xuống"
    return {"ok": True, "direction": d_low, "reply": f"🖱 Đã cuộn màn hình *{label}*."}


def type_text(text: str, press_enter: bool = False) -> dict:
    """Gõ văn bản (hỗ trợ đầy đủ tiếng Việt có dấu) qua pbcopy + Cmd+V của System Events."""
    if text is None or text == "":
        return {"ok": False, "error": "⚠️ Không có nội dung văn bản để gõ."}
    try:
        subprocess.run(["pbcopy"], input=text.encode("utf-8"), check=True, timeout=5)
        cmd_script = 'tell application "System Events" to keystroke "v" using command down'
        r = subprocess.run(["osascript", "-e", cmd_script], capture_output=True, text=True, timeout=6)
        if r.returncode != 0:
            err = r.stderr.strip()
            return {
                "ok": False,
                "error": f"⚠️ Không thể dán văn bản vào cửa sổ hiện tại (kiểm tra quyền Trợ năng / Accessibility): {err}",
            }
        if press_enter:
            time.sleep(0.15)
            subprocess.run(
                ["osascript", "-e", 'tell application "System Events" to key code 36'],
                capture_output=True,
                text=True,
                timeout=5,
            )
        return {
            "ok": True,
            "reply": f"⌨️ Đã gõ văn bản: `{text[:120]}`" + (" + Enter" if press_enter else ""),
        }
    except Exception as e:
        return {"ok": False, "error": f"❌ Lỗi khi gõ văn bản: {e}"}


_KEY_CODES = {
    "enter": 36,
    "return": 36,
    "space": 49,
    "cach": 49,
    "esc": 53,
    "escape": 53,
    "tab": 48,
    "backspace": 51,
    "delete": 51,
    "up": 126,
    "len": 126,
    "down": 125,
    "xuong": 125,
    "left": 123,
    "trai": 123,
    "right": 124,
    "phai": 124,
    "home": 115,
    "end": 119,
    "pageup": 116,
    "pgup": 116,
    "pagedown": 121,
    "pgdn": 121,
}


def press_key(key_spec: str) -> dict:
    """Bấm phím đơn hoặc tổ hợp phím (vd: space, enter, cmd+s, cmd+tab, cmd+w...)."""
    if not key_spec or not key_spec.strip():
        return {"ok": False, "error": "⚠️ Bạn chưa chỉ định phím cần bấm."}

    norm = safe_fs.strip_accents(key_spec.strip()).lower()
    norm = re.sub(r"\s+", "", norm).replace("-", "+")
    parts = [p for p in norm.split("+") if p]

    # Chặn tổ hợp phím có nguy cơ xoá file / dọn thùng rác
    blocked_combos = {
        frozenset({"cmd", "delete"}),
        frozenset({"command", "delete"}),
        frozenset({"cmd", "backspace"}),
        frozenset({"command", "backspace"}),
        frozenset({"cmd", "shift", "delete"}),
        frozenset({"command", "shift", "delete"}),
        frozenset({"cmd", "shift", "backspace"}),
    }
    if frozenset(parts) in blocked_combos:
        return {
            "ok": False,
            "error": "🔒 CHẾ ĐỘ BẢO VỆ AN TOÀN: Bot chặn các tổ hợp phím xoá file (Cmd+Delete / Empty Trash).",
        }

    mod_map = {
        "cmd": "command down",
        "command": "command down",
        "ctrl": "control down",
        "control": "control down",
        "opt": "option down",
        "option": "option down",
        "alt": "option down",
        "shift": "shift down",
    }

    mods = []
    main_key = None
    for p in parts:
        if p in mod_map:
            if mod_map[p] not in mods:
                mods.append(mod_map[p])
        else:
            main_key = p

    if not main_key:
        return {"ok": False, "error": f"⚠️ Không nhận diện được phím chính trong `{key_spec}`."}

    using_clause = ""
    if mods:
        using_clause = " using {" + ", ".join(mods) + "}" if len(mods) > 1 else f" using {mods[0]}"

    if main_key in _KEY_CODES:
        code = _KEY_CODES[main_key]
        as_script = f'tell application "System Events" to key code {code}{using_clause}'
    elif len(main_key) == 1 and main_key.isalnum():
        as_script = f'tell application "System Events" to keystroke "{main_key}"{using_clause}'
    else:
        return {"ok": False, "error": f"⚠️ Phím `{key_spec}` chưa được hỗ trợ."}

    try:
        r = subprocess.run(["osascript", "-e", as_script], capture_output=True, text=True, timeout=6)
        if r.returncode == 0:
            return {"ok": True, "reply": f"⌨️ Đã bấm phím: `{key_spec}`"}
        return {
            "ok": False,
            "error": f"⚠️ Không thể bấm phím `{key_spec}` (kiểm tra quyền Trợ năng / Accessibility): {r.stderr.strip()}",
        }
    except Exception as e:
        return {"ok": False, "error": f"❌ Lỗi khi bấm phím `{key_spec}`: {e}"}


def _resolve_app_name(app_query: str) -> str | None:
    """Tìm tên app khớp trong danh sách app đang chạy hoặc danh sách app đã cài trên macOS."""
    q_norm = safe_fs.strip_accents(app_query.strip()).lower()
    if not q_norm:
        return None
    running = get_running_apps().get("apps", [])
    for name in running:
        if safe_fs.strip_accents(name).lower() == q_norm:
            return name
    for name in running:
        if q_norm in safe_fs.strip_accents(name).lower():
            return name
    matched_name, _ = safe_fs.match_app(app_query)
    return matched_name


def focus_app(app_query: str) -> dict:
    """Đưa cửa sổ một ứng dụng lên phía trước."""
    app_name = _resolve_app_name(app_query) or app_query.strip()
    try:
        r = subprocess.run(
            ["osascript", "-e", f'tell application "{app_name}" to activate'],
            capture_output=True,
            text=True,
            timeout=8,
        )
        if r.returncode == 0:
            return {"ok": True, "app_name": app_name, "reply": f"🪟 Đã chuyển màn hình sang ứng dụng *{app_name}*."}
        res = safe_fs.open_application(app_query)
        if res.get("ok"):
            return {"ok": True, "app_name": res.get("app_name", app_name), "reply": res.get("reply", "")}
        return {"ok": False, "error": f"❌ Không thể chuyển sang ứng dụng '{app_query}': {r.stderr.strip()}"}
    except Exception as e:
        return {"ok": False, "error": f"❌ Lỗi khi chuyển sang ứng dụng '{app_query}': {e}"}


def quit_app(app_query: str) -> dict:
    """Thoát nhẹ nhàng một ứng dụng (chặn các ứng dụng lõi hệ thống)."""
    app_name = _resolve_app_name(app_query) or app_query.strip()
    n_low = safe_fs.strip_accents(app_name).lower()
    if any(p in n_low for p in PROTECTED_APPS):
        return {
            "ok": False,
            "error": f"🔒 Không thể tắt ứng dụng hệ thống lõi *{app_name}* để đảm bảo bot hoạt động liên tục.",
        }
    try:
        r = subprocess.run(
            ["osascript", "-e", f'tell application "{app_name}" to quit'],
            capture_output=True,
            text=True,
            timeout=8,
        )
        if r.returncode == 0:
            return {
                "ok": True,
                "app_name": app_name,
                "reply": f"✅ Đã gửi lệnh thoát nhẹ nhàng ứng dụng *{app_name}*.",
            }
        return {"ok": False, "error": f"❌ Không thể thoát '{app_name}': {r.stderr.strip()}"}
    except Exception as e:
        return {"ok": False, "error": f"❌ Lỗi khi thoát '{app_name}': {e}"}


def set_volume(action: str, value: int | None = None) -> dict:
    """Điều chỉnh âm lượng macOS: up (+15), down (-15), mute, unmute, toggle, set (0..100)."""
    try:
        v_res = subprocess.run(["osascript", "-e", "get volume settings"], capture_output=True, text=True, timeout=4)
        cur_vol = 50
        cur_muted = False
        if v_res.returncode == 0:
            mv = re.search(r"output volume:(\d+)", v_res.stdout)
            mm = re.search(r"output muted:(true|false)", v_res.stdout)
            if mv:
                cur_vol = int(mv.group(1))
            if mm:
                cur_muted = (mm.group(1) == "true")

        act = (action or "").lower().strip()
        if act == "up":
            new_v = min(100, cur_vol + 15)
            subprocess.run(["osascript", "-e", f"set volume output muted false output volume {new_v}"], capture_output=True, timeout=4)
            return {"ok": True, "reply": f"🔊 Đã tăng âm lượng lên *{new_v}%*."}
        if act == "down":
            new_v = max(0, cur_vol - 15)
            subprocess.run(["osascript", "-e", f"set volume output muted false output volume {new_v}"], capture_output=True, timeout=4)
            return {"ok": True, "reply": f"🔉 Đã giảm âm lượng xuống *{new_v}%*."}
        if act == "mute":
            subprocess.run(["osascript", "-e", "set volume with output muted"], capture_output=True, timeout=4)
            return {"ok": True, "reply": "🔇 Đã tắt tiếng máy Mac."}
        if act == "unmute":
            subprocess.run(["osascript", "-e", "set volume without output muted"], capture_output=True, timeout=4)
            return {"ok": True, "reply": f"🔊 Đã bật lại âm thanh (*{cur_vol}%*)."}
        if act == "toggle":
            if cur_muted:
                subprocess.run(["osascript", "-e", "set volume without output muted"], capture_output=True, timeout=4)
                return {"ok": True, "reply": f"🔊 Đã bật lại âm thanh (*{cur_vol}%*)."}
            subprocess.run(["osascript", "-e", "set volume with output muted"], capture_output=True, timeout=4)
            return {"ok": True, "reply": "🔇 Đã tắt tiếng máy Mac."}
        if act == "set" and value is not None:
            new_v = max(0, min(100, int(value)))
            subprocess.run(["osascript", "-e", f"set volume output muted false output volume {new_v}"], capture_output=True, timeout=4)
            return {"ok": True, "reply": f"🔊 Đã đặt âm lượng ở mức *{new_v}%*."}
        return {"ok": False, "error": f"⚠️ Thao tác âm lượng '{action}' không hợp lệ."}
    except Exception as e:
        return {"ok": False, "error": f"❌ Lỗi chỉnh âm lượng: {e}"}


def lock_screen() -> dict:
    """Khoá màn hình máy Mac (tương đương Ctrl+Cmd+Q)."""
    try:
        r = subprocess.run(
            ["osascript", "-e", 'tell application "System Events" to keystroke "q" using {control down, command down}'],
            capture_output=True,
            text=True,
            timeout=6,
        )
        if r.returncode == 0:
            return {"ok": True, "reply": "🔒 Đã khoá màn hình máy Mac an toàn!"}
        return {"ok": False, "error": f"⚠️ Không thể khoá màn hình: {r.stderr.strip()}"}
    except Exception as e:
        return {"ok": False, "error": f"❌ Lỗi khoá màn hình: {e}"}


def sleep_display() -> dict:
    """Tắt màn hình máy Mac ngay để tiết kiệm điện / bảo mật."""
    try:
        r = subprocess.run(["/usr/bin/pmset", "displaysleepnow"], capture_output=True, text=True, timeout=6)
        if r.returncode == 0:
            return {"ok": True, "reply": "🌙 Đã tắt màn hình máy Mac (máy vẫn chạy ngầm phục vụ bot & render)."}
        return {"ok": False, "error": f"⚠️ Không thể tắt màn hình: {r.stderr.strip()}"}
    except Exception as e:
        return {"ok": False, "error": f"❌ Lỗi tắt màn hình: {e}"}


def open_screen_recording_settings() -> dict:
    """Mở đúng trang Cài đặt quyền Ghi màn hình (Screen Recording) trong System Settings."""
    try:
        subprocess.run(
            ["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture"],
            capture_output=True,
            timeout=6,
        )
        return {
            "ok": True,
            "reply": (
                "⚙️ Đã mở màn hình *Quyền riêng tư & Bảo mật → Ghi màn hình (Screen Recording)* trên máy Mac!\n"
                "👉 Bạn hãy gạt BẬT công tắc cho `Python` / `Terminal` / `MacFileBot` rồi thử chụp lại nhé."
            ),
        }
    except Exception as e:
        return {"ok": False, "error": f"❌ Không thể mở Cài đặt hệ thống: {e}"}


def launch_remote_desktop(tool_name: str = "rustdesk") -> dict:
    """Mở RustDesk hoặc AnyDesk, đợi giao diện hiện ID kết nối rồi chụp màn hình gửi lên Telegram."""
    t_low = (tool_name or "rustdesk").lower().strip()
    target_tool = "anydesk" if "anydesk" in t_low else "rustdesk"
    res = safe_fs.open_application(target_tool)
    if not res.get("ok"):
        return {
            "ok": False,
            "error": res.get("error") or f"❌ Máy Mac chưa cài {target_tool.capitalize()}.",
        }
    time.sleep(2.5)
    cap = capture_screen(with_grid=False)
    app_title = res.get("app_name", target_tool.capitalize())
    if cap.get("ok"):
        return {
            "ok": True,
            "photo_path": cap["path"],
            "reply": (
                f"🖥 ĐÃ MỞ *{app_title}* ĐỂ BẠN ĐIỀU KHIỂN FULL MÀN HÌNH 60FPS!\n"
                f"👉 Xem mã ID / mật khẩu ngay trên ảnh và nhập vào app {app_title} trên điện thoại để kết nối."
            ),
        }
    return {
        "ok": True,
        "reply": res.get("reply", f"🖥 Đã mở *{app_title}*.") + f"\n⚠️ ({cap.get('error', 'Không chụp được ảnh')})",
    }


def build_remote_keyboard(grid_mode: bool = False) -> dict:
    """Tạo bảng nút bấm Điều khiển Máy Mac từ xa gắn ngay dưới ảnh chụp màn hình."""
    toggle_btn = (
        {"text": "🖼 Ảnh thường", "callback_data": "rc_snap"}
        if grid_mode
        else {"text": "🎯 Bật lưới Click", "callback_data": "rc_grid"}
    )
    return {
        "inline_keyboard": [
            [
                {"text": "🔄 Chụp lại", "callback_data": "rc_snap"},
                toggle_btn,
                {"text": "🔍 Ảnh nét HD", "callback_data": "rc_hd"},
            ],
            [
                {"text": "⏯ Space", "callback_data": "rc_key:space"},
                {"text": "⏎ Enter", "callback_data": "rc_key:enter"},
                {"text": "⎋ Esc", "callback_data": "rc_key:esc"},
                {"text": "💾 Cmd+S", "callback_data": "rc_key:cmd+s"},
            ],
            [
                {"text": "⬆️ Cuộn lên", "callback_data": "rc_scroll:up"},
                {"text": "⬇️ Cuộn xuống", "callback_data": "rc_scroll:down"},
                {"text": "🔄 Cmd+Tab", "callback_data": "rc_key:cmd+tab"},
                {"text": "❎ Đóng Tab", "callback_data": "rc_key:cmd+w"},
            ],
            [
                {"text": "🔊 Vol+", "callback_data": "rc_vol:up"},
                {"text": "🔉 Vol-", "callback_data": "rc_vol:down"},
                {"text": "🔇 Tiếng", "callback_data": "rc_vol:toggle"},
                {"text": "🔒 Khoá máy", "callback_data": "rc_lock"},
            ],
            [
                {"text": "🖥 Mở RustDesk", "callback_data": "rc_remote:rustdesk"},
                {"text": "📱 Mở AnyDesk", "callback_data": "rc_remote:anydesk"},
                {"text": "📊 Tình trạng", "callback_data": "rc_status"},
            ],
            [
                {"text": "📱 App đang chạy", "callback_data": "rc_apps"},
                {"text": "🏠 Menu chính", "callback_data": "home"},
            ],
        ]
    }
