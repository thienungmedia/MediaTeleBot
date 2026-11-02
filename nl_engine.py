#!/usr/bin/env python3
from __future__ import annotations
"""
Natural Language Engine (Vietnamese) for Safe Mac File Manager.
Supports:
- Default Google Drive upload destination: THIEN UNG PRODUCTION
- Automatic & on-demand Google Drive Share Link extraction ("Lấy link file test.mp4...", "up ... lên drive và lấy link")
- Flexible verbs & prepositions ("chuyển", "dời", "ra", "ra lại", "qua", "sang", "vào"...)
- Word-order-independent token matching ("a bin decor" <-> "2410 DECOR A BIN")
"""

import json
import os
import re
import shutil
import time
import unicodedata
from pathlib import Path
import safe_fs
from safe_fs import (
    DEFAULT_GDRIVE_SUBFOLDER,
    get_default_gdrive_subfolder,
    get_default_gdrive_folder_info,
    set_default_gdrive_folder,
    strip_accents,
    list_drives,
    list_directory,
    safe_copy,
    safe_move,
    get_folder_size,
    find_google_drive_root,
    resolve_subfolder_fuzzy,
    query_gdrive_items,
)

IGNORED_DIR_NAMES = {
    "Library",
    "node_modules",
    ".Trash",
    "Applications",
    ".gemini",
    "Macintosh HD",
    "Recovery",
    "Antigravity",
    "Adobe Premiere Pro Audio Previews",
    "Adobe Premiere Pro Video Previews",
    "Adobe Premiere Pro Captured Audio",
    "Adobe Premiere Pro Captured Video",
    "Peak Files",
    "Media Cache",
    "Media Cache Files",
    "Cache",
    "Caches",
    "User Data",
    "FolderSourcePreviews",
}

IGNORED_EXTENSIONS = {
    ".cfa",
    ".pek",
    ".ims",
    ".prmdc2",
    ".DS_Store",
    ".ini",
}


def is_ignored_dir(dirname: str) -> bool:
    if dirname.startswith(".") or dirname.startswith("$"):
        return True
    if dirname in IGNORED_DIR_NAMES:
        return True
    if dirname.endswith(".lrlibrary") or dirname.endswith(".PRV") or dirname.endswith(".app"):
        return True
    return False


def is_ignored_file(filename: str) -> bool:
    if filename.startswith("."):
        return True
    ext = Path(filename).suffix.lower()
    if ext in IGNORED_EXTENSIONS:
        return True
    return False


def clean_polite_phrases(s: str) -> str:
    """Remove polite Vietnamese suffixes/prefixes from an extracted entity name."""
    s = s.strip()
    suffixes = [
        r"\s+(?:và|rồi|xong)\s+(?:lấy|gửi|cho\s+tôi\s+xin)\s+link.*$",
        r"\s+để\s+gửi\s+khách.*$",
        r"\s+gửi\s+khách.*$",
        r"\s+trên\s+(?:google\s*drive|gg\s*drive|drive).*$",
        r"\s+(?:thợ|khách|ai\s+đó|người\s+khác)\s+(?:gửi|share)(?:\s+cho\s+tôi)?.*$",
        r"\s+(?:trong\s+|ở\s+)?(?:mục\s+)?(?:được\s+chia\s+sẻ(?:\s+với\s+tôi)?|shared\s+with\s+me).*$",
        r"\s+giúp\s+tôi.*$",
        r"\s+giúp\s+mình.*$",
        r"\s+cho\s+tôi.*$",
        r"\s+cho\s+mình.*$",
        r"\s+của\s+tôi.*$",
        r"\s+nhé.*$",
        r"\s+nha.*$",
        r"\s+với.*$",
        r"\s+ấy.*$",
        r"\s+đó.*$",
        r"\s+đi.*$",
        r"\s+luôn.*$",
        r"\s+nặng\s+bao\s+nhiêu.*$",
        r"\s+bao\s+nhiêu\s*(gb|mb|dung\s*lượng).*$",
        r"\s+có\s+dung\s+lượng.*$",
    ]
    for pat in suffixes:
        s = re.sub(pat, "", s, flags=re.IGNORECASE).strip()

    prefixes = [
        r"^(không\s*,?\s*|à\s*,?\s*|ừ\s*,?\s*|ý\s+tôi\s+là\s+)+",
        r"^(cho\s+tôi\s+xin|cho\s+xin|lấy\s+cho\s+tôi|lấy\s+giúp\s+tôi|cho\s+tôi|giúp\s+tôi|tôi\s+muốn|hãy|làm\s+ơn|lại)\s+",
        r"^(link\s+google\s+drive|link\s+gg\s+drive|link\s+drive|link\s+của|link|đường\s+link)\s+",
        r"^(?:bác\s+|anh\s+)?(?:thợ|khách|ai\s+đó|người\s+khác)\s+(?:có\s+)?(?:gửi|share)(?:\s+cho\s+tôi|\s+qua)?\s+",
        r"^(?:trong\s+|ở\s+)?(?:mục\s+)?(?:được\s+chia\s+sẻ(?:\s+với\s+tôi)?|shared\s+with\s+me)\s+",
        r"^(cái\s+|các\s+|những\s+|tổng\s+|lại\s+)+",
        r"^(thư\s+mục|folder|file|tệp|tập\s+tin|ổ\s+đĩa|ổ\s+cứng|ổ)\s+",
        r"^(cái\s+|các\s+|những\s+|tổng\s+|lại\s+)+",
        r"^(thư\s+mục|folder|file|tệp|tập\s+tin|ổ\s+đĩa|ổ\s+cứng|ổ)\s+",
    ]
    for pat in prefixes:
        s = re.sub(pat, "", s, flags=re.IGNORECASE).strip()

    return s.strip("\"' ,.")


def detect_item_type_hint(raw_text: str) -> str | None:
    """
    Detect if user explicitly asked for a specific file extension.
    Note: In Vietnamese video workflows, users often say 'file psc hằng cần' or 'file cưới 2510'
    to refer to a project folder, so we only restrict to 'file' when a file extension is present.
    """
    t = raw_text.strip().lower()
    if re.search(r"\.[a-z0-9]{2,5}\b", t):
        return "file"
    return None


def parse_source_specification(raw_src: str) -> tuple[str, str | None, str | None, str | None]:
    """
    Parse phrases like:
      - "file test trong phim xong"
      - "file test.mp4 trong thư mục THIEN UNG PRODUCTION"
      - "thư mục a bin decor trong film data"
      - "thư mục source ngoài desktop"
    Returns (item_name, parent_folder_hint, root_location_hint, type_hint)
    """
    type_hint = detect_item_type_hint(raw_src)
    s = clean_polite_phrases(raw_src)
    root_hint = None

    loc_match = re.search(
        r"\s+(?:ngoài|ở\s+ngoài|trong|ở\s+trong|ở|bên|trên)\s+(?:ổ\s+đĩa\s+|ổ\s+cứng\s+|ổ\s+)?(desktop|màn\s+hình|downloads?|tải\s+về|documents?|film\s*data|google\s*drive|gg\s*drive|drive|mục\s+được\s+chia\s+sẻ|được\s+chia\s+sẻ(?:\s+với\s+tôi)?|shared\s+with\s+me)$",
        s,
        flags=re.IGNORECASE,
    )
    if loc_match:
        root_hint = loc_match.group(1).lower()
        s = s[: loc_match.start()].strip()
        if any(kw in strip_accents(root_hint) for kw in ("chia se", "shared")):
            return clean_polite_phrases(s), "Được chia sẻ với tôi", "drive", type_hint

    in_match = re.search(
        r"^(.+?)\s+(?:trong|ở\s+trong|ngoài|ở\s+ngoài)\s+(?:thư\s+mục\s+|folder\s+|mục\s+)?(.+)$",
        s,
        flags=re.IGNORECASE,
    )
    if in_match:
        item_name = clean_polite_phrases(in_match.group(1))
        parent_hint = clean_polite_phrases(in_match.group(2))
        p_norm = strip_accents(parent_hint)
        if p_norm in ("desktop", "man hinh", "downloads", "download", "documents", "film data", "drive", "google drive", "gg drive"):
            return item_name, None, p_norm, type_hint
        if any(kw in p_norm for kw in ("duoc chia se", "chia se", "shared", "tho gui", "khach gui")):
            return item_name, "Được chia sẻ với tôi", "drive", type_hint
        return item_name, parent_hint, root_hint, type_hint

    return clean_polite_phrases(s), None, root_hint, type_hint


def tokens_match(query_norm: str, target_norm: str) -> bool:
    """Check if all word tokens in query_norm exist in target_norm (regardless of word order)."""
    q_tokens = [w for w in re.split(r"[^a-z0-9]+", query_norm) if w]
    if not q_tokens:
        return False
    t_tokens = set(w for w in re.split(r"[^a-z0-9]+", target_norm) if w)
    for qt in q_tokens:
        if qt in t_tokens:
            continue
        if len(qt) >= 3 and any(qt in tt for tt in t_tokens):
            continue
        return False
    return True


def find_folder_by_name(folder_hint: str, root_hint: str | None = None) -> Path | None:
    """Find a directory matching folder_hint."""
    matches = find_best_matches(folder_hint, force_type="dir", root_override=root_hint)
    if matches:
        return Path(matches[0]["path"])
    return None


