#!/usr/bin/env python3
from __future__ import annotations
"""
Safe File System Operations (NO DELETE ALLOWED) + Google Drive Link Extractor.
Allowed operations:
- List drives (/Volumes) and check disk free/used space
- Browse directories (ls)
- Search files by name/extension (find)
- Copy files/directories without overwriting existing files (cp)
- Move files/directories safely without overwriting existing files (mv)
- Upload to Google Drive (defaults to 'THIEN UNG PRODUCTION' folder) & auto-extract share links!

Strictly prohibited:
- Deleting any file or folder (rm, rmdir, unlink, trash)
- Overwriting any existing file at destination
"""

import json
import os
import re
import shutil
import sqlite3
import subprocess
import threading
import time
import unicodedata
import urllib.request
import ssl
from pathlib import Path
from datetime import datetime

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

BASE_DIR = Path(__file__).parent.resolve()
CONFIG_PATH = BASE_DIR / "config.json"


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def extract_gdrive_id_from_url(url_or_text: str) -> str | None:
    """Extract Google Drive folder/file cloud ID from a URL or raw ID."""
    raw = url_or_text.strip().strip("\"'<>")
    match = re.search(r"drive\.google\.com/(?:drive/(?:u/\d+/)?folders/|file/d/|open\?id=)([a-zA-Z0-9_-]+)", raw)
    if match:
        return match.group(1)
    if re.match(r"^[a-zA-Z0-9_-]{25,}$", raw):
        return raw
    return None


def lookup_gdrive_folder_by_id(cloud_id: str) -> dict | None:
    """Look up folder metadata in local Google DriveFS SQLite DB by cloud_id."""
    dbs = get_drivefs_db_paths()
    for db in dbs:
        try:
            conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=5)
            row = conn.execute("""
                SELECT i.local_title, i.is_folder, i.is_owner, i.shared_with_me_date, s.cloud_id
                FROM items i
                LEFT JOIN stable_ids s ON i.stable_id = s.stable_id
                WHERE (s.cloud_id = ? OR i.id = ?) AND i.trashed = 0 AND i.is_tombstone = 0
            """, (cloud_id, cloud_id)).fetchone()
            conn.close()
            if row:
                title, is_folder, is_owner, shared_date, cid = row
                is_shared = (is_owner == 0) or (shared_date is not None and int(shared_date or 0) > 0)
                effective_id = cid or cloud_id
                return {
                    "title": title,
                    "is_folder": bool(is_folder),
                    "is_shared": is_shared,
                    "cloud_id": effective_id,
                    "url": f"https://drive.google.com/drive/folders/{effective_id}?usp=sharing",
                }
        except Exception:
            continue
    return None


def fetch_gdrive_title_from_web(cloud_id: str) -> str | None:
    """Fallback: Fetch folder title from public web metadata if DriveFS DB hasn't indexed it yet."""
    url = f"https://drive.google.com/drive/folders/{cloud_id}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with _urlopen_robust(req, timeout=4) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
            m = re.search(r'<meta property="og:title" content="([^"]+)"', html)
            if m:
                return m.group(1).replace(" - Google Drive", "").strip()
            t = re.search(r"<title>([^<]+)</title>", html)
            if t:
                return t.group(1).replace(" - Google Drive", "").strip()
    except Exception:
        pass
    return None


def resolve_target_gdrive_folder(raw_input: str) -> dict:
    """
    Resolve user input (URL or folder name) to title, cloud_id, url, and is_shared status.
    """
    inp = raw_input.strip().strip("\"'<>")
    cid = extract_gdrive_id_from_url(inp)

    if cid:
        info = lookup_gdrive_folder_by_id(cid)
        if not info:
            web_title = fetch_gdrive_title_from_web(cid)
            info = {
                "title": web_title or f"Folder_{cid[:8]}",
                "is_folder": True,
                "is_shared": True,
                "cloud_id": cid,
                "url": f"https://drive.google.com/drive/folders/{cid}?usp=sharing",
            }
        return info
    else:
        matches = query_gdrive_items(inp)
        folder_matches = [m for m in matches if m.get("is_dir")]
        if folder_matches:
            best = folder_matches[0]
            return {
                "title": best["name"],
                "is_folder": True,
                "is_shared": best.get("is_shared", False),
                "cloud_id": best.get("cloud_id"),
                "url": best.get("url"),
            }
        return {
            "title": inp,
            "is_folder": True,
            "is_shared": False,
            "cloud_id": None,
            "url": None,
        }


def get_default_gdrive_subfolder() -> str:
    cfg = _read_json(CONFIG_PATH)
    return cfg.get("default_gdrive_folder") or "THIEN UNG PRODUCTION"


def get_default_gdrive_folder_info() -> dict:
    cfg = _read_json(CONFIG_PATH)
    folder_name = cfg.get("default_gdrive_folder") or "THIEN UNG PRODUCTION"
    folder_id = cfg.get("default_gdrive_folder_id")
    folder_url = cfg.get("default_gdrive_folder_url")
    is_shared = cfg.get("default_gdrive_is_shared", False)
    gdrive_root = find_google_drive_root(auto_launch=False)
    local_path = None
    if gdrive_root:
        local_path = resolve_subfolder_fuzzy(gdrive_root, folder_name)
    return {
        "folder_name": folder_name,
        "folder_id": folder_id,
        "folder_url": folder_url,
        "is_shared": is_shared,
        "local_path": str(local_path) if local_path else None,
        "exists_locally": bool(local_path and local_path.exists()),
    }


