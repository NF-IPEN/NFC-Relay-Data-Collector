from __future__ import annotations

import random
import time
import uuid
from typing import Optional, Sequence, Tuple

from smartcard.System import readers
from smartcard.Exceptions import (
    NoCardException,
    CardConnectionException,
)

from core.timing import (
    SessionResult, ApduTimer,
    save_session_csv, save_session_summary_json,
)
from apdu.transaction import run_emv_transaction


class ReaderError(Exception):
    """Reader 관련 기본 예외."""


class ReaderNotFoundError(ReaderError):
    """사용 가능한 리더를 찾을 수 없는 경우."""


class CardNotPresentError(ReaderError):
    """리더에 카드가 없는 경우."""


class NFCReader:
    """
    PC/SC 기반 NFC 카드 리더 (실물).

    기본적으로 ACR122 계열 리더를 자동 선택한다.

    계약: transmit(apdu) -> (response, sw1, sw2)
    baseline.py 등 팀 프레임워크가 dev.transmit 을 send_fn 으로 그대로
    넘겨 쓰므로, pyscard의 connection.transmit(apdu) -> (response, sw1, sw2)
    계약을 그대로 따른다.

    사용 예:
        with NFCReader() as reader:
            atr = reader.connect()
            resp, sw1, sw2 = reader.transmit([0x00, 0xA4, 0x04, 0x00, 0x00])
    """

    def __init__(self, reader_name: Optional[str] = None):
        self.reader_name = reader_name
        self._reader = None
        self._connection = None
        self._atr: Optional[bytes] = None

    # ------------------------------------------------------------------
    # 컨텍스트 매니저 지원
    # ------------------------------------------------------------------
    def __enter__(self) -> "NFCReader":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.disconnect()

    def _find_reader(self):
        """사용할 PC/SC 리더를 탐색한다."""
        available = readers()

        if not available:
            raise ReaderNotFoundError(
                "사용 가능한 스마트카드 리더가 없습니다. "
                "리더가 PC에 연결되어 있고 PC/SC 서비스(pcscd)가 "
                "실행 중인지 확인하세요."
            )

        # 특정 리더를 지정한 경우
        if self.reader_name:
            for reader in available:
                if self.reader_name.lower() in str(reader).lower():
                    return reader

            raise ReaderNotFoundError(
                f"'{self.reader_name}' 리더를 찾을 수 없습니다. "
                f"사용 가능한 리더: {[str(r) for r in available]}"
            )

        # ACR122 계열 우선 선택
        for reader in available:
            if "ACR122" in str(reader).upper():
                return reader

        # 개발 환경에 다른 리더만 있을 경우 첫 번째 사용
        return available[0]

    def connect(self) -> bytes:
        """
        리더와 카드에 연결한다.

        Returns:
            bytes: 연결된 카드의 ATR
        """
        if self._connection is not None:
            return self.get_atr()

        self._reader = self._find_reader()

        try:
            connection = self._reader.createConnection()
            connection.connect()

            self._connection = connection
            self._atr = bytes(connection.getATR())

            return self._atr

        except NoCardException as exc:
            raise CardNotPresentError(
                "카드가 감지되지 않았습니다. "
                "카드를 리더기에 올려주세요."
            ) from exc

        except CardConnectionException as exc:
            raise ReaderError(
                f"카드 연결 실패: {exc}"
            ) from exc

    def get_atr(self) -> bytes:
        """현재 연결된 카드의 ATR을 반환한다."""
        if self._connection is None:
            return self.connect()

        if self._atr is None:
            self._atr = bytes(self._connection.getATR())

        return self._atr

    @property
    def connection(self):
        """
        pyscard 표준 connection 객체를 그대로 노출한다.

        팀 코드가 기대하는 계약(connection.transmit(apdu) -> (response, sw1, sw2))을
        그대로 만족한다 — pyscard의 CardConnection.transmit()을 감싸지 않고 원본을
        반환하므로 response는 pyscard 표준대로 list[int]다.
        """
        if self._connection is None:
            self.connect()
        return self._connection

    def transmit(
        self,
        apdu: Sequence[int],
        raw: bool = False,
    ) -> Tuple[bytes, int, int]:
        """
        APDU를 실제 카드에 전송한다.

        내부적으로 pyscard 표준 connection.transmit(apdu) -> (response, sw1, sw2)
        계약을 그대로 사용한다. baseline.py 등에서 dev.transmit 을 send_fn 으로
        그대로 넘겨 호출하므로 시그니처(위치 인자 하나: apdu)를 그대로 유지한다.

        Args:
            apdu: 정수 배열 형태의 APDU
                  예: [0x00, 0xA4, 0x04, 0x00, ...]
            raw: True면 response를 pyscard 표준 그대로 list[int]로 반환한다.
                 False(기본값)면 다루기 쉬운 bytes로 변환해서 반환한다.

        Returns:
            response, sw1, sw2
        """
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
            # 카드가 리더에서 이탈했거나 연결이 끊어진 경우
            self.disconnect()
            raise ReaderError(
                f"APDU 전송 실패 (연결 끊김): {exc}"
            ) from exc

        except Exception as exc:
            raise ReaderError(
                f"APDU 전송 실패: {exc}"
            ) from exc

    def disconnect(self) -> None:
        """카드 연결을 실제로 해제하고 내부 상태를 초기화한다."""
        if self._connection is not None:
            try:
                self._connection.disconnect()
            except CardConnectionException:
                # 이미 끊어져 있는 경우 등은 무시
                pass
        self._connection = None
        self._atr = None

    @property
    def is_connected(self) -> bool:
        """현재 카드와 연결된 상태인지 반환한다."""
        return self._connection is not None

    @staticmethod
    def list_readers() -> list[str]:
        """연결된 PC/SC 리더 목록을 문자열로 반환한다 (디버깅용)."""
        return [str(r) for r in readers()]


