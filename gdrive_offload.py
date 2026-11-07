#!/usr/bin/env python3
from __future__ import annotations
"""
"Xoá bản tải về" (Remove Download) cho Google Drive for Desktop — giải phóng dung lượng máy Mac.

QUAN TRỌNG — ĐÂY KHÔNG PHẢI LÀ XOÁ FILE:
- Chỉ gỡ BẢN SAO CỤC BỘ (cache) của file nằm trong thư mục Google Drive trên máy Mac,
  giống hệt lệnh "Xoá bản tải về" khi click chuột phải trong Finder.
- File vẫn nằm nguyên vẹn trên Google Drive (đám mây) và vẫn hiện trong Finder (biểu tượng đám mây),
  bấm mở là tự tải về lại. File gốc ở ổ cứng (FILM DATA, SOURCE...) KHÔNG bị đụng tới.
- Chỉ thực hiện khi TOÀN BỘ file bên trong đã được Google Drive xác nhận tải lên đám mây 100%
  (NSURLUbiquitousItemIsUploaded = true, không còn đang tải lên, không lỗi, không xung đột,
  có Cloud ID thật), kiểm tra 2 lần cách nhau một khoảng thời gian, và (nếu biết file gốc)
  số lượng file + tổng dung lượng phải khớp tuyệt đối với bản gốc.
- Tuyệt đối từ chối với mọi đường dẫn nằm ngoài thư mục Google Drive.
"""

import json
import os
import subprocess
import threading
import time
from pathlib import Path

import safe_fs

BASE_DIR = Path(__file__).parent.resolve()
JOBS_PATH = BASE_DIR / "offload_jobs.json"
SETTINGS_PATH = BASE_DIR / "offload_settings.json"

BATCH_SIZE = 150
STABILITY_GAP_SEC = 20          # 2 lần kiểm tra 100% liên tiếp phải cách nhau ít nhất 20 giây
POLL_INTERVAL_SEC = 30
MAX_WAIT_SEC = 48 * 3600        # chờ đồng bộ tối đa 48 giờ

_IGNORED_NAMES = {".DS_Store", "Icon\r", ".localized"}
_jobs_lock = threading.Lock()
_active_jobs: set[str] = set()

# JXA (JavaScript for Automation) gọi trực tiếp API macOS NSURL / NSFileManager.
# mode = "status": chỉ đọc trạng thái. mode = "evict": kiểm tra lại từng file NGAY TRƯỚC khi gỡ bản tải về,
# file nào chưa upload xong 100% thì bỏ qua (không gỡ).
_JXA = r"""
ObjC.import('Foundation');
function val(url, key) {
  var ref = Ref();
  var ok = url.getResourceValueForKeyError(ref, $[key], null);
  var v = ref[0];
  if (!ok || !v || v.isNil()) return null;
  return ObjC.unwrap(v.description);
}
function run(argv) {
  var mode = argv[0];
  var out = [];
  var fm = $.NSFileManager.defaultManager;
  for (var i = 1; i < argv.length; i++) {
    var p = argv[i];
    var url = $.NSURL.fileURLWithPath(p);
    var r = {
      p: p,
      ubiq: val(url, 'NSURLIsUbiquitousItemKey'),
      up: val(url, 'NSURLUbiquitousItemIsUploadedKey'),
      uping: val(url, 'NSURLUbiquitousItemIsUploadingKey'),
      err: val(url, 'NSURLUbiquitousItemUploadingErrorKey'),
      conf: val(url, 'NSURLUbiquitousItemHasUnresolvedConflictsKey'),
      dl: val(url, 'NSURLUbiquitousItemDownloadingStatusKey')
    };
    if (mode === 'evict') {
      var safe = (r.ubiq === '1' && r.up === '1' && r.uping !== '1' && !r.err && r.conf !== '1');
      if (!safe) {
        r.evicted = false; r.skip = 'not_uploaded';
      } else if (r.dl && r.dl.indexOf('NotDownloaded') >= 0) {
        r.evicted = true; r.already = true;
      } else {
        var e = Ref();
        var ok = fm.evictUbiquitousItemAtURLError(url, e);
        r.evicted = !!ok;
        if (!ok && e[0] && !e[0].isNil()) r.error = ObjC.unwrap(e[0].localizedDescription);
      }
    }
    out.push(r);
  }
  return JSON.stringify(out);
}
"""


