# -*- coding: utf-8 -*-
"""
reader/baseline.py
==================
채널을 거치지 않는 "정상 통신" 기준선(baseline).
ACR122U에 카드를 직접 올려 EMV 흐름을 돌리며 RTT를 잰다.

[원본 위치] ppse_measure_channal.py 섹션 14 (run_baseline)

이 값이 "정상 무리"가 된다. 릴레이 채널들과 비교하는 기준선이다.
send_fn 은 dev.transmit (실물 또는 mock) 을 그대로 쓴다 => 소켓 없음.

[동하님 코드 흡수] 실물 모드일 때 connect_with_retry 로 카드 인식 재시도.
"""

from __future__ import annotations
import uuid

from core.timing import (
    SessionResult, ApduTimer,
    save_session_csv, save_session_summary_json,
)
from apdu.transaction import run_emv_transaction
from reader.reader import make_device


CHANNEL_LABEL = "baseline_usb"


def run_baseline(trials: int, use_mock: bool, reader_substr: str):
    sessions = []

    for trial in range(trials):
        session_id = f"trial{trial:03d}_{uuid.uuid4().hex[:6]}"
        session = SessionResult(session_id=session_id, channel=CHANNEL_LABEL)
        timer = ApduTimer(channel=CHANNEL_LABEL, session_id=session_id)

        try:
            with make_device(use_mock, reader_substr) as dev:
                # 실물 리더면 카드 인식될 때까지 재시도
                if hasattr(dev, "connect_with_retry"):
                    dev.connect_with_retry()
                timings = run_emv_transaction(dev.transmit, timer)
                session.timings.extend(timings)
        except Exception as e:
            print(f"[{CHANNEL_LABEL}] trial={trial:03d} ERROR={e}")
            continue

        if not session.timings:
            continue

        csv_path = save_session_csv(session)
        save_session_summary_json(session)

        stats = session.per_command_stats
        print(
            f"[{CHANNEL_LABEL}] trial={trial:03d} "
            f"total={session.total_ms:.2f}ms "
            f"mean={stats.get('mean_ms', 0):.2f}ms "
            f"std={stats.get('std_ms', 0):.2f}ms "
            f"jitter={stats.get('jitter_ms', 0):.2f}ms "
            f"success={session.success} -> {csv_path.name}"
        )
        sessions.append(session)

    return sessions