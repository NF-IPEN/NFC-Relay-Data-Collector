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
# -*- coding: utf-8 -*-
"""
core/framing.py
===============

소켓 기반 Relay Channel에서 사용하는 공통 메시지 framing 모듈.

APDU bytes를 TCP/Bluetooth 등의 소켓으로 전송할 때,
소켓 자체에는 메시지 경계가 없기 때문에 다음과 같은 형식으로
데이터를 주고받는다.

    [4-byte payload length][payload]

송신:
    send_framed()

수신:
    recv_exact()
    recv_framed()

Relay:
    relay_transmit_over_socket()

Card-side:
    serve_loop()

이 framing 규칙은 특정 채널(Wi-Fi/Bluetooth)에 종속되지 않으며,
channels/wifi.py와 channels/bluetooth.py에서 공통으로 사용한다.
"""

from __future__ import annotations

import struct


# 한 번에 보낼 수 있는 최대 frame 크기
# 비정상적으로 큰 데이터가 들어오는 것을 방지하기 위한 안전장치
MAX_FRAME_SIZE = 1024 * 1024


def send_framed(sock, payload: bytes):
    """
    payload 앞에 4바이트 길이 정보를 붙여 전송한다.

    Frame format:
        [4-byte payload length][payload]

    길이는 Big-Endian unsigned integer로 저장한다.
    """

    if len(payload) > MAX_FRAME_SIZE:
        raise ValueError("payload가 너무 큽니다.")

    sock.sendall(
        struct.pack(">I", len(payload)) + payload
    )


def recv_exact(sock, n: int) -> bytes:
    """
    소켓에서 정확히 n바이트를 받을 때까지 읽는다.

    TCP에서는 한 번의 recv() 호출이 하나의 메시지를
    의미하지 않기 때문에 반드시 필요한 함수이다.
    """

    buf = bytearray()

    while len(buf) < n:

        chunk = sock.recv(n - len(buf))

        if not chunk:
            raise ConnectionError(
                "소켓 연결이 종료되었습니다."
            )

        buf.extend(chunk)

    return bytes(buf)


def recv_framed(sock) -> bytes:
    """
    하나의 frame을 수신한다.

    1. 먼저 4바이트 payload length를 읽는다.
    2. 해당 길이만큼 payload를 읽는다.
    """

    raw_length = recv_exact(sock, 4)

    length = struct.unpack(
        ">I",
        raw_length
    )[0]

    if length > MAX_FRAME_SIZE:
        raise ValueError(
            f"비정상적인 frame size: {length}"
        )

    return recv_exact(sock, length)


def relay_transmit_over_socket(sock, apdu: bytes) -> bytes:
    """
    Relay Channel을 통해 APDU 하나를 전달하고
    해당 APDU에 대한 응답을 반환한다.

    동작:

        APDU
          ↓
        send_framed()
          ↓
        socket
          ↓
        remote side
          ↓
        response
          ↓
        recv_framed()
    """

    send_framed(sock, apdu)

    return recv_framed(sock, )


def serve_loop(sock, card_device):
    """
    Card-side relay loop.

    소켓에서 APDU를 수신하고,
    card_device를 통해 실제 NFC 카드에 전달한 뒤,
    카드의 응답을 다시 소켓으로 전송한다.

    동작:

        socket
          ↓
        recv_framed()
          ↓
        APDU
          ↓
        card_device.transmit()
          ↓
        response
          ↓
        send_framed()
          ↓
        socket
    """

    print("[card_role] 연결 수립. APDU relay 시작.")

    try:

        while True:

            apdu = recv_framed(sock)

            response = card_device.transmit(apdu)

            send_framed(
                sock,
                response
            )

    except ConnectionError:

        print("[card_role] 연결 종료.")
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
            response = card_device.transmit(apdu)
            send_framed(sock, response)
    except ConnectionError:
        print("[card_role] 연결 종료.")