def set_default_gdrive_folder(raw_input: str) -> dict:
    """
    Set default Google Drive upload folder from a URL or name,
    save to config.json and create/verify local folder on Mac.
    """
    info = resolve_target_gdrive_folder(raw_input)
    folder_name = info["title"]
    cloud_id = info.get("cloud_id")
    folder_url = info.get("url")
    is_shared = info.get("is_shared", False)

    cfg = _read_json(CONFIG_PATH)
    cfg["default_gdrive_folder"] = folder_name
    if cloud_id:
        cfg["default_gdrive_folder_id"] = cloud_id
    if folder_url:
        cfg["default_gdrive_folder_url"] = folder_url
    cfg["default_gdrive_is_shared"] = is_shared
    _write_json(CONFIG_PATH, cfg)

    global DEFAULT_GDRIVE_SUBFOLDER
    DEFAULT_GDRIVE_SUBFOLDER = folder_name

    gdrive_root = find_google_drive_root(auto_launch=True)
    local_path = None
    if gdrive_root:
        local_path = resolve_subfolder_fuzzy(gdrive_root, folder_name)
        try:
            local_path.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass

    return {
        "ok": True,
        "folder_name": folder_name,
        "cloud_id": cloud_id,
        "folder_url": folder_url,
        "is_shared": is_shared,
        "local_path": str(local_path) if local_path else None,
    }


DEFAULT_GDRIVE_SUBFOLDER = get_default_gdrive_subfolder()


def strip_accents(s: str) -> str:
    """Normalize Vietnamese accents for flexible folder/file matching."""
    s = s.replace("đ", "d").replace("Đ", "D")
    return "".join(
        c for c in unicodedata.normalize("NFD", s)
        if unicodedata.category(c) != "Mn"
    ).lower()


def format_size(num_bytes: int) -> str:
    """Format byte size into human-readable string."""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if abs(num_bytes) < 1024.0:
            return f"{num_bytes:.1f} {unit}" if unit != "B" else f"{num_bytes} B"
        num_bytes /= 1024.0
    return f"{num_bytes:.1f} PB"


def get_unique_destination(dst_path: Path) -> Path:
    """
    Ensure we NEVER overwrite an existing file or folder.
    If dst_path exists, append ' (copy 1)', ' (copy 2)', etc.
    """
    if not dst_path.exists():
        return dst_path
    stem = dst_path.stem
    suffix = dst_path.suffix
    parent = dst_path.parent
    counter = 1
    while True:
        candidate = parent / f"{stem} (copy {counter}){suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def send_telegram_notification(text: str, reply_markup: dict | None = None) -> None:
    """Send a message directly to the owner's Telegram chat using config.json."""
    try:
        if not CONFIG_PATH.exists():
            return
        cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        token = cfg.get("bot_token")
        chat_id = cfg.get("chat_id")
        if not token or not chat_id:
            return
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {"chat_id": chat_id, "text": text[:4000]}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        with _urlopen_robust(req, timeout=15):
            pass
    except Exception:
        pass


# ---------- Zalo: trạng thái chờ xác nhận (lưu file để không mất khi bot nạp lại code) ----------
ZALO_PENDING_PATH = BASE_DIR / "zalo_pending.json"              # tin nhắn đã soạn, chờ bấm "Gửi"
ZALO_AFTER_UPLOAD_PATH = BASE_DIR / "zalo_after_upload.json"    # "up xong thì gửi link cho ai"
DEFAULT_ZALO_TEMPLATE = "{name}\n{url}"




def build_zalo_text(name: str, url: str) -> str:
    cfg = _read_json(CONFIG_PATH)
    tpl = cfg.get("zalo_message_template") or DEFAULT_ZALO_TEMPLATE
    try:
        return tpl.format(name=name, url=url)
    except Exception:
        return f"{name}\n{url}"


def set_zalo_pending(to: str, text: str) -> None:
    _write_json(ZALO_PENDING_PATH, {"to": to, "text": text, "ts": time.time()})


def pop_zalo_pending() -> dict | None:
    data = _read_json(ZALO_PENDING_PATH)
    try:
        ZALO_PENDING_PATH.unlink()
    except OSError:
        pass
    if not data or time.time() - data.get("ts", 0) > 3600:
        return None
    return data


def zalo_confirm_markup(to: str) -> dict:
    return {"inline_keyboard": [
        [{"text": f"✅ Gửi Zalo cho {to}"[:60], "callback_data": "zalo_send"}],
        [{"text": "❌ Huỷ", "callback_data": "cancel_nl"}],
    ]}


def get_drivefs_db_paths() -> list[Path]:
    """Locate Google DriveFS SQLite metadata databases on macOS."""
    drivefs_root = Path.home() / "Library" / "Application Support" / "Google" / "DriveFS"
    dbs = []
    if not drivefs_root.exists():
        return dbs
    try:
        for entry in sorted(drivefs_root.iterdir()):
            if entry.is_dir() and entry.name.isdigit():
                for db_name in ("mirror_metadata_sqlite.db", "metadata_sqlite_db"):
                    candidate = entry / db_name
                    if candidate.exists():
                        dbs.append(candidate)
    except OSError:
        pass
    return dbs


