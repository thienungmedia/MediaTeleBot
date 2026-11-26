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
- Upload to Google Drive (defaults to 'MacFileBot Uploads' folder) & auto-extract share links!

Strictly prohibited:
- Deleting any file or folder (rm, rmdir, unlink, trash)
- Overwriting any existing file at destination
"""

import errno
import json
import os
import re
import shutil
import sqlite3
import subprocess
import threading
import time
from itertools import count
import unicodedata
import urllib.request
from pathlib import Path

from runtime import open_https as _urlopen_robust
from datetime import datetime

from runtime import BASE_DIR, CONFIG_PATH, IS_MAC, IS_WINDOWS, edit_config, mounted_roots, write_private_json


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_json(path: Path, data: dict) -> None:
    write_private_json(path, data)


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
    return cfg.get("default_gdrive_folder") or "MacFileBot Uploads"


def get_default_gdrive_folder_info() -> dict:
    cfg = _read_json(CONFIG_PATH)
    folder_name = cfg.get("default_gdrive_folder") or "MacFileBot Uploads"
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

    if not folder_name.strip() or folder_name.strip() in (".", "..") or any(c in folder_name for c in "/\\"):
        return {"ok": False, "error": "Hãy dùng tên một thư mục hoặc URL Google Drive hợp lệ."}

    edit_config(lambda cfg: cfg.update(
        default_gdrive_folder=folder_name, default_gdrive_folder_id=cloud_id,
        default_gdrive_folder_url=folder_url, default_gdrive_is_shared=is_shared,
    ), CONFIG_PATH)

    gdrive_root = find_google_drive_root(auto_launch=True)
    local_path = None
    if gdrive_root and not cloud_id:
        candidate = (gdrive_root / folder_name).resolve()
        if candidate.is_relative_to(gdrive_root.resolve()):
            local_path = candidate

    return {
        "ok": True,
        "folder_name": folder_name,
        "cloud_id": cloud_id,
        "folder_url": folder_url,
        "is_shared": is_shared,
        "local_path": str(local_path) if local_path else None,
    }


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


def send_telegram_notification(text: str, reply_markup: dict | None = None, *, owner: int | None = None, expected_token: str | None = None) -> None:
    """Send a message directly to the owner's Telegram chat using config.json."""
    try:
        if not CONFIG_PATH.exists():
            return
        cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        token = cfg.get("bot_token")
        chat_id = cfg.get("owner_id")
        if not token or type(chat_id) is not int or chat_id <= 0:
            return
        if expected_token is not None and (expected_token != token or owner != chat_id):
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
    if not IS_MAC:
        return None
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
    def_sub_norm = strip_accents(get_default_gdrive_subfolder())

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
                    in_target_parent = (strip_accents(get_default_gdrive_subfolder()) in parent_title_norm)

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


def _wait_and_notify_gdrive_link(dst_path: Path, src_path: Path) -> None:
    """Get the exact cloud ID of this copy instead of searching by filename."""
    cfg = _read_json(CONFIG_PATH)
    owner = cfg.get("owner_id")
    token = cfg.get("bot_token")
    if not token or not owner:
        return
    source_id = get_gdrive_cloud_id_from_xattr(src_path)
    for _ in range(360):
        time.sleep(5)
        current = _read_json(CONFIG_PATH)
        if not dst_path.exists() or current.get("owner_id") != owner or current.get("bot_token") != token:
            return
        cloud_id = get_gdrive_cloud_id_from_xattr(dst_path)
        if not cloud_id or cloud_id == source_id or cloud_id.startswith("local_") or not re.fullmatch(r"[A-Za-z0-9_-]+", cloud_id):
            continue
        url = format_gdrive_url(cloud_id, dst_path.is_dir())
        send_telegram_notification(f"Link Google Drive của {dst_path.name}:\n{url}\nKiểm tra đồng bộ và quyền chia sẻ trên Drive trước khi gửi khách.", owner=owner, expected_token=token)
        return
    send_telegram_notification(f"Chưa lấy được link chính xác cho {dst_path.name}. Hãy dùng menu Google Drive trong Finder để lấy link.", owner=owner, expected_token=token)


