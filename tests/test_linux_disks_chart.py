from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

HIGH_THROUGHPUT_AXIS_MAX = 1250.0
LEGACY_THROUGHPUT_AXIS_MAX = 130.0
SSD_ACCESS_AXIS_MAX = 1.0


def _load_disks_wrapper() -> ModuleType:
    wrapper_path = Path(__file__).resolve().parents[1] / "tools" / "linux" / "disks-benchmark-like.py"
    spec = importlib.util.spec_from_file_location("disks_benchmark_like", wrapper_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load Linux Disks wrapper from {wrapper_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_gnome_disks_like_chart_scales_throughput_axis_above_high_samples() -> None:
    disks_wrapper = _load_disks_wrapper()
    payload = {
        "device_size": 1000,
        "read_samples": [
            {"offset": 0, "mib_per_sec": 995.0},
            {"offset": 1000, "mib_per_sec": 1000.0},
        ],
        "write_samples": [
            {"offset": 0, "mib_per_sec": 820.0},
            {"offset": 1000, "mib_per_sec": 840.0},
        ],
        "access_time_samples": [{"offset": 500, "msec": 1.5}],
    }
    read_points = disks_wrapper._throughput_points(payload, "read_samples")
    write_points = disks_wrapper._throughput_points(payload, "write_samples")
    throughput_axis = disks_wrapper._nice_axis_max(
        disks_wrapper._max_y_value(read_points, write_points),
        disks_wrapper.MIN_THROUGHPUT_Y_MAX,
    )

    max_throughput = disks_wrapper._max_y_value(read_points, write_points)
    assert throughput_axis == HIGH_THROUGHPUT_AXIS_MAX
    assert throughput_axis > max_throughput
    assert throughput_axis > LEGACY_THROUGHPUT_AXIS_MAX


def test_gnome_disks_like_chart_preserves_legacy_minimum_throughput_axis() -> None:
    disks_wrapper = _load_disks_wrapper()

    assert disks_wrapper._nice_axis_max(90.0, disks_wrapper.MIN_THROUGHPUT_Y_MAX) == LEGACY_THROUGHPUT_AXIS_MAX


def test_gnome_disks_like_chart_scales_access_axis_for_ssd_latency() -> None:
    disks_wrapper = _load_disks_wrapper()
    payload = {
        "device_size": 1000,
        "read_samples": [
            {"offset": 0, "mib_per_sec": 250.0},
            {"offset": 1000, "mib_per_sec": 250.0},
        ],
        "write_samples": [
            {"offset": 0, "mib_per_sec": 200.0},
            {"offset": 1000, "mib_per_sec": 200.0},
        ],
        "access_time_samples": [
            {"offset": 0, "msec": 0.15},
            {"offset": 500, "msec": 0.85},
            {"offset": 1000, "msec": 0.2},
        ],
    }
    access_points = disks_wrapper._access_points(payload)
    access_axis = disks_wrapper._nice_axis_max(
        disks_wrapper._max_y_value(access_points),
        disks_wrapper.MIN_ACCESS_Y_MAX,
    )

    assert access_axis == SSD_ACCESS_AXIS_MAX
