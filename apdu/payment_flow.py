"""
apdu/payment_flow.py — EMV 컨택리스 결제 플로우 APDU 처리 및 단계별 RTT 측정
--------------------------------------------------------------------------
담당: 동하 (APDU & Timing)

역할:
  1. PPSE(2PAY.SYS.DDF01) SELECT로 카드가 지원하는 AID 목록 조회
  2. AID SELECT (첫 번째 지원 AID로 애플리케이션 선택)
  3. GPO(GET PROCESSING OPTIONS) 호출
  4. GPO 응답의 AFL을 바탕으로 READ RECORD 반복 실행
  5. 각 단계별 APDU 전송~응답 RTT(ms)를 측정해 구조화된 결과로 반환

=====================================================================
[중요] 팀 인터페이스 계약 (아란님의 reader/reader.py 완성 전 임시 정의)
=====================================================================
이 모듈은 "connection" 객체를 인자로 받되, 그 객체가 다음 조건만 만족하면
누가 만든 reader든 그대로 꽂아 쓸 수 있도록 설계했습니다.

    connection.transmit(apdu: List[int]) -> Tuple[List[int], int, int]
        - apdu: APDU 바이트 리스트 (예: [0x00, 0xA4, 0x04, 0x00, ...])
        - 반환값: (response_bytes: List[int], sw1: int, sw2: int)

이것은 pyscard의 CardConnection.transmit()과 동일한 시그니처입니다.
즉 아란님이 reader/reader.py에서 pyscard로 카드에 연결한 connection 객체를
그대로 이 모듈의 함수들에 넘겨주기만 하면 통합이 끝납니다.

reader.py가 아직 없어도 개발 가능하도록, 이 파일 하단에 MockConnection과
실카드용 임시 커넥터(TempPyscardConnection)를 함께 제공합니다.
=====================================================================
"""

import time
from dataclasses import dataclass, field
from typing import List, Tuple, Optional

from tlv import find_all_aids, find_afl, afl_to_records


# ---------------------------------------------------------------------------
# APDU 프리셋 (EMV 컨택리스 표준 명령)
# ---------------------------------------------------------------------------

# PPSE SELECT: "2PAY.SYS.DDF01" (컨택리스 결제 앱 목록을 담고 있는 디렉토리)
PPSE_AID = [0x32, 0x50, 0x41, 0x59, 0x2E, 0x53, 0x59, 0x53, 0x2E, 0x44, 0x44, 0x46, 0x30, 0x31]
SELECT_PPSE_APDU = [0x00, 0xA4, 0x04, 0x00, len(PPSE_AID)] + PPSE_AID + [0x00]


def build_select_aid_apdu(aid: List[int]) -> List[int]:
    """주어진 AID로 SELECT APDU를 생성."""
    return [0x00, 0xA4, 0x04, 0x00, len(aid)] + aid + [0x00]


def build_gpo_apdu(pdol_data: Optional[List[int]] = None) -> List[int]:
    """
    GPO(GET PROCESSING OPTIONS) APDU 생성.
    PDOL(Processing options Data Object List) 요구사항은 카드마다 다른데,
    많은 카드가 빈 Command Template(83 00)도 허용하므로 기본값으로 사용.
    실제로 GPO가 실패(SW=6985 등)하면 PDOL을 채워 재시도해야 함 (TODO 참고).
    """
    if pdol_data is None:
        # Command Template 태그 0x83, 길이 0 (빈 PDOL)
        data = [0x83, 0x00]
    else:
        data = [0x83, len(pdol_data)] + pdol_data
    return [0x80, 0xA8, 0x00, 0x00, len(data)] + data + [0x00]


def build_read_record_apdu(sfi: int, record_number: int) -> List[int]:
    """READ RECORD APDU 생성. P2 = (SFI << 3) | 0x04 (표준 EMV 인코딩)."""
    p2 = (sfi << 3) | 0x04
    return [0x00, 0xB2, record_number, p2, 0x00]


# ---------------------------------------------------------------------------
# 단일 APDU 전송 + RTT 측정
# ---------------------------------------------------------------------------

