# -*- coding: utf-8 -*-
"""
analysis/plot.py
================
data/ 에 쌓인 세션 CSV들을 읽어 채널별로 집계하고,
문헌값과 비교표/그래프를 만든다.

[원본 위치] ppse_measure_channal.py 의
  - 섹션 20 (Result loading): load_all_sessions
  - 섹션 21 (Statistics): summarize
  - 섹션 22 (Output): write_csv, write_markdown, plot_bar
  - 섹션 22 뒤 (run_analyze)

★ 4번 담당(Data & Analysis)이 주로 손볼 파일 ★
이 파일은 측정 코드에 의존하지 않는다. CSV 칸 이름(core/timing.CSV_FIELDS)만
알면 되므로, 가짜 CSV를 data/ 에 넣어두면 지금 바로 개발/테스트할 수 있다.

--------------------------------------------------------------------------
[병합 내역]
문헌값 비교(summarize/write_csv/write_markdown/plot_bar)는 원본 그대로 두고,
아래 두 가지를 추가함:
  1) build_session_totals / compute_threshold
     - baseline 채널(기본 usb) 세션 총 RTT의 평균+k*표준편차를 임계값으로 잡고,
       각 채널이 relay 의심 구간인지(above_threshold) 판정
  2) plot_histogram / plot_boxplot
     - 채널별 "세션 총 RTT" 분포를 히스토그램/박스플롯으로 시각화
     - 히스토그램에는 위 threshold를 점선으로 표시해 채널 간 분리 정도를 눈으로 확인
run_analyze()에서 문헌값 비교와 threshold 기반 탐지를 모두 실행하도록 합침.
--------------------------------------------------------------------------
"""

from __future__ import annotations
import argparse
import csv
import statistics
from collections import defaultdict
from pathlib import Path

from core.literature import LITERATURE, compare_to_literature


# ---------------------------------------------------------------------
# CSV 로딩  (원본 섹션 20)
# ---------------------------------------------------------------------

def load_all_sessions(results_dir: Path):
    by_channel = defaultdict(lambda: defaultdict(list))

    for csv_path in sorted(results_dir.glob("*.csv")):
        if csv_path.name in {"channel_comparison.csv"}:
            continue

        try:
            with open(csv_path, encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    channel = row.get("channel")
                    session_id = row.get("session_id")
                    rtt = row.get("rtt_ms")
                    if not channel or not session_id or not rtt:
                        continue
                    by_channel[channel][session_id].append(float(rtt))
        except Exception as e:
            print(f"CSV 읽기 실패: {csv_path}: {e}")

    return by_channel


# ---------------------------------------------------------------------
# 통계  (원본 섹션 21)
# ---------------------------------------------------------------------

def summarize(by_channel):
    rows = []

    for channel, sessions in by_channel.items():
        totals = []
        all_cmd_rtts = []

        for sid, rtts in sessions.items():
            if not rtts:
                continue
            totals.append(sum(rtts))
            all_cmd_rtts.extend(rtts)

        if not totals:
            continue

        mean_total = statistics.mean(totals)
        std_total = statistics.pstdev(totals) if len(totals) > 1 else 0.0
        mean_cmd = statistics.mean(all_cmd_rtts)
        std_cmd = statistics.pstdev(all_cmd_rtts) if len(all_cmd_rtts) > 1 else 0.0

        # trial 경계를 넘는 RTT 차이는 jitter에 포함하지 않음
        all_diffs = []
        for rtts in sessions.values():
            if len(rtts) < 2:
                continue
            for i in range(1, len(rtts)):
                all_diffs.append(abs(rtts[i] - rtts[i - 1]))

        jitter_cmd = (
            statistics.pstdev(all_diffs) if len(all_diffs) > 1
            else (all_diffs[0] if all_diffs else 0.0)
        )

        lit = compare_to_literature(mean_total, channel)

        rows.append({
            "channel": channel,
            "n_sessions": len(totals),
            "n_commands_total": len(all_cmd_rtts),
            "mean_total_ms": round(mean_total, 2),
            "std_total_ms": round(std_total, 2),
            "mean_per_cmd_ms": round(mean_cmd, 2),
            "std_per_cmd_ms": round(std_cmd, 2),
            "jitter_per_cmd_ms": round(jitter_cmd, 2),
            "literature_ref_ms": lit["literature_ref_ms"],
            "literature_reference_type": lit["literature_reference_type"],
            "ratio_vs_literature": (
                round(lit["ratio_measured_over_literature"], 3)
                if lit["ratio_measured_over_literature"] is not None else None
            ),
            "passes_fwi_upper_5s": lit["passes_fwi_spec_upper_5s"],
            "passes_pos_observed_35s": lit["passes_pos_observed_35s"],
            "passes_fwi_recommended_78ms": lit["passes_fwi_recommended_78ms"],
        })

    return rows


# ---------------------------------------------------------------------
# threshold 기반 relay 탐지  (병합 추가분)
# ---------------------------------------------------------------------

def build_session_totals(by_channel):
    """채널별 '세션 1회 = 총 RTT(ms)' 리스트. 히스토그램/박스플롯/threshold 계산에 사용."""
    totals_by_channel = {}
    for channel, sessions in by_channel.items():
        totals = [sum(rtts) for rtts in sessions.values() if rtts]
        if totals:
            totals_by_channel[channel] = totals
    return totals_by_channel


def compute_threshold(rows: list, baseline_channel: str = "usb", k: float = 3.0):
    """
    summarize()가 만든 rows에 채널별 relay 탐지 threshold/판정을 덧붙인다.
    threshold = baseline 채널의 mean_total_ms + k * std_total_ms
    (문헌값과는 별개로, 이번 실측 baseline 대비 이상치를 잡는 실전 임계값)
    """
    baseline_row = next((r for r in rows if r["channel"] == baseline_channel), None)
    if baseline_row is None:
        print(f"[경고] baseline 채널 '{baseline_channel}'이 데이터에 없어 threshold를 계산할 수 없습니다.")
        return rows

    threshold = baseline_row["mean_total_ms"] + k * baseline_row["std_total_ms"]

    for r in rows:
        r["detection_threshold_ms"] = round(threshold, 2)
        r["margin_from_threshold_ms"] = round(r["mean_total_ms"] - threshold, 2)
        r["above_threshold"] = r["mean_total_ms"] > threshold

    return rows


# ---------------------------------------------------------------------
# 출력  (원본 섹션 22)
# ---------------------------------------------------------------------

def write_csv(rows, out_path: Path):
    if not rows:
        print("결과가 없어 CSV를 생성하지 않습니다.")
        return

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"요약 CSV 저장: {out_path}")