def find_best_matches(
    raw_query: str,
    exclude_root: str | None = None,
    force_type: str | None = None,
    root_override: str | None = None,
) -> list[dict]:
    """Search for files/folders matching raw_query across user directories and drives."""
    item_name, parent_hint, root_hint, parsed_type = parse_source_specification(raw_query)
    type_filter = force_type or parsed_type
    effective_root_hint = root_override or root_hint

    if not item_name:
        return []

    home = Path.home()

    if parent_hint:
        parent_dir = find_folder_by_name(parent_hint, effective_root_hint)
        if parent_dir and parent_dir.exists():
            search_roots = [parent_dir]
        else:
            search_roots = [home / "Desktop", home / "Downloads", home / "Documents", Path("/Volumes/FILM DATA")]
    elif effective_root_hint in ("desktop", "màn hình", "man hinh"):
        search_roots = [home / "Desktop"]
    elif effective_root_hint in ("download", "downloads", "tải về", "tai ve"):
        search_roots = [home / "Downloads"]
    elif effective_root_hint in ("document", "documents"):
        search_roots = [home / "Documents"]
    elif effective_root_hint and "film" in effective_root_hint:
        search_roots = [Path("/Volumes/FILM DATA")]
    elif effective_root_hint and "drive" in effective_root_hint:
        search_roots = []
        gd_root = find_google_drive_root(auto_launch=False)
        if gd_root and gd_root.exists():
            def_sub = resolve_subfolder_fuzzy(gd_root, get_default_gdrive_subfolder())
            if def_sub.exists():
                search_roots.append(def_sub)
            search_roots.append(gd_root)
    else:
        search_roots = [
            home / "Desktop",
            home / "Downloads",
            home / "Documents",
            home / "Movies",
            home / "Pictures",
            home,
        ]
        gd_root = find_google_drive_root(auto_launch=False)
        if gd_root and gd_root.exists():
            def_sub = resolve_subfolder_fuzzy(gd_root, get_default_gdrive_subfolder())
            if def_sub.exists():
                search_roots.append(def_sub)
            search_roots.append(gd_root)
        volumes = Path("/Volumes")
        if volumes.exists():
            for v in sorted(volumes.iterdir()):
                if not is_ignored_dir(v.name):
                    search_roots.append(v)

    seen_paths = set()
    tier1_exact = []
    tier2_accent = []
    tier3_prefix = []
    tier4_substring = []
    tier5_tokens = []

    item_lower = item_name.lower()
    item_norm = strip_accents(item_name)
    parent_norm = strip_accents(parent_hint) if parent_hint else None
    exclude_resolved = str(Path(exclude_root).resolve()) if exclude_root else None

    def parent_ok(full_path: str) -> bool:
        if not parent_norm:
            return True
        parts_norm = [strip_accents(p) for p in Path(full_path).parent.parts]
        return any(parent_norm == p or parent_norm in p or tokens_match(parent_norm, p) for p in parts_norm)

    for root in search_roots:
        if not root.exists():
            continue

        is_cloud = "cloudstorage" in str(root).lower() or "googledrive" in str(root).lower()
        max_depth = 2 if (root == home or is_cloud) else 4
        budget = 1.5 if is_cloud else 4.0
        t_start = time.time()

        for dirpath, dirnames, filenames in os.walk(root, topdown=True):
            if time.time() - t_start > budget:
                break
            rel_depth = len(Path(dirpath).relative_to(root).parts)
            if rel_depth >= max_depth:
                dirnames[:] = []
            else:
                dirnames[:] = [d for d in dirnames if not is_ignored_dir(d)]

            if root == home and rel_depth == 0:
                dirnames[:] = [
                    d for d in dirnames
                    if d not in ("Desktop", "Downloads", "Documents", "Movies", "Pictures")
                ]

            if type_filter != "file":
                for d in dirnames:
                    d_lower = d.lower()
                    d_norm = strip_accents(d)
                    m_tier = 0
                    if d_lower == item_lower:
                        m_tier = 1
                    elif d_norm == item_norm:
                        m_tier = 2
                    elif d_norm.startswith(item_norm + " ") or d_norm.startswith(item_norm):
                        m_tier = 3
                    elif item_norm in d_norm:
                        m_tier = 4
                    elif tokens_match(item_norm, d_norm):
                        m_tier = 5
                    if not m_tier:
                        continue
                    full = str(Path(dirpath) / d)
                    norm_full = unicodedata.normalize("NFC", full)
                    if norm_full in seen_paths:
                        continue
                    if exclude_resolved and (full == exclude_resolved or str(Path(full).parent) == exclude_resolved):
                        continue
                    if not parent_ok(full):
                        continue
                    seen_paths.add(norm_full)
                    entry = {"path": full, "name": d, "is_dir": True}
                    if m_tier == 1:
                        tier1_exact.append(entry)
                    elif m_tier == 2:
                        tier2_accent.append(entry)
                    elif m_tier == 3:
                        tier3_prefix.append(entry)
                    elif m_tier == 4:
                        tier4_substring.append(entry)
                    else:
                        tier5_tokens.append(entry)

            if type_filter != "dir":
                for f in filenames:
                    if is_ignored_file(f):
                        continue
                    f_lower = f.lower()
                    stem_lower = Path(f).stem.lower()
                    f_norm = strip_accents(f)
                    stem_norm = strip_accents(Path(f).stem)
                    m_tier = 0
                    if f_lower == item_lower or stem_lower == item_lower:
                        m_tier = 1
                    elif f_norm == item_norm or stem_norm == item_norm:
                        m_tier = 2
                    elif stem_norm.startswith(item_norm):
                        m_tier = 3
                    elif item_norm in f_norm:
                        m_tier = 4
                    elif tokens_match(item_norm, stem_norm):
                        m_tier = 5
                    if not m_tier:
                        continue
                    full = str(Path(dirpath) / f)
                    norm_full = unicodedata.normalize("NFC", full)
                    if norm_full in seen_paths:
                        continue
                    if exclude_resolved and str(Path(full).parent) == exclude_resolved:
                        continue
                    if not parent_ok(full):
                        continue
                    seen_paths.add(norm_full)
                    entry = {"path": full, "name": f, "is_dir": False}
                    if m_tier == 1:
                        tier1_exact.append(entry)
                    elif m_tier == 2:
                        tier2_accent.append(entry)
                    elif m_tier == 3:
                        tier3_prefix.append(entry)
                    elif m_tier == 4:
                        tier4_substring.append(entry)
                    else:
                        tier5_tokens.append(entry)

    results = tier1_exact + tier2_accent + tier3_prefix + tier4_substring + tier5_tokens
    if not results:
        import subprocess
        q_tokens = [w for w in re.split(r"[^a-zA-Z0-9]+", item_norm) if len(w) >= 2]
        search_tok = max(q_tokens, key=len) if q_tokens else item_name
        try:
            md_res = subprocess.run(
                ["/usr/bin/mdfind", "-name", search_tok],
                capture_output=True,
                text=True,
                timeout=4,
            )
            for line in md_res.stdout.splitlines()[:200]:
                line = line.strip()
                if not line or "/." in line:
                    continue
                if "/Library/" in line and "/Library/CloudStorage/" not in line:
                    continue
                p_obj = Path(line)
                if not p_obj.exists():
                    continue
                full = str(p_obj.resolve())
                if full in seen_paths:
                    continue
                if not parent_ok(full):
                    continue
                is_d = p_obj.is_dir()
                if type_filter == "dir" and not is_d:
                    continue
                if type_filter == "file" and is_d:
                    continue
                name_norm = strip_accents(p_obj.name)
                if item_norm in name_norm or tokens_match(item_norm, name_norm):
                    seen_paths.add(full)
                    results.append({"path": full, "name": p_obj.name, "is_dir": is_d})
        except Exception:
            pass

    if type_filter is None:
        dirs = [r for r in results if r["is_dir"]]
        files = [r for r in results if not r["is_dir"]]
        return dirs + files
    return results


def resolve_destination(dest_phrase: str) -> Path | None:
    """Resolve a natural-language destination phrase into an actual directory Path."""
    d_clean = clean_polite_phrases(dest_phrase)
    d_clean = re.sub(
        r"^(lại\s+|ngoài\s+|ở\s+ngoài\s+|trong\s+|ở\s+trong\s+|bên\s+|trên\s+|vào\s+|ra\s+)+",
        "",
        d_clean,
        flags=re.IGNORECASE,
    ).strip()
    d_clean = re.sub(
        r"^(ổ\s+đĩa|ổ\s+cứng|ổ|thư\s+mục|folder)\s+",
        "",
        d_clean,
        flags=re.IGNORECASE,
    ).strip()

    d_norm = strip_accents(d_clean)
    home = Path.home()

    if d_norm in ("desktop", "man hinh", "man hinh chinh"):
        return home / "Desktop"
    if d_norm in ("downloads", "download", "tai ve", "thu muc tai ve"):
        return home / "Downloads"
    if d_norm in ("documents", "document", "tai lieu"):
        return home / "Documents"

    volumes = Path("/Volumes")
    if volumes.exists():
        for v in volumes.iterdir():
            if is_ignored_dir(v.name):
                continue
            v_norm = strip_accents(v.name)
            if d_norm == v_norm or d_norm == f"o dia {v_norm}" or d_norm == f"o cung {v_norm}":
                return v
            if "/" in d_clean and v_norm in d_norm:
                sub = d_clean.split("/", 1)[1].strip()
                return resolve_subfolder_fuzzy(v, sub)

    matches = find_best_matches(dest_phrase, force_type="dir")
    if matches:
        return Path(matches[0]["path"])

    if volumes.exists():
        for v in volumes.iterdir():
            if is_ignored_dir(v.name):
                continue
            v_norm = strip_accents(v.name)
            if v_norm in d_norm or d_norm in v_norm:
                return v

    return None


def clean_zalo_entity(name: str) -> str:
    name = clean_polite_phrases(name)
    name = re.sub(
        r"^(?:link\s+(?:file\s+|thư\s+mục\s+|folder\s+)?|file\s+|thư\s+mục\s+|folder\s+|video\s+|clip\s+)",
        "",
        name,
        flags=re.IGNORECASE,
    ).strip()
    return name


def clean_zalo_recipient(name: str) -> str:
    name = clean_polite_phrases(name)
    name = re.sub(r"^(?:qua\s+cho\s+|cho\s+|tới\s+|đến\s+|qua\s+)", "", name, flags=re.IGNORECASE).strip()
    name = re.sub(r"\s+(?:qua|bên|vào|trên|bằng)?\s*zalo.*$", "", name, flags=re.IGNORECASE).strip()
    return name


def _try_zalo_dispatch(t: str, chat_id: int) -> dict | None:
    t_clean = t.strip()
    t_lower = t_clean.lower()
    t_norm = strip_accents(t_clean)

    raw_target = None
    raw_recipient = None
    is_chain = False

    # Pattern A: Chained Upload to Drive + Send link via Zalo
    # Ví dụ: "up file test.mp4 lên drive rồi gửi link cho anh Thăng qua zalo"
    #        "up 2810 lên drive rồi gửi qua cho Hoàng Dựng"
    m_chain = re.search(
        r"^(?:hãy\s+|giúp\s+tôi\s+)?(?:up|upload|tải|đẩy)\s+(.+?)\s+lên\s+(?:google\s*drive|gg\s*drive|drive)\s+(?:rồi|và|xong|để)\s+(?:gửi|bắn|chia\s+sẻ)\s+(.*)$",
        t_clean,
        flags=re.IGNORECASE,
    )
    if m_chain:
        raw_target = m_chain.group(1).strip()
        rest = m_chain.group(2).strip()
        rest_clean = re.sub(r"^(?:link\s+)?(?:drive\s+)?", "", rest, flags=re.IGNORECASE).strip()
        rec = re.sub(r"(?:qua|bên|vào|trên|bằng)?\s*zalo", "", rest_clean, flags=re.IGNORECASE).strip()
        rec = re.sub(r"^(?:qua\s+cho|cho|tới|đến)\s+", "", rec, flags=re.IGNORECASE).strip()
        raw_recipient = rec
        is_chain = True

    # Pattern B: Direct Send Google Drive Link to a recipient (via Zalo or general)
    if not is_chain:
        # Form 1: Recipient first
        # e.g.: "gửi qua zalo cho Hoàng Dựng link 2510"
        #       "gửi qua zalo Hoàng Dựng link 2510"
        #       "gửi cho Hoàng Dựng link 2510 qua zalo"
        m1 = re.search(
            r"^(?:hãy\s+|giúp\s+tôi\s+)?(?:gửi|gui|bắn|ban|chia\s+sẻ|chia\s+se|share)\s+(?:(?:qua|bên|vào|trên)?\s*zalo\s+)?(?:qua\s+)?cho\s+(.+?)\s+(?:cái\s+|link\s+|drive\s+|file\s+|thư\s+mục\s+)(.+?)(?:\s+(?:qua|bên|vào|trên|bằng)?\s*zalo)?$",
            t_clean,
            flags=re.IGNORECASE,
        )
        if m1:
            raw_recipient = m1.group(1).strip()
            raw_target = m1.group(2).strip()

        if not raw_target:
            m1b = re.search(
                r"^(?:hãy\s+|giúp\s+tôi\s+)?(?:gửi|gui|bắn|ban|chia\s+sẻ|chia\s+se|share)\s+(?:qua|bên|vào|trên)?\s*zalo\s+(.+?)\s+(?:cái\s+|link\s+|drive\s+|file\s+|thư\s+mục\s+)(.+?)$",
                t_clean,
                flags=re.IGNORECASE,
            )
            if m1b:
                raw_recipient = m1b.group(1).strip()
                raw_target = m1b.group(2).strip()

        # Form 2: Target first, then separator, then recipient
        # Separator covers:
        # - "qua zalo cho [recipient]"
        # - "qua zalo [recipient]"
        # - "bên zalo cho [recipient]"
        # - "bên zalo [recipient]"
        # - "qua cho [recipient]"
        # - "cho [recipient]" (kèm hoặc không kèm "qua zalo" ở cuối)
        if not raw_target:
            action_prefix = r"^(?:hãy\s+|giúp\s+tôi\s+)?(?:gửi|gui|bắn|ban|chia\s+sẻ|chia\s+se|share)\s+(?:link\s+)?(?:google\s*drive\s+|gg\s*drive\s+|drive\s+)?(?:file\s+|thư\s+mục\s+|folder\s+|mục\s+)?"
            sep_pattern = r"(?:\s+(?:qua|bên|trên)?\s*zalo\s+cho\s+|\s+(?:qua|bên|trên)?\s*zalo\s+|\s+qua\s+cho\s+|\s+cho\s+)"
            m2 = re.search(
                f"{action_prefix}(.+?){sep_pattern}(.+?)(?:\\s+(?:qua|bên|vào|trên|bằng)?\\s*zalo)?$",
                t_clean,
                flags=re.IGNORECASE,
            )
            if m2:
                cand_target = m2.group(1).strip()
                cand_recipient = m2.group(2).strip()
                cand_clean_rec = clean_zalo_recipient(cand_recipient)
                # Ignore non-recipient objects like "cho tôi", "cho mình", "cho khách"
                if cand_clean_rec and cand_clean_rec.lower() not in ("toi", "minh", "khach", "ai", "link", "google drive"):
                    raw_target = cand_target
                    raw_recipient = cand_clean_rec

    if not raw_target or not raw_recipient:
        return None

    recipient = clean_zalo_recipient(raw_recipient)
    target = clean_zalo_entity(raw_target)

    t_target_norm = strip_accents(target).lower()
    if t_target_norm in ("nay", "do", "ay", "file nay", "thu muc nay", "muc nay", "folder nay", "cai nay", "no", ""):
        candidates = PENDING_CONFIRM.get(chat_id, {}).get("candidates", [])
        if candidates:
            target = candidates[0]["name"]
        elif chat_id in LAST_CONTEXT and LAST_CONTEXT[chat_id].get("last_item"):
            target = LAST_CONTEXT[chat_id]["last_item"]

    LAST_CONTEXT.setdefault(chat_id, {})["last_item"] = target

    if is_chain:
        safe_fs._write_json(safe_fs.ZALO_AFTER_UPLOAD_PATH, {"to": recipient, "ts": time.time()})
        res = _prepare_gdrive_confirmation(target, DEFAULT_GDRIVE_SUBFOLDER, chat_id)
        if res.get("handled") and "reply" in res:
            res["reply"] += f"\n\n💬 *Lưu ý:* Sau khi tải lên và Google Drive đồng bộ link xong, bot sẽ tự động tạo nút bấm gửi Zalo cho *{recipient}*!"
        return res

    # 1. Tìm trên Google Drive trước
    raw_matches = query_gdrive_items(target)
    matches = [m for m in raw_matches if not m.get("name", "").startswith("._")]
    if matches:
        m = matches[0]
        if m.get("is_synced") and m.get("url"):
            zalo_text = safe_fs.build_zalo_text(m["name"], m["url"])
            safe_fs.set_zalo_pending(recipient, zalo_text)
            icon = "📁 Thư mục" if m.get("is_dir") else "📄 File"
            parent_info = f"\n📂 Nằm trong: {m.get('parent_name')}" if m.get("parent_name") else ""
            return {
                "handled": True,
                "reply": (
                    f"📨 ĐÃ TÌM THẤY TRÊN GOOGLE DRIVE & SOẠN SẴN TIN ZALO:\n\n"
                    f"👤 Người nhận: *{recipient}*\n"
                    f"• {icon}: {m['name']} ({m.get('size', '-')}){parent_info}\n"
                    f"• Link Google Drive:\n{m['url']}\n\n"
                    f"📝 Nội dung tin nhắn sẽ gửi:\n{zalo_text}\n\n"
                    f"👉 Bấm nút bên dưới để gửi tin nhắn này qua Zalo:"
                ),
                "reply_markup": safe_fs.zalo_confirm_markup(recipient),
            }
        else:
            safe_fs._write_json(safe_fs.ZALO_AFTER_UPLOAD_PATH, {"to": recipient, "ts": time.time()})
            return {
                "handled": True,
                "reply": (
                    f"⏳ Mục '{m['name']}' đang được Google Drive đồng bộ lên mây.\n"
                    f"Ngay khi đồng bộ xong 100%, tôi sẽ tạo link và gửi nút bấm xác nhận gửi Zalo cho *{recipient}*!"
                ),
            }

    # 2. Chưa có trên Google Drive, tìm trên máy Mac / SOURCE / FILM DATA
    local_matches = find_best_matches(target)
    if local_matches:
        safe_fs._write_json(safe_fs.ZALO_AFTER_UPLOAD_PATH, {"to": recipient, "ts": time.time()})
        res = _prepare_gdrive_confirmation(target, DEFAULT_GDRIVE_SUBFOLDER, chat_id)
        if res.get("handled") and "reply" in res:
            res["reply"] = (
                f"ℹ️ '{target}' chưa có trên Google Drive, nhưng tôi đã tìm thấy trên máy Mac!\n\n"
                f"{res['reply']}\n\n"
                f"💬 *Lưu ý:* Sau khi tải lên và có link Google Drive, bot sẽ tự động tạo nút gửi Zalo cho *{recipient}*."
            )
        return res

    return {
        "handled": True,
        "reply": (
            f"🔍 Không tìm thấy file/thư mục nào khớp với '{target}' trên Google Drive cũng như trên máy Mac để gửi cho {recipient}."
        ),
    }

    return None


