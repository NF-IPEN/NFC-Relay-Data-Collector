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
    p_an.add_argument("--baseline-channel", default="baseline_usb")
    p_an.add_argument("--k", type=float, default=3.0)
    p_an.add_argument("--recursive", action="store_true")

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
        run_analyze(
            results_dir=args.results_dir,
            out_dir=args.out_dir,
            baseline_channel=args.baseline_channel,
            k=args.k,
            recursive=args.recursive,
        )


if __name__ == "__main__":
    main()