# ---------------------------------------------------------------- settings
def is_auto_offload_enabled() -> bool:
    data = safe_fs._read_json(SETTINGS_PATH)
    return bool(data.get("auto_offload_after_upload", True))


def set_auto_offload(enabled: bool) -> None:
    data = safe_fs._read_json(SETTINGS_PATH) or {}
    data["auto_offload_after_upload"] = bool(enabled)
    safe_fs._write_json(SETTINGS_PATH, data)


# ---------------------------------------------------------------- helpers
def _gdrive_mount_roots() -> list[Path]:
    roots = []
    cs = Path.home() / "Library" / "CloudStorage"
    try:
        if cs.exists():
            for e in cs.iterdir():
                if e.name.startswith("GoogleDrive") and e.is_dir():
                    roots.append(e.resolve())
    except OSError:
        pass
    try:
        for e in Path("/Volumes").iterdir():
            if "googledrive" in e.name.lower().replace(" ", ""):
                roots.append(e.resolve())
    except OSError:
        pass
    return roots


def is_inside_google_drive(path: str | Path) -> bool:
    try:
        p = Path(path).expanduser().resolve()
    except Exception:
        return False
    for r in _gdrive_mount_roots():
        try:
            p.relative_to(r)
            if p != r:
                return True
        except ValueError:
            continue
    return False


def _list_files(root: Path) -> list[Path]:
    if root.is_file():
        return [root]
    files = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for f in filenames:
            if f in _IGNORED_NAMES or f.startswith("._"):
                continue
            fp = Path(dirpath) / f
            if fp.is_symlink():
                continue
            files.append(fp)
    return files


def _logical_and_local_bytes(files: list[Path]) -> tuple[int, int]:
    logical = 0
    local = 0
    for f in files:
        try:
            st = f.stat()
            logical += st.st_size
            local += getattr(st, "st_blocks", 0) * 512
        except OSError:
            pass
    return logical, local


def _run_jxa(mode: str, paths: list[str]) -> list[dict]:
    results: list[dict] = []
    for i in range(0, len(paths), BATCH_SIZE):
        chunk = paths[i : i + BATCH_SIZE]
        try:
            res = subprocess.run(
                ["osascript", "-l", "JavaScript", "-e", _JXA, mode, *chunk],
                capture_output=True,
                text=True,
                timeout=180,
            )
            if res.returncode != 0:
                raise RuntimeError(res.stderr.strip() or "osascript failed")
            results.extend(json.loads(res.stdout.strip() or "[]"))
        except Exception as e:
            # Nếu không đọc được trạng thái -> coi như CHƯA an toàn (không bao giờ gỡ)
            for p in chunk:
                results.append({"p": p, "up": None, "fail": str(e)})
    return results


# ---------------------------------------------------------------- status
def check_sync_status(path: str | Path, src_path: str | Path | None = None) -> dict:
    """
    Kiểm tra xem toàn bộ file trong `path` (nằm trong Google Drive) đã tải lên đám mây 100% chưa.
    Trả về dict: ok_100, total, uploaded, pending (list tên), errors, logical_bytes, local_bytes, reasons.
    """
    p = Path(path).expanduser().resolve()
    info = {
        "path": str(p),
        "name": p.name,
        "ok_100": False,
        "total": 0,
        "uploaded": 0,
        "pending": [],
        "errors": [],
        "logical_bytes": 0,
        "local_bytes": 0,
        "reasons": [],
    }
    if not p.exists():
        info["reasons"].append("Đường dẫn không còn tồn tại.")
        return info
    if not is_inside_google_drive(p):
        info["reasons"].append("Mục này KHÔNG nằm trong thư mục Google Drive — từ chối để bảo vệ dữ liệu gốc.")
        return info

    files = _list_files(p)
    info["total"] = len(files)
    info["logical_bytes"], info["local_bytes"] = _logical_and_local_bytes(files)
    if not files:
        info["reasons"].append("Thư mục không có file nào để gỡ bản tải về.")
        return info

    statuses = _run_jxa("status", [str(f) for f in files])
    by_path = {s.get("p"): s for s in statuses}
    uploaded = 0
    for f in files:
        s = by_path.get(str(f), {})
        cid = safe_fs.get_gdrive_cloud_id_from_xattr(f)
        good = (
            s.get("ubiq") == "1"
            and s.get("up") == "1"
            and s.get("uping") != "1"
            and not s.get("err")
            and s.get("conf") != "1"
            and bool(cid)
            and not str(cid).startswith("local_")
        )
        if good:
            uploaded += 1
        else:
            if s.get("err") or s.get("fail"):
                info["errors"].append(f"{f.name}: {s.get('err') or s.get('fail')}")
            info["pending"].append(str(f.relative_to(p)) if p.is_dir() else f.name)
    info["uploaded"] = uploaded

    if src_path:
        src = Path(src_path).expanduser()
        if src.exists():
            src_files = _list_files(src.resolve())
            src_logical, _ = _logical_and_local_bytes(src_files)
            if len(src_files) != len(files):
                info["reasons"].append(
                    f"Số file trên Drive ({len(files)}) chưa khớp với bản gốc ({len(src_files)})."
                )
            if src_logical != info["logical_bytes"]:
                info["reasons"].append(
                    f"Tổng dung lượng trên Drive ({safe_fs.format_size(info['logical_bytes'])}) "
                    f"chưa khớp bản gốc ({safe_fs.format_size(src_logical)})."
                )

    if uploaded != len(files):
        info["reasons"].append(f"Mới đồng bộ {uploaded}/{len(files)} file lên đám mây.")
    info["ok_100"] = uploaded == len(files) and not info["reasons"]
    return info