def format_gdrive_url(cloud_id: str, is_folder: bool) -> str:
    if is_folder:
        return f"https://drive.google.com/drive/folders/{cloud_id}?usp=sharing"
    return f"https://drive.google.com/file/d/{cloud_id}/view?usp=sharing"


_LIBC = None


def get_gdrive_cloud_id_from_xattr(path: Path) -> str | None:
    """
    Read Google Drive Cloud ID directly from macOS FileProvider extended attributes
    (com.google.drivefs.item-id#S). Works without Full Disk Access!
    """
    global _LIBC
    try:
        if _LIBC is None:
            import ctypes
            _LIBC = ctypes.CDLL("/usr/lib/libSystem.B.dylib")
        import ctypes
        buf = ctypes.create_string_buffer(256)
        b_path = os.fsencode(str(path))
        for attr in (b"com.google.drivefs.item-id#S", b"com.google.drivefs.item-id"):
            n = _LIBC.getxattr(b_path, attr, buf, 256, 0, 0)
            if n > 0:
                cid = buf.raw[:n].decode("utf-8", "replace").strip()
                if cid:
                    return cid
    except Exception:
        pass
    try:
        res = subprocess.run(
            ["xattr", "-p", "com.google.drivefs.item-id#S", str(path)],
            capture_output=True,
            text=True,
            timeout=2,
        )
        if res.returncode == 0 and res.stdout.strip():
            return res.stdout.strip()
    except Exception:
        pass
    return None


def _query_gdrive_from_filesystem(
    item_query: str, parent_hint: str | None = None, prefer_shared: bool = False
) -> list[dict]:
    """
    Fast filesystem scanner for Google Drive (~/Library/CloudStorage/GoogleDrive-*)
    that extracts cloud_id via xattr when DriveFS SQLite DB is blocked by macOS TCC.
    """
    gd_root = find_google_drive_root(auto_launch=False)
    roots: list[Path] = []
    seen_roots: set[str] = set()
    if gd_root and gd_root.exists():
        norm_r = unicodedata.normalize("NFC", str(gd_root))
        seen_roots.add(norm_r)
        roots.append(gd_root)
    cs_dir = Path.home() / "Library" / "CloudStorage"
    if cs_dir.exists():
        try:
            for entry in sorted(cs_dir.iterdir()):
                if entry.name.startswith("GoogleDrive") and entry.is_dir():
                    for sub in sorted(entry.iterdir()):
                        if sub.is_dir() and not sub.name.startswith("."):
                            norm_sub = unicodedata.normalize("NFC", str(sub))
                            if norm_sub not in seen_roots:
                                seen_roots.add(norm_sub)
                                roots.append(sub)
        except OSError:
            pass
    if not roots:
        return []

    q_norm = strip_accents(item_query.strip())
    q_stem_norm = strip_accents(Path(item_query.strip()).stem)
    q_tokens = [w for w in re.split(r"[^a-z0-9]+", q_norm) if w]
    q_compact = "".join(re.findall(r"[a-z0-9]+", q_norm))
    p_norm = strip_accents(parent_hint.strip()) if parent_hint else None
    def_sub_norm = strip_accents(DEFAULT_GDRIVE_SUBFOLDER)

    tier1_exact_in_parent = []
    tier2_exact_any = []
    tier3_partial_in_parent = []
    tier4_partial_any = []
    seen_paths = set()

    def check_entry(entry_path: Path, is_folder: bool, parent_name: str, parent_path: Path) -> None:
        s_path = unicodedata.normalize("NFC", str(entry_path))
        if s_path in seen_paths:
            return
        title = entry_path.name
        if title.startswith("."):
            return
        title_norm = strip_accents(title)
        stem_norm = strip_accents(Path(title).stem)
        title_compact = "".join(re.findall(r"[a-z0-9]+", title_norm))
        title_tokens = [w for w in re.split(r"[^a-z0-9]+", title_norm) if w]
        parent_title_norm = strip_accents(parent_name or "")

        is_exact = (
            (title_norm == q_norm)
            or (not is_folder and stem_norm == q_norm)
            or (not is_folder and stem_norm == q_stem_norm)
            or (bool(q_compact) and q_compact == title_compact)
        )
        is_partial = False
        if not is_exact:
            if (q_norm in title_norm) or (bool(q_compact) and q_compact in title_compact):
                is_partial = True
            elif bool(q_tokens) and all(
                (any(qt in tt for tt in title_tokens) or (qt in title_compact)) for qt in q_tokens
            ):
                is_partial = True

        if not (is_exact or is_partial):
            return

        in_target_parent = False
        if p_norm:
            in_target_parent = (p_norm == parent_title_norm) or (p_norm in parent_title_norm)
        else:
            in_target_parent = (def_sub_norm in parent_title_norm)

        if p_norm and not in_target_parent and not is_exact:
            return

        cid = get_gdrive_cloud_id_from_xattr(entry_path)
        dedup_key = cid or s_path
        if dedup_key in seen_paths:
            return
        seen_paths.add(s_path)
        seen_paths.add(dedup_key)
        pid = get_gdrive_cloud_id_from_xattr(parent_path)
        is_synced = bool(cid and not str(cid).startswith("local_"))
        file_size = None
        if not is_folder:
            try:
                file_size = entry_path.stat().st_size
            except OSError:
                pass

        item_info = {
            "stable_id": None,
            "cloud_id": cid or s_path,
            "name": title,
            "path": str(entry_path),
            "is_dir": bool(is_folder),
            "size": "-" if is_folder or file_size is None else format_size(int(file_size)),
            "bytes": int(file_size) if (not is_folder and file_size is not None) else 0,
            "file_count": 0 if is_folder else 1,
            "dir_count": 0,
            "parent_name": parent_name or "Drive của tôi",
            "parent_id": pid,
            "url": format_gdrive_url(cid, bool(is_folder)) if is_synced else None,
            "parent_url": format_gdrive_url(pid, True) if (pid and not str(pid).startswith("local_")) else None,
            "is_synced": is_synced,
            "is_shared": False,
        }

        if is_exact and in_target_parent:
            tier1_exact_in_parent.append(item_info)
        elif is_exact:
            tier2_exact_any.append(item_info)
        elif in_target_parent:
            tier3_partial_in_parent.append(item_info)
        else:
            tier4_partial_any.append(item_info)

    t0 = time.time()
    for r in roots:
        l1_dirs: list[Path] = []
        try:
            with os.scandir(r) as it1:
                for e1 in it1:
                    if e1.name.startswith("."):
                        continue
                    is_d = e1.is_dir(follow_symlinks=False)
                    p1 = Path(e1.path)
                    check_entry(p1, is_d, r.name, r)
                    if is_d:
                        l1_dirs.append(p1)
        except OSError:
            continue

        # Prioritize DEFAULT_GDRIVE_SUBFOLDER and parent_hint first
        def _dir_priority(d_path: Path) -> int:
            dn = strip_accents(d_path.name)
            if p_norm and (p_norm == dn or p_norm in dn):
                return 0
            if def_sub_norm and (def_sub_norm == dn or def_sub_norm in dn):
                return 1
            return 2

        l1_dirs.sort(key=_dir_priority)

        for d1 in l1_dirs:
            prio = _dir_priority(d1)
            if prio == 2 and (time.time() - t0 > 1.5 or (tier1_exact_in_parent or tier2_exact_any or tier3_partial_in_parent)):
                continue
            l2_dirs: list[Path] = []
            try:
                with os.scandir(d1) as it2:
                    for e2 in it2:
                        if e2.name.startswith("."):
                            continue
                        is_d2 = e2.is_dir(follow_symlinks=False)
                        p2 = Path(e2.path)
                        check_entry(p2, is_d2, d1.name, d1)
                        if is_d2 and prio < 2:
                            l2_dirs.append(p2)
            except OSError:
                continue

            if tier1_exact_in_parent or tier2_exact_any or tier3_partial_in_parent:
                continue

            for d2 in l2_dirs:
                if time.time() - t0 > 1.5:
                    break
                try:
                    with os.scandir(d2) as it3:
                        for e3 in it3:
                            if e3.name.startswith("."):
                                continue
                            is_d3 = e3.is_dir(follow_symlinks=False)
                            check_entry(Path(e3.path), is_d3, d2.name, d2)
                except OSError:
                    continue

    combined = tier1_exact_in_parent + tier2_exact_any + tier3_partial_in_parent + tier4_partial_any
    for item in combined[:5]:
        if item.get("is_dir") and item.get("path"):
            sz_info = get_folder_size(item["path"])
            if sz_info.get("ok"):
                item["size"] = sz_info["size_human"]
                item["bytes"] = sz_info["bytes"]
                item["file_count"] = sz_info["file_count"]
                item["dir_count"] = sz_info["dir_count"]
    return combined