PENDING_CONFIRM: dict[int, dict] = {}
LAST_CONTEXT: dict[int, dict] = {}


def parse_and_execute_nl(text: str, chat_id: int = 0, _from_llm: bool = False) -> dict:
    """Analyze natural Vietnamese command and return confirmation prompt or execute action."""
    t = text.strip()
    t_lower = t.lower()
    t_norm = strip_accents(t)

    # 0. Check if user is replying to a pending confirmation ("ok", "đúng rồi", "xác nhận", "1", "2", "huỷ", "huỷ up 3110"...)
    if chat_id in PENDING_CONFIRM:
        pending = PENDING_CONFIRM[chat_id]
        if (
            t_norm in ("huy", "huy bo", "khong", "thoi", "cancel", "dung lai", "stop")
            or t_norm.startswith(("huy ", "huy bo ", "cancel ", "dung ", "thoi "))
            or "huy up" in t_norm
            or "khong up" in t_norm
            or "dung up" in t_norm
            or "thoi khong" in t_norm
            or "khong can" in t_norm
        ):
            PENDING_CONFIRM.pop(chat_id, None)
            return {"handled": True, "reply": "✅ Đã huỷ thao tác theo yêu cầu của bạn."}

        candidates = pending.get("candidates", [])
        chosen_item = None

        if t_norm in ("ok", "oke", "uk", "uh", "u", "dung", "dung roi", "xac nhan", "chuyen di", "up di", "yes", "dong y") and len(candidates) == 1:
            chosen_item = candidates[0]
        else:
            num_match = re.match(r"^(?:số\s+|cái\s+|mục\s+|thư\s+mục\s+|file\s+)?(\d+)$", t_lower)
            if num_match:
                idx = int(num_match.group(1)) - 1
                if 0 <= idx < len(candidates):
                    chosen_item = candidates[idx]

        if chosen_item:
            PENDING_CONFIRM.pop(chat_id, None)
            dst_path = pending["dst_path"]
            is_copy = pending["is_copy"]
            is_gdrive = pending.get("is_gdrive", False)
            sz_info = get_folder_size(chosen_item["path"])
            sz_str = sz_info.get("size_human", "?") if sz_info.get("ok") else "?"
            res = safe_copy(chosen_item["path"], dst_path) if is_copy else safe_move(chosen_item["path"], dst_path)
            if res.get("ok"):
                if is_gdrive:
                    dst_folder_name = Path(res["dst"]).parent.name if Path(res["dst"]).is_file() else Path(res["dst"]).name
                    return {
                        "handled": True,
                        "reply": (
                            f"☁️ ĐÃ UPLOAD LÊN GOOGLE DRIVE ({dst_folder_name})!\n"
                            f"• File/Thư mục: {chosen_item['name']} ({sz_str})\n"
                            f"• Nguồn: {res['src']}\n"
                            f"• Đích Google Drive: {res['dst']}\n"
                            f"🔗 Đang lấy Link Google Drive để gửi khách..."
                        ),
                    }
                act_vn = "SAO CHÉP" if is_copy else "CHUYỂN (DỜI)"
                return {
                    "handled": True,
                    "reply": (
                        f"✅ ĐÃ {act_vn} THÀNH CÔNG!\n"
                        f"• Tên: {chosen_item['name']} ({sz_str})\n"
                        f"• Từ: {res['src']}\n"
                        f"• Sang: {res['dst']}"
                    ),
                }
            else:
                return {"handled": True, "reply": f"❌ Lỗi: {res.get('error')}"}

    # Cancel command when nothing is pending (or general cancel phrases)
    if (
        t_norm in ("huy", "huy bo", "cancel", "thoi", "dung lai", "stop")
        or t_norm.startswith(("huy ", "huy bo ", "cancel ", "dung ", "thoi "))
        or "huy up" in t_norm
        or "khong up" in t_norm
    ):
        PENDING_CONFIRM.pop(chat_id, None)
        return {
            "handled": True,
            "reply": "✅ Đã huỷ (hiện tại không có tiến trình nào đang chờ hoặc đã được huỷ an toàn).",
        }

    # 0.1 Check for updates: "cập nhật", "update", "kiểm tra bản mới", "có bản cập nhật không"
    if t_norm in ("cap nhat", "update", "kiem tra cap nhat", "kiem tra ban moi", "co ban moi khong", "update bot", "cap nhat bot"):
        import updater
        res = updater.check_for_updates()
        if res.get("has_update"):
            markup = {"inline_keyboard": [
                [{"text": f"🚀 Cập nhật lên v{res['latest_version']}", "callback_data": "do_update"}],
                [{"text": "❌ Để sau", "callback_data": "cancel_nl"}]
            ]}
            return {
                "handled": True,
                "reply": (
                    f"🎉 PHÁT HIỆN BẢN CẬP NHẬT MỚI: v{res['latest_version']}!\n\n"
                    f"📝 Chi tiết nâng cấp:\n{res.get('release_notes')}\n\n"
                    f"👉 Bấm nút bên dưới để cập nhật tự động:"
                ),
                "reply_markup": markup,
            }
        elif res.get("error"):
            return {"handled": True, "reply": f"⚠️ Không thể kiểm tra máy chủ cập nhật: {res['error']}"}
        else:
            return {"handled": True, "reply": f"✅ Bạn đang sử dụng phiên bản mới nhất (v{updater.CURRENT_VERSION})!"}

    # 0.2 View or Set Default Google Drive Upload Folder:
    # Commands: /setfolder, /thumuc, /folder, /getfolder
    # NL: "đặt thư mục mặc định là...", "thư mục upload là...", "thư mục mặc định hiện tại là gì"
    setfolder_cmd = re.match(r"^/(?:setfolder|thumuc|folder|set_upload_folder)(?:\s+(.+))?$", t, flags=re.IGNORECASE)
    getfolder_cmd = re.match(r"^/(?:getfolder|thumuchientai|currentfolder)$", t, flags=re.IGNORECASE)

    nl_get_folder = bool(re.search(
        r"^(?:xem\s+|kiểm\s+tra\s+)?(?:thư\s+mục|folder)\s+(?:mặc\s+định|upload|drive\s+mặc\s+định|drive|up\s+drive)(?:\s+(?:hiện\s+tại|là\s+gì|\?))*(?:\s+là\s+gì\??)?$",
        t,
        flags=re.IGNORECASE,
    ) or t_norm in ("thu muc mac dinh", "thu muc upload", "thu muc drive mac dinh", "xem thu muc mac dinh", "thu muc mac dinh la gi"))

    nl_set_folder = re.search(
        r"^(?:đặt|cài|chọn|thay\s+đổi|đổi)\s+(?:lại\s+)?(?:thư\s+mục|folder)\s+(?:mặc\s+định|upload|drive|up\s+drive)?\s*(?:là|thành|sang)?\s*(.+)$",
        t,
        flags=re.IGNORECASE,
    )
    if not nl_set_folder and not nl_get_folder:
        nl_set_folder = re.search(
            r"^(?:thư\s+mục|folder)\s+(?:mặc\s+định|upload|drive)\s+(?:là|thành|sang)\s*(.+)$",
            t,
            flags=re.IGNORECASE,
        )

    if setfolder_cmd:
        arg = (setfolder_cmd.group(1) or "").strip()
        if arg:
            res = set_default_gdrive_folder(arg)
            shared_str = " (Được chia sẻ với tôi)" if res.get("is_shared") else ""
            lines = [
                f"✅ ĐÃ ĐẶT THƯ MỤC UPLOAD MẶC ĐỊNH THÀNH CÔNG!\n",
                f"📁 Tên thư mục: {res['folder_name']}{shared_str}",
            ]
            if res.get("folder_url"):
                lines.append(f"🔗 Link Google Drive:\n{res['folder_url']}")
            if res.get("local_path"):
                lines.append(f"📂 Vị trí trên máy Mac:\n`{res['local_path']}`")
            lines.append(
                f"\n💡 Từ bây giờ, khi bạn nhắn: \"Up file X lên drive\", bot sẽ tự động tải thẳng vào thư mục này và lấy link gửi bạn!"
            )
            if res.get("is_shared"):
                lines.append(
                    f"\n👉 Lưu ý: Nếu đây là thư mục do chủ dự án chia sẻ cho bạn, hãy đảm bảo bạn đã bấm \"Thêm lối tắt vào Drive\" (Add shortcut to Drive) trên Google Drive web để file tự động chạy về Drive của chủ nhân nhé!"
                )
            return {"handled": True, "reply": "\n".join(lines)}
        else:
            getfolder_cmd = True

    if nl_get_folder or getfolder_cmd:
        info = get_default_gdrive_folder_info()
        shared_str = " (Được chia sẻ với tôi)" if info.get("is_shared") else ""
        lines = [
            f"📁 THƯ MỤC UPLOAD MẶC ĐỊNH HIỆN TẠI:\n",
            f"• Tên thư mục: {info['folder_name']}{shared_str}",
        ]
        if info.get("folder_url"):
            lines.append(f"• Link Google Drive:\n  {info['folder_url']}")
        if info.get("local_path"):
            lines.append(f"• Vị trí trên máy Mac:\n  `{info['local_path']}`")
        lines.append(
            f"\n👉 Để đổi thư mục khác, bạn có thể:\n"
            f"• Nhắn: `/setfolder <dán link hoặc gõ tên thư mục>`\n"
            f"• Hoặc nhắn: \"đổi thư mục mặc định thành <link hoặc tên>\""
        )
        return {"handled": True, "reply": "\n".join(lines)}

    if nl_set_folder and not re.search(r"^(?:up|upload|tải|chuyển|copy|xem|kiểm\s+tra)\b", t_lower):
        arg = nl_set_folder.group(1).strip()
        if re.search(r"^(?:gì|gì\s*\?|nào|nao|sao|đâu|dau)$", arg, flags=re.IGNORECASE):
            info = get_default_gdrive_folder_info()
            shared_str = " (Được chia sẻ với tôi)" if info.get("is_shared") else ""
            lines = [
                f"📁 THƯ MỤC UPLOAD MẶC ĐỊNH HIỆN TẠI:\n",
                f"• Tên thư mục: {info['folder_name']}{shared_str}",
            ]
            if info.get("folder_url"):
                lines.append(f"• Link Google Drive:\n  {info['folder_url']}")
            if info.get("local_path"):
                lines.append(f"• Vị trí trên máy Mac:\n  `{info['local_path']}`")
            lines.append(
                f"\n👉 Để đổi thư mục khác, bạn có thể:\n"
                f"• Nhắn: `/setfolder <dán link hoặc gõ tên thư mục>`\n"
                f"• Hoặc nhắn: \"đổi thư mục mặc định thành <link hoặc tên>\""
            )
            return {"handled": True, "reply": "\n".join(lines)}

        res = set_default_gdrive_folder(arg)
        shared_str = " (Được chia sẻ với tôi)" if res.get("is_shared") else ""
        lines = [
            f"✅ ĐÃ ĐẶT THƯ MỤC UPLOAD MẶC ĐỊNH THÀNH CÔNG!\n",
            f"📁 Tên thư mục: {res['folder_name']}{shared_str}",
        ]
        if res.get("folder_url"):
            lines.append(f"🔗 Link Google Drive:\n{res['folder_url']}")
        if res.get("local_path"):
            lines.append(f"📂 Vị trí trên máy Mac:\n`{res['local_path']}`")
        lines.append(
            f"\n💡 Từ bây giờ, khi bạn nhắn: \"Up file X lên drive\", bot sẽ tự động tải thẳng vào thư mục này và lấy link gửi bạn!"
        )
        if res.get("is_shared"):
            lines.append(
                f"\n👉 Lưu ý: Nếu đây là thư mục do chủ dự án chia sẻ cho bạn, hãy đảm bảo bạn đã bấm \"Thêm lối tắt vào Drive\" (Add shortcut to Drive) trên Google Drive web để file tự động chạy về Drive của chủ nhân nhé!"
            )
        return {"handled": True, "reply": "\n".join(lines)}

    # 0.4 Xem lịch: "ngày 25.10 tôi có bao nhiêu lịch", "hôm nay có lịch gì", "tuần này có lịch gì"
    q_res = _try_calendar_query(t)
    if q_res:
        return q_res

    # 0.5 Note lịch vào Google Calendar: "note lịch 1610 psc a Thăng" | "note 1610 psc a Thăng" | "1610 psc a Thăng"
    cal_res = _try_note_calendar(t)
    if cal_res:
        return cal_res

    # 0.6 Gửi link / upload gửi link qua Zalo
    zalo_res = _try_zalo_dispatch(t, chat_id)
    if zalo_res:
        return zalo_res

    # 1. Get Google Drive Share Link ("Lấy link file test.mp4 trong thư mục THIEN UNG PRODUCTION cho tôi", "xin link test.mp4")
    link_match = re.search(
        r"(?:lấy\s+link|xin\s+link|gửi\s+link|tạo\s+link|copy\s+link|link\s+google\s+drive|link\s+gg\s+drive|link\s+drive|cho\s+tôi\s+link|cho\s+xin\s+link)\s+(.+)$",
        t,
        flags=re.IGNORECASE,
    )
    if link_match and not re.search(r"^(?:up|upload|tải|đẩy)\b", t_lower):
        raw_query = link_match.group(1)
        return _execute_get_gdrive_link(raw_query)

    # 2. Check disk / drive free space
    if re.search(r"(ổ\s*(cứng|đĩa)|film\s*data).*?(trống|dung\s*lượng|bao\s*nhiêu)", t_lower) or t_lower in (
        "kiểm tra ổ đĩa",
        "kiểm tra ổ cứng",
        "xem ổ đĩa",
    ):
        drives = list_drives()
        lines = ["💽 THÔNG TIN DUNG LƯỢNG CÁC Ổ ĐĨA:\n"]
        for d in drives:
            lines.append(f"• {d['name']} ({d['mount']})\n  Trống: {d['free']} / Tổng: {d['total']} (Đã dùng: {d['used']})")
        return {"handled": True, "reply": "\n".join(lines)}

    # 3. Check folder/file size
    size_match = re.search(
        r"(?:kiểm\s+tra\s+(?:xem\s+)?|xem\s+|tính\s+)?(?:tổng\s+|dung\s+lượng\s+)?(.+?)\s+(?:nặng\s+bao\s+nhiêu|bao\s+nhiêu\s*(?:gb|mb|dung\s*lượng)|có\s+dung\s+lượng\s+bao\s+nhiêu)",
        t,
        flags=re.IGNORECASE,
    )
    if not size_match:
        size_match = re.search(
            r"(?:kiểm\s+tra\s+)?dung\s+lượng\s+(?:của\s+)?(.+)$",
            t,
            flags=re.IGNORECASE,
        )
    if size_match:
        raw_target = size_match.group(1)
        clean_target = clean_polite_phrases(raw_target)
        matches = find_best_matches(raw_target)
        gd_matches = query_gdrive_items(clean_target) if clean_target else []

        if not matches and not gd_matches:
            return {
                "handled": True,
                "reply": f"🔍 Tôi đã tìm trên máy Mac, ổ cứng ngoài và Google Drive nhưng không thấy thư mục/file nào khớp với '{clean_target}'.",
            }
        lines = ["📊 KẾT QUẢ KIỂM TRA DUNG LƯỢNG:\n"]
        for m in matches[:5]:
            sz_info = get_folder_size(m["path"])
            if sz_info.get("ok"):
                icon = "📁" if m["is_dir"] else "📄"
                if m["is_dir"]:
                    lines.append(
                        f"{icon} {m['name']}\n"
                        f"  • Đường dẫn: {m['path']}\n"
                        f"  • Tổng dung lượng: {sz_info['size_human']}\n"
                        f"  • Số lượng: {sz_info['file_count']} file, {sz_info['dir_count']} thư mục con\n"
                    )
                else:
                    lines.append(
                        f"{icon} {m['name']}\n"
                        f"  • Đường dẫn: {m['path']}\n"
                        f"  • Kích thước: {sz_info['size_human']}\n"
                    )
        if gd_matches:
            lines.append("☁️ TRÊN GOOGLE DRIVE:")
            for gm in gd_matches[:5]:
                icon = "📁" if gm.get("is_dir") else "📄"
                shared_tag = " [Được chia sẻ với tôi]" if gm.get("is_shared") else ""
                cnt_info = ""
                if gm.get("is_dir") and gm.get("file_count") is not None:
                    cnt_info = f" ({gm['file_count']} file, {gm.get('dir_count', 0)} thư mục con)"
                url_line = f"\n  • 🔗 {gm['url']}" if gm.get("url") else ""
                lines.append(
                    f"{icon} {gm['name']}{shared_tag}\n"
                    f"  • Nằm trong: {gm.get('parent_name', 'Google Drive')}\n"
                    f"  • Tổng dung lượng: {gm.get('size', '?')}{cnt_info}{url_line}\n"
                )
        if matches:
            LAST_CONTEXT.setdefault(chat_id, {})["last_item"] = matches[0]["name"]
        elif gd_matches:
            LAST_CONTEXT.setdefault(chat_id, {})["last_item"] = gd_matches[0]["name"]
        return {"handled": True, "reply": "\n".join(lines), "matches": matches[:5]}

    # 4. Upload to Google Drive (Default destination: THIEN UNG PRODUCTION!)
    # Supports: "up file test trong phim xong lên drive", "up 2710 lên drive và lấy link cho tôi"
    gdrive_match = re.search(
        r"(?:up|upload|tải|đẩy|chuyển|copy|sao\s+chép)(?:\s+lại)?\s+(.+?)\s+lên\s+(?:google\s*drive|gg\s*drive|drive)(?:\s*[,/-]?\s*(?:vào\s+|trong\s+|ở\s+)?(?:thư\s+mục|folder)\s+(.+))?.*$",
        t,
        flags=re.IGNORECASE,
    )
    if gdrive_match:
        raw_target = gdrive_match.group(1)
        raw_subfolder = gdrive_match.group(2) or ""
        subfolder = clean_polite_phrases(raw_subfolder) if raw_subfolder else get_default_gdrive_subfolder()
        if not subfolder:
            subfolder = get_default_gdrive_subfolder()
        LAST_CONTEXT[chat_id] = {"action": "gdrive", "subfolder": subfolder}
        return _prepare_gdrive_confirmation(raw_target, subfolder, chat_id)

    # 5. Move or Copy between folders/drives
    move_copy_match = re.search(
        r"(?:hãy\s+|giúp\s+tôi\s+|cho\s+tôi\s+)?(chuyển|di\s+chuyển|dời|đưa|mang|move|copy|sao\s+chép|chép)(?:\s+lại)?\s+(.+?)\s+(?:qua|sang|vào|vô|ra|về|đến|tới|xuống)(?:\s+lại|\s+ngoài|\s+trong|\s+bên)?\s+(.+)$",
        t,
        flags=re.IGNORECASE,
    )
    if move_copy_match:
        verb = move_copy_match.group(1).lower()
        raw_src = move_copy_match.group(2)
        raw_dst = move_copy_match.group(3)
        is_copy = verb in ("copy", "sao chép", "chép")
        LAST_CONTEXT[chat_id] = {"action": "move_copy", "raw_dst": raw_dst, "is_copy": is_copy}
        return _prepare_move_copy_confirmation(raw_src, raw_dst, is_copy, chat_id)

    # 6. Follow-up clarification
    if chat_id in LAST_CONTEXT and (
        t_lower.startswith("thư mục ")
        or t_lower.startswith("folder ")
        or t_lower.startswith("file ")
        or t_lower.startswith("không")
        or "trong " in t_lower
        or "ngoài " in t_lower
        or t_lower.endswith("ấy")
    ):
        ctx = LAST_CONTEXT[chat_id]
        if ctx.get("action") == "move_copy":
            return _prepare_move_copy_confirmation(t, ctx["raw_dst"], ctx["is_copy"], chat_id)
        elif ctx.get("action") == "gdrive":
            return _prepare_gdrive_confirmation(t, ctx.get("subfolder", get_default_gdrive_subfolder()), chat_id)

    # 7. Browse / View folder
    browse_match = re.search(
        r"(?:xem|mở|kiểm\s+tra|liệt\s+kê)\s+(?:trong\s+|ở\s+|ngoài\s+)?(.+?)(?:\s+có\s+những\s+gì|\s+có\s+gì|\s+gồm\s+những\s+gì)?$",
        t,
        flags=re.IGNORECASE,
    )
    if browse_match:
        raw_loc = browse_match.group(1)
        loc_path = resolve_destination(raw_loc)
        if loc_path and loc_path.exists():
            return {"handled": True, "open_dir": str(loc_path)}

    # 7.5 Check collaborator / shared with me queries
    # Ví dụ: "thợ gửi file flycam ofi", "bác thợ gửi cho tôi file flycam ofi", "file thợ gửi flycam ofi", "trong mục được chia sẻ flycam ofi"
    shared_match = re.search(
        r"^(?:(?:bác\s+|anh\s+)?(?:thợ|khách|người\s+khác|ai\s+đó)\s+(?:có\s+)?(?:gửi|share|chuyển)|(?:trong\s+|ở\s+)?(?:mục\s+)?(?:được\s+chia\s+sẻ|shared\s+with\s+me))\b",
        t,
        flags=re.IGNORECASE,
    )
    if shared_match:
        sr = _smart_search_reply(t)
        if sr.get("matches"):
            LAST_CONTEXT.setdefault(chat_id, {})["last_item"] = sr["matches"][0]["name"]
        return sr

    # 8. Search file/folder (smart search: ưu tiên SOURCE & FILM DATA & Google Drive)
    # Bỏ qua tìm kiếm ổ cứng nếu người dùng đang hỏi thông tin/kiến thức (vd: "tìm thông tin iphone 18 pro", "tìm hiểu...", "tìm cách...")
    is_knowledge_search = bool(re.match(
        r"^(?:tìm|tìm\s+kiếm|kiếm|kiểm\s+tra|check)\s+(?:thông\s+tin|hiểu|cách|ý\s+tưởng|giá|cấu\s+hình|thông\s+số|địa\s+chỉ|quán|tin\s+tức|bài\s+viết|caption|stt|status|lời\s+bài\s+hát)\b",
        t,
        flags=re.IGNORECASE,
    ))
    find_match = None if is_knowledge_search else re.search(r"^(?:tìm|tìm\s+kiếm|kiếm|kiểm\s+tra|check)\s+(.+)$", t, flags=re.IGNORECASE)
    if find_match:
        sr = _smart_search_reply(find_match.group(1))
        if sr.get("matches"):
            LAST_CONTEXT.setdefault(chat_id, {})["last_item"] = sr["matches"][0]["name"]
        if _from_llm or "Không tìm thấy mục nào" not in sr.get("reply", ""):
            return sr

    # 9. Trí tuệ nhân tạo Gemini tích hợp sẵn:
    #    - Dịch mọi ngữ cảnh nói tự nhiên / tiếng lóng / nối tiếp câu trước sang chuẩn lệnh máy (CMD:)
    #    - Hoặc trò chuyện tự nhiên "trên trời dưới đất" (CHAT:)
    if not _from_llm:
        # Nếu người dùng gõ trực tiếp mã dự án / tên file ngắn (vd: "psc hằng cần", "2510") không chứa từ khoá tán gẫu
        chat_indicators = {
            "chao", "hello", "hi", "alo", "oi", "ban", "em", "anh", "tao", "may", "ai",
            "sao", "gi", "nao", "khong", "ha", "nhi", "ke", "viet", "tu", "van", "hoi",
            "buon", "vui", "met", "chan", "dep", "xau", "thoi", "tiet", "an", "uong",
        }
        words_norm = [w for w in re.split(r"[^a-z0-9]+", t_norm) if w]
        if (
            1 <= len(words_norm) <= 4
            and not t.startswith("/")
            and not any(w in chat_indicators for w in words_norm)
            and "?" not in t
        ):
            sr = _smart_search_reply(t)
            if sr.get("handled") and "Không tìm thấy mục nào" not in sr.get("reply", ""):
                if sr.get("matches"):
                    LAST_CONTEXT.setdefault(chat_id, {})["last_item"] = sr["matches"][0]["name"]
                return sr

        try:
            import importlib
            import llm_intent
            saved_hist = dict(getattr(llm_intent, "CHAT_HISTORY", {}))
            importlib.reload(llm_intent)
            llm_intent.CHAT_HISTORY.update(saved_hist)
            last_item = LAST_CONTEXT.get(chat_id, {}).get("last_item")
            gem_res = llm_intent.process_with_gemini(
                t,
                chat_id=chat_id,
                last_item=last_item,
                default_folder=get_default_gdrive_subfolder(),
            )
        except Exception:
            gem_res = None

        if gem_res:
            if gem_res.get("mode") == "cmd":
                canonical = (gem_res.get("command") or "").strip()
                if canonical and canonical.lower() != t.strip().lower():
                    res = parse_and_execute_nl(canonical, chat_id, _from_llm=True)
                    if res.get("matches"):
                        LAST_CONTEXT.setdefault(chat_id, {})["last_item"] = res["matches"][0]["name"]
                    if res.get("handled") and res.get("reply") and not res["reply"].startswith("🤔"):
                        res["reply"] = f"🤖 Tôi hiểu ý bạn: \"{canonical}\"\n\n{res['reply']}"
                        return res
                    if res.get("open_dir"):
                        return res
            elif gem_res.get("mode") == "chat" and gem_res.get("reply"):
                return {"handled": True, "reply": gem_res["reply"]}

        # Dự phòng nếu không có mạng tới Gemini nhưng câu ngắn khớp tên file trên máy/Drive
        if 1 <= len(t.split()) <= 7 and not t.startswith("/"):
            sr = _smart_search_reply(t)
            if sr.get("handled") and "Không tìm thấy mục nào" not in sr.get("reply", ""):
                if sr.get("matches"):
                    LAST_CONTEXT.setdefault(chat_id, {})["last_item"] = sr["matches"][0]["name"]
                return sr

    return {
        "handled": True,
        "reply": (
            f"🤔 Tôi chưa hiểu rõ câu lệnh: \"{t}\"\n\n"
            f"💡 Bạn có thể nhắn tự nhiên hoặc trò chuyện bất kỳ chủ đề gì, ví dụ:\n"
            f"• \"Up file test trong phim xong lên drive\"\n"
            f"• \"Lấy link psc hằng cần gửi qua zalo cho Hoàng Dựng\"\n"
            f"• \"Note lịch 20/12 quay phóng sự cưới\"\n"
            f"• \"Kiểm tra file psc hằng cần nặng bao nhiêu\""
        ),
    }


