# -*- coding: utf-8 -*-
"""
channels/wifi.py
================
TCP 소켓(WiFi/유선)으로 APDU를 릴레이하는 채널.

[원본 위치] ppse_measure_channal.py 의
  - 섹션 17 (Reader-side relay): _run_relay_reader_role
  - 섹션 18 (TCP relay): run_relay_tcp_card, run_relay_tcp_reader

★ 3번 담당(Relay Channel)이 주로 손볼 파일 ★

역할이 둘로 나뉜다 (서로 다른 PC/프로세스에서 실행):
  - card 역할  : 서버. 카드(mole)를 들고 소켓 대기. reader가 보낸 APDU를 카드에 전달.
  - reader 역할: 클라이언트. EMV 흐름을 돌리며 매 APDU를 소켓 너머로 보냄. RTT는 여기서 잰다.

채널이 하는 일은 "bytes를 나른다"뿐. APDU 내용은 모른다.
core/framing.py 의 send_framed/recv_framed 규칙을 그대로 따른다.
"""

from __future__ import annotations
import socket
import uuid

from core.framing import serve_loop, relay_transmit_over_socket
from core.timing import (
    SessionResult, ApduTimer,
    save_session_csv, save_session_summary_json,
)
from apdu.transaction import run_emv_transaction
from reader.reader import make_device


CHANNEL_LABEL = "relay_tcp_wifi"


# ---------------------------------------------------------------------
# reader 역할 공통 루프  (원본 섹션 17)
#   connect_fn: 소켓을 열어 돌려주는 함수 (채널마다 다름)
# ---------------------------------------------------------------------

def run_reader_role(connect_fn, channel_label: str, trials: int):
    sessions = []

    for trial in range(trials):
        session_id = f"trial{trial:03d}_{uuid.uuid4().hex[:6]}"
        session = SessionResult(session_id=session_id, channel=channel_label)
        timer = ApduTimer(channel=channel_label, session_id=session_id)

        sock = None
        try:
            sock = connect_fn()
            send_fn = (
                lambda apdu, s=sock: relay_transmit_over_socket(s, apdu)
            )
            timings = run_emv_transaction(send_fn, timer)
            session.timings.extend(timings)

        except Exception as e:
            print(f"[{channel_label}] trial={trial:03d} ERROR={e}")

        finally:
            if sock is not None:
                try:
                    sock.close()
                except Exception:
                    pass

        if not session.timings:
            continue

        csv_path = save_session_csv(session)
        save_session_summary_json(session)

        stats = session.per_command_stats
        print(
            f"[{channel_label}] trial={trial:03d} "
            f"total={session.total_ms:.2f}ms "
            f"mean={stats.get('mean_ms', 0):.2f}ms "
            f"std={stats.get('std_ms', 0):.2f}ms "
            f"jitter={stats.get('jitter_ms', 0):.2f}ms "
            f"success={session.success} -> {csv_path.name}"
        )
        sessions.append(session)

    return sessions


# ---------------------------------------------------------------------
# TCP card 역할 (서버)  (원본 섹션 18)
# ---------------------------------------------------------------------

def run_card(host: str, port: int, use_mock: bool, reader_substr: str, trials: int):
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((host, port))
    srv.listen(5)
    print(f"[card_role/TCP] {host}:{port} 대기 중")

    try:
        with make_device(use_mock, reader_substr) as dev:
            for i in range(trials):
                conn, addr = srv.accept()
                print(f"[card_role/TCP] session={i} client={addr}")
                with conn:
                    serve_loop(conn, dev)
    finally:
        srv.close()
        print("[card_role/TCP] 서버 종료")


# ---------------------------------------------------------------------
# TCP reader 역할 (클라이언트)  (원본 섹션 18)
# ---------------------------------------------------------------------

def run_reader(host: str, port: int, trials: int):
    def connect_fn():
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(30)
        sock.connect((host, port))
        return sock

    return run_reader_role(connect_fn, CHANNEL_LABEL, trials)