def write_markdown(rows, out_path: Path):
    if not rows:
        return

    out_path.parent.mkdir(parents=True, exist_ok=True)
    has_detection = "above_threshold" in rows[0]

    header = (
        "| 채널 | 세션수 | 평균 총 RTT(ms) | 표준편차(ms) | 명령당 평균(ms) | "
        "지터(ms) | 문헌 기준(ms) | 문헌 유형 | 실측/문헌 | "
        "5초 기준 | POS 35초 | 78ms 권장 기준"
    )
    sep = "|---|---:|---:|---:|---:|---:|---:|---|---:|---|---|---"
    if has_detection:
        header += " | 탐지 threshold(ms) | margin(ms) | relay 의심 |"
        sep += "|---:|---:|---|"
    else:
        header += " |"
        sep += "|"

    lines = ["# 채널별 APDU RTT 실측 vs 문헌값 비교\n", header, sep]

    for r in rows:
        line = (
            f"| {r['channel']} "
            f"| {r['n_sessions']} "
            f"| {r['mean_total_ms']} "
            f"| {r['std_total_ms']} "
            f"| {r['mean_per_cmd_ms']} "
            f"| {r['jitter_per_cmd_ms']} "
            f"| {r['literature_ref_ms']} "
            f"| {r['literature_reference_type']} "
            f"| {r['ratio_vs_literature']} "
            f"| {'O' if r['passes_fwi_upper_5s'] else 'X'} "
            f"| {'O' if r['passes_pos_observed_35s'] else 'X'} "
            f"| {'O' if r['passes_fwi_recommended_78ms'] else 'X'} "
        )
        if has_detection:
            line += (
                f"| {r['detection_threshold_ms']} "
                f"| {r['margin_from_threshold_ms']} "
                f"| {'O' if r['above_threshold'] else 'X'} |"
            )
        else:
            line += "|"
        lines.append(line)

    lines.append("\n## 문헌 기준값\n")
    lines.append(
        "문헌값은 본 실험과 동일 조건의 절대 benchmark가 아니라 참고 기준값으로 사용한다.\n"
    )
    for key, value in LITERATURE.items():
        lines.append(f"- `{key}` = {value}")

    if has_detection:
        lines.append(
            "\n탐지 threshold는 baseline 채널의 (평균 + k*표준편차)로 계산한 "
            "실측 기준 임계값이며, 문헌 기준값과는 별개의 지표다.\n"
        )

    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"요약 Markdown 저장: {out_path}")


