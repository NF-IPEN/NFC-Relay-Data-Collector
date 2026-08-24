"""
tlv.py — EMV APDU 응답(TLV: Tag-Length-Value) 파싱 유틸리티
------------------------------------------------------------
PPSE SELECT, AID SELECT, GPO 응답은 모두 TLV 구조로 인코딩되어 있음.
필요한 태그(AID, AFL 등)만 뽑아내기 위한 최소 기능 파서.

참고: EMV Book 3 / ISO 7816-4 TLV 인코딩 규칙을 따름.
- Tag: 1바이트(0x1F 미만 하위 5비트≠11111) 또는 2바이트 이상(멀티바이트 태그)
- Length: 1바이트(0x80 미만) 또는 0x81/0x82로 시작하는 확장 길이
- Value: Length 만큼의 바이트

이 프로젝트에서 실제로 필요한 태그만 다루므로, 범용 TLV 파서보다는
"필요한 만큼만" 구현한 실용적 버전임.
"""

from typing import List, Tuple, Dict


def _parse_tag(data: List[int], pos: int) -> Tuple[int, int]:
    """태그를 파싱. (태그값, 다음 위치) 반환."""
    tag = data[pos]
    start = pos
    pos += 1
    # 하위 5비트가 모두 1이면(0x1F) 태그가 다음 바이트로 이어짐 (멀티바이트 태그)
    if (tag & 0x1F) == 0x1F:
        while pos < len(data):
            b = data[pos]
            pos += 1
            if (b & 0x80) == 0:
                break
    tag_bytes = data[start:pos]
    tag_value = int.from_bytes(bytes(tag_bytes), byteorder="big")
    return tag_value, pos


def _parse_length(data: List[int], pos: int) -> Tuple[int, int]:
    """길이를 파싱. (길이값, 다음 위치) 반환."""
    first = data[pos]
    pos += 1
    if first < 0x80:
        return first, pos
    num_bytes = first & 0x7F
    length = 0
    for _ in range(num_bytes):
        length = (length << 8) | data[pos]
        pos += 1
    return length, pos


def parse_tlv(data: List[int]) -> Dict[int, List[int]]:
    """
    TLV 바이트 리스트를 파싱해 {태그: 값} 딕셔너리로 반환.
    중첩된 템플릿(constructed TLV, 예: 0x6F, 0xA5, 0x70, 0x77)은 재귀적으로 펼쳐서
    최종적으로 모든 leaf 태그를 한 딕셔너리에 평탄화(flatten)해서 담음.

    주의: 실전 EMV 파서는 계층 구조를 유지해야 하지만,
    이 실험에서는 AID(태그 4F)와 AFL(태그 94)만 뽑아내면 되므로 평탄화 방식으로 충분함.
    """
    result: Dict[int, List[int]] = {}
    pos = 0
    while pos < len(data):
        tag, pos = _parse_tag(data, pos)
        if pos >= len(data):
            break
        length, pos = _parse_length(data, pos)
        value = data[pos:pos + length]
        pos += length

        # constructed TLV 여부: 태그의 첫 바이트 중 0x20 비트가 1이면 constructed
        first_tag_byte = (tag >> (8 * (_tag_byte_len(tag) - 1))) & 0xFF
        is_constructed = bool(first_tag_byte & 0x20)

        if is_constructed:
            nested = parse_tlv(value)
            result.update(nested)
        else:
            result[tag] = value

    return result


def _tag_byte_len(tag_value: int) -> int:
    """정수로 저장된 태그값의 원래 바이트 길이를 추정 (1~3바이트 지원)."""
    if tag_value <= 0xFF:
        return 1
    elif tag_value <= 0xFFFF:
        return 2
    else:
        return 3


def find_all_aids(ppse_response: List[int]) -> List[List[int]]:
    """
    PPSE(2PAY.SYS.DDF01) SELECT 응답에서 카드가 지원하는 모든 AID 목록을 추출.
    구조: FCI Template(6F) > FCI Proprietary Template(A5) > FCI Directory(BF0C)
          > Application Template(61)[반복] > AID(4F)
    이 구조는 중첩이 깊어 평탄화 파서로는 AID가 여러 개일 때 구분이 안 되므로,
    Application Template(0x61) 단위로 먼저 나눈 뒤 각각 파싱함.
    """
    aids = []
    pos = 0
    # 최상위 레벨 태그들을 순회하며 0x61(Application Template)을 직접 찾음
    def _walk(data):
        p = 0
        while p < len(data):
            tag, p2 = _parse_tag(data, p)
            length, p3 = _parse_length(data, p2)
            value = data[p3:p3 + length]
            p = p3 + length
            if tag == 0x61:
                parsed = parse_tlv(value)
                if 0x4F in parsed:
                    aids.append(parsed[0x4F])
            elif tag in (0x6F, 0xA5, 0xBF0C):
                _walk(value)
    _walk(ppse_response)
    return aids


def find_afl(gpo_response: List[int]) -> List[int]:
    """
    GPO(GET PROCESSING OPTIONS) 응답에서 AFL(Application File Locator, 태그 94)을 추출.
    응답 포맷 1(태그 80) 또는 포맷 2(템플릿 77) 두 가지가 있음.
    """
    parsed = parse_tlv(gpo_response)
    return parsed.get(0x94, [])


def afl_to_records(afl: List[int]) -> List[Tuple[int, int]]:
    """
    AFL 바이트를 (SFI, record_number) 튜플 리스트로 변환.
    AFL은 4바이트씩 한 그룹: [SFI<<3|기타, 시작레코드, 끝레코드, 인증에필요한레코드수]
    """
    records = []
    for i in range(0, len(afl), 4):
        group = afl[i:i + 4]
        if len(group) < 4:
            continue
        sfi = group[0] >> 3
        start_rec = group[1]
        end_rec = group[2]
        for rec_num in range(start_rec, end_rec + 1):
            records.append((sfi, rec_num))
    return records