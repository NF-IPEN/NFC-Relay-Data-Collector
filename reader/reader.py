# -*- coding: utf-8 -*-
"""
reader/reader.py
================
PC/SC 기반 NFC 카드 리더(실물)와, 하드웨어 없이 검증하는 MockDevice.

담당: 아란 (NFC Reader)

계약(팀 표준 인터페이스):
    transmit(apdu) -> (response, sw1, sw2)
  baseline/채널 코드가 dev.transmit 을 send_fn 으로 그대로 넘겨 쓰므로,
  pyscard의 connection.transmit(apdu) -> (response, sw1, sw2) 계약을 그대로 따른다.

[동하님 코드에서 흡수한 것]
  run_experiment.py 의 wait_for_card_ready(카드 인식 재시도) 로직을
  NFCReader.connect_with_retry() 로 통합했다. 실물 측정 중 카드가 잠깐
  떨어져 0x80100069 가 나도 잠시 기다렸다 재시도한다.
"""

from __future__ import annotations

import random
import time
from typing import Optional, Sequence, Tuple

# 주의: pyscard(smartcard)는 실물 리더를 쓸 때만 필요하다.
# mock 전용 개발자가 pyscard 없이도 돌릴 수 있도록, import 를 실제
# 리더 사용 시점(_find_reader 등)까지 지연시킨다.


class ReaderError(Exception):
    """Reader 관련 기본 예외."""


class ReaderNotFoundError(ReaderError):
    """사용 가능한 리더를 찾을 수 없는 경우."""


class CardNotPresentError(ReaderError):
    """리더에 카드가 없는 경우."""


class NFCReader:
    """
    PC/SC 기반 NFC 카드 리더 (실물). 기본적으로 ACR122 계열을 자동 선택한다.

    사용 예:
        with NFCReader() as reader:
            reader.connect_with_retry()          # 카드 올릴 때까지 대기
            resp, sw1, sw2 = reader.transmit([0x00, 0xA4, 0x04, 0x00, 0x00])
    """

    def __init__(self, reader_name: Optional[str] = None):
        self.reader_name = reader_name
        self._reader = None
        self._connection = None
        self._atr: Optional[bytes] = None

    # ------------------------------------------------------------------
    # 컨텍스트 매니저
    # ------------------------------------------------------------------
    def __enter__(self) -> "NFCReader":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.disconnect()

    # ------------------------------------------------------------------
    # 리더 탐색
    # ------------------------------------------------------------------
    def _find_reader(self):
        from smartcard.System import readers
        available = readers()
        if not available:
            raise ReaderNotFoundError(
                "사용 가능한 스마트카드 리더가 없습니다. "
                "리더가 연결되어 있고 PC/SC 서비스가 실행 중인지 확인하세요."
            )

        if self.reader_name:
            for reader in available:
                if self.reader_name.lower() in str(reader).lower():
                    return reader
            raise ReaderNotFoundError(
                f"'{self.reader_name}' 리더를 찾을 수 없습니다. "
                f"사용 가능한 리더: {[str(r) for r in available]}"
            )

        for reader in available:
            if "ACR122" in str(reader).upper():
                return reader
        return available[0]

    # ------------------------------------------------------------------
    # 연결
    # ------------------------------------------------------------------
    def connect(self) -> bytes:
        """리더와 카드에 연결한다. 반환: ATR."""
        if self._connection is not None:
            return self.get_atr()

        from smartcard.Exceptions import NoCardException, CardConnectionException
        self._reader = self._find_reader()
        try:
            connection = self._reader.createConnection()
            connection.connect()
            self._connection = connection
            self._atr = bytes(connection.getATR())
            return self._atr
        except NoCardException as exc:
            raise CardNotPresentError(
                "카드가 감지되지 않았습니다. 카드를 리더기에 올려주세요."
            ) from exc
        except CardConnectionException as exc:
            raise ReaderError(f"카드 연결 실패: {exc}") from exc

    def connect_with_retry(self, timeout: float = 15.0, interval: float = 0.3) -> bytes:
        """
        카드가 리더 위에 인식될 때까지 재시도하며 연결한다.
        (동하님 run_experiment.py 의 wait_for_card_ready 를 통합한 것)

        실물 측정 중 카드가 잠깐 떨어져도 timeout 안에서 다시 시도한다.
        반환: ATR / 실패 시 CardNotPresentError.
        """
        print("카드를 리더 위에 올려주세요...")
        start = time.time()
        last_err = None
        while time.time() - start < timeout:
            try:
                atr = self.connect()
                print("카드 인식 완료.")
                return atr
            except ReaderError as e:
                last_err = e
                time.sleep(interval)
        raise CardNotPresentError(
            f"제한 시간({timeout}s) 내 카드 인식 실패: {last_err}"
        )

    def get_atr(self) -> bytes:
        if self._connection is None:
            return self.connect()
        if self._atr is None:
            self._atr = bytes(self._connection.getATR())
        return self._atr

    @property
    def connection(self):
        if self._connection is None:
            self.connect()
        return self._connection

    # ------------------------------------------------------------------
    # APDU 전송 (팀 표준 계약)
    # ------------------------------------------------------------------
    def transmit(
        self,
        apdu: Sequence[int],
        raw: bool = False,
    ) -> Tuple[bytes, int, int]:
        from smartcard.Exceptions import NoCardException, CardConnectionException
        if self._connection is None:
            self.connect()
        try:
            response, sw1, sw2 = self._connection.transmit(list(apdu))
            return (response if raw else bytes(response)), sw1, sw2
        except NoCardException as exc:
            self.disconnect()
            raise CardNotPresentError(
                "APDU 전송 중 카드 연결이 해제되었습니다."
            ) from exc
        except CardConnectionException as exc:
            self.disconnect()
            raise ReaderError(f"APDU 전송 실패 (연결 끊김): {exc}") from exc
        except Exception as exc:
            raise ReaderError(f"APDU 전송 실패: {exc}") from exc

    def disconnect(self) -> None:
        if self._connection is not None:
            try:
                self._connection.disconnect()
            except Exception:
                pass
        self._connection = None
        self._atr = None

    @property
    def is_connected(self) -> bool:
        return self._connection is not None

    @staticmethod
    def list_readers() -> list[str]:
        from smartcard.System import readers
        return [str(r) for r in readers()]


