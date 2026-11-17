# -*- coding: utf-8 -*-
"""
apdu/commands.py
================
EMV 결제에 쓰는 APDU 명령을 만들고, 카드 응답을 파싱한다.

[원본 위치] ppse_measure_channal.py 의
  - 섹션 4 (EMV APDU): SELECT_PPSE, build_select_aid, build_gpo, build_read_record
  - 섹션 5 (PPSE/AID parsing): extract_aids_from_ppse, extract_aid_candidates
  - 섹션 6 (PDOL): parse_dol, generate_pdol_value, build_pdol_data
  - 섹션 7 (AFL): parse_afl_from_gpo

★ 2번 담당(APDU & Timing)이 주로 손볼 파일 ★
이 파일은 "무엇을 보낼지"만 담당한다. "어떻게 보낼지(채널)"는 모른다.
"""

from __future__ import annotations
import random
import time
from typing import List, Optional, Tuple

from core.tlv import (
    bytes_to_hex, bcd_encode,
    parse_tlv, find_all_tag, find_first_tag,
)


# =====================================================================
# APDU 조립  (원본 섹션 4)
# =====================================================================

#1. 결제 애플리케이션 탐색
SELECT_PPSE = (
    "SELECT_PPSE",
    "00A404000E" "325041592E5359532E4444463031" "00",
)


def build_select_aid(aid: bytes) -> Tuple[str, str]:
    if not aid:
        raise ValueError("AID가 비어 있습니다.")
    if len(aid) > 255:
        raise ValueError("AID 길이가 너무 깁니다.")

    #2. 전달받은 AID로 애플리케이션 선택 명령 구성
    apdu = bytes.fromhex("00A40400") + bytes([len(aid)]) + aid + bytes.fromhex("00")
    return ("SELECT_AID", bytes_to_hex(apdu))


#3. PDOL 데이터를 포함한 GPO 명령 생성
def build_gpo(pdol_data: bytes = b"") -> Tuple[str, str]:
    command_data = bytes([0x83, len(pdol_data)]) + pdol_data
    apdu = (
        bytes.fromhex("80A80000")
        + bytes([len(command_data)])
        + command_data
        + bytes.fromhex("00")
    )
    return ("GPO", bytes_to_hex(apdu))

#4. SFI와 레코드 번호로 읽기 명령 생성
def build_read_record(sfi: int, record: int) -> Tuple[str, str]:
    if not 1 <= sfi <= 30:
        raise ValueError(f"잘못된 SFI: {sfi}")
    if not 1 <= record <= 255:
        raise ValueError(f"잘못된 record 번호: {record}")

    p2 = (sfi << 3) | 0x04
    apdu = bytes([0x00, 0xB2, record, p2, 0x00])
    return (f"READ_RECORD_SFI{sfi}_REC{record}", bytes_to_hex(apdu))


# =====================================================================
# PPSE / AID 파싱  (원본 섹션 5)
# =====================================================================

def extract_aids_from_ppse(response: bytes) -> List[str]:
    """PPSE 응답에서 4F(AID) 추출."""
    if len(response) < 2:
        return []

    data = response[:-2]
    sw = response[-2:]

    if sw != b"\x90\x00":
        raise RuntimeError(f"SELECT PPSE 실패: SW={bytes_to_hex(sw)}")

    aids = []
    for aid in find_all_tag(data, 0x4F):
        aid_hex = bytes_to_hex(aid)
        if aid_hex not in aids:
            aids.append(aid_hex)
    return aids