def list_drives() -> list[dict]:
    """List mounted drives/volumes in /Volumes and home directory status."""
    drives = []
    for item in mounted_roots():
        try:
            usage = shutil.disk_usage(item)
            drives.append({
                "name": item.name or item.drive,
                "path": str(item.resolve() if item.is_symlink() else item),
                "mount": str(item),
                "total": format_size(usage.total),
                "used": format_size(usage.used),
                "free": format_size(usage.free),
            })
        except PermissionError:
            drives.append({
                "name": item.name or item.drive,
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


def search_shared(keyword: str, raw_root: str, limit: int = 15) -> list[str]:
    """Return relative names from a locally approved directory, skipping links."""
    root = Path(raw_root).expanduser().resolve()
    query = strip_accents(keyword)
    if not query or not root.is_dir() or limit <= 0:
        return []
    found = []
    deadline = time.monotonic() + 2
    for folder, dirs, files in os.walk(root):
        if time.monotonic() >= deadline:
            break
        path = Path(folder)
        dirs[:] = [name for name in dirs if not name.startswith(".") and not _is_link(path / name)]
        for name in [*dirs, *files]:
            candidate = path / name
            if name.startswith(".") or _is_link(candidate) or query not in strip_accents(name):
                continue
            if candidate.resolve().is_relative_to(root):
                found.append(f"{root.name}/{candidate.relative_to(root).as_posix()}")
                if len(found) == limit:
                    return found
    return found


def _is_link(path: Path) -> bool:
    return path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction())


def _copy_contents(src: Path, dst: Path, drive_upload: bool) -> None:
    if src.is_dir():
        if drive_upload:
            for folder, dirs, files in os.walk(src):
                if any(_is_link(Path(folder) / name) for name in [*dirs, *files]):
                    raise ValueError("Tách liên kết tượng trưng ra khỏi thư mục trước khi upload.")
        dst.mkdir()
        try:
            shutil.copytree(src, dst, symlinks=True, dirs_exist_ok=True, copy_function=shutil.copyfile if drive_upload else shutil.copy2)
        except Exception:
            shutil.rmtree(dst)
            raise
    else:
        with dst.open("xb") as output:
            try:
                with src.open("rb") as input_file:
                    shutil.copyfileobj(input_file, output, length=1024 * 1024)
            except Exception:
                output.close()
                dst.unlink()
                raise
        if drive_upload:
            # Never copy FileProvider xattrs / cloud IDs from the source to a new item.
            shutil.copymode(src, dst)
        else:
            shutil.copystat(src, dst)


def _rename_no_replace(src: Path, dst: Path) -> None:
    if IS_WINDOWS:
        os.rename(src, dst)  # Windows fails if the destination already exists.
    elif IS_MAC:
        import ctypes
        libc = ctypes.CDLL(None, use_errno=True)
        rename_excl = libc.renamex_np
        rename_excl.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        rename_excl.restype = ctypes.c_int
        if rename_excl(os.fsencode(src), os.fsencode(dst), 0x00000004) != 0:
            err = ctypes.get_errno()
            raise OSError(err, os.strerror(err), str(src), str(dst))
    else:
        raise OSError(errno.EXDEV, "Portable copy and remove")


def _transfer(src_str: str, dst_str: str, move: bool, drive_upload: bool = False) -> dict:
    try:
        src = Path(src_str).expanduser().resolve(strict=True)
        dst = Path(dst_str).expanduser().resolve()
        if not (src.is_file() or src.is_dir()):
            raise ValueError("Nguồn phải là file hoặc thư mục thông thường.")
        if move and (src == Path.home() or src == BASE_DIR or src in BASE_DIR.parents or src.parent == src or src in {p.resolve() for p in mounted_roots()}):
            raise ValueError("Không thể dời thư mục gốc, ổ đĩa hoặc thư mục hoạt động của bot.")
        requested = dst / src.name if dst.is_dir() else dst
        if requested == src or (src.is_dir() and requested.is_relative_to(src)):
            raise ValueError("Đích phải nằm ngoài thư mục hoặc file nguồn.")
        requested.parent.mkdir(parents=True, exist_ok=True)
        for index in count():
            suffix = requested.suffix if src.is_file() else ""
            stem = requested.name[:-len(suffix)] if suffix else requested.name
            final = requested if index == 0 else requested.with_name(f"{stem} (copy {index}){suffix}")
            try:
                if move:
                    try:
                        _rename_no_replace(src, final)
                    except OSError as exc:
                        if exc.errno != errno.EXDEV and getattr(exc, "winerror", None) != 17:
                            raise
                        _copy_contents(src, final, drive_upload=False)
                        try:
                            shutil.rmtree(src) if src.is_dir() else src.unlink()
                        except OSError:
                            return {"ok": False, "error": f"Đã tạo bản sao ở {final}, nhưng chưa thể dọn hết dữ liệu nguồn."}
                else:
                    _copy_contents(src, final, drive_upload)
                break
            except FileExistsError:
                continue
        return {"ok": True, "action": "move" if move else "copy", "src": str(src), "dst": str(final)}
    except (ValueError, OSError) as exc:
        return {"ok": False, "error": str(exc)}


def safe_copy(src_str: str, dst_str: str, *, drive_upload: bool = False) -> dict:
    if not drive_upload:
        root = find_google_drive_root(auto_launch=False)
        drive_upload = bool(root and Path(dst_str).expanduser().resolve().is_relative_to(root.resolve()))
    res = _transfer(src_str, dst_str, move=False, drive_upload=drive_upload)
    if res.get("ok") and drive_upload and IS_MAC:
        src, dst = (Path(res[key]) for key in ("src", "dst"))
        threading.Thread(target=_wait_and_notify_gdrive_link, args=(dst, src), daemon=True).start()
        import gdrive_offload
        if gdrive_offload.is_auto_offload_enabled():
            gdrive_offload.schedule_offload_when_synced(dst, src)
    return res


def safe_move(src_str: str, dst_str: str) -> dict:
    return _transfer(src_str, dst_str, move=True)


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
    selected = _read_json(CONFIG_PATH).get("google_drive_root")
    if selected:
        root = Path(selected).expanduser()
        return root if root.is_dir() else None

    names = ("My Drive", "Bộ nhớ của tôi", "Drive của tôi")
    candidates = set()
    cloud = Path.home() / "Library" / "CloudStorage"
    locations = []
    if IS_MAC:
        if cloud.is_dir():
            locations.extend(folder for folder in cloud.glob("GoogleDrive*") if folder.is_dir())
        locations.extend(folder for folder in mounted_roots() if "googledrive" in strip_accents(folder.name).replace(" ", ""))
    elif IS_WINDOWS:
        locations.extend(root for root in mounted_roots() if any((root / name).is_dir() for name in names))

    for loc in locations:
        child = next((loc / name for name in names if (loc / name).is_dir()), None)
        if child:
            candidates.add(child.resolve())
    direct = Path.home() / "Google Drive"
    if direct.is_dir():
        candidates.add(next((direct / name for name in names if (direct / name).is_dir()), direct).resolve())
    if len(candidates) > 1:
        return None
    if candidates:
        return candidates.pop()
    if IS_MAC and auto_launch and Path("/Applications/Google Drive.app").exists():
        try:
            subprocess.run(["open", "-g", "-a", "Google Drive"], check=False, timeout=5)
        except (OSError, subprocess.SubprocessError):
            pass
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


def drive_upload_destination(subfolder: str = "") -> Path:
    root = find_google_drive_root()
    if not root:
        raise ValueError("Chưa chọn được Google Drive. Đăng nhập Drive cho máy tính và chọn đúng thư mục Drive trong MediaTeleBot.")
    info = get_default_gdrive_folder_info()
    folder_name = subfolder.strip() or info["folder_name"]
    if folder_name in (".", "..") or any(c in folder_name for c in "/\\"):
        raise ValueError("Tên thư mục Drive không hợp lệ.")
    if not subfolder and info.get("folder_id"):
        matches = [entry for entry in root.iterdir() if entry.is_dir() and get_gdrive_cloud_id_from_xattr(entry) == info["folder_id"]]
        if len(matches) != 1:
            raise ValueError("Chưa xác minh được thư mục Drive theo URL. Hãy đồng bộ thư mục này hoặc chọn thư mục đích từ máy chủ.")
        dest = matches[0].resolve()
    else:
        dest = (root / folder_name).resolve()
    if not dest.is_relative_to(root.resolve()):
        raise ValueError("Thư mục đích nằm ngoài Drive đã chọn.")
    return dest


def copy_to_drive_path(src_str: str, dst_str: str) -> dict:
    try:
        root = find_google_drive_root(auto_launch=False)
        dest = Path(dst_str).resolve()
        if not root or not dest.is_relative_to(root.resolve()):
            raise ValueError("Đích không còn nằm trong Google Drive đã chọn. Hãy chọn lại.")
        dest.mkdir(parents=True, exist_ok=True)
        return safe_copy(src_str, str(dest), drive_upload=True)
    except (ValueError, OSError) as exc:
        return {"ok": False, "error": str(exc)}


def upload_to_google_drive(src_str: str, subfolder: str = "") -> dict:
    try:
        return copy_to_drive_path(src_str, str(drive_upload_destination(subfolder)))
    except (ValueError, OSError) as exc:
        return {"ok": False, "error": str(exc)}


# ==============================================================================
# QUẢN LÝ ỨNG DỤNG (APPLICATIONS) & KIỂM TRA THÙNG RÁC (TRASH) TRÊN MACOS
# ==============================================================================

APP_DIRS = [
    "/Applications",
    "/System/Applications",
    "/System/Applications/Utilities",
    str(Path.home() / "Applications"),
]

RAW_APP_ALIASES = {
    "premiere": ["Adobe Premiere Pro", "Premiere"],
    "pr": ["Adobe Premiere Pro"],
    "photoshop": ["Adobe Photoshop", "Photoshop"],
    "pts": ["Adobe Photoshop"],
    "ps": ["Adobe Photoshop"],
    "after effects": ["Adobe After Effects", "After Effects"],
    "after effect": ["Adobe After Effects"],
    "ae": ["Adobe After Effects"],
    "audition": ["Adobe Audition"],
    "au": ["Adobe Audition"],
    "illustrator": ["Adobe Illustrator"],
    "ai": ["Adobe Illustrator"],
    "media encoder": ["Adobe Media Encoder"],
    "me": ["Adobe Media Encoder"],
    "lightroom": ["Adobe Lightroom", "Lightroom"],
    "lr": ["Adobe Lightroom"],
    "capcut": ["CapCut"],
    "davinci": ["DaVinci Resolve"],
    "davinci resolve": ["DaVinci Resolve"],
    "resolve": ["DaVinci Resolve"],
    "final cut": ["Final Cut Pro"],
    "final cut pro": ["Final Cut Pro"],
    "fcp": ["Final Cut Pro"],
    "fcpx": ["Final Cut Pro"],
    "capture one": ["Capture One"],
    "zalo": ["Zalo"],
    "telegram": ["Telegram"],
    "tele": ["Telegram"],
    "chrome": ["Google Chrome"],
    "google chrome": ["Google Chrome"],
    "coccoc": ["CocCoc", "Cốc Cốc"],
    "cốc cốc": ["CocCoc", "Cốc Cốc"],
    "brave": ["Brave Browser", "Brave"],
    "safari": ["Safari"],
    "finder": ["Finder"],
    "lịch": ["Calendar"],
    "calendar": ["Calendar"],
    "ghi chú": ["Notes"],
    "notes": ["Notes"],
    "nhắc nhở": ["Reminders"],
    "reminders": ["Reminders"],
    "tin nhắn": ["Messages"],
    "messages": ["Messages"],
    "mail": ["Mail"],
    "máy tính": ["Calculator"],
    "calculator": ["Calculator"],
    "drive": ["Google Drive"],
    "google drive": ["Google Drive"],
    "antigravity": ["Antigravity"],
    "chatgpt": ["ChatGPT"],
    "claude": ["Claude"],
    "rustdesk": ["RustDesk"],
    "rust desk": ["RustDesk"],
    "ultraviewer": ["UltraViewer"],
    "ultra viewer": ["UltraViewer"],
    "teamviewer": ["TeamViewer"],
    "team viewer": ["TeamViewer"],
    "anydesk": ["AnyDesk"],
    "any desk": ["AnyDesk"],
}

APP_ALIASES = {strip_accents(k).lower(): v for k, v in RAW_APP_ALIASES.items()}


def find_installed_apps() -> dict[str, str]:
    """Quét các thư mục ứng dụng chuẩn trên macOS để lấy danh sách App Name -> App Path."""
    apps = {}
    for d in APP_DIRS:
        p = Path(d)
        if not p.exists():
            continue
        try:
            for it in p.iterdir():
                if it.name.endswith(".app") and not it.name.startswith("."):
                    apps[it.name[:-4]] = str(it)
                elif it.is_dir() and not it.name.startswith("."):
                    try:
                        for sub in it.iterdir():
                            if sub.name.endswith(".app") and not sub.name.startswith("."):
                                apps[sub.name[:-4]] = str(sub)
                    except OSError:
                        pass
        except OSError:
            pass
    return apps


def match_app(query: str) -> tuple[str | None, str | None]:
    """Tìm ứng dụng phù hợp nhất trên macOS theo tên hoặc từ khoá viết tắt."""
    q_clean = query.strip()
    q_norm = strip_accents(q_clean).lower()

    # Xử lý phần đuôi mở rộng .app / .exe nếu người dùng gõ
    if q_norm.endswith(".app") or q_norm.endswith(".exe"):
        q_norm = re.sub(r"\.(?:app|exe)$", "", q_norm).strip()

    # Bỏ các tiền tố / hậu tố thông dụng
    for prefix in ("app ", "ung dung ", "phan mem ", "file ", "tep "):
        if q_norm.startswith(prefix):
            q_norm = q_norm[len(prefix):].strip()
    for suffix in (" app", " ung dung", " phan mem"):
        if q_norm.endswith(suffix):
            q_norm = q_norm[:-len(suffix)].strip()

    # Bỏ các cụm từ vị trí: "trong application", "tren mac", v.v.
    q_norm = re.sub(r"\s+(?:trong|tren|o)\s+(?:applications?|ung\s*dung|may|may\s*mac)$", "", q_norm).strip()

    if not q_norm:
        return None, None

    installed = find_installed_apps()
    q_compact = re.sub(r"[^a-z0-9]", "", q_norm)

    def _score(item):
        n_low = item[0].lower()
        penalize = any(bad in n_low for bad in ("render engine", "helper", "uninstall", "crash", "eventviewer"))
        is_prefix = strip_accents(item[0]).lower().startswith(q_norm)
        return (penalize, not is_prefix, len(item[0]))

    # 1. Alias match
    aliases = APP_ALIASES.get(q_norm, [])
    if not aliases and q_compact:
        aliases = APP_ALIASES.get(q_compact, [])
    for a in aliases:
        a_norm = strip_accents(a).lower()
        matched = []
        for name, path in installed.items():
            if a_norm in strip_accents(name).lower():
                matched.append((name, path))
        if matched:
            matched.sort(key=_score)
            return matched[0]

    # 2. Exact match
    for name, path in installed.items():
        if q_norm == strip_accents(name).lower():
            return name, path

    # 3. Substring match
    candidates = []
    for name, path in installed.items():
        n_norm = strip_accents(name).lower()
        if q_norm in n_norm:
            candidates.append((name, path))

    if candidates:
        candidates.sort(key=_score)
        return candidates[0]

    # 4. Compact match (bỏ khoảng trắng và dấu gạch nối)
    if len(q_compact) >= 3:
        compact_candidates = []
        for name, path in installed.items():
            name_compact = re.sub(r"[^a-z0-9]", "", strip_accents(name).lower())
            if q_compact == name_compact or (len(q_compact) >= 4 and q_compact in name_compact):
                compact_candidates.append((name, path))
        if compact_candidates:
            compact_candidates.sort(key=_score)
            return compact_candidates[0]

    return None, None


def open_application(app_query: str) -> dict:
    """Mở ứng dụng macOS bằng tên hoặc từ khoá (vd: 'premiere', 'capcut', 'zalo')."""
    app_name, app_path = match_app(app_query)
    if not app_name or not app_path:
        installed = find_installed_apps()
        sample = [name for name in installed if any(k in name.lower() for k in ("premiere", "photoshop", "capcut", "after effects", "zalo", "telegram"))][:5]
        sugg = "\n".join(f"• {s}" for s in sample) if sample else ""
        return {
            "ok": False,
            "error": f"🔍 Không tìm thấy ứng dụng nào khớp với '{app_query}' trên máy Mac." + (f"\n\n💡 Một số ứng dụng có sẵn trên máy:\n{sugg}" if sugg else ""),
        }

    try:
        res = subprocess.run(["open", app_path], capture_output=True, text=True, timeout=10)
        if res.returncode == 0:
            return {
                "ok": True,
                "app_name": app_name,
                "path": app_path,
                "reply": f"🚀 ĐÃ MỞ ỨNG DỤNG THÀNH CÔNG:\n• Ứng dụng: *{app_name}*\n• Vị trí: `{app_path}`",
            }
        else:
            return {
                "ok": False,
                "error": f"❌ Lỗi khi mở ứng dụng '{app_name}': {res.stderr.strip()}",
            }
    except Exception as e:
        return {"ok": False, "error": f"❌ Lỗi khi mở ứng dụng '{app_name}': {e}"}


def list_popular_apps() -> list[dict]:
    """Trả về danh sách các ứng dụng thông dụng chia theo nhóm ngành Media, Trình duyệt, Chat, Hệ thống."""
    categories = [
        ("🎬 Quay dựng & Đồ hoạ", ["premiere", "photoshop", "after effects", "capcut", "davinci", "illustrator", "lightroom", "media encoder", "capture one"]),
        ("💬 Giao tiếp & Trợ lý", ["zalo", "telegram", "antigravity", "chatgpt", "claude", "anydesk"]),
        ("🌐 Trình duyệt web", ["brave", "safari", "chrome", "coccoc"]),
        ("⚙️ Tiện ích & Hệ thống", ["finder", "calendar", "notes", "calculator", "keka", "air explorer", "disk drill"]),
    ]
    curated = []
    for cat_name, keywords in categories:
        cat_apps = []
        for kw in keywords:
            name, path = match_app(kw)
            if name and path and (name, path) not in cat_apps:
                cat_apps.append((name, path))
        if cat_apps:
            curated.append({"category": cat_name, "apps": cat_apps})
    return curated


def get_trash_items(query: str | None = None, limit: int = 50) -> dict:
    if not IS_MAC:
        return {"ok": False, "error": "Thùng rác qua Finder cần macOS."}
    """Đọc danh sách và dung lượng file/thư mục trong Thùng rác (Trash) trên macOS (Chế độ chỉ đọc)."""
    jxa_script = """
    var finder = Application("Finder");
    var items = finder.trash.items();
    var list = [];
    var totalSize = 0;
    for (var i = 0; i < items.length; i++) {
        var it = items[i];
        var sz = 0;
        try { sz = it.size() || 0; } catch(e) {}
        totalSize += sz;
        var mod = "";
        try { mod = it.modificationDate().toLocaleString("vi-VN"); } catch(e) {}
        var kind = "";
        try { kind = it.kind() || ""; } catch(e) {}
        var p = "";
        try {
            var u = it.url();
            if (u) p = decodeURIComponent(u.replace(/^file:\\/\\//, ""));
        } catch(e) {}
        list.push({
            name: it.name(),
            size: sz,
            kind: kind,
            modified: mod,
            path: p
        });
    }
    JSON.stringify({total_count: items.length, total_size: totalSize, items: list});
    """
    try:
        res = subprocess.run(["osascript", "-l", "JavaScript", "-e", jxa_script], capture_output=True, text=True, timeout=12)
        if res.returncode == 0 and res.stdout.strip():
            data = json.loads(res.stdout)
            raw_items = data.get("items", [])
            for it in raw_items:
                it["size_human"] = format_size(it.get("size") or 0)
                k = (it.get("kind") or "").lower()
                it["is_dir"] = ("thư mục" in k or "folder" in k or "bộ sưu tập" in k)
                it["icon"] = "📁" if it["is_dir"] else "📄"

            # Lọc theo query nếu có
            if query and query.strip():
                q_norm = strip_accents(query.strip()).lower()
                q_tokens = [w for w in re.split(r"[^a-z0-9]+", q_norm) if w]
                matched = []
                for it in raw_items:
                    n_norm = strip_accents(it["name"]).lower()
                    if q_norm in n_norm or (q_tokens and all(tk in n_norm for tk in q_tokens)):
                        matched.append(it)
                return {
                    "ok": True,
                    "query": query,
                    "matched_count": len(matched),
                    "total_count": data.get("total_count", 0),
                    "total_size": data.get("total_size", 0),
                    "total_size_human": format_size(data.get("total_size", 0)),
                    "items": matched[:limit],
                }

            return {
                "ok": True,
                "total_count": data.get("total_count", 0),
                "total_size": data.get("total_size", 0),
                "total_size_human": format_size(data.get("total_size", 0)),
                "items": raw_items[:limit],
            }
    except Exception as e:
        return {"ok": False, "error": f"Không thể đọc thông tin Thùng rác: {e}"}

    return {"ok": True, "total_count": 0, "total_size": 0, "total_size_human": "0 B", "items": []}


def get_trash_summary() -> dict:
    """Trả về nội dung tóm tắt Thùng rác (Trash) để hiển thị trong chat hoặc menu Telegram."""
    res = get_trash_items(limit=10)
    if not res.get("ok"):
        return {"ok": False, "reply": res.get("error", "Lỗi đọc Thùng rác.")}

    tc = res.get("total_count", 0)
    ts_human = res.get("total_size_human", "0 B")
    items = res.get("items", [])

    if tc == 0:
        return {
            "ok": True,
            "reply": "🗑 THÙNG RÁC (TRASH) HIỆN ĐANG TRỐNG!\n• Tổng dung lượng: 0 B\n• Không có file nào trong Thùng rác.",
            "items": [],
        }

    lines = [
        f"🗑 THÔNG TIN THÙNG RÁC (TRASH) TRÊN MÁY MAC:",
        f"• Tổng số mục: {tc} file / thư mục",
        f"• Tổng dung lượng đang chiếm: {ts_human}\n",
        f"📋 Danh sách các mục gần nhất trong Thùng rác:",
    ]
    for idx, it in enumerate(items, 1):
        mod_str = f" — {it['modified']}" if it.get("modified") else ""
        lines.append(f"{idx}. {it['icon']} {it['name']} ({it['size_human']}){mod_str}")

    if tc > len(items):
        lines.append(f"\n... và còn {tc - len(items)} mục khác.")

    lines.append("\n💡 Mẹo: Nhắn 'khôi phục <tên file>' để đưa file về lại thư mục ban đầu, hoặc bấm nút Khôi phục bên dưới!")
    return {"ok": True, "reply": "\n".join(lines), "items": items}


def _locate_restored_item(target_name: str, extra_dirs: list[str] | None = None) -> str | None:
    """Tìm đường dẫn thực tế của file/thư mục vừa được khôi phục từ Thùng rác."""
    target_nfc = unicodedata.normalize("NFC", target_name)
    home = Path.home()
    dirs_to_check: list[Path] = []
    if extra_dirs:
        for ed in extra_dirs:
            if ed:
                dirs_to_check.append(Path(ed).expanduser())
    dirs_to_check.extend([home / "Desktop", home / "Downloads", home / "Documents", home])

    seen_dirs: set[str] = set()
    for d in dirs_to_check:
        try:
            if not d.is_dir():
                continue
            d_key = str(d.resolve())
            if d_key in seen_dirs:
                continue
            seen_dirs.add(d_key)
            for fname in os.listdir(d):
                if unicodedata.normalize("NFC", fname) == target_nfc:
                    cand = d / fname
                    if cand.exists():
                        return str(cand)
        except OSError:
            pass

    try:
        md = subprocess.run(
            ["mdfind", "-name", target_name],
            capture_output=True,
            text=True,
            timeout=3,
        )
        if md.returncode == 0 and md.stdout.strip():
            for line in md.stdout.strip().splitlines():
                line = line.strip()
                if not line or "/.Trash/" in line:
                    continue
                p = Path(line)
                if unicodedata.normalize("NFC", p.name) == target_nfc and p.exists():
                    return str(p)
    except Exception:
        pass
    return None


def restore_from_trash(query: str, dest_dir: str | None = None) -> dict:
    """Khôi phục file/thư mục từ Thùng rác về lại thư mục ban đầu (Đưa trở lại / Put Back) hoặc chuyển ra thư mục chỉ định."""
    res = get_trash_items(query=query, limit=50)
    if not res.get("ok"):
        return {"ok": False, "error": res.get("error", "Không thể đọc Thùng rác.")}

    items = res.get("items", [])
    if not items:
        return {
            "ok": False,
            "error": f"🔍 Không tìm thấy file hay thư mục nào khớp với '{query}' trong Thùng rác (Trash).",
        }

    q_norm = strip_accents(query.strip()).lower()
    target_item = None
    for it in items:
        if strip_accents(it["name"]).lower() == q_norm:
            target_item = it
            break
    if not target_item:
        target_item = items[0]

    target_name = target_item["name"]
    size_human = target_item.get("size_human", "0 B")

    fallback_dir = str(dest_dir) if dest_dir else str(Path.home() / "Desktop")

    jxa_extract_from_trash = r"""
function run(argv) {
    var targetName = argv[0].normalize("NFC");
    var fallbackDir = argv[1];
    var finder = Application("Finder");
    var items = finder.trash.items();
    var target = null;
    for (var i = 0; i < items.length; i++) {
        if (items[i].name().normalize("NFC") === targetName) {
            target = items[i];
            break;
        }
    }
    if (!target) {
        return JSON.stringify({ok: false, error: "NOT_FOUND"});
    }

    var closeTrashWin = function() {
        try {
            var wins = finder.finderWindows();
            for (var w = 0; w < wins.length; w++) {
                var wn = wins[w].name();
                if (wn === "Thùng rác" || wn === "Trash") {
                    wins[w].close();
                }
            }
        } catch(e) {}
    };

    var isStillInTrash = function() {
        try {
            var cur = finder.trash.items();
            for (var k = 0; k < cur.length; k++) {
                if (cur[k].name().normalize("NFC") === targetName) {
                    return true;
                }
            }
        } catch(e) {}
        return false;
    };

    try {
        finder.reveal(target);
        finder.activate();
        delay(0.6);

        var se = Application("System Events");
        var finderProc = se.processes.byName("Finder");
        var fileMenu = finderProc.menuBars[0].menuBarItems[2].menus[0];

        var findPutBack = function() {
            var mItems = fileMenu.menuItems();
            for (var j = 0; j < mItems.length; j++) {
                try {
                    var n = mItems[j].name();
                    if (n === "Đưa trở lại" || n === "Put Back" || n === "Đặt lại") {
                        return mItems[j];
                    }
                } catch(e) {}
            }
            return null;
        };

        var putBackItem = findPutBack();
        if (!putBackItem) {
            delay(0.4);
            putBackItem = findPutBack();
        }
        if (putBackItem && putBackItem.enabled()) {
            putBackItem.click();
            delay(0.8);
            closeTrashWin();
            if (!isStillInTrash()) {
                return JSON.stringify({ok: true, method: "put_back"});
            }
        }

        closeTrashWin();
        try {
            var moved = finder.move(target, {to: Path(fallbackDir), replacing: false});
            var movedPath = fallbackDir;
            try {
                var u = moved.url();
                if (u) movedPath = decodeURIComponent(u.replace(/^file:\/\//, ""));
            } catch(e) {}
            return JSON.stringify({ok: true, method: "direct_move", dest: movedPath});
        } catch(moveErr) {
            return JSON.stringify({ok: false, error: String(moveErr)});
        }
    } catch(e) {
        return JSON.stringify({ok: false, error: String(e)});
    }
}
"""
    try:
        run_res = subprocess.run(
            ["osascript", "-l", "JavaScript", "-e", jxa_extract_from_trash, target_name, fallback_dir],
            capture_output=True,
            text=True,
            timeout=25,
        )
        if run_res.returncode == 0 and run_res.stdout.strip():
            out = json.loads(run_res.stdout.strip())
            if out.get("ok"):
                res_method = out.get("method", "put_back")
                restored_path = _locate_restored_item(target_name, [str(dest_dir)] if dest_dir else None)
                if not restored_path:
                    time.sleep(0.5)
                    restored_path = _locate_restored_item(target_name, [str(dest_dir)] if dest_dir else None)

                if dest_dir:
                    dest_p = Path(dest_dir).expanduser().resolve()
                    if restored_path:
                        restored_p = Path(restored_path).resolve()
                        if restored_p.parent != dest_p:
                            mv_res = safe_move(restored_path, str(dest_p))
                            if mv_res.get("ok"):
                                final_dest = mv_res.get("dst")
                            else:
                                return {"ok": False, "error": mv_res.get("error", "❌ Không thể dời file sau khi khôi phục.")}
                        else:
                            final_dest = str(restored_p)
                    else:
                        final_dest = str(dest_p / target_name)

                    return {
                        "ok": True,
                        "item_name": target_name,
                        "method": "move_to_dir",
                        "dest": final_dest,
                        "reply": (
                            f"♻️ ĐÃ LẤY FILE TỪ THÙNG RÁC RA THƯ MỤC ĐÍCH:\n"
                            f"• Tên mục: {target_name} ({size_human})\n"
                            f"• Nơi đến: `{final_dest}`"
                        ),
                    }

                if res_method == "put_back":
                    dest_label = f"`{restored_path}`" if restored_path else "Thư mục gốc ban đầu (Đưa trở lại / Put Back)"
                    return {
                        "ok": True,
                        "item_name": target_name,
                        "method": "put_back",
                        "dest": restored_path or "Thư mục gốc ban đầu (Đưa trở lại / Put Back)",
                        "reply": (
                            f"♻️ ĐÃ KHÔI PHỤC VỀ THƯ MỤC BAN ĐẦU THÀNH CÔNG:\n"
                            f"• Tên mục: {target_name} ({size_human})\n"
                            f"• Vị trí hiện tại: {dest_label}"
                        ),
                    }

                final_dest = restored_path or out.get("dest", fallback_dir)
                return {
                    "ok": True,
                    "item_name": target_name,
                    "method": "fallback_desktop",
                    "dest": final_dest,
                    "reply": (
                        f"♻️ ĐÃ LẤY RA KHỎI THÙNG RÁC (Chuyển ra Desktop):\n"
                        f"• Tên mục: {target_name} ({size_human})\n"
                        f"• Vị trí hiện tại: `{final_dest}`\n"
                        f"ℹ️ Thư mục gốc ban đầu không còn thông tin lưu vết nên Finder đã chuyển an toàn ra Desktop."
                    ),
                }

            action_err = out.get("error", "Lỗi không xác định")
            if dest_dir:
                return {"ok": False, "error": f"❌ Không thể chuyển '{target_name}' từ Thùng rác: {action_err}"}
            return {"ok": False, "error": f"❌ Không thể khôi phục '{target_name}': {action_err}"}
        err_msg = run_res.stderr.strip() or run_res.stdout.strip()
        return {"ok": False, "error": f"❌ Lỗi hệ thống khi khôi phục '{target_name}': {err_msg}"}
    except Exception as e:
        return {"ok": False, "error": f"❌ Lỗi khi khôi phục '{target_name}' từ Thùng rác: {e}"}

