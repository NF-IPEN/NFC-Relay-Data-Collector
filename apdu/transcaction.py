# -*- coding: utf-8 -*-
"""
apdu/transaction.py
===================
EMV 거래 한 번의 전체 흐름:
  SELECT PPSE -> AID 추출 -> SELECT AID -> PDOL 추출
  -> GPO -> AFL 추출 -> READ RECORD (여러 개)

[원본 위치] ppse_measure_channal.py 의
  - 섹션 13 (Dynamic EMV transaction): run_emv_transaction

★ 2번 담당(APDU & Timing)의 핵심 산출물 ★
이게 "측정할 내용물"이다. 채널(3번)도, 분석(4번)도 결국 이 흐름을 재고 분석한다.

핵심: 이 함수는 send_fn 만 받는다.
  send_fn(apdu: bytes) -> bytes
  그 send_fn 이 실물이든/mock이든/소켓이든 신경쓰지 않는다.
  => 그래서 baseline(직결)과 relay(소켓)가 이 함수 하나를 공유한다.
"""

from __future__ import annotations
from typing import Callable, List

from core.tlv import hex_to_bytes, bytes_to_hex, find_first_tag
from core.timing import ApduTiming, ApduTimer
from apdu.commands import (
    SELECT_PPSE,
    build_select_aid, build_gpo, build_read_record,
    extract_aid_candidates, extract_aids_from_ppse,
    parse_dol, build_pdol_data,
    parse_afl_from_gpo,
)


def run_emv_transaction(
    send_fn: Callable[[bytes], bytes],
    timer: ApduTimer,
) -> List[ApduTiming]:

    timings = []

    # ---- STEP 1: SELECT PPSE ----
    name, apdu_hex = SELECT_PPSE
    rec = timer.measure_call(name, hex_to_bytes(apdu_hex), send_fn)
    timings.append(rec)

    if not rec.success:
        raise RuntimeError(f"SELECT PPSE 실패: SW={rec.sw1sw2}")

    response = hex_to_bytes(rec.resp_hex)
    candidates = extract_aid_candidates(response)

    if not candidates:
        aids = extract_aids_from_ppse(response)
        if not aids:
            raise RuntimeError("PPSE 응답에서 AID(4F)를 찾지 못했습니다.")
        selected_aid = aids[0]
        print(f"[PPSE] AID={selected_aid}")
    else:
        selected = candidates[0]
        selected_aid = selected["aid"]
        print(
            f"[PPSE] AID={selected_aid} "
            f"LABEL={selected['label']} PRIORITY={selected['priority']}"
        )

    # ---- STEP 2: SELECT AID ----
    name, apdu_hex = build_select_aid(hex_to_bytes(selected_aid))
    rec = timer.measure_call(name, hex_to_bytes(apdu_hex), send_fn)
    timings.append(rec)

    if not rec.success:
        raise RuntimeError(f"SELECT AID 실패: AID={selected_aid}, SW={rec.sw1sw2}")

    aid_response = hex_to_bytes(rec.resp_hex)
    pdol = find_first_tag(aid_response, 0x9F38)

    if pdol:
        print(f"[AID] PDOL={bytes_to_hex(pdol)}")
        for tag, length in parse_dol(pdol):
            print(f"    TAG={tag:02X} LEN={length}")
        pdol_data = build_pdol_data(pdol)
    else:
        print("[AID] PDOL 없음 -> 83 00 사용")
        pdol_data = b""

    # ---- STEP 3: GPO ----
    name, apdu_hex = build_gpo(pdol_data)
    rec = timer.measure_call(name, hex_to_bytes(apdu_hex), send_fn)
    timings.append(rec)
    print(f"[GPO] SW={rec.sw1sw2} RTT={rec.rtt_ms:.2f}ms")

    if not rec.success:
        raise RuntimeError(f"GPO 실패: SW={rec.sw1sw2}")

    # ---- STEP 4: AFL 파싱 ----
    gpo_response = hex_to_bytes(rec.resp_hex)
    afl_records = parse_afl_from_gpo(gpo_response)

    if not afl_records:
        print("[GPO] AFL(94)을 찾지 못했습니다.")
        return timings

    print(f"[AFL] READ RECORD {len(afl_records)}개")
    for item in afl_records:
        print(f"    SFI={item['sfi']} RECORD={item['record']}")

    # ---- STEP 5: READ RECORD ----
    for item in afl_records:
        name, apdu_hex = build_read_record(item["sfi"], item["record"])
        rec = timer.measure_call(name, hex_to_bytes(apdu_hex), send_fn)
        timings.append(rec)
        if not rec.success:
            print(f"[READ RECORD] {name} 실패 SW={rec.sw1sw2}")

    return timings