def get_gdrive_item_size_from_db(stable_id: int) -> dict:
    """Calculate total size, file count, and subfolder count of a Google Drive folder/file from DriveFS SQLite DB."""
    dbs = get_drivefs_db_paths()
    for db_path in dbs:
        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)
            rows = conn.execute(
                """
                WITH RECURSIVE descendants(stable_id) AS (
                    SELECT ?
                    UNION ALL
                    SELECT sp.item_stable_id
                    FROM stable_parents sp
                    JOIN descendants d ON sp.parent_stable_id = d.stable_id
                )
                SELECT i.stable_id, i.is_folder, COALESCE(i.file_size, 0)
                FROM descendants d
                JOIN items i ON i.stable_id = d.stable_id
                WHERE i.trashed = 0 AND i.is_tombstone = 0
                """,
                (stable_id,),
            ).fetchall()
            conn.close()
            if rows:
                total_bytes = sum(int(r[2] or 0) for r in rows if not r[1])
                file_count = sum(1 for r in rows if not r[1])
                dir_count = max(0, sum(1 for r in rows if r[1]) - 1)
                return {
                    "ok": True,
                    "bytes": total_bytes,
                    "size_human": format_size(total_bytes),
                    "file_count": file_count,
                    "dir_count": dir_count,
                }
        except Exception:
            continue
    return {"ok": False, "bytes": 0, "size_human": "0 B", "file_count": 0, "dir_count": 0}


