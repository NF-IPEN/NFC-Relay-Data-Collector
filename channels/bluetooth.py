# -*- coding: utf-8 -*-
"""
channels/bluetooth.py
=====================
Bluetooth RFCOMM 으로 APDU를 릴레이하는 채널.

[원본 위치] ppse_measure_channal.py 의
  - 섹션 19 (Bluetooth relay): run_relay_bt_card, run_relay_bt_reader

★ 3번 담당(Relay Channel)이 손볼 파일 — 단, 마지막에 ★

주의: PyBluez 설치가 요즘 환경에서 까다롭다(특히 Windows).
      Bluetooth 채널 실험 전에 `import bluetooth` 가 되는지 먼저 확인할 것.
      안 되면 대안(BLE 라이브러리 등)을 검토해야 한다.

reader 역할 루프는 wifi.py 의 run_reader_role 을 그대로 재사용한다
(채널이 달라도 "소켓으로 나른다"는 공통이라 core+wifi 로직을 공유).
"""

from __future__ import annotations

from core.framing import serve_loop
from channels.wifi import run_reader_role
from reader.reader import make_device


CHANNEL_LABEL = "relay_bt"
RFCOMM_PORT = 4
BT_UUID_STR = "94f39d29-7d6d-437d-973b-fba39e49d4ee"


def _require_bt():
    try:
        import bluetooth
    except ImportError:
        raise RuntimeError(
            "PyBluez가 설치되어 있지 않습니다.\n"
            "Linux에서는 Bluetooth 개발 패키지가 필요할 수 있습니다."
        )
    return bluetooth


# ---------------------------------------------------------------------
# BT card 역할 (서버)
# ---------------------------------------------------------------------

def run_card(use_mock: bool, reader_substr: str, trials: int):
    bluetooth = _require_bt()

    srv = bluetooth.BluetoothSocket(bluetooth.Protocols.RFCOMM)
    srv.bind(("", RFCOMM_PORT))
    srv.listen(5)

    print(f"[card_role/BT] RFCOMM channel={RFCOMM_PORT} 대기 중")

    try:
        with make_device(use_mock, reader_substr) as dev:
            for i in range(trials):
                conn, addr = srv.accept()
                print(f"[card_role/BT] session={i} client={addr}")
                try:
                    serve_loop(conn, dev)
                finally:
                    try:
                        conn.close()
                    except Exception:
                        pass
    finally:
        srv.close()


# ---------------------------------------------------------------------
# BT reader 역할 (클라이언트)
# ---------------------------------------------------------------------

def run_reader(target_mac: str, trials: int):
    bluetooth = _require_bt()

    def connect_fn():
        sock = bluetooth.BluetoothSocket(bluetooth.Protocols.RFCOMM)
        sock.connect((target_mac, RFCOMM_PORT))
        return sock

    return run_reader_role(connect_fn, CHANNEL_LABEL, trials)