@dataclass
class ApduStepResult:
    """APDU 한 번 전송에 대한 측정 결과 레코드."""
    step_name: str
    apdu_hex: str
    response_hex: str
    sw1: int
    sw2: int
    rtt_ms: float
    success: bool
    note: str = ""


def _to_hex(data: List[int]) -> str:
    return "".join(f"{b:02X}" for b in data)


def send_apdu(connection, apdu: List[int], step_name: str) -> ApduStepResult:
    """
    APDU 하나를 전송하고 RTT(ms)를 측정.
    connection은 팀 인터페이스 계약(transmit(apdu) -> (resp, sw1, sw2))을 만족해야 함.
    """
    t0 = time.perf_counter()
    try:
        response, sw1, sw2 = connection.transmit(apdu)
        t1 = time.perf_counter()
        success = (sw1 == 0x90 and sw2 == 0x00)
        note = "" if success else f"비정상 상태워드 (정상 거래 흐름이 아닐 수 있음)"
    except Exception as e:
        t1 = time.perf_counter()
        response, sw1, sw2 = [], 0x00, 0x00
        success = False
        note = f"전송 예외: {e}"

    rtt_ms = (t1 - t0) * 1000.0
    return ApduStepResult(
        step_name=step_name,
        apdu_hex=_to_hex(apdu),
        response_hex=_to_hex(response),
        sw1=sw1,
        sw2=sw2,
        rtt_ms=round(rtt_ms, 4),
        success=success,
        note=note,
    )


# ---------------------------------------------------------------------------
# 전체 EMV 컨택리스 플로우 실행: PPSE → AID SELECT → GPO → READ RECORD
# ---------------------------------------------------------------------------

@dataclass
class PaymentFlowResult:
    """플로우 1회 실행 결과 전체 (단계별 결과 리스트 + 선택된 AID 등 부가정보)."""
    steps: List[ApduStepResult] = field(default_factory=list)
    selected_aid_hex: str = ""
    total_rtt_ms: float = 0.0
    all_success: bool = True


def run_payment_flow(connection) -> PaymentFlowResult:
    """
    EMV 컨택리스 표준 흐름을 1회 실행:
      1) PPSE SELECT
      2) 첫 번째 AID SELECT
      3) GPO
      4) AFL 기반 READ RECORD 반복

    각 단계는 실패해도 플로우를 중단하지 않고 기록만 남김 (RTT 통계 목적).
    단, AID/AFL을 못 얻으면 이후 단계는 스킵됨.
    """
    result = PaymentFlowResult()

    # 1) PPSE SELECT
    ppse_step = send_apdu(connection, SELECT_PPSE_APDU, "PPSE_SELECT")
    result.steps.append(ppse_step)

    if not ppse_step.success:
        result.all_success = False
        return result  # PPSE 실패 시 이후 단계 진행 불가

    ppse_response = [int(ppse_step.response_hex[i:i+2], 16)
                     for i in range(0, len(ppse_step.response_hex), 2)]
    aids = find_all_aids(ppse_response)
    if not aids:
        result.all_success = False
        result.steps[-1].note += " | AID 추출 실패 (카드가 PPSE 미지원일 수 있음)"
        return result

    chosen_aid = aids[0]
    result.selected_aid_hex = _to_hex(chosen_aid)

    # 2) AID SELECT
    select_aid_apdu = build_select_aid_apdu(chosen_aid)
    aid_step = send_apdu(connection, select_aid_apdu, "SELECT_AID")
    result.steps.append(aid_step)

    if not aid_step.success:
        result.all_success = False
        return result

    # 3) GPO
    gpo_apdu = build_gpo_apdu()
    gpo_step = send_apdu(connection, gpo_apdu, "GPO")
    result.steps.append(gpo_step)

    if not gpo_step.success:
        result.all_success = False
        gpo_step.note += " | GPO 실패: PDOL 데이터가 필요한 카드일 수 있음 (TODO: PDOL 파싱 후 재시도)"
        return result

    gpo_response = [int(gpo_step.response_hex[i:i+2], 16)
                    for i in range(0, len(gpo_step.response_hex), 2)]
    afl = find_afl(gpo_response)
    if not afl:
        result.all_success = False
        gpo_step.note += " | AFL 추출 실패"
        return result

    # 4) READ RECORD 반복
    records_to_read = afl_to_records(afl)
    for sfi, record_number in records_to_read:
        read_apdu = build_read_record_apdu(sfi, record_number)
        step_name = f"READ_RECORD_SFI{sfi}_REC{record_number}"
        read_step = send_apdu(connection, read_apdu, step_name)
        result.steps.append(read_step)
        if not read_step.success:
            result.all_success = False

    result.total_rtt_ms = round(sum(s.rtt_ms for s in result.steps), 4)
    return result


