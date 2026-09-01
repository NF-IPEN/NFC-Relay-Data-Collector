# -*- coding: utf-8 -*-
"""
channels/ipc.py
===============
같은 PC 안에서 APDU를 릴레이하는 채널 (localhost TCP 소켓 이용).

[원본 위치] 원본 코드에는 없음 (신규 추가).
  단, 구현은 wifi.py 와 거의 같다. 목적지가 127.0.0.1(자기 자신)일 뿐이다.
  => 세 채널(IPC/WiFi/BT) 중 지연이 가장 작을 것으로 기대되는 "기준 릴레이".

★ 3번 담당(Relay Channel)이 가장 먼저 짜보기 좋은, 제일 쉬운 채널 ★
  localhost 소켓이라 네트워크 설정이 필요 없어 바로 테스트된다.

card 역할과 reader 역할을 같은 PC에서 각각 실행하면 된다
(터미널 2개, 또는 프로세스 2개).
"""

from __future__ import annotations
import socket
import uuid

from core.framing import serve_loop, relay_transmit_over_socket
from channels.wifi import run_reader_role
from reader.reader import make_device


CHANNEL_LABEL = "relay_ipc"
DEFAULT_HOST = "127.0.0.1"   # 자기 자신 (localhost)
DEFAULT_PORT = 9998


def run_card(use_mock: bool, reader_substr: str, trials: int,
             host: str = DEFAULT_HOST, port: int = DEFAULT_PORT):
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((host, port))
    srv.listen(5)
    print(f"[card_role/IPC] {host}:{port} 대기 중")

    try:
        with make_device(use_mock, reader_substr) as dev:
            for i in range(trials):
                conn, addr = srv.accept()
                print(f"[card_role/IPC] session={i} client={addr}")
                with conn:
                    serve_loop(conn, dev)
    finally:
        srv.close()
        print("[card_role/IPC] 서버 종료")


def run_reader(trials: int, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT):
    def connect_fn():
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(30)
        sock.connect((host, port))
        return sock

    return run_reader_role(connect_fn, CHANNEL_LABEL, trials)