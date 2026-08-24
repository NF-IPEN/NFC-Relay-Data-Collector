"""
apdu/run_experiment.py — payment_flow.py를 반복 실행해 단계별 RTT를 CSV로 저장
------------------------------------------------------------------------------
담당: 동하 (APDU & Timing)

사용법 (터미널):
    python run_experiment.py --n 100
    python run_experiment.py --n 200 --out ../data/rtt_log.csv

주피터에서:
    %run run_experiment.py --n 100

[통합 관련 메모 - 하정님 core/logger.py 완성 시]
지금은 이 파일이 CSV 저장을 직접 담당하지만, 최종적으로는
core.logger.save_records(records) 같은 공용 함수로 교체될 예정입니다.
그때까지는 아래 write_csv() 함수만 통째로 교체하면 됩니다.

[통합 관련 메모 - 라희님 channels/*.py 완성 시]
지금은 get_temp_connection_from_pyscard()로 "릴레이 없는 정상 통신"만 측정합니다.
릴레이 채널이 붙으면, connection 인자 자리에 각 채널 모듈이 제공하는
"릴레이를 거친 connection-like 객체"를 넣기만 하면 동일한 run_payment_flow()가
그대로 재사용됩니다 (그래서 payment_flow.py를 채널에 의존하지 않게 설계했습니다).
"""

import argparse
import csv
import statistics
import sys
import time
from datetime import datetime
from collections import defaultdict

from payment_flow import (
    run_payment_flow,
    get_temp_connection_from_pyscard,
    MockConnection,
)


def wait_for_card_ready(connect_fn, timeout=15):
    """카드가 리더 위에 인식될 때까지 재시도."""
    print("카드를 리더 위에 올려주세요...")
    start = time.time()
    last_err = None
    while time.time() - start < timeout:
        try:
            conn = connect_fn()
            print("카드 인식 완료.")
            return conn
        except Exception as e:
            last_err = e
            time.sleep(0.3)
    print(f"[오류] 제한 시간 내 카드 인식 실패: {last_err}")
    sys.exit(1)


def run_n_times(connect_fn, n: int, channel_label: str):
    """
    전체 플로우를 n회 반복 실행하고, 매 회마다 새로 카드에 연결(connect)해
    실제 컨택리스 탭(tap) 상황과 유사하게 측정.
    """
    all_rows = []
    fail_count = 0

    for i in range(1, n + 1):
        connection = connect_fn()
        flow_result = run_payment_flow(connection)

        for step in flow_result.steps:
            all_rows.append({
                "iteration": i,
                "timestamp": datetime.now().isoformat(),
                "channel": channel_label,
                "step_name": step.step_name,
                "apdu_hex": step.apdu_hex,
                "rtt_ms": step.rtt_ms,
                "sw1": f"{step.sw1:02X}",
                "sw2": f"{step.sw2:02X}",
                "success": step.success,
                "note": step.note,
            })

        status = "OK" if flow_result.all_success else "PARTIAL/FAIL"
        print(f"[{i:4d}/{n}] 총RTT={flow_result.total_rtt_ms:8.3f} ms  "
              f"단계수={len(flow_result.steps)}  {status}")

        if not flow_result.all_success:
            fail_count += 1

    print(f"\n완료: 총 {n}회 중 {fail_count}회 일부 실패.")
    return all_rows


def write_csv(rows, out_path):
    if not rows:
        print("[경고] 저장할 데이터가 없습니다.")
        return
    fieldnames = list(rows[0].keys())
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"CSV 저장 완료: {out_path}")


def print_step_summary(rows):
    """단계(step_name)별 RTT 평균/표준편차 요약 출력."""
    by_step = defaultdict(list)
    for r in rows:
        if r["success"]:
            by_step[r["step_name"]].append(r["rtt_ms"])

    print("\n=== 단계별 RTT 요약 (성공한 시도만) ===")
    for step_name, rtts in by_step.items():
        mean = statistics.mean(rtts)
        std = statistics.stdev(rtts) if len(rtts) > 1 else 0.0
        print(f"  {step_name:25s} n={len(rtts):4d}  평균={mean:7.3f}ms  표준편차={std:6.3f}ms")


def main():
    parser = argparse.ArgumentParser(description="EMV 결제 플로우 반복 실행 및 RTT 로깅")
    parser.add_argument("--n", type=int, default=100, help="반복 횟수 (기본 100)")
    parser.add_argument("--out", type=str, default=None,
                         help="출력 CSV 경로 (기본: ../data/rtt_baseline_<timestamp>.csv)")
    parser.add_argument("--channel", type=str, default="baseline_no_relay",
                         help="채널 라벨 (기본: baseline_no_relay, 릴레이 붙으면 'usb'/'bluetooth'/'wifi' 등으로 지정)")
    parser.add_argument("--mock", action="store_true",
                         help="실제 리더 없이 MockConnection으로 로직만 테스트")
    args, _unknown = parser.parse_known_args()  # Jupyter -f 인자 무시

    out_path = args.out or f"../data/rtt_baseline_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

    if args.mock:
        print("[MOCK 모드] 실제 하드웨어 없이 로직만 검증합니다.")
        connect_fn = lambda: MockConnection(artificial_delay_ms=3.0)
    else:
        connect_fn = get_temp_connection_from_pyscard
        # 최초 1회는 카드 인식 대기 (이후 반복에서도 매번 connect_fn 호출)
        wait_for_card_ready(connect_fn)

    rows = run_n_times(connect_fn, args.n, args.channel)
    write_csv(rows, out_path)
    print_step_summary(rows)


if __name__ == "__main__":
    main()