# ---------------------------------------------------------------------------
# [임시] reader/reader.py 완성 전까지 단독 개발/테스트용 커넥터
# ---------------------------------------------------------------------------

class MockConnection:
    """
    하드웨어 없이 로직만 테스트하고 싶을 때 쓰는 가짜 connection.
    실제 카드 응답과 비슷한 형태의 더미 TLV를 돌려줌 (AID 1개, 레코드 1개짜리).
    실전 RTT 측정에는 쓸 수 없고, tlv.py 파싱 로직 및 플로우 분기 검증용.
    """

    def __init__(self, artificial_delay_ms: float = 5.0):
        self.artificial_delay_ms = artificial_delay_ms
        self._dummy_aid = [0xA0, 0x00, 0x00, 0x00, 0x03, 0x10, 0x10]  # 예시 Visa-like AID

    def transmit(self, apdu: List[int]) -> Tuple[List[int], int, int]:
        time.sleep(self.artificial_delay_ms / 1000.0)

        # PPSE SELECT 요청이면 더미 FCI 응답
        if apdu[:5] == SELECT_PPSE_APDU[:5]:
            aid = self._dummy_aid
            app_template = [0x61, len(aid) + 2, 0x4F, len(aid)] + aid
            fci = [0x6F, len(app_template)] + app_template
            return fci, 0x90, 0x00

        # AID SELECT 요청이면 성공만 반환
        if apdu[:2] == [0x00, 0xA4] and apdu[5:5+len(self._dummy_aid)] == self._dummy_aid:
            return [], 0x90, 0x00

        # GPO 요청이면 더미 AFL 응답 (SFI=1, 레코드 1~1)
        if apdu[:2] == [0x80, 0xA8]:
            afl = [0x08, 0x01, 0x01, 0x00]  # SFI 1, 시작/끝 레코드 1
            gpo_data = [0x94, len(afl)] + afl
            return gpo_data, 0x90, 0x00

        # READ RECORD 요청이면 더미 레코드 데이터
        if apdu[:2] == [0x00, 0xB2]:
            return [0x70, 0x02, 0x5A, 0x00], 0x90, 0x00

        return [], 0x6A, 0x82  # File not found (알 수 없는 요청)


def get_temp_connection_from_pyscard(reader_name_substring: str = "ACR122"):
    """
    아란님의 reader/reader.py가 아직 없을 때, 직접 pyscard로 카드에 연결해
    동일한 계약(transmit)을 만족하는 connection을 얻는 임시 함수.
    reader.py가 완성되면 이 함수 대신 그쪽 connect 함수를 import해서 쓰면 됨.
    """
    from smartcard.System import readers
    from smartcard.Exceptions import NoCardException

    r_list = readers()
    target = None
    for r in r_list:
        if reader_name_substring in str(r):
            target = r
            break
    if target is None and r_list:
        target = r_list[0]
    if target is None:
        raise RuntimeError("연결된 PC/SC 리더가 없습니다.")

    connection = target.createConnection()
    connection.connect()  # 카드가 이미 리더 위에 있어야 함
    return connection


if __name__ == "__main__":
    # 간단 동작 확인: MockConnection으로 플로우 로직만 검증
    print("[MockConnection으로 플로우 로직 검증]")
    mock_conn = MockConnection(artificial_delay_ms=3.0)
    result = run_payment_flow(mock_conn)
    for step in result.steps:
        print(f"  {step.step_name:25s} RTT={step.rtt_ms:7.3f}ms  "
              f"SW={step.sw1:02X}{step.sw2:02X}  success={step.success}")
    print(f"선택된 AID: {result.selected_aid_hex}")
    print(f"전체 성공 여부: {result.all_success}")
    print(f"총 RTT 합: {result.total_rtt_ms} ms")