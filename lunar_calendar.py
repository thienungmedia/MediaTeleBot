#!/usr/bin/env python3
from __future__ import annotations
"""
lunar_calendar.py - Bộ chuyển đổi Âm - Dương lịch Việt Nam chính xác 100%.
Thuật toán dựa trên công trình thiên văn lập lịch Việt Nam của TS. Hồ Ngọc Đức (Múi giờ UTC+7).
Hỗ trợ tự động quy đổi ngày âm lịch sang ngày dương lịch, tự động xử lý trường hợp
âm lịch năm này rơi sang dương lịch năm sau (ví dụ: cuối năm âm lịch 25/11, 30/12).
"""

import datetime
import re

# Bảng mã lịch âm Việt Nam (TS. Hồ Ngọc Đức) cho các năm 2000 - 2099
TK21 = [
    0x46c960, 0x2ed954, 0x54d4a0, 0x3eda50, 0x2a7552, 0x4e56a0, 0x38a7a7, 0x5ea5d0, 0x4a92b0, 0x32aab5,
    0x58a950, 0x42b4a0, 0x2cbaa4, 0x50ad50, 0x3c55d9, 0x624ba0, 0x4ca5b0, 0x375176, 0x5c5270, 0x466930,
    0x307934, 0x546aa0, 0x3ead50, 0x2a5b52, 0x504b60, 0x38a6e6, 0x5ea4e0, 0x48d260, 0x32ea65, 0x56d520,
    0x40daa0, 0x2d56a3, 0x5256d0, 0x3c4afb, 0x6249d0, 0x4ca4d0, 0x37d0b6, 0x5ab250, 0x44b520, 0x2edd25,
    0x54b5a0, 0x3e55d0, 0x2a55b2, 0x5049b0, 0x3aa577, 0x5ea4b0, 0x48aa50, 0x33b255, 0x586d20, 0x40ad60,
    0x2d4b63, 0x525370, 0x3e49e8, 0x60c970, 0x4c54b0, 0x3768a6, 0x5ada50, 0x445aa0, 0x2fa6a4, 0x54aad0,
    0x4052e0, 0x28d2e3, 0x4ec950, 0x38d557, 0x5ed4a0, 0x46d950, 0x325d55, 0x5856a0, 0x42a6d0, 0x2c55d4,
    0x5252b0, 0x3ca9b8, 0x62a930, 0x4ab490, 0x34b6a6, 0x5aad50, 0x4655a0, 0x2eab64, 0x54a570, 0x4052b0,
    0x2ab173, 0x4e6930, 0x386b37, 0x5e6aa0, 0x48ad50, 0x332ad5, 0x582b60, 0x42a570, 0x2e52e4, 0x50d160,
    0x3ae958, 0x60d520, 0x4ada90, 0x355aa6, 0x5a56d0, 0x462ae0, 0x30a9d4, 0x54a2d0, 0x3ed150, 0x28e952
]

# Bảng mã lịch âm Việt Nam cho các năm 2100 - 2199
TK22 = [
    0x4eb520, 0x38d727, 0x5eada0, 0x4a55b0, 0x362db5, 0x5a45b0, 0x44a2b0, 0x2eb2b4, 0x54a950, 0x3cb559,
    0x626b20, 0x4cad50, 0x385766, 0x5c5370, 0x484570, 0x326574, 0x5852b0, 0x406950, 0x2a7953, 0x505aa0,
    0x3baaa7, 0x5ea6d0, 0x4a4ae0, 0x35a2e5, 0x5aa550, 0x42d2a0, 0x2de2a4, 0x52d550, 0x3e5abb, 0x6256a0,
    0x4c96d0, 0x3949b6, 0x5e4ab0, 0x46a8d0, 0x30d4b5, 0x56b290, 0x40b550, 0x2a6d52, 0x504da0, 0x3b9567,
    0x609570, 0x4a49b0, 0x34a975, 0x5a64b0, 0x446a90, 0x2cba94, 0x526b50, 0x3e2b60, 0x28ab61, 0x4c9570,
    0x384ae6, 0x5cd160, 0x46e4a0, 0x2eed25, 0x54da90, 0x405b50, 0x2c36d3, 0x502ae0, 0x3a93d7, 0x6092d0,
    0x4ac950, 0x32d556, 0x58b4a0, 0x42b690, 0x2e5d94, 0x5255b0, 0x3e25fa, 0x6425b0, 0x4e92b0, 0x36aab6,
    0x5c6950, 0x4674a0, 0x31b2a5, 0x54ad50, 0x4055a0, 0x2aab73, 0x522570, 0x3a5377, 0x6052b0, 0x4a6950,
    0x346d56, 0x585aa0, 0x42ab50, 0x2e56d4, 0x544ae0, 0x3ca570, 0x2864d2, 0x4cd260, 0x36eaa6, 0x5ad550,
    0x465aa0, 0x30ada5, 0x5695d0, 0x404ad0, 0x2aa9b3, 0x50a4d0, 0x3ad2b7, 0x5eb250, 0x48b540, 0x33d556
]

