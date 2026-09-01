# -*- coding: utf-8 -*-
"""
core/framing.py
===============
소켓으로 bytes를 주고받을 때의 "포장 규칙".

[원본 위치] ppse_measure_channal.py 의
  - 섹션 15 (Socket framing): send_framed, recv_exact, recv_framed,
                              relay_transmit_over_socket

TCP든 Bluetooth든, 소켓은 "메시지 경계"를 스스로 모른다.
그래서 매 메시지 앞에 4바이트로 '길이'를 붙여 보내고(send_framed),
받을 때 그 길이만큼 정확히 읽는다(recv_framed).

channels/wifi.py 와 channels/bluetooth.py 가 이 함수들을 가져다 쓴다.
채널 종류가 달라도 이 포장 규칙은 동일하다 => 그래서 core에 둔다.
"""

from __future__ import annotations
import struct

# 한 번에 보낼 수 있는 최대 크기 (안전장치)
MAX_FRAME_SIZE = 1024 * 1024


def send_framed(sock, payload: bytes):
    """payload 앞에 4바이트 길이를 붙여서 전송."""
    if len(payload) > MAX_FRAME_SIZE:
        raise ValueError("payload가 너무 큽니다.")

    sock.sendall(struct.pack(">I", len(payload)) + payload)


def recv_exact(sock, n: int) -> bytes:
    """정확히 n바이트를 다 받을 때까지 읽는다."""
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("소켓 연결이 종료되었습니다.")
        buf.extend(chunk)
    return bytes(buf)


def recv_framed(sock) -> bytes:
    """먼저 4바이트 길이를 읽고, 그 길이만큼 본문을 읽는다."""
    raw_length = recv_exact(sock, 4)
    length = struct.unpack(">I", raw_length)[0]

    if length > MAX_FRAME_SIZE:
        raise ValueError(f"비정상적인 frame size: {length}")

    return recv_exact(sock, length)


def relay_transmit_over_socket(sock, apdu: bytes) -> bytes:
    """
    APDU 하나를 소켓 너머로 보내고, 응답 하나를 받아 돌려준다.
    이게 바로 send_fn 이 소켓 위에서 하는 일이다.
    (reader 역할 쪽에서 사용)
    """
    send_framed(sock, apdu)
    return recv_framed(sock)


def serve_loop(sock, card_device):
    """
    card 역할 쪽 무한 루프.
    소켓에서 APDU를 받아 -> 카드에 전달 -> 응답을 다시 소켓으로.

    [원본 위치] 섹션 16 (card_side_serve_loop)
    """
    print("[card_role] 연결 수립. APDU relay 시작.")
    try:
        while True:
            apdu = recv_framed(sock)
            # card_device.transmit 은 리스트(int) APDU를 받고
            # (response_body, sw1, sw2) 튜플을 돌려준다(reader 계약).
            result = card_device.transmit(list(apdu))
            if isinstance(result, tuple) and len(result) == 3:
                body, sw1, sw2 = result
                response = bytes(body) + bytes([sw1, sw2])
            else:
                response = bytes(result)
            send_framed(sock, response)
    except ConnectionError:
        print("[card_role] 연결 종료.")