_USER_GCAL_BIN = str(Path.home() / ".gemini" / "antigravity" / "bin" / "gcalendar")
GCALENDAR_BIN = (
    _USER_GCAL_BIN
    if os.path.exists(_USER_GCAL_BIN)
    else (shutil.which("gcalendar") or _USER_GCAL_BIN)
)
LOCAL_CALENDAR_PATH = Path(__file__).parent.resolve() / "local_calendar.json"


def _save_local_calendar_event(summary: str, start_iso: str, end_iso: str) -> None:
    try:
        events = []
        if LOCAL_CALENDAR_PATH.exists():
            events = json.loads(LOCAL_CALENDAR_PATH.read_text(encoding="utf-8"))
        events.append({
            "summary": summary,
            "start": {"date": start_iso},
            "end": {"date": end_iso},
            "status": "confirmed",
        })
        LOCAL_CALENDAR_PATH.write_text(json.dumps(events, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def _load_local_calendar_events(start_date, end_date) -> list[dict]:
    import datetime
    try:
        if not LOCAL_CALENDAR_PATH.exists():
            return []
        events = json.loads(LOCAL_CALENDAR_PATH.read_text(encoding="utf-8"))
        matched = []
        for ev in events:
            st_str = ev.get("start", {}).get("date")
            en_str = ev.get("end", {}).get("date")
            if not st_str:
                continue
            ev_s = datetime.date.fromisoformat(st_str[:10])
            ev_e = (datetime.date.fromisoformat(en_str[:10]) - datetime.timedelta(days=1)) if en_str else ev_s
            if ev_e < ev_s:
                ev_e = ev_s
            if not (ev_e < start_date or ev_s > end_date):
                matched.append(ev)
        return matched
    except Exception:
        return []


def _clean_calendar_content(raw_text: str) -> str:
    """Strip 'vào google calendar', 'vào lịch', etc. from calendar event summary."""
    s = raw_text.strip()
    patterns = [
        r"^(?:vào|lên|trên|trong|ở)\s+(?:google\s*calen(?:dar|der)|gg\s*calen(?:dar|der)|lịch\s*google|lịch)\s*",
        r"\s+(?:vào|lên|trên|trong|ở)\s+(?:google\s*calen(?:dar|der)|gg\s*calen(?:dar|der)|lịch\s*google|lịch)\s*$",
        r"^(?:google\s*calen(?:dar|der)|gg\s*calen(?:dar|der)|lịch\s*google)\s*",
    ]
    for _ in range(2):
        for pat in patterns:
            s = re.sub(pat, "", s, flags=re.IGNORECASE).strip()
    return s.strip(" -:,.")


def _build_gcal_template_url(summary: str, d_start, d_end_inclusive) -> str:
    import datetime
    import urllib.parse
    d_end_excl = d_end_inclusive + datetime.timedelta(days=1)
    dates_param = f"{d_start.strftime('%Y%m%d')}/{d_end_excl.strftime('%Y%m%d')}"
    params = urllib.parse.urlencode({
        "action": "TEMPLATE",
        "text": summary,
        "dates": dates_param,
        "details": "Được tạo tự động từ MacFileBot trên Telegram",
    })
    return f"https://calendar.google.com/calendar/render?{params}"


def _sync_to_macos_calendar(summary: str, d_start, d_end_inclusive) -> str | None:
    """
    Create an all-day event in macOS native Calendar.app (Lịch).
    If the user signed into their Google account in macOS Internet Accounts,
    Calendar.app automatically syncs this event 2-way with Google Calendar!
    Returns the calendar name if created, or None.
    """
    import subprocess
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
            set calList to every calendar whose writable is true
            repeat with c in calList
                set cName to name of c
                if cName contains "@" or cName contains "Google" or cName contains "Gmail" then
                    set targetCal to c
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
                return name of targetCal
            end if
        end tell
    end try
    return ""
    '''
    try:
        res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=8)
        cal_name = (res.stdout or "").strip()
        if res.returncode == 0 and cal_name:
            return cal_name
    except Exception:
        pass
    return None


def _try_note_calendar(t: str) -> dict | None:
    """
    Parse "[note|note lịch|ghi lịch|thêm lịch|lịch] DDMM nội dung" (hoặc DD/MM, hoặc ngày ÂM LỊCH)
    và tự động tạo all-day event trên Google Calendar / Apple Calendar / Nút 1 chạm Google Calendar.
    Hỗ trợ ÂM LỊCH: tự động quy đổi chính xác sang Dương lịch (kể cả trường hợp âm lịch
    năm nay rơi sang dương lịch năm sau).
    """
    import datetime
    import subprocess
    import lunar_calendar

    # 1. KIỂM TRA XEM CÓ PHẢI YÊU CẦU THEO ÂM LỊCH KHÔNG
    lunar_info = lunar_calendar.parse_lunar_in_text(t)
    if lunar_info and re.search(r"\b(note|ghi|thêm|them|tạo|tao|lịch|lich)\b", t, flags=re.IGNORECASE):
        d = lunar_info["solar_start"]
        d_end = lunar_info["solar_end"]
        l_label = lunar_info["lunar_label"]
        raw_clean = lunar_info["clean_content"]
        
        # Lọc bỏ các từ tiền tố "thêm lịch", "note lịch", "ghi lịch"...
        content = re.sub(
            r"^(?:(?:note|ghi|thêm|them|tạo|tao)\s+(?:lịch|lich)|note|lịch|lich)\s*",
            "",
            raw_clean,
            flags=re.IGNORECASE,
        ).strip()
        content = _clean_calendar_content(content)
        if not content:
            content = f"Lịch âm {l_label}"

        start = d.isoformat()
        end = (d_end + datetime.timedelta(days=1)).isoformat()
        event_summary = f"{content} (Âm lịch: {l_label})"
        when_solar = d.strftime('%d/%m/%Y') if d == d_end else f"{d.strftime('%d/%m/%Y')} → {d_end.strftime('%d/%m/%Y')}"
        year_note = " (Năm sau)" if d.year > datetime.date.today().year else ""
        gcal_url = _build_gcal_template_url(event_summary, d, d_end)
        gcal_markup = {"inline_keyboard": [[{"text": "📅 Lưu vào Google Calendar (1 chạm)", "url": gcal_url}]]}

        _save_local_calendar_event(event_summary, start, end)

        if Path(GCALENDAR_BIN).exists():
            try:
                res = subprocess.run(
                    [GCALENDAR_BIN, "mutate", "create", "--summary", event_summary, "--start", start, "--end", end, "--all-day"],
                    capture_output=True, text=True, timeout=60,
                )
                out = (res.stdout or "") + (res.stderr or "")
                if res.returncode == 0:
                    link_m = re.search(r"Link:\s*(\S+)", out)
                    reply = (
                        f"📅 ĐÃ NOTE LỊCH GOOGLE (TỰ ĐỘNG ĐỔI TỪ ÂM LỊCH):\n"
                        f"• 🌙 Âm lịch: {l_label}\n"
                        f"• ☀️ Dương lịch: {when_solar}{year_note}\n"
                        f"• 📝 Nội dung: {content}"
                    )
                    if link_m:
                        reply += f"\n🔗 {link_m.group(1)}"
                    return {"handled": True, "reply": reply}
            except Exception:
                pass

        mac_cal = _sync_to_macos_calendar(event_summary, d, d_end)
        mac_note = f"\n• 🖥 Đã tự động ghi vào ứng dụng Lịch ({mac_cal}) trên máy Mac." if mac_cal else ""
        return {
            "handled": True,
            "reply": (
                f"📅 ĐÃ LƯU LỊCH (TỰ ĐỘNG ĐỔI TỪ ÂM LỊCH):\n"
                f"• 🌙 Âm lịch: {l_label}\n"
                f"• ☀️ Dương lịch: {when_solar}{year_note}\n"
                f"• 📝 Nội dung: {content}{mac_note}\n\n"
                f"👇 Bấm nút bên dưới để mở & lưu thẳng vào Google Calendar:"
            ),
            "reply_markup": gcal_markup,
        }

    # 2. XỬ LÝ LỊCH DƯƠNG THÔNG THƯỜNG
    # Strip prefixes like "note lịch vào google calendar ngày ..."
    t_cleaned = re.sub(
        r"^(?:(?:note|ghi|thêm|them|tạo|tao)\s+(?:vào\s+|lên\s+)?(?:lịch\s+google|google\s*calen(?:dar|der)|gg\s*calen(?:dar|der)|lịch|lich)|(?:note|ghi|thêm|them|tạo|tao|lịch|lich))\s*(?:(?:vào|lên|trên)\s+(?:google\s*calen(?:dar|der)|gg\s*calen(?:dar|der)|lịch\s*google)\s*)?(?:ngày\s+)?",
        "",
        t.strip(),
        flags=re.IGNORECASE,
    ).strip()

    pm = re.match(
        r"^(\S+)\s+(.+)$",
        t_cleaned,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not pm or not re.match(r"^(?:note|ghi|thêm|them|tạo|tao|lịch|lich|\d)", t.strip(), flags=re.IGNORECASE):
        return None
    token, raw_content = pm.group(1), pm.group(2).strip()
    content = _clean_calendar_content(raw_content) or raw_content

    # Supported date tokens: 1610 | 16/10 | 20-22/1 | 20/1-22/1 | 2001-2201
    tm = (
        re.fullmatch(r"(\d{1,2})-(\d{1,2})[/.](\d{1,2})", token) and ("range", re.fullmatch(r"(\d{1,2})-(\d{1,2})[/.](\d{1,2})", token))
        or re.fullmatch(r"(\d{1,2})[/.](\d{1,2})-(\d{1,2})[/.](\d{1,2})", token) and ("cross", re.fullmatch(r"(\d{1,2})[/.](\d{1,2})-(\d{1,2})[/.](\d{1,2})", token))
        or re.fullmatch(r"(\d{2})(\d{2})-(\d{2})(\d{2})", token) and ("cross", re.fullmatch(r"(\d{2})(\d{2})-(\d{2})(\d{2})", token))
        or re.fullmatch(r"(\d{1,2})[/.](\d{1,2})", token) and ("single", re.fullmatch(r"(\d{1,2})[/.](\d{1,2})", token))
        or re.fullmatch(r"(\d{2})(\d{2})", token) and ("single", re.fullmatch(r"(\d{2})(\d{2})", token))
    )
    if not tm:
        return None
    kind, g = tm[0], tm[1]
    if kind == "range":
        d1, d2, m1 = int(g.group(1)), int(g.group(2)), int(g.group(3))
        day1, mon1, day2, mon2 = d1, m1, d2, m1
    elif kind == "cross":
        day1, mon1, day2, mon2 = (int(g.group(i)) for i in (1, 2, 3, 4))
    else:
        day1, mon1 = int(g.group(1)), int(g.group(2))
        day2, mon2 = day1, mon1

    today = datetime.date.today()

    def pick_year(mon: int) -> int:
        # Month already passed this year -> next year. Current month stays this year.
        return today.year if mon >= today.month else today.year + 1

    try:
        d = datetime.date(pick_year(mon1), mon1, day1)
        d_end = datetime.date(d.year, mon2, day2)
        if d_end < d:  # range crossing new year, e.g. 30/12-2/1
            d_end = datetime.date(d.year + 1, mon2, day2)
    except ValueError:
        return {"handled": True, "reply": f"❌ Ngày '{token}' không hợp lệ."}

    start = d.isoformat()
    end = (d_end + datetime.timedelta(days=1)).isoformat()
    when = d.strftime('%d/%m/%Y') if d == d_end else f"{d.strftime('%d/%m/%Y')} → {d_end.strftime('%d/%m/%Y')}"
    gcal_url = _build_gcal_template_url(content, d, d_end)
    gcal_markup = {"inline_keyboard": [[{"text": "📅 Lưu vào Google Calendar (1 chạm)", "url": gcal_url}]]}

    _save_local_calendar_event(content, start, end)

    if Path(GCALENDAR_BIN).exists():
        try:
            res = subprocess.run(
                [GCALENDAR_BIN, "mutate", "create", "--summary", content, "--start", start, "--end", end, "--all-day"],
                capture_output=True, text=True, timeout=60,
            )
            out = (res.stdout or "") + (res.stderr or "")
            if res.returncode == 0:
                link_m = re.search(r"Link:\s*(\S+)", out)
                reply = f"📅 ĐÃ NOTE LỊCH GOOGLE:\n• Ngày: {when}\n• Nội dung: {content}"
                if link_m:
                    reply += f"\n🔗 {link_m.group(1)}"
                return {"handled": True, "reply": reply}
        except Exception:
            pass

    mac_cal = _sync_to_macos_calendar(content, d, d_end)
    mac_note = f"\n• 🖥 Đã tự động ghi vào ứng dụng Lịch ({mac_cal}) trên máy Mac." if mac_cal else ""
    return {
        "handled": True,
        "reply": (
            f"📅 ĐÃ LƯU LỊCH:\n"
            f"• Ngày: {when}\n"
            f"• Nội dung: {content}{mac_note}\n\n"
            f"👇 Bấm nút bên dưới để mở & lưu thẳng vào Google Calendar:"
        ),
        "reply_markup": gcal_markup,
    }


def _fmt_event_time(ev: dict) -> tuple[str, str]:
    """Return (sort_key, label) for a Google Calendar event dict."""
    import datetime

    st, en = ev.get("start", {}), ev.get("end", {})
    if "dateTime" in st:
        s = datetime.datetime.fromisoformat(st["dateTime"])
        e = datetime.datetime.fromisoformat(en.get("dateTime", st["dateTime"]))
        if s.date() == e.date():
            label = f"🕘 {s:%d/%m %H:%M}–{e:%H:%M}"
        else:
            label = f"🕘 {s:%d/%m %H:%M} → {e:%d/%m %H:%M}"
        return s.strftime("%Y-%m-%d %H:%M"), label
    s = datetime.date.fromisoformat(st.get("date"))
    e = datetime.date.fromisoformat(en.get("date", st.get("date"))) - datetime.timedelta(days=1)
    if e <= s:
        label = f"📆 {s:%d/%m} (cả ngày)"
    else:
        label = f"📆 {s:%d/%m} → {e:%d/%m} (cả ngày)"
    return s.strftime("%Y-%m-%d 00:00"), label


def _parse_query_range(tl: str):
    """Extract (start_date, end_date_inclusive, label) from a Vietnamese calendar question."""
    import datetime
    import lunar_calendar

    today = datetime.date.today()
    td = datetime.timedelta

    # 1. Hỗ trợ tra cứu theo ÂM LỊCH (ví dụ: "25/11 âm có lịch gì", "ngày 15/8 âm lịch tôi có bận không")
    lunar_q = lunar_calendar.parse_lunar_in_text(tl)
    if lunar_q:
        s_start = lunar_q["solar_start"]
        s_end = lunar_q["solar_end"]
        l_label = lunar_q["lunar_label"]
        when_lbl = f"{s_start:%d/%m/%Y}" if s_start == s_end else f"{s_start:%d/%m/%Y}→{s_end:%d/%m/%Y}"
        year_note = " NĂM SAU" if s_start.year > today.year else ""
        return s_start, s_end, f"NGÀY {when_lbl}{year_note} (ÂM LỊCH: {l_label})"

    def qyear(day: int, month: int) -> int:
        try:
            cand = datetime.date(today.year, month, day)
        except ValueError:
            return today.year
        return today.year + 1 if cand < today - td(days=180) else today.year

    if "hôm nay" in tl or "ngày hôm nay" in tl:
        return today, today, "HÔM NAY"
    if "ngày mai" in tl or "hôm sau" in tl:
        d = today + td(days=1)
        return d, d, "NGÀY MAI"
    if "ngày mốt" in tl or "ngày kia" in tl:
        d = today + td(days=2)
        return d, d, "NGÀY MỐT"
    if "hôm qua" in tl:
        d = today - td(days=1)
        return d, d, "HÔM QUA"
    if re.search(r"tuần\s+(này|nay)", tl) or re.search(r"tuần\s+(sau|tới|tới)", tl):
        base = today - td(days=today.weekday())
        if re.search(r"tuần\s+(sau|tới)", tl):
            base += td(days=7)
        return base, base + td(days=6), "TUẦN NÀY" if base <= today <= base + td(days=6) else "TUẦN SAU"

    # Absolute: range "20-22/1"
    m = re.search(r"(\d{1,2})\s*-\s*(\d{1,2})\s*[/.]\s*(\d{1,2})(?!\d)", tl)
    if m:
        d1, d2, mo = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            y = qyear(d1, mo)
            return datetime.date(y, mo, d1), datetime.date(y, mo, d2), f"{d1:02d}→{d2:02d}/{mo:02d}/{y}"
        except ValueError:
            return None
    # "ngày 25 tháng 10 [năm 2026]" or "25.10" / "25/10" / "25-10" [/2026]
    m = re.search(r"(\d{1,2})\s*(?:tháng|[/.\-])\s*(\d{1,2})(?:\s*(?:năm|[/.\-])\s*(\d{4}))?(?!\d)", tl)
    if m:
        d1, mo = int(m.group(1)), int(m.group(2))
        y = int(m.group(3)) if m.group(3) else qyear(d1, mo)
        try:
            d = datetime.date(y, mo, d1)
            return d, d, f"NGÀY {d:%d/%m/%Y}"
        except ValueError:
            return None
    # "tháng 11" / "tháng này" / "tháng sau"
    if re.search(r"tháng\s+(này|nay)", tl):
        first = today.replace(day=1)
    elif re.search(r"tháng\s+(sau|tới)", tl):
        first = (today.replace(day=28) + td(days=4)).replace(day=1)
    else:
        mm = re.search(r"tháng\s+(\d{1,2})(?!\d)", tl)
        first = None
        if mm and 1 <= int(mm.group(1)) <= 12:
            mo = int(mm.group(1))
            first = datetime.date(qyear(1, mo), mo, 1)
    if first:
        last = ((first.replace(day=28) + td(days=4)).replace(day=1)) - td(days=1)
        return first, last, f"THÁNG {first:%m/%Y}"
    # "ngày 25" (tháng hiện tại)
    m = re.search(r"ngày\s+(\d{1,2})(?!\d)", tl)
    if m:
        try:
            d = today.replace(day=int(m.group(1)))
            return d, d, f"NGÀY {d:%d/%m/%Y}"
        except ValueError:
            return None
    return None


def _try_calendar_query(t: str) -> dict | None:
    """Answer questions like 'ngày 25.10 tôi có bao nhiêu lịch' by listing Google Calendar events."""
    import datetime
    import json as _json
    import subprocess

    tl = t.lower().strip()
    if re.match(r"^(note|ghi|thêm|them|tạo|tao)\b", tl):
        return None
    if not re.search(r"\b(lịch|lich)\b", tl):
        return None
    rng = _parse_query_range(tl)
    if not rng:
        return None
    asks = re.search(r"(bao nhiêu|mấy|những gì|có gì|gì không|lịch gì|nào|liệt kê|xem|kiểm tra|check|có lịch|không\??$)", tl)
    short = len(tl.split()) <= 4  # e.g. "lịch 25/10", "lịch hôm nay"
    if not (asks or short):
        return None

    start, end, label = rng
    s_iso = f"{start.isoformat()}T00:00:00+07:00"
    e_iso = f"{(end + datetime.timedelta(days=1)).isoformat()}T00:00:00+07:00"
    events = []
    if Path(GCALENDAR_BIN).exists():
        try:
            res = subprocess.run(
                [GCALENDAR_BIN, "readonly", "events", "--start", s_iso, "--end", e_iso, "--max", "100", "--json"],
                capture_output=True, text=True, timeout=60,
            )
            if res.returncode == 0:
                events = _json.loads(res.stdout or "[]")
        except Exception:
            events = []
    if not events:
        events = _load_local_calendar_events(start, end)

    events = [e for e in events if e.get("status") != "cancelled"]
    if not events:
        return {"handled": True, "reply": f"📅 {label}: bạn không có lịch nào."}

    items = []
    for ev in events:
        try:
            key, tlabel = _fmt_event_time(ev)
        except Exception:
            continue
        items.append((key, tlabel, ev.get("summary") or "(không tiêu đề)"))
    items.sort()
    lines = [f"📅 {label}: bạn có {len(items)} lịch\n"]
    for i, (_, tlabel, title) in enumerate(items, 1):
        lines.append(f"{i}. {tlabel}\n    {title}")
    return {"handled": True, "reply": "\n".join(lines)}


SEARCH_STOPWORDS = {
    "thu", "muc", "folder", "file", "tep", "cho", "toi", "giup", "xem", "o", "dau", "nao", "di", "nhe",
    "trong", "tren", "ngoai", "tai", "google", "drive", "gg"
}


def _search_priority_roots() -> list[tuple[Path, int, float]]:
    """(root, max_depth, time_budget_seconds) in priority order: SOURCE, FILM DATA, rest."""
    home = Path.home()
    roots: list[tuple[Path, int, float]] = []
    roots.append((home / "Desktop" / "SOURCE", 5, 8.0))
    roots.append((Path("/Volumes/FILM DATA"), 5, 15.0))
    volumes = Path("/Volumes")
    if volumes.exists():
        for v in sorted(volumes.iterdir()):
            if v.name != "FILM DATA" and not is_ignored_dir(v.name):
                roots.append((v, 4, 8.0))
    for sub in ("Desktop", "Downloads", "Documents", "Movies", "Pictures"):
        roots.append((home / sub, 4, 6.0))
    gd_root = find_google_drive_root(auto_launch=False)
    if gd_root and gd_root.exists():
        def_sub = resolve_subfolder_fuzzy(gd_root, get_default_gdrive_subfolder())
        if def_sub.exists():
            roots.append((def_sub, 2, 1.5))
        roots.append((gd_root, 1, 1.0))
    return roots


def _token_score(qt: str, name_tokens: list[str], name_norm: str) -> float:
    import difflib

    if qt in name_tokens:
        return 1.0
    if len(qt) >= 3 and any(nt.startswith(qt) or (len(nt) >= 3 and qt.startswith(nt)) for nt in name_tokens):
        return 0.85
    if len(qt) >= 3 and qt in name_norm:
        return 0.7
    if len(qt) >= 4:
        for nt in name_tokens:
            if len(nt) >= 3 and difflib.SequenceMatcher(None, qt, nt).ratio() >= 0.8:
                return 0.6
    return 0.0


def smart_search(raw_query: str, limit: int = 12) -> tuple[list[dict], list[str]]:
    """
    Search the whole machine. Priority: Desktop/SOURCE, then FILM DATA, then other drives/folders.
    Returns (results sorted by relevance, query_tokens). Each result has path/name/is_dir/score/exact.
    """
    import time as _time

    type_filter = detect_item_type_hint(raw_query)
    q = clean_polite_phrases(raw_query)
    q = re.sub(r"^(tìm|kiếm)\s+", "", q, flags=re.IGNORECASE)
    q_norm = strip_accents(q)
    q_tokens = [w for w in re.split(r"[^a-z0-9]+", q_norm) if w and w not in SEARCH_STOPWORDS]
    if not q_tokens:
        return [], []

    results: dict[str, dict] = {}
    seen_dirs: set[str] = set()
    priority_names = {"source", "film data"}

    def consider(path: Path, is_dir: bool, bonus: float) -> None:
        name = path.name
        if not is_dir and is_ignored_file(name):
            return
        name_norm = strip_accents(name if is_dir else path.stem)
        name_tokens = [w for w in re.split(r"[^a-z0-9]+", name_norm) if w]
        scores = [_token_score(qt, name_tokens, name_norm) for qt in q_tokens]
        avg = sum(scores) / len(q_tokens)
        matched = sum(1 for s in scores if s > 0)
        if len(q_tokens) == 1:
            if avg < 0.6:
                return
        elif avg < 0.45 or matched < max(1, len(q_tokens) // 2):
            return
        key = str(path)
        final = avg + bonus + (0.03 if is_dir else 0.0)
        prev = results.get(key)
        if prev is None or final > prev["score"]:
            results[key] = {
                "path": key, "name": name, "is_dir": is_dir,
                "score": final, "exact": avg >= 0.85 and matched == len(q_tokens),
            }

    for root, max_depth, budget in _search_priority_roots():
        if not root.exists():
            continue
        bonus = 0.15 if (root.name.lower() in priority_names) else 0.0
        t0 = _time.time()
        for dirpath, dirnames, filenames in os.walk(root, topdown=True):
            if _time.time() - t0 > budget:
                break
            real = os.path.realpath(dirpath)
            if real in seen_dirs:
                dirnames[:] = []
                continue
            seen_dirs.add(real)
            depth = len(Path(dirpath).relative_to(root).parts)
            if depth >= max_depth:
                dirnames[:] = []
            else:
                dirnames[:] = [d for d in dirnames if not is_ignored_dir(d)]
            if type_filter != "file":
                for d in dirnames:
                    consider(Path(dirpath) / d, True, bonus)
            if type_filter != "dir":
                for f in filenames:
                    consider(Path(dirpath) / f, False, bonus)

    ranked = sorted(results.values(), key=lambda r: (-r["score"], len(r["path"])))
    return ranked[:limit], q_tokens


def _smart_search_reply(raw_query: str) -> dict:
    q = raw_query.strip()
    is_shared_intent = False
    in_gdrive = bool(re.search(r"(?:trong|ở|trên|tại)\s+(?:google\s*drive|gg\s*drive|drive)\b", q, flags=re.IGNORECASE))

    # Detect explicit shared with me / collaborator query
    shared_patterns = [
        r"(?:trong|ở|tại)\s+(?:mục\s+|phần\s+)?(?:được\s+chia\s+sẻ(?:\s+với\s+tôi)?|shared\s+with\s+me)\b",
        r"(?:mục\s+|phần\s+)?(?:được\s+chia\s+sẻ(?:\s+với\s+tôi)?|shared\s+with\s+me)\b",
        r"(?:bác\s+|anh\s+)?(?:thợ|khách|ai\s+đó|người\s+khác)\s+(?:có\s+)?(?:gửi|share)(?:\s+cho\s+tôi|\s+qua)?\b",
    ]
    for p in shared_patterns:
        if re.search(p, q, flags=re.IGNORECASE):
            is_shared_intent = True
            in_gdrive = True
            q = re.sub(p, " ", q, flags=re.IGNORECASE)

    clean_q = re.sub(r"\s+(?:trong|ở|trên|tại)\s+(?:google\s*drive|gg\s*drive|drive)\b.*$", "", q, flags=re.IGNORECASE)
    clean_q = re.sub(r"\s+(?:trong|ở|trên|tại)\s+(?:film\s*data|ổ\s*film|ổ\s*cứng)\b.*$", "", clean_q, flags=re.IGNORECASE)
    clean_q = re.sub(r"\s+(?:ngoài|ở|trên|trong)\s+desktop\b.*$", "", clean_q, flags=re.IGNORECASE)
    clean_q = clean_polite_phrases(clean_q)

    # Strip prefixes like 'tìm', 'link', 'file', 'thư mục'
    prefixes = [
        r"^(?:tìm|tìm\s+kiếm|kiếm)\s+",
        r"^(?:lấy\s+link|xin\s+link|gửi\s+link|link|đường\s+link)\s+",
        r"^(?:thư\s+mục|folder|file|tập\s+tin|tệp|mục)\s+",
        r"^(?:cho\s+tôi|giúp\s+tôi|xem|kiểm\s+tra)\s+",
    ]
    for _ in range(4):
        for pat in prefixes:
            clean_q = re.sub(pat, "", clean_q, flags=re.IGNORECASE).strip()

    suffixes = [
        r"\s+(?:cho\s+tôi|giúp\s+tôi|với|nhé|nha|ạ|đi|luôn)$",
        r"\s+để\s+gửi\s+khách$",
        r"\s+gửi\s+khách$",
    ]
    for _ in range(3):
        for pat in suffixes:
            clean_q = re.sub(pat, "", clean_q, flags=re.IGNORECASE).strip()

    clean_q = re.sub(r"\s+", " ", clean_q).strip(" \"',.")
    shown_q = clean_q or raw_query

    gd_raw = query_gdrive_items(clean_q, prefer_shared=is_shared_intent) if clean_q else []
    gd_matches = [m for m in gd_raw if not m.get("name", "").startswith("._")]

    if is_shared_intent:
        shared_matches = [m for m in gd_matches if m.get("is_shared")]
        matches_to_show = shared_matches or gd_matches
        if not matches_to_show:
            return {
                "handled": True,
                "reply": (
                    f"🔍 Không tìm thấy mục nào khớp với '{shown_q}' trong mục 'Được chia sẻ với tôi'.\n\n"
                    f"💡 Mẹo: Trên Google Drive, khi thợ hoặc ai đó gửi link chia sẻ, bạn chỉ cần click mở link 1 lần thì mục đó mới xuất hiện trong 'Được chia sẻ với tôi' để bot quét được."
                ),
            }
        lines = [f"🤝 KẾT QUẢ TÌM TRONG MỤC 'ĐƯỢC CHIA SẺ VỚI TÔI' (Google Drive) cho '{shown_q}':\n"]
        for i, m in enumerate(matches_to_show[:8], 1):
            icon = "📁" if m.get("is_dir") else "📄"
            parent_str = f" (nằm trong {m['parent_name']})" if m.get("parent_name") else ""
            lines.append(f"{i}. {icon} {m['name']}{parent_str}\n    🔗 {m.get('url', 'Đang đồng bộ...')}")
        if len(matches_to_show) == 1 and matches_to_show[0].get("parent_url"):
            lines.append(f"\n📂 Link trực tiếp vào mục Được chia sẻ:\n{matches_to_show[0]['parent_url']}")
        return {"handled": True, "reply": "\n".join(lines)}

    if in_gdrive:
        if not gd_matches:
            local_results, _ = smart_search(clean_q, limit=5)
            if local_results:
                lines = [
                    f"🔍 Không tìm thấy '{shown_q}' trên Google Drive.",
                    f"\n💡 Nhưng tôi tìm thấy trên máy Mac / ổ cứng:"
                ]
                for r in local_results[:3]:
                    lines.append(f"• {'📁' if r['is_dir'] else '📄'} {r['name']} ({r['path']})")
                lines.append(f"\n👉 Bạn có thể nhắn: \"Up {local_results[0]['name']} lên drive\" để tải lên!")
                return {"handled": True, "reply": "\n".join(lines)}
            return {"handled": True, "reply": f"🔍 Không tìm thấy mục nào khớp với '{shown_q}' trên Google Drive của bạn (kể cả mục Được chia sẻ với tôi)."}

        lines = [f"☁️ KẾT QUẢ TÌM TRÊN GOOGLE DRIVE cho '{shown_q}':\n"]
        matches = []
        for i, m in enumerate(gd_matches[:8], 1):
            icon = "📁" if m.get("is_dir") else "📄"
            sz_str = f" — ⚖️ {m['size']}" if m.get("size") and m.get("size") != "-" else ""
            parent_str = f" (nằm trong {m['parent_name']})" if m.get("parent_name") else ""
            lines.append(f"{i}. {icon} {m['name']}{sz_str}{parent_str}\n    🔗 {m.get('url', 'Đang đồng bộ...')}")
            if m.get("path"):
                matches.append({"path": m["path"], "name": m["name"], "is_dir": bool(m.get("is_dir"))})
        return {"handled": True, "reply": "\n".join(lines), "matches": matches}

    results, q_tokens = smart_search(clean_q)

    if not results and not gd_matches:
        return {"handled": True, "reply": f"🔍 Không tìm thấy mục nào liên quan tới '{shown_q}' trên máy, ổ cứng hay Google Drive."}

    lines = [f"🔍 KẾT QUẢ TÌM KIẾM cho '{shown_q}':\n"]
    matches = []

    if gd_matches:
        lines.append("☁️ TRÊN GOOGLE DRIVE (bao gồm cả 'Được chia sẻ với tôi'):")
        for m in gd_matches[:5]:
            icon = "📁" if m.get("is_dir") else "📄"
            sz_str = f" — ⚖️ {m['size']}" if m.get("size") and m.get("size") != "-" else ""
            parent_str = f" ({m['parent_name']})" if m.get("parent_name") else ""
            lines.append(f"• {icon} {m['name']}{sz_str}{parent_str}\n  🔗 {m.get('url', '')}")
            if m.get("path") and len(matches) < 5:
                matches.append({"path": m["path"], "name": m["name"], "is_dir": bool(m.get("is_dir"))})
        lines.append("")

    if results:
        def short(p: str) -> str:
            home = str(Path.home())
            return p.replace(home, "~")

        exact = [r for r in results if r["exact"]]
        related = [r for r in results if not r["exact"]]

        lines.append("💽 TRÊN MÁY MAC & Ổ CỨNG (Ưu tiên SOURCE & FILM DATA):")
        n = 0
        if exact:
            for r in exact[:5]:
                n += 1
                matches.append(r)
                lines.append(f"{n}. {'📁' if r['is_dir'] else '📄'} {r['name']}\n    📍 {short(str(Path(r['path']).parent))}")
        if related and len(matches) < 5:
            lines.append("\n🔎 LIÊN QUAN:")
            for r in related[:5]:
                n += 1
                matches.append(r)
                lines.append(f"{n}. {'📁' if r['is_dir'] else '📄'} {r['name']}\n    📍 {short(str(Path(r['path']).parent))}")

    return {"handled": True, "reply": "\n".join(lines), "matches": matches}


def _execute_get_gdrive_link(raw_query: str) -> dict:
    item_name, parent_hint, _, _ = parse_source_specification(raw_query)
    if not item_name:
        return {"handled": True, "reply": "ℹ️ Bạn muốn lấy link của file hay thư mục nào trên Google Drive?"}

    is_shared_hint = bool(
        parent_hint and any(kw in strip_accents(parent_hint) for kw in ("duoc chia se", "chia se", "shared", "tho gui", "khach gui"))
    )
    matches = query_gdrive_items(item_name, parent_hint=parent_hint, prefer_shared=is_shared_hint)
    if not matches:
        def_folder = get_default_gdrive_subfolder()
        return {
            "handled": True,
            "reply": (
                f"🔍 Không tìm thấy file/thư mục '{item_name}' trên Google Drive của bạn (kể cả mục Được chia sẻ với tôi).\n"
                f"💡 Bạn có thể nhắn: \"Up file {item_name} lên drive\" để tải lên thư mục {def_folder} và nhận link ngay!"
            ),
        }

    lines = [f"🔗 LINK GOOGLE DRIVE ĐỂ GỬI KHÁCH:\n"]
    for m in matches[:5]:
        icon = "📁 Thư mục" if m["is_dir"] else "📄 File"
        shared_tag = " [Được chia sẻ với tôi]" if m.get("is_shared") else ""
        if m.get("is_synced") and m.get("url"):
            lines.append(
                f"• {icon}: {m['name']} ({m['size']}){shared_tag}\n"
                f"  Nằm trong: {m['parent_name']}\n"
                f"  👉 Link gửi khách:\n  {m['url']}\n"
            )
            if m.get("parent_url") and len(matches) == 1:
                lines.append(f"📂 Link cả thư mục {m['parent_name']}:\n{m['parent_url']}\n")
        else:
            lines.append(
                f"• {icon}: {m['name']} ({m['size']}){shared_tag}\n"
                f"  ⏳ Đang được Google Drive tải lên mây, vui lòng thử lấy link lại sau ít phút.\n"
            )

    return {"handled": True, "reply": "\n".join(lines)}

    return {"handled": True, "reply": "\n".join(lines)}


def _prepare_gdrive_confirmation(raw_target: str, subfolder: str, chat_id: int) -> dict:
    gdrive_root = find_google_drive_root(auto_launch=True)
    if not gdrive_root:
        return {
            "handled": True,
            "reply": "❌ Chưa tìm thấy thư mục Google Drive trên máy Mac. Bạn hãy mở ứng dụng Google Drive.app trước nhé!",
        }

    effective_subfolder = subfolder.strip() if subfolder and subfolder.strip() else get_default_gdrive_subfolder()
    dst_dir = resolve_subfolder_fuzzy(gdrive_root, effective_subfolder)
    try:
        dst_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    dst_display = f"Google Drive / {dst_dir.name}"

    item_name, parent_hint, root_hint, type_hint = parse_source_specification(raw_target)
    matches = find_best_matches(raw_target)

    if not matches and parent_hint:
        parent_dir = find_folder_by_name(parent_hint, root_hint)
        if parent_dir and parent_dir.exists():
            dir_info = list_directory(str(parent_dir), limit=15)
            candidates = [
                {"path": it["path"], "name": it["name"], "is_dir": it["is_dir"]}
                for it in dir_info.get("items", [])
            ]
            if candidates:
                PENDING_CONFIRM[chat_id] = {
                    "candidates": candidates,
                    "dst_path": str(dst_dir),
                    "is_copy": True,
                    "is_gdrive": True,
                }
                lines = [
                    f"📂 Đã mở thư mục `{parent_dir.name}` ({parent_dir}), nhưng không thấy file tên '{item_name}'.\n"
                    f"☁️ Đích mặc định: `{dst_display}` (Tự động lấy link sau khi Up)\n\n"
                    f"👉 Bạn muốn upload file nào trong `{parent_dir.name}` lên `{dst_dir.name}`? (Bấm chọn bên dưới hoặc nhắn số thứ tự):"
                ]
                for i, c in enumerate(candidates[:10], 1):
                    sz = get_folder_size(c["path"]).get("size_human", "?")
                    lines.append(f"{i}. {'📁' if c['is_dir'] else '📄'} {c['name']} ({sz})")
                return {
                    "handled": True,
                    "reply": "\n".join(lines),
                    "matches": candidates[:10],
                    "quick_move_dst": str(dst_dir),
                    "quick_is_copy": True,
                    "quick_is_gdrive": True,
                }

    if not matches:
        return {
            "handled": True,
            "reply": f"🔍 Không tìm thấy file/thư mục nào khớp với '{item_name}' để tải lên Google Drive.",
        }

    candidates = matches[:8]
    PENDING_CONFIRM[chat_id] = {
        "candidates": candidates,
        "dst_path": str(dst_dir),
        "is_copy": True,
        "is_gdrive": True,
    }
    if candidates:
        LAST_CONTEXT.setdefault(chat_id, {})["last_item"] = candidates[0]["name"]

    if len(candidates) == 1:
        c = candidates[0]
        sz = get_folder_size(c["path"]).get("size_human", "?")
        reply = (
            f"☁️ XÁC NHẬN UPLOAD LÊN GOOGLE DRIVE & LẤY LINK:\n\n"
            f"• Nguồn tìm thấy: {'📁' if c['is_dir'] else '📄'} {c['name']} ({sz})\n"
            f"• Đường dẫn: {c['path']}\n"
            f"• Thư mục đích mặc định: {dst_display}\n\n"
            f"👉 Bấm nút xác nhận bên dưới (hoặc nhắn \"ok\") để tải lên và nhận Link gửi khách:"
        )
    else:
        lines = [
            f"🔍 Tìm thấy {len(candidates)} mục khớp với '{item_name}'.\n"
            f"☁️ Thư mục đích mặc định: `{dst_display}` (Tự động gửi link sau khi Up)\n\n"
            f"👉 Bạn muốn upload mục nào lên `{dst_dir.name}`? (Bấm trực tiếp nút bên dưới hoặc nhắn số 1, 2...):\n"
        ]
        for i, c in enumerate(candidates, 1):
            sz = get_folder_size(c["path"]).get("size_human", "?")
            lines.append(f"{i}. {'📁' if c['is_dir'] else '📄'} {c['name']} ({sz})\n   `{c['path']}`")
        reply = "\n".join(lines)

    return {
        "handled": True,
        "reply": reply,
        "matches": candidates,
        "quick_move_dst": str(dst_dir),
        "quick_is_copy": True,
        "quick_is_gdrive": True,
    }


def _prepare_move_copy_confirmation(raw_src: str, raw_dst: str, is_copy: bool, chat_id: int) -> dict:
    dst_path = resolve_destination(raw_dst)
    if not dst_path or not dst_path.exists():
        dst_clean = clean_polite_phrases(raw_dst)
        return {
            "handled": True,
            "reply": f"❌ Không tìm thấy ổ đĩa hoặc thư mục đích '{dst_clean}'.",
        }

    matches = find_best_matches(raw_src, exclude_root=str(dst_path))
    src_name, _, _, _ = parse_source_specification(raw_src)

    if not matches:
        already_in_dst = find_best_matches(raw_src)
        if already_in_dst:
            paths_str = "\n".join(f"• {m['path']}" for m in already_in_dst[:5])
            return {
                "handled": True,
                "reply": (
                    f"ℹ️ Không tìm thấy '{src_name}' ở ngoài, nhưng phát hiện đã có sẵn trong `{dst_path}`:\n"
                    f"{paths_str}"
                ),
            }
        return {
            "handled": True,
            "reply": f"🔍 Tôi đã tìm trên máy Mac và ổ cứng ngoài nhưng không thấy thư mục/file nào khớp với '{src_name}'.",
        }

    candidates = matches[:8]
    PENDING_CONFIRM[chat_id] = {
        "candidates": candidates,
        "dst_path": str(dst_path),
        "is_copy": is_copy,
        "is_gdrive": False,
    }
    if candidates:
        LAST_CONTEXT.setdefault(chat_id, {})["last_item"] = candidates[0]["name"]

    act_vn = "SAO CHÉP (COPY)" if is_copy else "CHUYỂN (DỜI)"
    if len(candidates) == 1:
        c = candidates[0]
        sz_info = get_folder_size(c["path"])
        sz_str = sz_info.get("size_human", "?") if sz_info.get("ok") else "?"
        cnt_str = f" ({sz_info['file_count']} file)" if sz_info.get("ok") and c["is_dir"] else ""
        reply = (
            f"📦 XÁC NHẬN {act_vn} QUA {dst_path.name}:\n\n"
            f"• Mục tìm thấy: {'📁' if c['is_dir'] else '📄'} {c['name']}\n"
            f"• Đường dẫn nguồn: {c['path']}\n"
            f"• Tổng dung lượng: {sz_str}{cnt_str}\n"
            f"• Đích đến mặc định: {dst_path}\n\n"
            f"👉 Bấm nút [✅ Xác nhận] bên dưới (hoặc nhắn \"ok\") để thực hiện ngay:"
        )
    else:
        lines = [
            f"🔍 Tìm thấy {len(candidates)} mục khớp với '{src_name}'.\n"
            f"💽 Đích đến mặc định: `{dst_path}`\n\n"
            f"👉 Bạn muốn {act_vn.lower()} mục nào qua `{dst_path.name}`? (Bấm chọn bên dưới hoặc nhắn số 1, 2...):\n"
        ]
        for i, c in enumerate(candidates, 1):
            sz_info = get_folder_size(c["path"])
            sz_str = sz_info.get("size_human", "?") if sz_info.get("ok") else "?"
            lines.append(f"{i}. {'📁' if c['is_dir'] else '📄'} {c['name']} ({sz_str})\n   `{c['path']}`")
        reply = "\n".join(lines)

    return {
        "handled": True,
        "reply": reply,
        "matches": candidates,
        "quick_move_dst": str(dst_path),
        "quick_is_copy": is_copy,
        "quick_is_gdrive": False,
    }