def query_gdrive_items(item_query: str, parent_hint: str | None = None, prefer_shared: bool = False) -> list[dict]:
    """
    Search Google DriveFS local metadata DB for files/folders matching item_query.
    Supports both user's own Drive and 'Shared with me' ('Được chia sẻ với tôi') items.
    Returns list of dicts with cloud_id, title, is_folder, parent_title, parent_id, url, parent_url, is_synced, is_shared.
    """
    dbs = get_drivefs_db_paths()
    if not dbs:
        return _query_gdrive_from_filesystem(item_query, parent_hint=parent_hint, prefer_shared=prefer_shared)

    q_norm = strip_accents(item_query.strip())
    q_stem_norm = strip_accents(Path(item_query.strip()).stem)
    q_tokens = [w for w in re.split(r"[^a-z0-9]+", q_norm) if w]
    q_compact = "".join(re.findall(r"[a-z0-9]+", q_norm))
    p_norm = strip_accents(parent_hint.strip()) if parent_hint else None

    is_shared_parent_hint = bool(
        p_norm and any(kw in p_norm for kw in ("duoc chia se", "chia se", "shared", "tho gui", "khach gui"))
    )

    sql = """
    SELECT i.stable_id, i.id, s.cloud_id, i.local_title, i.is_folder, i.file_size,
           p.local_title AS parent_title, p.id AS parent_id,
           EXISTS(SELECT 1 FROM local_stable_ids l WHERE l.stable_id = i.stable_id) AS is_local_only,
           i.is_owner, i.shared_with_me_date
    FROM items i
    LEFT JOIN stable_ids s ON i.stable_id = s.stable_id
    LEFT JOIN stable_parents sp ON i.stable_id = sp.item_stable_id
    LEFT JOIN items p ON sp.parent_stable_id = p.stable_id
    WHERE i.trashed = 0 AND i.is_tombstone = 0 AND i.local_title IS NOT NULL
    """

    seen_ids = set()
    tier1_exact_in_parent = []
    tier2_exact_any = []
    tier3_partial_in_parent = []
    tier4_partial_any = []

    for db_path in dbs:
        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)
            rows = conn.execute(sql).fetchall()
            conn.close()
        except Exception:
            continue

        for row in rows:
            stable_id, item_id, cloud_id, title, is_folder, file_size, parent_title, parent_id, is_local_only, is_owner, shared_date = row
            effective_id = cloud_id or item_id
            if not effective_id or effective_id in seen_ids:
                continue

            title_norm = strip_accents(title)
            stem_norm = strip_accents(Path(title).stem)
            title_compact = "".join(re.findall(r"[a-z0-9]+", title_norm))
            title_tokens = [w for w in re.split(r"[^a-z0-9]+", title_norm) if w]
            parent_title_norm = strip_accents(parent_title or "")

            is_shared = (is_owner == 0) or (shared_date is not None and int(shared_date or 0) > 0)
            if is_shared and (not parent_title or parent_title_norm in ("root", "drive cua toi", "my drive", "none", "")):
                display_parent = "Được chia sẻ với tôi"
            else:
                display_parent = parent_title or ("Được chia sẻ với tôi" if is_shared else "Drive của tôi")

            # Check if title matches query
            is_exact = (
                (title_norm == q_norm)
                or (not is_folder and stem_norm == q_norm)
                or (not is_folder and stem_norm == q_stem_norm)
                or (bool(q_compact) and q_compact == title_compact)
            )

            is_partial = False
            if not is_exact:
                if (q_norm in title_norm) or (bool(q_compact) and q_compact in title_compact):
                    is_partial = True
                elif bool(q_tokens) and all(
                    (any(qt in tt for tt in title_tokens) or (qt in title_compact)) for qt in q_tokens
                ):
                    is_partial = True

            if not (is_exact or is_partial):
                continue

            # Check parent hint if provided
            in_target_parent = False
            if is_shared_parent_hint:
                in_target_parent = is_shared
            elif p_norm:
                in_target_parent = (p_norm == parent_title_norm) or (p_norm in parent_title_norm)
            else:
                if prefer_shared:
                    in_target_parent = is_shared
                else:
                    in_target_parent = (strip_accents(DEFAULT_GDRIVE_SUBFOLDER) in parent_title_norm)

            is_synced = (not is_local_only) and (not str(effective_id).startswith("local_"))
            item_info = {
                "stable_id": stable_id,
                "cloud_id": effective_id,
                "name": title,
                "is_dir": bool(is_folder),
                "size": "-" if is_folder or file_size is None else format_size(int(file_size)),
                "parent_name": display_parent,
                "parent_id": parent_id,
                "url": format_gdrive_url(effective_id, bool(is_folder)) if is_synced else None,
                "parent_url": (
                    "https://drive.google.com/drive/shared-with-me"
                    if display_parent == "Được chia sẻ với tôi"
                    else (format_gdrive_url(parent_id, True) if parent_id and not str(parent_id).startswith("local_") else None)
                ),
                "is_synced": is_synced,
                "is_shared": is_shared,
            }

            if p_norm and not in_target_parent:
                # Still keep in fallback tiers in case user misremembered folder
                if is_exact:
                    seen_ids.add(effective_id)
                    tier2_exact_any.append(item_info)
                continue

            seen_ids.add(effective_id)
            if is_exact and in_target_parent:
                tier1_exact_in_parent.append(item_info)
            elif is_exact:
                tier2_exact_any.append(item_info)
            elif in_target_parent:
                tier3_partial_in_parent.append(item_info)
            else:
                tier4_partial_any.append(item_info)

    combined = tier1_exact_in_parent + tier2_exact_any + tier3_partial_in_parent + tier4_partial_any
    if not combined:
        return _query_gdrive_from_filesystem(item_query, parent_hint=parent_hint, prefer_shared=prefer_shared)
    for item in combined[:10]:
        if item.get("is_dir") and item.get("stable_id") is not None:
            sz_db = get_gdrive_item_size_from_db(item["stable_id"])
            if sz_db.get("ok"):
                item["size"] = sz_db["size_human"]
                item["bytes"] = sz_db["bytes"]
                item["file_count"] = sz_db["file_count"]
                item["dir_count"] = sz_db["dir_count"]
        elif not item.get("is_dir"):
            item["file_count"] = 1
            item["dir_count"] = 0
    return combined


