#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

MIB = 1024 * 1024
DEFAULT_NUM_SAMPLES = 125
DEFAULT_SAMPLE_SIZE_MIB = 125
DEFAULT_NUM_ACCESS_SAMPLES = 125
CHART_WIDTH = 680
CHART_HEIGHT = 361
PLOT_TOP = 15
PLOT_BOTTOM = 324
RIGHT_GUTTER = 73
THROUGHPUT_Y_MAX = 130.0
ACCESS_Y_MAX = 50.0
MIB_TO_MBS = 1.048576
MIN_POINTS = 2


def _parse_args(argv: list[str]) -> tuple[str, int, int, int, list[str]]:
    parser = argparse.ArgumentParser(
        description=(
            "Python wrapper for disks-benchmark-like.sh. "
            "Converts --sample-size from MiB to bytes and renders a GNOME Disks-like chart."
        ),
        epilog="Additional unrecognized options are forwarded to the bash/C benchmark tool.",
    )
    parser.add_argument("--device", required=True, help="Block device path (example: /dev/sda).")
    parser.add_argument("--num-samples", type=int, default=DEFAULT_NUM_SAMPLES)
    parser.add_argument(
        "--sample-size",
        type=int,
        dest="sample_size_mib",
        default=DEFAULT_SAMPLE_SIZE_MIB,
        help="Sample size in MiB (wrapper converts to bytes for the C tool).",
    )
    parser.add_argument("--num-access-samples", type=int, default=DEFAULT_NUM_ACCESS_SAMPLES)

    args, passthrough = parser.parse_known_args(argv)

    if args.num_samples <= 0:
        raise SystemExit("--num-samples must be > 0")
    if args.sample_size_mib <= 0:
        raise SystemExit("--sample-size must be > 0 (MiB)")
    if args.num_access_samples <= 0:
        raise SystemExit("--num-access-samples must be > 0")

    return args.device, args.num_samples, args.sample_size_mib, args.num_access_samples, passthrough


def _extract_option_value(args: list[str], option: str) -> str | None:
    for index, token in enumerate(args):
        if token == option and index + 1 < len(args):
            return args[index + 1]
        if token.startswith(option + "="):
            return token.split("=", 1)[1]
    return None


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for candidate in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ):
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _throughput_points(payload: dict[str, Any], key: str) -> list[tuple[float, float]]:
    device_size = float(payload.get("device_size") or 1.0)
    samples = payload.get(key, [])
    points: list[tuple[float, float]] = []

    for item in samples:
        if not isinstance(item, dict) or "offset" not in item or "mib_per_sec" not in item:
            continue
        x_pct = (float(item["offset"]) / device_size) * 100.0
        y_mbs = float(item["mib_per_sec"]) * MIB_TO_MBS
        points.append((x_pct, y_mbs))

    points.sort(key=lambda point: point[0])
    return points


def _access_points(payload: dict[str, Any]) -> list[tuple[float, float]]:
    device_size = float(payload.get("device_size") or 1.0)
    samples = payload.get("access_time_samples", [])
    points: list[tuple[float, float]] = []

    for item in samples:
        if not isinstance(item, dict) or "offset" not in item:
            continue
        x_pct = (float(item["offset"]) / device_size) * 100.0
        y_ms = float(item.get("msec", 0.0))
        points.append((x_pct, y_ms))

    points.sort(key=lambda point: point[0])
    return points


def _compute_plot_left(font: ImageFont.FreeTypeFont | ImageFont.ImageFont) -> int:
    probe = Image.new("RGB", (10, 10))
    probe_draw = ImageDraw.Draw(probe)
    left_labels = [f"{i * 13} MB/s" for i in range(11)]
    max_width = max(probe_draw.textbbox((0, 0), text, font=font)[2] for text in left_labels)
    return max_width + 14


