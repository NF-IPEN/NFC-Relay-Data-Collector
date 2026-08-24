# -*- coding: utf-8 -*-
"""
core/timing.py
==============

APDU RTT 측정 및 측정 결과 저장을 담당하는 공통 모듈.

[원본 위치] ppse_measure_channal.py 의
  - 섹션 8  (Timing data structures): ApduTiming, SessionResult
  - 섹션 9  (APDU timer): ApduTimer
  - 섹션 10 (Result saving): save_session_csv, save_session_summary_json

핵심 인터페이스:

    send_fn(apdu: bytes) -> bytes

APDU bytes를 send_fn에 전달하면 응답 bytes가 반환되어야 한다.

send_fn 내부 구현은 이 모듈에서 알지 않는다.

    baseline
        → ACR122U 직접 통신

    relay_bt
        → Bluetooth relay

    relay_tcp_wifi
        → Wi-Fi relay

    relay_ipc
        → IPC relay

등 모든 채널에서 동일한 방식으로 RTT를 측정할 수 있다.

CSV_FIELDS는 팀 전체가 공유하는 CSV 표준이다.
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
# 측정 결과 데이터 구조
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
    """
    한 번의 EMV transaction에 대한 전체 측정 결과.

    하나의 SessionResult 안에 여러 ApduTiming이 순서대로 저장된다.
    """

    session_id: str
    channel: str
    timings: List[ApduTiming] = field(default_factory=list)

    @property
    def total_ms(self) -> float:
        """
        transaction을 구성하는 APDU RTT의 합(ms).

        현재 프로젝트에서는 APDU들이 순차적으로 처리되므로
        전체 transaction의 통신 지연을 나타내는 값으로 사용한다.
        """

        return sum(
            timing.rtt_ms
            for timing in self.timings
        )

    @property
    def success(self) -> bool:
        """
        모든 APDU의 SW1SW2가 9000인지 확인한다.
        """

        if not self.timings:
            return False

        return all(
            timing.success
            for timing in self.timings
        )

    @property
    def per_command_stats(self):
        """
        APDU별 RTT 통계.

        반환:
            n
            mean_ms
            std_ms
            jitter_ms
            min_ms
            max_ms
        """

        vals = [
            timing.rtt_ms
            for timing in self.timings
        ]

        if not vals:
            return {}

        mean = statistics.mean(vals)

        std = (
            statistics.pstdev(vals)
            if len(vals) > 1
            else 0.0
        )

        diffs = [
            abs(vals[i] - vals[i - 1])
            for i in range(1, len(vals))
        ]

        jitter = (
            statistics.pstdev(diffs)
            if len(diffs) > 1
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
# APDU Timer
# ---------------------------------------------------------------------

class ApduTimer:
    """
    APDU 하나의 왕복 시간을 측정한다.

    send_fn은 다음 인터페이스를 만족해야 한다.

        send_fn(apdu: bytes) -> bytes

    send_fn 내부가 실제 카드 통신인지,
    mock인지, IPC인지, Bluetooth인지,
    Wi-Fi인지에 관계없이 동일한 방식으로 측정한다.
    """

    def __init__(
        self,
        channel: str,
        session_id: str
    ):
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

        # 실제 기록용 timestamp
        t_epoch = time.time()

        # RTT 측정 시작
        t0 = time.perf_counter()

        # 실제 APDU 왕복
        resp = send_fn(apdu_bytes)

        # RTT 측정 종료
        t1 = time.perf_counter()

        rtt_ms = (
            t1 - t0
        ) * 1000.0

        resp_hex = bytes_to_hex(resp)

        sw1sw2 = (
            resp_hex[-4:]
            if len(resp_hex) >= 4
            else ""
        )

        success = (
            sw1sw2 == "9000"
        )

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
# CSV 저장
# ---------------------------------------------------------------------

# ★ 팀 표준 CSV 칸 이름 ★
# analysis/ 담당은 이 이름을 그대로 사용한다.

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


def save_session_csv(
    session: SessionResult,
    out_dir: str = "data"
) -> Path:

    out_path = Path(out_dir)

    out_path.mkdir(
        parents=True,
        exist_ok=True
    )

    fname = (
        out_path
        / f"{session.channel}_{session.session_id}.csv"
    )

    with open(
        fname,
        "w",
        newline="",
        encoding="utf-8"
    ) as f:

        writer = csv.DictWriter(
            f,
            fieldnames=CSV_FIELDS
        )

        writer.writeheader()

        for timing in session.timings:
            writer.writerow(
                asdict(timing)
            )

    return fname


def save_session_summary_json(
    session: SessionResult,
    out_dir: str = "data"
) -> Path:

    out_path = Path(out_dir)

    out_path.mkdir(
        parents=True,
        exist_ok=True
    )

    fname = (
        out_path
        / f"{session.channel}_{session.session_id}_summary.json"
    )

    summary = {
        "session_id": session.session_id,
        "channel": session.channel,
        "total_ms": session.total_ms,
        "success": session.success,
        "stats": session.per_command_stats,
        "n_commands": len(session.timings),
    }

    with open(
        fname,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            summary,
            f,
            ensure_ascii=False,
            indent=2
        )

    return fname