def _wait_and_notify_gdrive_link(dst_path: Path) -> None:
    """
    Background worker that waits for Google Drive for Desktop to finish syncing dst_path
    and automatically sends the shareable Google Drive link to Telegram.
    """
    item_name = dst_path.name
    parent_name = dst_path.parent.name
    # Poll for up to 30 minutes (for large video files)
    start_time = time.time()
    notified_uploading = False

    while time.time() - start_time < 1800:
        time.sleep(2.5)
        matches = query_gdrive_items(item_name, parent_hint=parent_name)
        exact = [m for m in matches if m["name"].lower() == item_name.lower()]
        target = exact[0] if exact else (matches[0] if matches else None)

        if target and target.get("is_synced") and target.get("url"):
            lines = [
                f"🔗 LINK GOOGLE DRIVE ĐỂ GỬI KHÁCH:",
                f"• {'📁 Thư mục' if target['is_dir'] else '📄 File'}: {target['name']} ({target['size']})",
                f"• Nằm trong: {target['parent_name']}",
                f"\n👉 Link trực tiếp ({target['name']}):",
                f"{target['url']}",
            ]
            if target.get("parent_url"):
                lines.append(f"\n📂 Link cả thư mục {target['parent_name']}:\n{target['parent_url']}")
            send_telegram_notification("\n".join(lines))

            # Nếu lệnh là "up xong gửi link cho ai đó qua Zalo": soạn sẵn tin và chờ bạn bấm xác nhận
            after = _read_json(ZALO_AFTER_UPLOAD_PATH)
            if after and time.time() - after.get("ts", 0) < 3600:
                try:
                    ZALO_AFTER_UPLOAD_PATH.unlink()
                except OSError:
                    pass
                zalo_text = build_zalo_text(target["name"], target["url"])
                set_zalo_pending(after["to"], zalo_text)
                send_telegram_notification(
                    f"📨 SẴN SÀNG GỬI ZALO cho: {after['to']}\n\n{zalo_text}\n\n👉 Bấm nút bên dưới để gửi:",
                    reply_markup=zalo_confirm_markup(after["to"]),
                )
            return

        if not notified_uploading and (time.time() - start_time > 8.0):
            notified_uploading = True
            send_telegram_notification(
                f"⏳ Google Drive đang tải '{item_name}' lên đám mây. "
                f"Ngay khi đồng bộ xong 100%, tôi sẽ tự động gửi Link Google Drive vào đây cho bạn!"
            )


def list_drives() -> list[dict]:
    """List mounted drives/volumes in /Volumes and home directory status."""
    volumes_dir = Path("/Volumes")
    drives = []
    if volumes_dir.exists():
        for item in sorted(volumes_dir.iterdir()):
            try:
                usage = shutil.disk_usage(item)
                drives.append({
                    "name": item.name,
                    "path": str(item.resolve() if item.is_symlink() else item),
                    "mount": str(item),
                    "total": format_size(usage.total),
                    "used": format_size(usage.used),
                    "free": format_size(usage.free),
                })
            except PermissionError:
                drives.append({
                    "name": item.name,
                    "path": str(item),
                    "mount": str(item),
                    "total": "N/A",
                    "used": "N/A",
                    "free": "Không có quyền đọc",
                })
            except OSError:
                continue

    gdrive_root = find_google_drive_root(auto_launch=False)
    if gdrive_root and gdrive_root.exists():
        already = any(str(gdrive_root) == d.get("path") or "googledrive" in d.get("name", "").lower() for d in drives)
        if not already:
            try:
                usage = shutil.disk_usage(gdrive_root)
                drives.append({
                    "name": f"☁️ Google Drive ({gdrive_root.name})",
                    "path": str(gdrive_root),
                    "mount": str(gdrive_root),
                    "total": format_size(usage.total),
                    "used": format_size(usage.used),
                    "free": format_size(usage.free),
                })
            except Exception:
                drives.append({
                    "name": f"☁️ Google Drive ({gdrive_root.name})",
                    "path": str(gdrive_root),
                    "mount": str(gdrive_root),
                    "total": "Cloud",
                    "used": "Cloud",
                    "free": "Đang kết nối",
                })
    return drives