def plot_bar(rows, out_path: Path):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib 미설치. 그래프를 생략합니다.")
        return

    if not rows:
        return

    out_path.parent.mkdir(parents=True, exist_ok=True)

    channels = [r["channel"] for r in rows]
    measured = [r["mean_total_ms"] for r in rows]
    literature = [
        r["literature_ref_ms"] if r["literature_ref_ms"] is not None else 0
        for r in rows
    ]

    x = range(len(channels))
    width = 0.35

    fig, ax = plt.subplots(figsize=(9, 5))
    ax.bar([i - width / 2 for i in x], measured, width, label="Measured")
    ax.bar([i + width / 2 for i in x], literature, width, label="Literature")
    ax.set_xticks(list(x))
    ax.set_xticklabels(channels, rotation=15)
    ax.set_ylabel("Total session RTT (ms)")
    ax.set_title("APDU relay latency: measured vs literature")
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    print(f"그래프 저장: {out_path}")


def plot_histogram(totals_by_channel: dict, threshold, out_path: Path):
    """채널별 세션 총 RTT 분포 히스토그램. threshold가 있으면 점선으로 표시."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib 미설치. 히스토그램을 생략합니다.")
        return

    if not totals_by_channel:
        return

    out_path.parent.mkdir(parents=True, exist_ok=True)
    channels = sorted(totals_by_channel.keys())

    fig, axes = plt.subplots(len(channels), 1, figsize=(8, 3 * len(channels)), sharex=True)
    if len(channels) == 1:
        axes = [axes]

    for ax, channel in zip(axes, channels):
        values = totals_by_channel[channel]
        ax.hist(values, bins=min(30, max(5, len(values) // 2)),
                 alpha=0.7, color="steelblue", edgecolor="black")
        if threshold is not None:
            ax.axvline(threshold, color="red", linestyle="--",
                        label=f"threshold={threshold:.1f}ms")
            ax.legend()
        ax.set_title(f"{channel} (n={len(values)} sessions)")
        ax.set_ylabel("count")

    axes[-1].set_xlabel("Session total RTT (ms)")
    fig.suptitle("Session Total RTT Distribution by Channel")
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    print(f"히스토그램 저장: {out_path}")


def plot_boxplot(totals_by_channel: dict, out_path: Path):
    """채널별 세션 총 RTT 박스플롯."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib 미설치. 박스플롯을 생략합니다.")
        return

    if not totals_by_channel:
        return

    out_path.parent.mkdir(parents=True, exist_ok=True)
    channels = sorted(totals_by_channel.keys())
    data = [totals_by_channel[ch] for ch in channels]

    fig, ax = plt.subplots(figsize=(7, 5))
    ax.boxplot(data, tick_labels=channels, showfliers=True)
    ax.set_ylabel("Session total RTT (ms)")
    ax.set_title("Session Total RTT Boxplot by Channel")
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    print(f"박스플롯 저장: {out_path}")


# ---------------------------------------------------------------------
# 실행 진입점
# ---------------------------------------------------------------------

def run_analyze(
    results_dir: str = "data",
    out_dir: str = "data/summary",
    baseline_channel: str = "usb",
    k: float = 3.0,
):
    results_dir_p = Path(results_dir)
    out_dir_p = Path(out_dir)

    by_channel = load_all_sessions(results_dir_p)
    rows = summarize(by_channel)
    rows = compute_threshold(rows, baseline_channel=baseline_channel, k=k)

    write_csv(rows, out_dir_p / "channel_comparison.csv")
    write_markdown(rows, out_dir_p / "channel_comparison.md")
    plot_bar(rows, out_dir_p / "channel_comparison.png")

    totals_by_channel = build_session_totals(by_channel)
    threshold = next(
        (r["detection_threshold_ms"] for r in rows if "detection_threshold_ms" in r),
        None,
    )
    plot_histogram(totals_by_channel, threshold, out_dir_p / "histogram.png")
    plot_boxplot(totals_by_channel, out_dir_p / "boxplot.png")

    for row in rows:
        print(row)

    return rows


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="채널별 RTT 세션 분석 (문헌값 비교 + threshold 탐지)")
    parser.add_argument("--data-dir", default="data", help="세션 CSV들이 있는 폴더")
    parser.add_argument("--out-dir", default="data/summary", help="결과 저장 폴더")
    parser.add_argument("--baseline-channel", default="usb", help="threshold 계산 기준 채널")
    parser.add_argument("--k", type=float, default=3.0, help="threshold = baseline_mean + k*std")
    args = parser.parse_args()

    run_analyze(
        results_dir=args.data_dir,
        out_dir=args.out_dir,
        baseline_channel=args.baseline_channel,
        k=args.k,
    )