class MockDevice:
    """
    실물 리더 없이 파이프라인을 검증하기 위한 mock.
    NFCReader와 동일한 계약(transmit(apdu) -> (response, sw1, sw2))을 따른다.

    실제 EMV 흐름(PPSE->AID->GPO->READ)을 흉내내도록 respond_map 기본값을 채워둔다.
    latency_range_ms 로 실측 RTT 비슷한 인위적 지연을 준다.
    """

    def __init__(
        self,
        latency_range_ms: Tuple[float, float] = (2.5, 4.0),
        respond_map: Optional[dict] = None,
    ):
        self.latency_range_ms = latency_range_ms
        self.respond_map = respond_map or {}
        self._connected = False

    def __enter__(self) -> "MockDevice":
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.disconnect()

    def connect(self) -> bytes:
        self._connected = True
        return bytes.fromhex("3B8F8001804F0CA000000306030001000000006A")

    def connect_with_retry(self, timeout: float = 15.0, interval: float = 0.3) -> bytes:
        # mock은 항상 즉시 성공 (실물 인터페이스와 맞추기 위해 존재)
        return self.connect()

    def transmit(
        self,
        apdu: Sequence[int],
        raw: bool = False,
    ) -> Tuple[bytes, int, int]:
        if not self._connected:
            self.connect()

        low, high = self.latency_range_ms
        time.sleep(random.uniform(low, high) / 1000.0)

        apdu = list(apdu)

        # respond_map 우선
        key = tuple(apdu)
        if key in self.respond_map:
            response, sw1, sw2 = self.respond_map[key]
            return (list(response) if raw else bytes(response)), sw1, sw2

        # 기본 EMV 흐름 흉내
        resp = self._default_emv_response(apdu)
        if resp is not None:
            data = resp
            return (list(data) if raw else bytes(data)), 0x90, 0x00

        return (b"" if not raw else []), 0x90, 0x00

    @staticmethod
    def _default_emv_response(apdu):
        # SELECT PPSE
        if len(apdu) >= 2 and apdu[0] == 0x00 and apdu[1] == 0xA4 and \
           bytes([0x32, 0x50, 0x41, 0x59]) in bytes(apdu):
            return bytes.fromhex(
                "6F2F"
                "840E325041592E5359532E4444463031"
                "A51D"
                "BF0C1A"
                "6118"
                "4F07A0000000031010"
                "500A5649534120434845434B"
                "870101"
            )
        # SELECT AID
        if len(apdu) >= 2 and apdu[0] == 0x00 and apdu[1] == 0xA4:
            return bytes.fromhex("6F0A8407A0000000031010")
        # GPO (AFL: SFI=2, records 1~4)  77 06 94 04 10010400
        if len(apdu) >= 2 and apdu[0] == 0x80 and apdu[1] == 0xA8:
            return bytes.fromhex("7706940410010400")
        # READ RECORD
        if len(apdu) >= 2 and apdu[0] == 0x00 and apdu[1] == 0xB2:
            return bytes.fromhex("7000")
        return b""

    def disconnect(self) -> None:
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected


def make_device(use_mock: bool, reader_substr: Optional[str] = None):
    """
    baseline/채널 코드가 기대하는 팩토리.

    with make_device(use_mock, reader_substr) as dev:
        run_emv_transaction(dev.transmit, timer)
    """
    if use_mock:
        return MockDevice()
    return NFCReader(reader_name=reader_substr)