def extract_aid_candidates(response: bytes) -> List[dict]:
    """PPSE 응답에서 AID + Label(50) + Priority(87)를 함께 추출."""
    result = []

    def walk(buf: bytes):
        for tag, value in parse_tlv(buf):
            if tag == 0x61:
                aid = find_first_tag(value, 0x4F)
                label = find_first_tag(value, 0x50)
                priority = find_first_tag(value, 0x87)

                if aid is not None:
                    result.append({
                        "aid": bytes_to_hex(aid),
                        "label": (
                            label.decode("ascii", errors="replace")
                            if label else ""
                        ),
                        "priority": priority[0] if priority else 255,
                    })

            tag_bytes = tag.to_bytes(max(1, (tag.bit_length() + 7) // 8), "big")
            if tag_bytes[0] & 0x20:
                walk(value)

    walk(response)

    unique = {}
    for item in result:
        unique[item["aid"]] = item

    return sorted(unique.values(), key=lambda x: x["priority"])


# =====================================================================
# PDOL  (원본 섹션 6)
# =====================================================================

def parse_dol(dol: bytes) -> List[Tuple[int, int]]:
    """DOL 파서. 반환: [(tag, length), ...]"""
    result = []
    i = 0
    while i < len(dol):
        first = dol[i]
        i += 1
        tag = first

        if (first & 0x1F) == 0x1F:
            while i < len(dol):
                b = dol[i]
                i += 1
                tag = (tag << 8) | b
                if not (b & 0x80):
                    break

        if i >= len(dol):
            break

        length = dol[i]
        i += 1
        result.append((tag, length))

    return result


def generate_pdol_value(tag: int, length: int) -> bytes:
    """
    실험용 terminal data 생성.
    완전한 EMV 단말 구현이 목적이 아니라, 카드가 요구하는 PDOL 길이를
    채워 GPO가 통과되게 하는 실험용 값이다. 주요 tag만 현실적으로 채운다.
    """
    now = time.localtime()

    if tag == 0x9F02 and length == 6:            # Amount Authorised
        return bcd_encode("000000000000", 6)
    if tag == 0x9F03 and length == 6:            # Amount Other
        return bcd_encode("000000000000", 6)
    if tag == 0x9F1A and length == 2:            # Terminal Country Code (Korea 410)
        return bytes.fromhex("0410")
    if tag == 0x5F2A and length == 2:            # Transaction Currency (KRW 410)
        return bytes.fromhex("0410")
    if tag == 0x9A and length == 3:              # Transaction Date YYMMDD
        return bytes([
            int(f"{now.tm_year % 100:02d}", 16),
            int(f"{now.tm_mon:02d}", 16),
            int(f"{now.tm_mday:02d}", 16),
        ])
    if tag == 0x9C and length == 1:              # Transaction Type (purchase)
        return b"\x00"
    if tag == 0x9F35 and length == 1:            # Terminal Type
        return b"\x22"
    if tag == 0x9F33 and length == 3:            # Terminal Capabilities
        return bytes.fromhex("E0F8C8")
    if tag == 0x9F40 and length == 5:            # Additional Terminal Capabilities
        return bytes.fromhex("F000F0A001")
    if tag == 0x9B and length == 2:              # Transaction Status Info
        return b"\x00\x00"
    if tag == 0x95 and length == 5:              # TVR
        return b"\x00" * 5
    if tag == 0x9F66 and length == 4:            # TTQ (Visa contactless)
        return bytes.fromhex("26000000")
    if tag == 0x9F37 and length == 4:            # Unpredictable Number
        return random.randbytes(4)

    return b"\x00" * length


def build_pdol_data(pdol: Optional[bytes]) -> bytes:
    """PDOL 정의를 받아 실제 GPO command data 생성."""
    if not pdol:
        return b""

    fields = parse_dol(pdol)
    result = bytearray()
    for tag, length in fields:
        result.extend(generate_pdol_value(tag, length))
    return bytes(result)


# =====================================================================
# AFL  (원본 섹션 7)
# =====================================================================

def parse_afl_from_gpo(response: bytes) -> List[dict]:
    """GPO 응답에서 AFL(94)을 찾아 READ RECORD 대상 목록으로 변환."""
    if len(response) < 2:
        return []

    sw = response[-2:]
    data = response[:-2]
    if sw != b"\x90\x00":
        return []

    afl_values = find_all_tag(data, 0x94)
    if not afl_values:
        return []

    afl = afl_values[0]
    if len(afl) % 4 != 0:
        raise ValueError(f"AFL 길이가 4의 배수가 아님: {len(afl)}")

    records = []
    for i in range(0, len(afl), 4):
        sfi = afl[i] >> 3
        first_record = afl[i + 1]
        last_record = afl[i + 2]
        offline_auth_records = afl[i + 3]

        for record in range(first_record, last_record + 1):
            records.append({
                "sfi": sfi,
                "record": record,
                "offline_auth_records": offline_auth_records,
            })

    return records
