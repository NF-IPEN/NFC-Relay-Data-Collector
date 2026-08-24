#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
main.py
=======
전체 지휘자. 어떤 채널/역할로 몇 번 잴지 정하고, 각 폴더의 부품을 불러 실행한다.

[원본 위치] ppse_measure_channal.py 의
  - 섹션 23 (CLI): build_arg_parser
  - 섹션 24 (Main): main

★ 5번 담당(Integration)이 주로 손볼 파일 ★
이 파일은 직접 일하지 않는다. 각 폴더(reader/channels/analysis)를 조립만 한다.

────────────────────────────────────────────────────────────────────
사용 예시
────────────────────────────────────────────────────────────────────
# 0) 실물 없이 mock 으로 baseline 30회 (지금 바로 가능)
python main.py baseline --use-mock --trials 30

# 1) 실물 ACR 로 baseline
python main.py baseline --trials 200

# 2) IPC 채널 (같은 PC, 터미널 2개)
#    터미널 A (card 역할):
python main.py ipc card --use-mock --trials 30
#    터미널 B (reader 역할):
python main.py ipc reader --trials 30

# 3) WiFi(TCP) 채널 (PC 2대)
#    카드쪽 PC:
python main.py relay-tcp card --use-mock --trials 30
#    리더쪽 PC:
python main.py relay-tcp reader --host <카드쪽 IP> --trials 30

# 4) Bluetooth 채널 (PyBluez 필요)
python main.py relay-bt card --use-mock --trials 30
python main.py relay-bt reader --target-mac <카드쪽 MAC> --trials 30

# 5) 집계/분석
python main.py analyze
"""

from __future__ import annotations
import argparse

from reader.baseline import run_baseline
from channels import ipc as ch_ipc
from channels import wifi as ch_wifi
from channels import bluetooth as ch_bt
from analysis.plot import run_analyze


def build_arg_parser():
    parser = argparse.ArgumentParser(
        description="NFC/EMV APDU relay channel timing experiment",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # --- baseline ---
    p_base = sub.add_parser("baseline", help="USB 직결 기준선 측정")
    p_base.add_argument("--trials", type=int, default=30)
    p_base.add_argument("--reader-substr", default="ACR122U")
    p_base.add_argument("--use-mock", action="store_true")

    # --- ipc (같은 PC) ---
    p_ipc = sub.add_parser("ipc", help="같은 PC 내 IPC relay")
    ipc_sub = p_ipc.add_subparsers(dest="role", required=True)

    ipc_card = ipc_sub.add_parser("card")
    ipc_card.add_argument("--reader-substr", default="ACR122U")
    ipc_card.add_argument("--use-mock", action="store_true")
    ipc_card.add_argument("--trials", type=int, default=30)

    ipc_reader = ipc_sub.add_parser("reader")
    ipc_reader.add_argument("--trials", type=int, default=30)

    # --- relay-tcp (WiFi) ---
    p_tcp = sub.add_parser("relay-tcp", help="TCP/WiFi APDU relay")
    tcp_sub = p_tcp.add_subparsers(dest="role", required=True)

    tcp_card = tcp_sub.add_parser("card")
    tcp_card.add_argument("--host", default="0.0.0.0")
    tcp_card.add_argument("--port", type=int, default=9999)
    tcp_card.add_argument("--reader-substr", default="ACR122U")
    tcp_card.add_argument("--use-mock", action="store_true")
    tcp_card.add_argument("--trials", type=int, default=30)

    tcp_reader = tcp_sub.add_parser("reader")
    tcp_reader.add_argument("--host", required=True)
    tcp_reader.add_argument("--port", type=int, default=9999)
    tcp_reader.add_argument("--trials", type=int, default=30)

    # --- relay-bt (Bluetooth) ---
    p_bt = sub.add_parser("relay-bt", help="Bluetooth RFCOMM APDU relay")
    bt_sub = p_bt.add_subparsers(dest="role", required=True)

    bt_card = bt_sub.add_parser("card")
    bt_card.add_argument("--reader-substr", default="ACR122U")
    bt_card.add_argument("--use-mock", action="store_true")
    bt_card.add_argument("--trials", type=int, default=30)

    bt_reader = bt_sub.add_parser("reader")
    bt_reader.add_argument("--target-mac", required=True)
    bt_reader.add_argument("--trials", type=int, default=30)

    # --- analyze ---
    p_an = sub.add_parser("analyze", help="결과 집계")
    p_an.add_argument("--results-dir", default="data")
    p_an.add_argument("--out-dir", default="data/summary")

    return parser


def main():
    args = build_arg_parser().parse_args()

    if args.command == "baseline":
        run_baseline(
            trials=args.trials,
            use_mock=args.use_mock,
            reader_substr=args.reader_substr,
        )

    elif args.command == "ipc":
        if args.role == "card":
            ch_ipc.run_card(
                use_mock=args.use_mock,
                reader_substr=args.reader_substr,
                trials=args.trials,
            )
        elif args.role == "reader":
            ch_ipc.run_reader(trials=args.trials)

    elif args.command == "relay-tcp":
        if args.role == "card":
            ch_wifi.run_card(
                host=args.host,
                port=args.port,
                use_mock=args.use_mock,
                reader_substr=args.reader_substr,
                trials=args.trials,
            )
        elif args.role == "reader":
            ch_wifi.run_reader(
                host=args.host,
                port=args.port,
                trials=args.trials,
            )

    elif args.command == "relay-bt":
        if args.role == "card":
            ch_bt.run_card(
                use_mock=args.use_mock,
                reader_substr=args.reader_substr,
                trials=args.trials,
            )
        elif args.role == "reader":
            ch_bt.run_reader(
                target_mac=args.target_mac,
                trials=args.trials,
            )

    elif args.command == "analyze":
        run_analyze(results_dir=args.results_dir, out_dir=args.out_dir)


if __name__ == "__main__":
    main()
