# -*- coding: utf-8 -*-
"""
core/timing.py
==============
RTT 측정의 "약속(인터페이스)"이 모여 있는 파일. 팀 전체가 공유한다.

[원본 위치] ppse_measure_channal.py 의
  - 섹션 8  (Timing data structures): ApduTiming, SessionResult
  - 섹션 9  (APDU timer): ApduTimer
  - 섹션 10 (Result saving): save_session_csv, save_session_summary_json

여기서 정한 CSV 칸 이름(CSV_FIELDS)이 곧 팀 표준이다.
  -> analysis/ 담당은 이 칸 이름만 알면 그래프를 짤 수 있다.
  -> 실제 측정값이 없어도, 이 구조만 있으면 가짜 CSV로 개발 가능.

핵심 약속:
  send_fn(apdu: bytes) -> bytes
  "APDU 바이트를 넣으면 응답 바이트가 나온다."
  이 send_fn 안이 실물 카드든/mock이든/소켓이든 상관없다.
"""

from __future__ import annotations

import csv
import json
import statistics
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Callable, List

from core.tlv import bytes_to_hex


# ---------------------------------------------------------------------
# 측정 결과를 담는 그릇  (원본 섹션 8)
# ---------------------------------------------------------------------

@dataclass
class ApduTiming:
    """APDU 한 개의 측정 결과."""
    seq: int
    apdu_name: str
    apdu_hex: str
    rtt_ms: float
    resp_hex: str
    sw1sw2: str
    success: bool
    channel: str
    session_id: str
    t_sent_epoch: float


@dataclass
class SessionResult:
    """한 번의 EMV 거래(여러 APDU) 전체 결과."""
    session_id: str
    channel: str
    timings: List[ApduTiming] = field(default_factory=list)

    @property
    def total_ms(self) -> float:
        return sum(t.rtt_ms for t in self.timings)

    @property
    def success(self) -> bool:
        if not self.timings:
            return False
        return all(t.success for t in self.timings)

    @property
    def per_command_stats(self):
        vals = [t.rtt_ms for t in self.timings]
        if not vals:
            return {}

        mean = statistics.mean(vals)
        std = statistics.pstdev(vals) if len(vals) > 1 else 0.0

        diffs = [abs(vals[i] - vals[i - 1]) for i in range(1, len(vals))]
        jitter = (
            statistics.pstdev(diffs) if len(diffs) > 1
            else (diffs[0] if diffs else 0.0)
        )

        return {
            "n": len(vals),
            "mean_ms": mean,
            "std_ms": std,
            "jitter_ms": jitter,
            "min_ms": min(vals),
            "max_ms": max(vals),
        }


# ---------------------------------------------------------------------
# 타이머  (원본 섹션 9)
# ---------------------------------------------------------------------

class ApduTimer:
    """
    APDU 하나를 보내고 RTT를 재는 도구.
    measure_call 에 send_fn 을 넘겨주면, 그 send_fn 이 무엇이든
    (실물/mock/소켓) 동일한 방식으로 시간을 잰다.
    """

    def __init__(self, channel: str, session_id: str):
        self.channel = channel
        self.session_id = session_id
        self.seq = 0

    def measure_call(
        self,
        apdu_name: str,
        apdu_bytes: bytes,
        send_fn: Callable[[bytes], bytes],
    ) -> ApduTiming:
        self.seq += 1
        t_epoch = time.time()

        t0 = time.perf_counter()
        resp = send_fn(apdu_bytes)          # <-- 여기서 실제 왕복 발생
        t1 = time.perf_counter()

        rtt_ms = (t1 - t0) * 1000.0

        # send_fn 응답 형태를 두 가지 모두 허용한다:
        #  (A) reader.transmit 방식: (response_body, sw1, sw2) 튜플
        #  (B) 소켓 채널 방식:        response_bytes (뒤 2바이트가 SW)
        if isinstance(resp, tuple) and len(resp) == 3:
            body, sw1, sw2 = resp
            body_bytes = bytes(body)
            sw1sw2 = f"{sw1:02X}{sw2:02X}"
            resp_hex = bytes_to_hex(body_bytes) + sw1sw2
        else:
            resp_bytes = bytes(resp)
            resp_hex = bytes_to_hex(resp_bytes)
            sw1sw2 = resp_hex[-4:] if len(resp_hex) >= 4 else ""

        success = (sw1sw2 == "9000")

        return ApduTiming(
            seq=self.seq,
            apdu_name=apdu_name,
            apdu_hex=bytes_to_hex(apdu_bytes),
            rtt_ms=rtt_ms,
            resp_hex=resp_hex,
            sw1sw2=sw1sw2,
            success=success,
            channel=self.channel,
            session_id=self.session_id,
            t_sent_epoch=t_epoch,
        )


# ---------------------------------------------------------------------
# 저장  (원본 섹션 10)
# ---------------------------------------------------------------------

# ★ 팀 표준 CSV 칸 이름 ★  analysis/ 는 이 이름을 그대로 읽는다.
CSV_FIELDS = [
    "seq",
    "apdu_name",
    "apdu_hex",
    "rtt_ms",
    "resp_hex",
    "sw1sw2",
    "success",
    "channel",
    "session_id",
    "t_sent_epoch",
]


def save_session_csv(session: SessionResult, out_dir: str = "data") -> Path:
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    fname = out_path / f"{session.channel}_{session.session_id}.csv"

    with open(fname, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for timing in session.timings:
            writer.writerow(asdict(timing))

    return fname


def save_session_summary_json(session: SessionResult, out_dir: str = "data") -> Path:
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    fname = out_path / f"{session.channel}_{session.session_id}_summary.json"

    summary = {
        "session_id": session.session_id,
        "channel": session.channel,
        "total_ms": session.total_ms,
        "success": session.success,
        "stats": session.per_command_stats,
        "n_commands": len(session.timings),
    }

    with open(fname, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    return fname