class MockDevice:
    """
    실물 리더 없이 파이프라인을 검증하기 위한 목(mock) 디바이스.

    NFCReader와 동일한 계약(transmit(apdu) -> (response, sw1, sw2))을
    따르므로 make_device(use_mock=True, ...) 로 그대로 교체해 쓸 수 있다.

    - APDU 헤더(CLA, INS)만 보고 그럴듯한 성공 응답(SW=9000)을 만들어 낸다.
    - latency_range_ms 로 실측 RTT와 비슷한 인위적 지연을 흉내낸다.
      (baseline과 동일한 파이프라인으로 timing 코드 자체를 검증할 때 유용)

    실제 EMV 응답 데이터가 필요한 테스트라면 respond_map 에
    APDU(tuple) -> (response_bytes, sw1, sw2) 를 미리 채워 넣어 사용한다.
    """

    def __init__(
        self,
        latency_range_ms: Tuple[float, float] = (5.0, 15.0),
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
        return bytes.fromhex("3B8F8001804F0CA000000306030001000000006A")  # 임의 ATR

    def transmit(
        self,
        apdu: Sequence[int],
        raw: bool = False,
    ) -> Tuple[bytes, int, int]:
        if not self._connected:
            self.connect()

        # 실측 RTT 분포를 흉내내는 인위적 지연
        low, high = self.latency_range_ms
        time.sleep(random.uniform(low, high) / 1000.0)

        key = tuple(apdu)
        if key in self.respond_map:
            response, sw1, sw2 = self.respond_map[key]
        else:
            response, sw1, sw2 = b"", 0x90, 0x00

        return (list(response) if raw else bytes(response)), sw1, sw2

    def disconnect(self) -> None:
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected


def make_device(use_mock: bool, reader_substr: Optional[str] = None):
    """
    baseline.py 등에서 기대하는 팩토리 함수.

    with make_device(use_mock, reader_substr) as dev:
        run_emv_transaction(dev.transmit, timer)

    Args:
        use_mock: True면 실물 리더 없이 MockDevice를 반환한다.
        reader_substr: 실물 모드에서 사용할 리더 이름 부분 문자열
                       (예: "ACR122"). None이면 자동 선택.

    Returns:
        NFCReader 또는 MockDevice — 둘 다 컨텍스트 매니저이며
        transmit(apdu) -> (response, sw1, sw2) 계약을 동일하게 따른다.
    """
    if use_mock:
        return MockDevice()
    return NFCReader(reader_name=reader_substr)


# ----------------------------------------------------------------------
# Baseline 측정
# ----------------------------------------------------------------------
# 채널을 거치지 않는 "정상 통신" 기준선(baseline).
# ACR122U에 카드를 직접 올려 EMV 흐름을 돌리며 RTT를 잰다.
#
# [원본 위치] ppse_measure_channal.py 의
#   - 섹션 14 (Baseline): run_baseline
#
# 이 값이 "정상 무리"가 된다. 릴레이 채널들과 비교하는 기준선이다.
# send_fn 은 dev.transmit (실물 또는 mock) 을 그대로 쓴다 => 소켓 없음.

CHANNEL_LABEL = "baseline_usb"


def run_baseline(trials: int, use_mock: bool, reader_substr: str):
    sessions = []

    for trial in range(trials):
        session_id = f"trial{trial:03d}_{uuid.uuid4().hex[:6]}"
        session = SessionResult(session_id=session_id, channel=CHANNEL_LABEL)
        timer = ApduTimer(channel=CHANNEL_LABEL, session_id=session_id)

        try:
            with make_device(use_mock, reader_substr) as dev:
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