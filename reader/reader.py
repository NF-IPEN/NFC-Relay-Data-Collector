from __future__ import annotations

import random
import time
from typing import Optional, Sequence, Tuple


class ReaderError(Exception):
    """Reader 관련 기본 예외."""


class ReaderNotFoundError(ReaderError):
    """사용 가능한 리더를 찾을 수 없는 경우."""


class CardNotPresentError(ReaderError):
    """리더에 카드가 없는 경우."""


class NFCReader:
    def __init__(self, reader_name: Optional[str] = None):
        self.reader_name = reader_name
        self._reader = None
        self._connection = None
        self._atr: Optional[bytes] = None

    def __enter__(self) -> "NFCReader":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.disconnect()

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