def list_directory(path_str: str, limit: int = 50) -> dict:
    """List folders and files inside a directory."""
    target = Path(path_str).expanduser().resolve()
    if not target.exists():
        return {"ok": False, "error": f"Đường dẫn không tồn tại: {target}"}
    if not target.is_dir():
        stat = target.stat()
        return {
            "ok": True,
            "is_file": True,
            "path": str(target),
            "size": format_size(stat.st_size),
            "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
        }

    items = []
    try:
        entries = sorted(
            target.iterdir(),
            key=lambda p: (not p.is_dir(), p.name.lower())
        )
        total_count = len(entries)
        for entry in entries[:limit]:
            if entry.name.startswith("."):
                continue
            try:
                st = entry.stat()
                items.append({
                    "name": entry.name,
                    "path": str(entry),
                    "is_dir": entry.is_dir(),
                    "size": "-" if entry.is_dir() else format_size(st.st_size),
                    "modified": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M"),
                })
            except OSError:
                items.append({
                    "name": entry.name,
                    "path": str(entry),
                    "is_dir": entry.is_dir(),
                    "size": "?",
                    "modified": "?",
                })
        return {
            "ok": True,
            "is_file": False,
            "path": str(target),
            "parent": str(target.parent) if target.parent != target else None,
            "total_count": total_count,
            "items": items,
        }
    except PermissionError:
        return {"ok": False, "error": f"Không có quyền truy cập thư mục: {target}"}


def search_files(keyword: str, root_str: str = "~", max_results: int = 30) -> dict:
    """Search for files/folders matching keyword under root_str."""
    root = Path(root_str).expanduser().resolve()
    if not root.exists():
        return {"ok": False, "error": f"Thư mục tìm kiếm không tồn tại: {root}"}

    kw_lower = keyword.lower()
    matches = []
    for dirpath, dirnames, filenames in os.walk(root, topdown=True):
        dirnames[:] = [
            d for d in dirnames
            if not d.startswith(".")
            and d not in ("Library", "node_modules", ".Trash", "Macintosh HD", "Recovery", "Antigravity")
        ]
        for d in dirnames:
            if kw_lower in d.lower():
                full = Path(dirpath) / d
                matches.append({"path": str(full), "is_dir": True, "size": "Thư mục"})
                if len(matches) >= max_results:
                    return {"ok": True, "root": str(root), "matches": matches}
        for f in filenames:
            if f.startswith("."):
                continue
            if kw_lower in f.lower():
                full = Path(dirpath) / f
                try:
                    sz = format_size(full.stat().st_size)
                except OSError:
                    sz = "?"
                matches.append({"path": str(full), "is_dir": False, "size": sz})
                if len(matches) >= max_results:
                    return {"ok": True, "root": str(root), "matches": matches}

    return {"ok": True, "root": str(root), "matches": matches}


def safe_copy(src_str: str, dst_str: str) -> dict:
    """
    Copy a file or directory to dst_str.
    Never overwrites existing files.
    If copying into Google Drive:
      - If an identical file (same name & size) already exists at destination, reuses it
        instead of creating '(copy 1)' and immediately sends the Google Drive share link!
      - Otherwise copies the file and starts a background thread to send the Google Drive
        share link as soon as Google Drive finishes syncing!
    """
    src = Path(src_str).expanduser().resolve()
    dst = Path(dst_str).expanduser().resolve()

    if not src.exists():
        return {"ok": False, "error": f"File/thư mục nguồn không tồn tại: {src}"}

    is_gdrive_dst = "googledrive" in str(dst).lower().replace(" ", "").replace("_", "").replace("-", "")

    if dst.exists() and dst.is_dir():
        candidate_dst = dst / src.name
        # If uploading to Google Drive and exact same file already exists, reuse it to get its link directly!
        if (
            is_gdrive_dst
            and candidate_dst.exists()
            and src.is_file()
            and candidate_dst.is_file()
            and src.stat().st_size == candidate_dst.stat().st_size
        ):
            threading.Thread(target=_wait_and_notify_gdrive_link, args=(candidate_dst,), daemon=True).start()
            return {
                "ok": True,
                "action": "copy",
                "src": str(src),
                "dst": str(candidate_dst),
                "reused_existing": True,
            }
        final_dst = get_unique_destination(candidate_dst)
    else:
        final_dst = get_unique_destination(dst)

    final_dst.parent.mkdir(parents=True, exist_ok=True)

    try:
        if src.is_dir():
            shutil.copytree(src, final_dst, dirs_exist_ok=False)
        else:
            shutil.copy2(src, final_dst)

        if is_gdrive_dst:
            threading.Thread(target=_wait_and_notify_gdrive_link, args=(final_dst,), daemon=True).start()

        return {
            "ok": True,
            "action": "copy",
            "src": str(src),
            "dst": str(final_dst),
        }
    except Exception as e:
        return {"ok": False, "error": f"Lỗi khi sao chép: {e}"}


def safe_move(src_str: str, dst_str: str) -> dict:
    """
    Move a file or directory to dst_str (including across external drives).
    Never overwrites existing files at destination.
    """
    src = Path(src_str).expanduser().resolve()
    dst = Path(dst_str).expanduser().resolve()

    if not src.exists():
        return {"ok": False, "error": f"File/thư mục nguồn không tồn tại: {src}"}

    protected = {Path("/"), Path("/Volumes"), Path("/Users"), Path.home()}
    if src in protected:
        return {"ok": False, "error": f"Từ chối dời thư mục gốc hệ thống: {src}"}

    if dst.exists() and dst.is_dir():
        final_dst = get_unique_destination(dst / src.name)
    else:
        final_dst = get_unique_destination(dst)

    final_dst.parent.mkdir(parents=True, exist_ok=True)

    try:
        shutil.move(str(src), str(final_dst))
        return {
            "ok": True,
            "action": "move",
            "src": str(src),
            "dst": str(final_dst),
        }
    except Exception as e:
        return {"ok": False, "error": f"Lỗi khi dời file: {e}"}


