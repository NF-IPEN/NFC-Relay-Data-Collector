# -*- coding: utf-8 -*-
"""
core/literature.py
==================

선행 논문에서 제시된 기준값을 관리하고,
실험에서 측정한 전체 RTT를 문헌값과 비교한다.

이 모듈은 탐지 임계값을 결정하지 않는다.
문헌값은 현재 실험 환경과 동일하지 않을 수 있으므로
비교 및 참고 목적으로만 사용한다.

[원본 위치] ppse_measure_channal.py 의
  - 섹션 1 (Literature reference)
    - LITERATURE
    - compare_to_literature
"""

from __future__ import annotations


LITERATURE = {
    "normal_total_ms": 151.6,
    "bt_relay_total_ms": 665.0,
    "bt_relay_ratio": 665.0 / 151.6,
    "bt_overhead_per_cmd_best_ms": 50.0,
    "bt_overhead_per_cmd_worst_ms": 80.0,
    "wifi_estimated_total_ms": 1500.0,

    # 참고값
    "fwi_recommended_ms": 78.0,
    "fwi_spec_upper_bound_ms": 5000.0,
    "pos_observed_timeout_s": 35.0,
    "passport_reader_timeout_s": 5.2,
}


def compare_to_literature(
    measured_total_ms: float,
    channel: str
) -> dict:
    """
    측정된 전체 RTT를 선행 연구의 문헌값과 비교한다.

    Args:
        measured_total_ms:
            하나의 transaction에서 측정된 전체 RTT(ms)

        channel:
            실험 채널 이름.
            기존 프로젝트에서 사용하는 channel 이름을 그대로 사용한다.

    Returns:
        문헌 기준값, 측정값 대비 비율,
        각 참고 기준의 통과 여부를 포함한 dict.
    """

    out = {
        "channel": channel,
        "measured_total_ms": measured_total_ms,
    }

    if channel == "baseline_usb":
        out["literature_ref_ms"] = LITERATURE["normal_total_ms"]
        out["literature_reference_type"] = "reported"

    elif channel == "relay_bt":
        out["literature_ref_ms"] = LITERATURE["bt_relay_total_ms"]
        out["literature_reference_type"] = "reported"

    elif channel == "relay_tcp_wifi":
        out["literature_ref_ms"] = LITERATURE["wifi_estimated_total_ms"]
        out["literature_reference_type"] = "estimate"

    else:
        out["literature_ref_ms"] = None
        out["literature_reference_type"] = None

    ref = out["literature_ref_ms"]

    if ref is not None and ref > 0:
        out["ratio_measured_over_literature"] = (
            measured_total_ms / ref
        )
    else:
        out["ratio_measured_over_literature"] = None

    out["passes_fwi_spec_upper_5s"] = (
        measured_total_ms
        < LITERATURE["fwi_spec_upper_bound_ms"]
    )

    out["passes_pos_observed_35s"] = (
        measured_total_ms
        < LITERATURE["pos_observed_timeout_s"] * 1000
    )

    out["passes_fwi_recommended_78ms"] = (
        measured_total_ms
        < LITERATURE["fwi_recommended_ms"]
    )

    return out