from __future__ import annotations
from typing import List, Optional, Tuple


# ---------------------------------------------------------------------
# Basic helpers  (원본 섹션 2)
# ---------------------------------------------------------------------

def hex_to_bytes(h: str) -> bytes:
    return bytes.fromhex(h.replace(" ", "").replace("\n", ""))


def bytes_to_hex(data: bytes) -> str:
    return data.hex().upper()


def bcd_encode(value: str, length: int) -> bytes:
    """
    숫자 문자열을 BCD로 변환.
    예: "000001" -> 00 00 01
    """
    value = value.zfill(length * 2)
    if len(value) > length * 2:
        value = value[-length * 2:]

    result = bytearray()
    for i in range(0, len(value), 2):
        result.append(int(value[i:i + 2], 16))
    return bytes(result)


# ---------------------------------------------------------------------
# BER-TLV parser  (원본 섹션 3)
# ---------------------------------------------------------------------

def parse_tlv(data: bytes) -> List[Tuple[int, bytes]]:
    """
    간단한 BER-TLV parser.
    반환: [(tag, value), ...]
    """
    result = []
    i = 0

    while i < len(data):
        # --- TAG ---
        first = data[i]
        i += 1
        tag = first

        if (first & 0x1F) == 0x1F:
            while i < len(data):
                b = data[i]
                i += 1
                tag = (tag << 8) | b
                if not (b & 0x80):
                    break

        # --- LENGTH ---
        if i >= len(data):
            break

        length_byte = data[i]
        i += 1

        if length_byte & 0x80:
            n = length_byte & 0x7F
            if n == 0:
                # indefinite length는 이 실험에서 사용하지 않음
                break
            if i + n > len(data):
                break
            length = int.from_bytes(data[i:i + n], "big")
            i += n
        else:
            length = length_byte

        # --- VALUE ---
        if i + length > len(data):
            break

        value = data[i:i + length]
        i += length
        result.append((tag, value))

    return result


def find_all_tag(data: bytes, target_tag: int) -> List[bytes]:
    """중첩된 constructed TLV까지 재귀적으로 탐색."""
    found = []

    def walk(buf: bytes):
        for tag, value in parse_tlv(buf):
            if tag == target_tag:
                found.append(value)

            first_tag_byte = tag.to_bytes(
                max(1, (tag.bit_length() + 7) // 8), "big"
            )[0]

            if first_tag_byte & 0x20:  # constructed
                walk(value)

    walk(data)
    return found


def find_first_tag(data: bytes, target_tag: int) -> Optional[bytes]:
    values = find_all_tag(data, target_tag)
    return values[0] if values else None
