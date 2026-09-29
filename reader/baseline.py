from __future__ import annotations
import uuid

from core.timing import SessionResult, ApduTimer, save_sessions_csv
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
                if hasattr(dev, "connect_with_retry"):
                    dev.connect_with_retry()
                timings = run_emv_transaction(dev.transmit, timer)
                session.timings.extend(timings)
        except Exception as e:
            print(f"[{CHANNEL_LABEL}] trial={trial:03d} ERROR={e}")
            continue

        if not session.timings:
            continue

        stats = session.per_command_stats
        print(
            f"[{CHANNEL_LABEL}] trial={trial:03d} "
            f"total={session.total_ms:.2f}ms "
            f"mean={stats.get('mean_ms', 0):.2f}ms "
            f"std={stats.get('std_ms', 0):.2f}ms "
            f"jitter={stats.get('jitter_ms', 0):.2f}ms "
            f"success={session.success}"
        )
        sessions.append(session)

    if sessions:
        csv_path = save_sessions_csv(
            sessions,
            filename=f"{CHANNEL_LABEL}_{trials}trials_{uuid.uuid4().hex[:6]}.csv",
        )
        print(f"[{CHANNEL_LABEL}] {len(sessions)}/{trials} trials 저장 -> {csv_path}")

    return sessions