def _draw_grid_and_axes(
    draw: ImageDraw.ImageDraw,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    plot_left: int,
    plot_right: int,
) -> None:
    plot_w = plot_right - plot_left
    plot_h = PLOT_BOTTOM - PLOT_TOP

    draw.rectangle((plot_left, PLOT_TOP, plot_right, PLOT_BOTTOM), fill="#dedede")

    for i in range(11):
        x = plot_left + round((i / 10.0) * plot_w)
        draw.line((x, PLOT_TOP, x, PLOT_BOTTOM), fill="#9f9f9f", width=1)

    for i in range(11):
        y = PLOT_BOTTOM - round((i / 10.0) * plot_h)
        draw.line((plot_left, y, plot_right, y), fill="#9f9f9f", width=1)

    for i in range(11):
        x = plot_left + round((i / 10.0) * plot_w)
        label = f"{i * 10}%"
        bbox = draw.textbbox((0, 0), label, font=font)
        draw.text((x - (bbox[2] - bbox[0]) // 2, PLOT_BOTTOM + 4), label, fill="#f0f0f0", font=font)

    for i in range(11):
        y = PLOT_BOTTOM - round((i / 10.0) * plot_h)

        left_label = f"{i * 13} MB/s"
        left_bbox = draw.textbbox((0, 0), left_label, font=font)
        left_w = left_bbox[2] - left_bbox[0]
        left_h = left_bbox[3] - left_bbox[1]
        draw.text((plot_left - left_w - 8, y - left_h // 2), left_label, fill="#f0f0f0", font=font)

        right_label = f"{i * 5} ms"
        right_bbox = draw.textbbox((0, 0), right_label, font=font)
        right_h = right_bbox[3] - right_bbox[1]
        draw.text((plot_right + 8, y - right_h // 2), right_label, fill="#f0f0f0", font=font)


def _to_plot_xy(x_pct: float, y_val: float, y_max: float, plot_bounds: tuple[int, int]) -> tuple[float, float]:
    plot_left, plot_right = plot_bounds
    plot_w = plot_right - plot_left
    plot_h = PLOT_BOTTOM - PLOT_TOP
    x = plot_left + (x_pct / 100.0) * plot_w
    y = PLOT_BOTTOM - (y_val / y_max) * plot_h
    return x, y


def _draw_series(
    draw: ImageDraw.ImageDraw,
    points: list[tuple[float, float]],
    y_max: float,
    color: str,
    plot_bounds: tuple[int, int],
    width: int = 2,
) -> None:
    if len(points) < MIN_POINTS:
        return
    coords = [_to_plot_xy(x, y, y_max, plot_bounds) for x, y in points]
    draw.line(coords, fill=color, width=width)


def _draw_access_series(
    draw: ImageDraw.ImageDraw,
    points: list[tuple[float, float]],
    plot_bounds: tuple[int, int],
) -> None:
    if not points:
        return

    coords = [_to_plot_xy(x, y, ACCESS_Y_MAX, plot_bounds) for x, y in points]

    if len(coords) >= MIN_POINTS:
        draw.line(coords, fill=(153, 230, 153, 90), width=1)

    for x, y in coords:
        radius = 2
        draw.ellipse(
            (x - radius, y - radius, x + radius, y + radius),
            fill=(153, 230, 153, 180),
            outline=(153, 230, 153, 220),
        )


def _render_gnome_disks_like_chart(payload: dict[str, Any], output_path: Path) -> None:
    read_points = _throughput_points(payload, "read_samples")
    write_points = _throughput_points(payload, "write_samples")
    access_points = _access_points(payload)

    font = _load_font(14)
    plot_left = _compute_plot_left(font)
    plot_right = CHART_WIDTH - RIGHT_GUTTER
    plot_bounds = (plot_left, plot_right)

    image = Image.new("RGB", (CHART_WIDTH, CHART_HEIGHT), "#2f3136")
    draw = ImageDraw.Draw(image, "RGBA")

    _draw_grid_and_axes(draw, font, plot_left, plot_right)
    _draw_series(draw, read_points, THROUGHPUT_Y_MAX, "#5f66ff", plot_bounds)
    _draw_series(draw, write_points, THROUGHPUT_Y_MAX, "#ff5e5e", plot_bounds)
    _draw_access_series(draw, access_points, plot_bounds)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path)


def _prepare_json_output(passthrough: list[str]) -> tuple[Path, bool]:
    requested = _extract_option_value(passthrough, "--json-out")
    if requested is not None:
        return Path(requested), False

    with tempfile.NamedTemporaryFile(prefix="disks_bench_", suffix=".json", delete=False) as temp_file:
        return Path(temp_file.name), True


def _base_command(
    script_path: Path,
    device: str,
    num_samples: int,
    sample_size_mib: int,
    num_access_samples: int,
) -> list[str]:
    return [
        str(script_path),
        "--device",
        device,
        "--num-samples",
        str(num_samples),
        "--sample-size",
        str(sample_size_mib * MIB),
        "--num-access-samples",
        str(num_access_samples),
    ]


def _build_command(
    base_args: list[str],
    passthrough: list[str],
    json_out_path: Path,
    append_json_out: bool,
) -> list[str]:
    command = [*base_args, *passthrough]
    if append_json_out:
        command.extend(["--json-out", str(json_out_path)])
    return command


def _determine_chart_path(json_out_path: Path, used_temp_json: bool) -> Path:
    if used_temp_json:
        return Path.cwd() / "disks-benchmark-like_gnome_disks_like.png"
    return json_out_path.with_name(f"{json_out_path.stem}_gnome_disks_like.png")


def _load_payload(json_out_path: Path) -> tuple[dict[str, Any], str]:
    if not json_out_path.exists():
        raise RuntimeError("Benchmark completed but JSON output file was not created.")

    payload_text = json_out_path.read_text(encoding="utf-8")
    payload = json.loads(payload_text)
    if not isinstance(payload, dict):
        raise RuntimeError("Benchmark JSON payload is not an object.")

    return payload, payload_text


def main() -> int:
    device, num_samples, sample_size_mib, num_access_samples, passthrough = _parse_args(sys.argv[1:])
    script_path = Path(__file__).with_name("disks-benchmark-like.sh")
    json_out_path, used_temp_json = _prepare_json_output(passthrough)

    try:
        base_args = _base_command(
            script_path=script_path,
            device=device,
            num_samples=num_samples,
            sample_size_mib=sample_size_mib,
            num_access_samples=num_access_samples,
        )
        command = _build_command(
            base_args=base_args,
            passthrough=passthrough,
            json_out_path=json_out_path,
            append_json_out=used_temp_json,
        )

        result = subprocess.run(command, check=False, capture_output=True, text=True)

        if result.stdout:
            print(result.stdout, end="")
        if result.stderr:
            print(result.stderr, end="", file=sys.stderr)
        if result.returncode != 0:
            return result.returncode

        try:
            payload, payload_text = _load_payload(json_out_path)
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            return 1

        if used_temp_json:
            print(payload_text)

        chart_path = _determine_chart_path(json_out_path, used_temp_json)
        _render_gnome_disks_like_chart(payload, chart_path)
        print(f"Chart saved to: {chart_path}", file=sys.stderr)
        return 0
    finally:
        if used_temp_json:
            json_out_path.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