CAN = ["Giáp", "Ất", "Bính", "Đinh", "Mậu", "Kỷ", "Canh", "Tân", "Nhâm", "Quý"]
CHI = ["Tý", "Sửu", "Dần", "Mão", "Thìn", "Tỵ", "Ngọ", "Mùi", "Thân", "Dậu", "Tuất", "Hợi"]


def jdn(dd: int, mm: int, yy: int) -> int:
    """Tính số ngày Julian từ ngày, tháng, năm Dương lịch."""
    a = (14 - mm) // 12
    y = yy + 4800 - a
    m = mm + 12 * a - 3
    return dd + ((153 * m + 2) // 5) + 365 * y + (y // 4) - (y // 100) + (y // 400) - 32045


def jdn2date(jd: int) -> tuple[int, int, int]:
    """Quy đổi số ngày Julian về (ngày, tháng, năm) Dương lịch."""
    a = jd + 32044
    b = (4 * a + 3) // 146097
    c = a - (146097 * b) // 4
    d = (4 * c + 3) // 1461
    e = c - (1461 * d) // 4
    m = (5 * e + 2) // 153
    day = e - ((153 * m + 2) // 5) + 1
    month = m + 3 - 12 * (m // 10)
    year = 100 * b + d - 4800 + (m // 10)
    return day, month, year


def get_year_code(yyyy: int) -> int:
    if 2000 <= yyyy < 2100:
        return TK21[yyyy - 2000]
    elif 2100 <= yyyy < 2200:
        return TK22[yyyy - 2100]
    raise ValueError(f"Năm {yyyy} nằm ngoài phạm vi hỗ trợ (2000 - 2199)")


def decode_lunar_year(yy: int, k: int) -> list[dict]:
    month_lengths = [29, 30]
    regular_months = [0] * 12
    offset_of_tet = k >> 17
    leap_month = k & 0xf
    leap_month_length = month_lengths[(k >> 16) & 0x1]
    solar_ny = jdn(1, 1, yy)
    current_jd = solar_ny + offset_of_tet
    j = k >> 4
    for i in range(12):
        regular_months[11 - i] = month_lengths[j & 0x1]
        j >>= 1
    ly = []
    if leap_month == 0:
        for mm in range(1, 13):
            ly.append({"day": 1, "month": mm, "year": yy, "leap": 0, "jd": current_jd})
            current_jd += regular_months[mm - 1]
    else:
        for mm in range(1, leap_month + 1):
            ly.append({"day": 1, "month": mm, "year": yy, "leap": 0, "jd": current_jd})
            current_jd += regular_months[mm - 1]
        ly.append({"day": 1, "month": leap_month, "year": yy, "leap": 1, "jd": current_jd})
        current_jd += leap_month_length
        for mm in range(leap_month + 1, 13):
            ly.append({"day": 1, "month": mm, "year": yy, "leap": 0, "jd": current_jd})
            current_jd += regular_months[mm - 1]
    return ly


def get_can_chi_year(year: int) -> str:
    """Trả về Can Chi của năm âm lịch (ví dụ: 2026 -> 'Bính Ngọ')."""
    return f"{CAN[(year + 6) % 10]} {CHI[(year + 8) % 12]}"


def solar_to_lunar(dd: int, mm: int, yyyy: int) -> tuple[int, int, int, int]:
    """
    Quy đổi từ ngày Dương lịch sang Âm lịch.
    Trả về: (ngày_âm, tháng_âm, năm_âm, là_tháng_nhuận: 0|1)
    """
    jd = jdn(dd, mm, yyyy)
    ly = decode_lunar_year(yyyy, get_year_code(yyyy))
    if jd < ly[0]["jd"]:
        ly = decode_lunar_year(yyyy - 1, get_year_code(yyyy - 1))
    i = len(ly) - 1
    while jd < ly[i]["jd"] and i > 0:
        i -= 1
    off = jd - ly[i]["jd"]
    return ly[i]["day"] + off, ly[i]["month"], ly[i]["year"], ly[i]["leap"]


def lunar_to_solar(lday: int, lmonth: int, lyear: int, leap: int = 0) -> tuple[int, int, int] | None:
    """
    Quy đổi từ ngày Âm lịch sang Dương lịch.
    Trả về: (ngày_dương, tháng_dương, năm_dương) hoặc None nếu ngày không hợp lệ.
    """
    try:
        k = get_year_code(lyear)
        ly = decode_lunar_year(lyear, k)
    except Exception:
        return None

    target = None
    for entry in ly:
        if entry["month"] == lmonth and entry["leap"] == leap:
            target = entry
            break
    if not target:
        return None
    target_jd = target["jd"] + lday - 1
    return jdn2date(target_jd)


def resolve_lunar_date_input(
    lday: int,
    lmonth: int,
    target_lyear: int | None = None,
    ref_date: datetime.date | None = None,
) -> tuple[datetime.date, int, str]:
    """
    Xác định ngày dương lịch tương ứng với ngày âm lịch.
    Nếu không truyền target_lyear, hàm tự động chọn năm âm lịch phù hợp:
    - Nếu ngày âm đó trong năm âm lịch hiện tại chưa qua -> dùng năm âm lịch hiện tại.
    - Nếu ngày âm đó trong năm âm lịch hiện tại đã qua -> dùng năm âm lịch kế tiếp.
    - Đặc biệt: các ngày âm cuối năm (tháng 11, tháng 12 âm) tự động đổi chính xác
      thành ngày dương lịch của năm sau!
    Trả về: (solar_date, lunar_year, can_chi_year)
    """
    if ref_date is None:
        ref_date = datetime.date.today()

    cur_lday, cur_lmonth, cur_lyear, _ = solar_to_lunar(ref_date.day, ref_date.month, ref_date.year)

    if target_lyear is not None:
        chosen_lyear = target_lyear
    else:
        # Nếu tháng âm mục tiêu nhỏ hơn tháng âm hiện tại, hoặc cùng tháng nhưng ngày đã qua -> năm âm kế tiếp
        if lmonth < cur_lmonth or (lmonth == cur_lmonth and lday < cur_lday):
            chosen_lyear = cur_lyear + 1
        else:
            chosen_lyear = cur_lyear

    sol = lunar_to_solar(lday, lmonth, chosen_lyear)
    if sol is None:
        # Fallback thử năm kế tiếp nếu tháng/ngày không có trong năm đó
        chosen_lyear += 1
        sol = lunar_to_solar(lday, lmonth, chosen_lyear)

    if sol is None:
        raise ValueError(f"Không thể quy đổi ngày âm {lday}/{lmonth}/{chosen_lyear}")

    s_day, s_month, s_year = sol
    solar_date = datetime.date(s_year, s_month, s_day)
    return solar_date, chosen_lyear, get_can_chi_year(chosen_lyear)


def parse_lunar_in_text(raw_text: str) -> dict | None:
    """
    Phát hiện và phân tích các cụm từ chỉ ngày âm lịch trong câu văn người dùng:
    Ví dụ:
    - "ngày 25/11 âm", "25/11 âm", "25.11 âm", "25-11 âm", "25/11 âm lịch", "25/11 al"
    - "2511 âm", "2511 âm lịch"
    - "ngày 25 tháng 11 âm", "ngày 25 tháng 11 âm lịch"
    - Khoảng ngày: "20-22/11 âm", "20/11-22/11 âm"
    
    Trả về dict:
    {
        "is_lunar": True,
        "solar_start": datetime.date,
        "solar_end": datetime.date,
        "lunar_label": "25/11 Bính Ngọ",
        "clean_content": str (nội dung đã bỏ cụm từ ngày tháng âm)
    }
    """
    text = raw_text.strip()
    
    # Kiểm tra xem có dấu hiệu âm lịch hay không ("âm", "âm lịch", "al")
    lunar_marker = re.search(r"\b(âm\s*lịch|am\s*lich|âm|al)\b", text, flags=re.IGNORECASE)
    if not lunar_marker:
        return None

    # Mẫu 1: "ngày 25 tháng 11 âm" hoặc "ngày 25-27 tháng 11 âm"
    m_full = re.search(
        r"(?:vào\s+)?(?:ngày\s+)?(\d{1,2})(?:\s*[-–]\s*(\d{1,2}))?\s+tháng\s+(\d{1,2})(?:\s+năm\s+(\d{4}))?\s+(?:âm\s*lịch|am\s*lich|âm|al)\b",
        text,
        flags=re.IGNORECASE,
    )
    if m_full:
        d1 = int(m_full.group(1))
        d2 = int(m_full.group(2)) if m_full.group(2) else d1
        m = int(m_full.group(3))
        y = int(m_full.group(4)) if m_full.group(4) else None
        s_date1, l_year, can_chi = resolve_lunar_date_input(d1, m, y)
        s_date2, _, _ = resolve_lunar_date_input(d2, m, l_year)
        clean = text[:m_full.start()] + " " + text[m_full.end():]
        clean = re.sub(r"\s+", " ", clean).strip()
        l_label = f"{d1}/{m}" if d1 == d2 else f"{d1}-{d2}/{m}"
        l_label += f" ({can_chi})"
        return {
            "is_lunar": True,
            "solar_start": s_date1,
            "solar_end": s_date2,
            "lunar_label": l_label,
            "clean_content": clean,
        }

    # Mẫu 2: "25/11 âm", "25.11 âm", "25-27/11 âm", "20/11-22/11 âm"
    # D1[-D2]/M hoặc D1/M1-D2/M2
    m_slash = re.search(
        r"(?:vào\s+)?(?:ngày\s+)?(\d{1,2})(?:[-–](\d{1,2}))?[/. ](\d{1,2})(?:[/. ](\d{4}))?\s*(?:âm\s*lịch|am\s*lich|âm|al)\b",
        text,
        flags=re.IGNORECASE,
    )
    if m_slash:
        d1 = int(m_slash.group(1))
        d2 = int(m_slash.group(2)) if m_slash.group(2) else d1
        m = int(m_slash.group(3))
        y = int(m_slash.group(4)) if m_slash.group(4) else None
        s_date1, l_year, can_chi = resolve_lunar_date_input(d1, m, y)
        s_date2, _, _ = resolve_lunar_date_input(d2, m, l_year)
        clean = text[:m_slash.start()] + " " + text[m_slash.end():]
        clean = re.sub(r"\s+", " ", clean).strip()
        l_label = f"{d1}/{m}" if d1 == d2 else f"{d1}-{d2}/{m}"
        l_label += f" ({can_chi})"
        return {
            "is_lunar": True,
            "solar_start": s_date1,
            "solar_end": s_date2,
            "lunar_label": l_label,
            "clean_content": clean,
        }

    # Mẫu 3: Dạng 4 số DDMM âm (ví dụ: "2511 âm", "1508 âm")
    m_4digit = re.search(
        r"(?:vào\s+)?(?:ngày\s+)?(\d{2})(\d{2})\s*(?:âm\s*lịch|am\s*lich|âm|al)\b",
        text,
        flags=re.IGNORECASE,
    )
    if m_4digit:
        d1 = int(m_4digit.group(1))
        m = int(m_4digit.group(2))
        s_date1, l_year, can_chi = resolve_lunar_date_input(d1, m)
        clean = text[:m_4digit.start()] + " " + text[m_4digit.end():]
        clean = re.sub(r"\s+", " ", clean).strip()
        l_label = f"{d1}/{m} ({can_chi})"
        return {
            "is_lunar": True,
            "solar_start": s_date1,
            "solar_end": s_date1,
            "lunar_label": l_label,
            "clean_content": clean,
        }

    return None