def get_folder_size(path_str: str) -> dict:
    """Calculate total size, file count, and folder count of a file or directory."""
    target = Path(path_str).expanduser().resolve()
    if not target.exists():
        return {"ok": False, "error": f"Đường dẫn không tồn tại: {target}"}

    if target.is_file():
        sz = target.stat().st_size
        return {
            "ok": True,
            "path": str(target),
            "is_dir": False,
            "bytes": sz,
            "size_human": format_size(sz),
            "file_count": 1,
            "dir_count": 0,
        }

    total_bytes = 0
    file_count = 0
    dir_count = 0
    for dirpath, dirnames, filenames in os.walk(target):
        dir_count += len(dirnames)
        for f in filenames:
            if f == ".DS_Store":
                continue
            fp = Path(dirpath) / f
            try:
                if not fp.is_symlink():
                    total_bytes += fp.stat().st_size
                    file_count += 1
            except OSError:
                continue

    return {
        "ok": True,
        "path": str(target),
        "is_dir": True,
        "bytes": total_bytes,
        "size_human": format_size(total_bytes),
        "file_count": file_count,
        "dir_count": dir_count,
    }


def find_google_drive_root(auto_launch: bool = True) -> Path | None:
    """
    Locate mounted Google Drive folder on macOS (Google Drive for Desktop).
    Checks ~/Library/CloudStorage/GoogleDrive-*, ~/Google Drive, and /Volumes/GoogleDrive*.
    """
    for attempt in range(2):
        cloud_storage = Path.home() / "Library" / "CloudStorage"
        try:
            if cloud_storage.exists():
                for entry in sorted(cloud_storage.iterdir()):
                    if entry.name.startswith("GoogleDrive"):
                        for sub in ("My Drive", "Bộ nhớ của tôi", "Drive của tôi", "Drive của tôi"):
                            candidate = entry / sub
                            if candidate.exists():
                                return candidate
                        try:
                            for child in sorted(entry.iterdir()):
                                if child.is_dir() and not child.name.startswith("."):
                                    return child
                        except OSError:
                            pass
                        return entry
        except OSError:
            pass

        for direct_name in ("Google Drive", "My Drive", "Bộ nhớ của tôi", "Drive của tôi"):
            try:
                candidate = Path.home() / direct_name
                if candidate.exists() and candidate.is_dir():
                    for sub in ("My Drive", "Bộ nhớ của tôi", "Drive của tôi", "Drive của tôi"):
                        sub_candidate = candidate / sub
                        if sub_candidate.exists():
                            return sub_candidate
                    return candidate
            except OSError:
                pass

        volumes = Path("/Volumes")
        try:
            if volumes.exists():
                for entry in sorted(volumes.iterdir()):
                    if "googledrive" in entry.name.lower() or "google drive" in entry.name.lower():
                        for sub in ("My Drive", "Bộ nhớ của tôi", "Drive của tôi", "Drive của tôi"):
                            candidate = entry / sub
                            if candidate.exists():
                                return candidate
                        return entry
        except OSError:
            pass

        if attempt == 0 and auto_launch and Path("/Applications/Google Drive.app").exists():
            try:
                subprocess.run(["open", "-g", "-a", "Google Drive"], timeout=5)
                time.sleep(2)
            except Exception:
                break

    return None


def resolve_subfolder_fuzzy(root_dir: Path, subfolder: str) -> Path:
    """
    Find an existing subfolder inside root_dir matching `subfolder` (case/accent-insensitive),
    or return root_dir / subfolder if not found.
    """
    if not subfolder:
        return root_dir
    target_norm = strip_accents(subfolder.strip())
    try:
        for entry in root_dir.iterdir():
            if entry.is_dir() and not entry.name.startswith("."):
                if strip_accents(entry.name) == target_norm or target_norm in strip_accents(entry.name):
                    return entry
    except OSError:
        pass
    return root_dir / subfolder.strip()


def upload_to_google_drive(src_str: str, subfolder: str = "") -> dict:
    """
    Copy a file or folder into Google Drive folder (defaults to THIEN UNG PRODUCTION)
    so Google Drive.app syncs it to the cloud and auto-sends the share link.
    """
    gdrive_root = find_google_drive_root(auto_launch=True)
    if not gdrive_root:
        return {
            "ok": False,
            "error": (
                "Chưa tìm thấy thư mục Google Drive được gắn trên máy Mac. "
                "Bạn hãy mở ứng dụng 'Google Drive.app' trên máy Mac trước nhé!"
            ),
        }

    effective_subfolder = subfolder.strip() if subfolder and subfolder.strip() else DEFAULT_GDRIVE_SUBFOLDER
    dst_dir = resolve_subfolder_fuzzy(gdrive_root, effective_subfolder)
    dst_dir.mkdir(parents=True, exist_ok=True)
    return safe_copy(src_str, str(dst_dir))