def format_status_text(st: dict) -> str:
    pct = (st["uploaded"] * 100 // st["total"]) if st["total"] else 0
    lines = [
        f"☁️ TRẠNG THÁI ĐỒNG BỘ: {st['name']}",
        f"• Đã lên đám mây: {st['uploaded']}/{st['total']} file ({pct}%)",
        f"• Dung lượng: {safe_fs.format_size(st['logical_bytes'])}",
        f"• Đang chiếm trên máy Mac: {safe_fs.format_size(st['local_bytes'])}",
    ]
    if st["pending"]:
        sample = "\n".join(f"   - {n}" for n in st["pending"][:5])
        more = f"\n   ... và {len(st['pending']) - 5} file khác" if len(st["pending"]) > 5 else ""
        lines.append(f"• Chưa đồng bộ xong:\n{sample}{more}")
    if st["errors"]:
        lines.append("• ⚠️ Lỗi: " + "; ".join(st["errors"][:3]))
    return "\n".join(lines)


# ---------------------------------------------------------------- evict
def offload_local_copy(path: str | Path, src_path: str | Path | None = None, require_stable: bool = True) -> dict:
    """
    Gỡ bản tải về (giải phóng dung lượng) — CHỈ KHI đồng bộ 100% đã được xác minh.
    """
    st1 = check_sync_status(path, src_path)
    if not st1["ok_100"]:
        return {"ok": False, "status": st1, "error": " ".join(st1["reasons"]) or "Chưa đồng bộ xong 100%."}

    if require_stable:
        time.sleep(STABILITY_GAP_SEC)
        st2 = check_sync_status(path, src_path)
        if not st2["ok_100"] or st2["total"] != st1["total"] or st2["logical_bytes"] != st1["logical_bytes"]:
            return {"ok": False, "status": st2, "error": "Trạng thái đồng bộ chưa ổn định, sẽ kiểm tra lại sau."}
        st1 = st2

    p = Path(path).expanduser().resolve()
    files = _list_files(p)
    before_local = _logical_and_local_bytes(files)[1]
    results = _run_jxa("evict", [str(f) for f in files])
    failed = [r for r in results if not r.get("evicted")]
    time.sleep(2)
    after_local = _logical_and_local_bytes(files)[1]
    freed = max(0, before_local - after_local)
    return {
        "ok": not failed,
        "status": st1,
        "total": len(files),
        "evicted": len(files) - len(failed),
        "failed": [Path(r.get("p", "")).name + (f" ({r.get('error') or r.get('skip')})") for r in failed],
        "freed_bytes": freed,
        "freed_human": safe_fs.format_size(freed),
        "remaining_local": safe_fs.format_size(after_local),
    }


def format_offload_result(res: dict) -> str:
    st = res.get("status", {})
    if res.get("ok"):
        return (
            f"🧹 ĐÃ XOÁ BẢN TẢI VỀ THÀNH CÔNG (giải phóng dung lượng máy Mac):\n\n"
            f"• Mục: {st.get('name')}\n"
            f"• Đã xác minh đồng bộ 100%: {st.get('uploaded')}/{st.get('total')} file\n"
            f"• Đã giải phóng: {res.get('freed_human')}\n\n"
            f"✅ File vẫn còn nguyên trên Google Drive (đám mây) và vẫn hiện trong Finder — bấm mở là tự tải lại.\n"
            f"✅ File gốc trên ổ cứng không bị đụng tới."
        )
    if "evicted" in res:
        fails = "\n".join(f"   - {x}" for x in res.get("failed", [])[:5])
        return (
            f"⚠️ Đã gỡ bản tải về {res.get('evicted')}/{res.get('total')} file "
            f"(giải phóng {res.get('freed_human')}). Một số file chưa gỡ được:\n{fails}"
        )
    return f"⏳ CHƯA XOÁ BẢN TẢI VỀ — để an toàn:\n{res.get('error')}\n\n{format_status_text(st) if st else ''}"


# ---------------------------------------------------------------- background jobs
def _load_jobs() -> list[dict]:
    try:
        if JOBS_PATH.exists():
            data = json.loads(JOBS_PATH.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
    except Exception:
        pass
    return []


def _save_jobs(jobs: list[dict]) -> None:
    try:
        JOBS_PATH.write_text(json.dumps(jobs, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def _remove_job(dst: str) -> None:
    with _jobs_lock:
        jobs = [j for j in _load_jobs() if j.get("dst") != dst]
        _save_jobs(jobs)
        _active_jobs.discard(dst)


def _job_worker(dst: str, src: str | None, started: float) -> None:
    last_pct_notice = -1
    try:
        while time.time() - started < MAX_WAIT_SEC:
            if not Path(dst).exists():
                safe_fs.send_telegram_notification(
                    f"ℹ️ Huỷ tự động xoá bản tải về: '{Path(dst).name}' không còn trong Google Drive."
                )
                return
            st = check_sync_status(dst, src)
            if st["ok_100"]:
                res = offload_local_copy(dst, src, require_stable=True)
                if res.get("ok") or "evicted" in res:
                    safe_fs.send_telegram_notification(format_offload_result(res))
                    return
            else:
                pct = (st["uploaded"] * 100 // st["total"]) if st["total"] else 0
                # Báo tiến độ mỗi khi qua mốc 50%
                if pct >= 50 and last_pct_notice < 50:
                    last_pct_notice = pct
            time.sleep(POLL_INTERVAL_SEC)
        safe_fs.send_telegram_notification(
            f"⚠️ Sau 48 giờ '{Path(dst).name}' vẫn chưa đồng bộ đủ 100% lên Google Drive, "
            f"nên tôi KHÔNG xoá bản tải về. Hãy kiểm tra ứng dụng Google Drive trên máy Mac."
        )
    finally:
        _remove_job(dst)


def schedule_offload_when_synced(dst: str | Path, src: str | Path | None = None, notify: bool = False) -> dict:
    """Đăng ký 1 tác vụ nền: chờ đồng bộ 100% rồi tự động xoá bản tải về (lưu lại để chạy tiếp sau khi khởi động lại)."""
    dst_s = str(Path(dst).expanduser().resolve())
    if not is_inside_google_drive(dst_s):
        return {"ok": False, "error": "Mục này không nằm trong Google Drive."}
    src_s = str(Path(src).expanduser().resolve()) if src else None
    with _jobs_lock:
        if dst_s in _active_jobs:
            return {"ok": True, "already": True}
        jobs = [j for j in _load_jobs() if j.get("dst") != dst_s]
        started = time.time()
        jobs.append({"dst": dst_s, "src": src_s, "ts": started})
        _save_jobs(jobs)
        _active_jobs.add(dst_s)
    threading.Thread(target=_job_worker, args=(dst_s, src_s, started), daemon=True).start()
    if notify:
        safe_fs.send_telegram_notification(
            f"🧹 Đã hẹn: khi '{Path(dst_s).name}' đồng bộ xong 100% lên Google Drive, "
            f"tôi sẽ tự động xoá bản tải về để giải phóng dung lượng máy Mac."
        )
    return {"ok": True}


def resume_pending_jobs() -> int:
    """Gọi khi bot khởi động: chạy tiếp các tác vụ chờ đồng bộ còn dang dở."""
    count = 0
    with _jobs_lock:
        jobs = _load_jobs()
    for j in jobs:
        dst = j.get("dst")
        if not dst or dst in _active_jobs:
            continue
        with _jobs_lock:
            _active_jobs.add(dst)
        threading.Thread(
            target=_job_worker, args=(dst, j.get("src"), float(j.get("ts") or time.time())), daemon=True
        ).start()
        count += 1
    return count


def list_pending_jobs() -> list[dict]:
    return _load_jobs()
