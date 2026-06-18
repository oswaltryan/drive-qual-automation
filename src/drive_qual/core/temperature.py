#!/usr/bin/env python3
# ruff: noqa: I001, PLR0912, PLR0915, PLR2004
"""
Single script to parse raw temp TXT + disk test LOG files and plot speed vs temp.

Modes:
1) Targeted:
   python plotter.py --log disk_test.log --txt 02181235.TXT 02190515.TXT
2) Auto directory matching (default):
   python plotter.py --dir .

For auto mode, each .log is matched to .txt files by overlapping timestamps.
One plot + merged CSV is produced per .log file.
"""

import argparse
import json
import re
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


TEMP_MIN = -30
TEMP_MAX = 60
SPEED_MAX = 2000
AUTO_OFFSET_MAX_HOURS = 6
LOG_LINE_RE = re.compile(r"^\[(?P<ts>.+?)\]\s+(?P<msg>.*)$")
SNAPSHOT_TIMESTAMP_COLUMN = "timestamp"
SNAPSHOT_TEMPERATURE_C_COLUMN = "temperature_c"
SNAPSHOT_TEMPERATURE_F_COLUMN = "temperature_f"
PROFILE_SERIES = [
    ("SEQUENTIAL", "read", "Sequential Read", "#1f77b4", "-"),
    ("SEQUENTIAL", "write", "Sequential Write", "#ff7f0e", "-"),
    ("RANDOM", "read", "Random Read", "#2ca02c", "--"),
    ("RANDOM", "write", "Random Write", "#d62728", "--"),
]


def parse_temp_offset_arg(value: str) -> float | None:
    text = str(value).strip().lower()
    if text in {"auto", "detect", "autodetect"}:
        return None
    return float(text)


def parse_temp_file(path: Path) -> pd.DataFrame:
    rows = []
    with path.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            if not line.startswith("AT"):
                continue
            parts = line.split()
            if len(parts) < 5:
                continue
            ts = f"{parts[1]} {parts[2]}"
            try:
                temp1 = float(parts[4])
            except ValueError:
                continue
            rows.append((pd.to_datetime(ts, errors="coerce"), temp1))

    if not rows:
        return pd.DataFrame(columns=["Timestamp", "Temp1"])

    df = pd.DataFrame(rows, columns=["Timestamp", "Temp1"]).dropna(subset=["Timestamp"])
    return df.sort_values("Timestamp")


def parse_snapshot_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    if df.empty:
        return pd.DataFrame(columns=["Timestamp", "Temp1"])
    if SNAPSHOT_TIMESTAMP_COLUMN not in df or SNAPSHOT_TEMPERATURE_C_COLUMN not in df:
        return pd.DataFrame(columns=["Timestamp", "Temp1"])

    timestamp_text = df[SNAPSHOT_TIMESTAMP_COLUMN].astype(str).str.replace(r"(?:Z|[+-]\d\d:\d\d)$", "", regex=True)
    timestamps = pd.to_datetime(timestamp_text, errors="coerce")
    parsed = pd.DataFrame(
        {
            "Timestamp": timestamps,
            "Temp1": pd.to_numeric(df[SNAPSHOT_TEMPERATURE_C_COLUMN], errors="coerce"),
        }
    )
    return parsed.dropna(subset=["Timestamp", "Temp1"]).sort_values("Timestamp").reset_index(drop=True)


def parse_log_file(path: Path) -> tuple[pd.DataFrame, str]:
    speed_rows = []
    capacities = []

    speed_re = re.compile(
        r"^\[(?P<ts>.+?)\]\s+(?P<mode>SEQUENTIAL|RANDOM)\s+(?P<op>write|read):\s+(?P<speed>[\d.]+)\s+MiB/s",
        re.IGNORECASE,
    )
    cap_re = re.compile(r"Capacity:\s*total=(?P<total>[^,]+),\s*free=(?P<free>.+)$")

    with path.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            cap_m = cap_re.search(line)
            if cap_m:
                capacities.append(f"{cap_m.group('total').strip()} total")

            m = speed_re.search(line)
            if not m:
                continue
            ts = pd.to_datetime(m.group("ts"), errors="coerce")
            if pd.isna(ts):
                continue
            speed = float(m.group("speed"))
            mode = m.group("mode").upper()
            op = m.group("op").lower()
            speed_rows.append((ts, mode, op, speed))

    if not speed_rows:
        return pd.DataFrame(columns=["Timestamp", "Mode", "Operation", "SpeedMiB"]), "Unknown capacity"

    speed_df = pd.DataFrame(speed_rows, columns=["Timestamp", "Mode", "Operation", "SpeedMiB"])
    speed_df = speed_df.sort_values("Timestamp").reset_index(drop=True)
    capacity_text = ", ".join(sorted(set(capacities))) if capacities else "Unknown capacity"
    return speed_df, capacity_text


def parse_log_time_range(path: Path) -> tuple[pd.Timestamp | None, pd.Timestamp | None]:
    first_ts = None
    last_ts = None

    with path.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            m = LOG_LINE_RE.match(line.strip())
            if not m:
                continue
            ts = pd.to_datetime(m.group("ts"), errors="coerce")
            if pd.isna(ts):
                continue
            if first_ts is None:
                first_ts = ts
            last_ts = ts

    return first_ts, last_ts


def infer_device_id(log_path: Path) -> str:
    serial_re = re.compile(r"Apricorn DUT Serial\s*=\s*(?P<serial>\S+)")
    with log_path.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            m = serial_re.search(line)
            if m:
                return m.group("serial")

    name_match = re.match(r".*?_(?P<id>[A-Za-z0-9]+)_\d{8}_\d{6}$", log_path.stem)
    if name_match:
        return name_match.group("id")
    return log_path.stem


def parse_failure_events(log_path: Path) -> pd.DataFrame:
    rows = []
    fio_error_re = re.compile(r"^FIO_ERROR\s+(?P<op>\w+)\s+(?P<payload>\{.*\})$")
    stage_re = re.compile(r"Failure detected during\s+(?P<stage>[a-z_]+)\.", re.IGNORECASE)

    with log_path.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            m = LOG_LINE_RE.match(line)
            if not m:
                continue

            ts = pd.to_datetime(m.group("ts"), errors="coerce")
            if pd.isna(ts):
                continue
            msg = m.group("msg")

            fio_m = fio_error_re.match(msg)
            if fio_m:
                op = fio_m.group("op").lower()
                payload = fio_m.group("payload")
                returncode = None
                err_excerpt = ""
                parse_error = ""
                try:
                    err_obj = json.loads(payload)
                    returncode = err_obj.get("returncode")
                    err_excerpt = (err_obj.get("stderr") or err_obj.get("stdout") or "").replace("\n", " ").strip()
                    parse_error = str(err_obj.get("parse_error") or "")
                except json.JSONDecodeError:
                    err_excerpt = payload[:300]
                    parse_error = "json_decode_error"

                rows.append(
                    {
                        "Timestamp": ts,
                        "FailureSource": "FIO_ERROR",
                        "FailureStage": op,
                        "ReturnCode": returncode,
                        "ErrorExcerpt": err_excerpt[:300],
                        "ParseError": parse_error,
                    }
                )
                continue

            stage_m = stage_re.search(msg)
            if stage_m:
                rows.append(
                    {
                        "Timestamp": ts,
                        "FailureSource": "FAILURE_DETECTED",
                        "FailureStage": stage_m.group("stage").lower(),
                        "ReturnCode": None,
                        "ErrorExcerpt": "",
                        "ParseError": "",
                    }
                )

    if not rows:
        return pd.DataFrame(
            columns=[
                "Timestamp",
                "FailureSource",
                "FailureStage",
                "ReturnCode",
                "ErrorExcerpt",
                "ParseError",
            ]
        )

    df = pd.DataFrame(rows).sort_values("Timestamp").reset_index(drop=True)
    df["FailureIndex"] = range(1, len(df) + 1)
    return df


def build_failure_temp_rows(
    log_path: Path,
    txt_paths: list[Path],
    temp_offset_hours: float | None,
    max_temp_gap_sec: int,
) -> pd.DataFrame:
    failure_df = parse_failure_events(log_path)
    if failure_df.empty:
        return pd.DataFrame()

    speed_df, _ = parse_log_file(log_path)
    temp_df, _ = load_aligned_temp_df(
        txt_paths=txt_paths,
        speed_df=speed_df,
        temp_offset_hours=temp_offset_hours,
        max_temp_gap_sec=max_temp_gap_sec,
    )
    if temp_df.empty:
        out = failure_df.copy()
        out["Temp1"] = pd.NA
        out["TempTimestamp"] = pd.NaT
        out["TempDeltaSec"] = pd.NA
    else:
        out = pd.merge_asof(
            failure_df.sort_values("Timestamp"),
            temp_df.sort_values("Timestamp").rename(columns={"Timestamp": "TempTimestamp"}),
            left_on="Timestamp",
            right_on="TempTimestamp",
            direction="nearest",
            tolerance=pd.Timedelta(seconds=max_temp_gap_sec),
        )
        out["TempDeltaSec"] = (out["Timestamp"] - out["TempTimestamp"]).dt.total_seconds().abs()

    out.insert(0, "LogFile", log_path.name)
    out.insert(1, "Device", infer_device_id(log_path))
    out["MatchedTxtFiles"] = ",".join(p.name for p in txt_paths)
    return out


def export_failure_temps_csv(
    pairs: list[tuple[Path, list[Path]]],
    out_csv: Path,
    temp_offset_hours: float | None,
    max_temp_gap_sec: int,
) -> None:
    all_rows = []
    for log_path, txt_paths in pairs:
        rows = build_failure_temp_rows(
            log_path=log_path,
            txt_paths=txt_paths,
            temp_offset_hours=temp_offset_hours,
            max_temp_gap_sec=max_temp_gap_sec,
        )
        if not rows.empty:
            all_rows.append(rows)

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    if not all_rows:
        empty = pd.DataFrame(
            columns=[
                "LogFile",
                "Device",
                "FailureIndex",
                "Timestamp",
                "FailureSource",
                "FailureStage",
                "Temp1",
                "TempTimestamp",
                "TempDeltaSec",
                "ReturnCode",
                "ErrorExcerpt",
                "ParseError",
                "MatchedTxtFiles",
            ]
        )
        empty.to_csv(out_csv, index=False)
        print(f"[ok] no failures found. Wrote empty CSV: {out_csv}")
        return

    combined = pd.concat(all_rows, ignore_index=True)
    keep_cols = [
        "LogFile",
        "Device",
        "FailureIndex",
        "Timestamp",
        "FailureSource",
        "FailureStage",
        "Temp1",
        "TempTimestamp",
        "TempDeltaSec",
        "ReturnCode",
        "ErrorExcerpt",
        "ParseError",
        "MatchedTxtFiles",
    ]
    combined = combined[keep_cols]
    combined.to_csv(out_csv, index=False)
    print(f"[ok] failure temperature CSV: {out_csv}")
    print(f"  rows: {len(combined)}")


def get_time_range(df: pd.DataFrame) -> tuple[pd.Timestamp | None, pd.Timestamp | None]:
    if df.empty:
        return None, None
    return df["Timestamp"].min(), df["Timestamp"].max()


def ranges_overlap(a0, a1, b0, b1) -> bool:
    if any(x is None for x in (a0, a1, b0, b1)):
        return False
    return (a0 <= b1) and (b0 <= a1)


def merge_speed_temp_nearest(
    temp_df: pd.DataFrame,
    speed_df: pd.DataFrame,
    temp_offset_hours: float,
    max_temp_gap_sec: int,
) -> pd.DataFrame:
    temp_shifted = temp_df.copy()
    speed_sorted = speed_df.sort_values("Timestamp").copy()
    temp_shifted["Timestamp"] = temp_shifted["Timestamp"] + pd.to_timedelta(temp_offset_hours, unit="h")
    temp_shifted = temp_shifted.sort_values("Timestamp").rename(columns={"Timestamp": "TempTimestamp"})

    merged = pd.merge_asof(
        speed_sorted,
        temp_shifted,
        left_on="Timestamp",
        right_on="TempTimestamp",
        direction="nearest",
        tolerance=pd.Timedelta(seconds=max_temp_gap_sec),
    )
    merged["TempDeltaSec"] = (merged["Timestamp"] - merged["TempTimestamp"]).dt.total_seconds().abs()
    return merged


def auto_detect_temp_offset_hours(
    temp_df: pd.DataFrame,
    speed_df: pd.DataFrame,
    max_temp_gap_sec: int,
) -> float:
    if temp_df.empty or speed_df.empty:
        return 0.0

    temp_df = temp_df.sort_values("Timestamp")
    speed_df = speed_df.sort_values("Timestamp")

    temp_start = temp_df["Timestamp"].min()
    temp_end = temp_df["Timestamp"].max()
    temp_mid = temp_start + (temp_end - temp_start) / 2

    speed_anchors = (
        speed_df.assign(_MinuteBlock=speed_df["Timestamp"].dt.floor("1min"))
        .drop_duplicates("_MinuteBlock")
        ["Timestamp"]
        .tolist()
    )

    max_offset_seconds = int(AUTO_OFFSET_MAX_HOURS * 3600)
    candidate_seconds = {0}
    for temp_anchor in (temp_start, temp_mid, temp_end):
        for speed_anchor in speed_anchors:
            delta_seconds = int(round((speed_anchor - temp_anchor).total_seconds()))
            if abs(delta_seconds) <= max_offset_seconds:
                candidate_seconds.add(delta_seconds)

    best_key = None
    best_offset_seconds = 0
    zero_metrics = None
    best_metrics = None
    for offset_seconds in sorted(candidate_seconds):
        merged = merge_speed_temp_nearest(temp_df, speed_df, offset_seconds / 3600.0, max_temp_gap_sec)
        usable = merged[
            merged["Temp1"].notna()
            & (merged["SpeedMiB"] < SPEED_MAX)
            & merged["Temp1"].between(TEMP_MIN, TEMP_MAX, inclusive="both")
        ]
        matched_count = len(usable)
        if matched_count:
            matched_rows = usable[["Timestamp", "TempDeltaSec"]]
            span_sec = float((matched_rows["Timestamp"].max() - matched_rows["Timestamp"].min()).total_seconds())
            median_delta_sec = float(matched_rows["TempDeltaSec"].median())
            temp_span = float(usable["Temp1"].max() - usable["Temp1"].min())
        else:
            span_sec = -1.0
            median_delta_sec = float("inf")
            temp_span = -1.0

        key = (matched_count, temp_span, span_sec, -median_delta_sec, -abs(offset_seconds))
        metrics = {
            "matched_count": matched_count,
            "temp_span": temp_span,
            "span_sec": span_sec,
        }
        if offset_seconds == 0:
            zero_metrics = metrics
        if best_key is None or key > best_key:
            best_key = key
            best_offset_seconds = offset_seconds
            best_metrics = metrics

    if zero_metrics and best_metrics:
        zero_good_enough = (
            zero_metrics["matched_count"] >= max(50, int(best_metrics["matched_count"] * 0.5))
            and zero_metrics["temp_span"] >= best_metrics["temp_span"] * 0.8
            and zero_metrics["span_sec"] >= best_metrics["span_sec"] * 0.5
        )
        if zero_good_enough:
            return 0.0

    return best_offset_seconds / 3600.0


def resolve_temp_offset_hours(
    temp_df: pd.DataFrame,
    speed_df: pd.DataFrame,
    temp_offset_hours: float | None,
    max_temp_gap_sec: int,
) -> float:
    if temp_offset_hours is not None:
        return temp_offset_hours
    return auto_detect_temp_offset_hours(temp_df=temp_df, speed_df=speed_df, max_temp_gap_sec=max_temp_gap_sec)


def load_aligned_temp_df(
    txt_paths: list[Path],
    speed_df: pd.DataFrame,
    temp_offset_hours: float | None,
    max_temp_gap_sec: int,
) -> tuple[pd.DataFrame, list[tuple[str, float]]]:
    aligned_frames = []
    offset_details = []

    for txt_path in txt_paths:
        tdf = parse_temp_file(txt_path)
        if tdf.empty:
            continue

        resolved_offset_hours = resolve_temp_offset_hours(
            temp_df=tdf,
            speed_df=speed_df,
            temp_offset_hours=temp_offset_hours,
            max_temp_gap_sec=max_temp_gap_sec,
        )
        shifted = tdf.copy()
        shifted["Timestamp"] = shifted["Timestamp"] + pd.to_timedelta(resolved_offset_hours, unit="h")
        aligned_frames.append(shifted)
        offset_details.append((txt_path.name, resolved_offset_hours))

    if not aligned_frames:
        return pd.DataFrame(columns=["Timestamp", "Temp1"]), []

    combined = pd.concat(aligned_frames, ignore_index=True).sort_values("Timestamp").reset_index(drop=True)
    return combined, offset_details


def merge_and_aggregate(
    temp_df: pd.DataFrame,
    speed_df: pd.DataFrame,
    temp_offset_hours: float | None,
    max_temp_gap_sec: int,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    applied_offset_hours = temp_offset_hours or 0.0
    merged = merge_speed_temp_nearest(
        temp_df=temp_df,
        speed_df=speed_df,
        temp_offset_hours=applied_offset_hours,
        max_temp_gap_sec=max_temp_gap_sec,
    )

    merged = merged[merged["SpeedMiB"] < SPEED_MAX]
    merged = merged[merged["Temp1"].between(TEMP_MIN, TEMP_MAX, inclusive="both")]

    merged["TimeBlock"] = merged["Timestamp"].dt.floor("1min")
    merged["TempRounded"] = merged["Temp1"].round()

    agg = (
        merged.groupby(["Mode", "Operation", "TempRounded", "TimeBlock"])["SpeedMiB"]
        .mean()
        .reset_index()
        .groupby(["Mode", "Operation", "TempRounded"])["SpeedMiB"]
        .mean()
        .reset_index()
        .sort_values(["Mode", "Operation", "TempRounded"])
    )

    return merged, agg


def filter_merged_rows(merged_df: pd.DataFrame) -> pd.DataFrame:
    filtered = merged_df.copy()
    filtered = filtered[filtered["SpeedMiB"] < SPEED_MAX]
    filtered = filtered[filtered["Temp1"].between(TEMP_MIN, TEMP_MAX, inclusive="both")]
    filtered["TempRounded"] = filtered["Temp1"].round()
    return filtered.sort_values(["Mode", "Operation", "TempRounded", "Timestamp"]).reset_index(drop=True)


def select_real_operation_profile(
    merged_df: pd.DataFrame,
    *,
    mode: str,
    operation: str,
    temperatures: list[float] | list[int] | None = None,
) -> pd.DataFrame:
    part = merged_df[(merged_df["Mode"] == mode) & (merged_df["Operation"] == operation)].copy()
    if part.empty:
        base_cols = ["TempRounded", "TempActual", "SpeedMiB", "Timestamp", "TempDeltaSec"]
        if temperatures is None:
            return pd.DataFrame(columns=base_cols)
        return pd.DataFrame(
            {
                "RequestedTemp": temperatures,
                "TempRounded": [pd.NA] * len(temperatures),
                "TempActual": [pd.NA] * len(temperatures),
                "SpeedMiB": [pd.NA] * len(temperatures),
                "Timestamp": [pd.NaT] * len(temperatures),
                "TempDeltaSec": [pd.NA] * len(temperatures),
            }
        )

    part["TempRounded"] = part["Temp1"].round()
    part["TempBucketDistance"] = (part["Temp1"] - part["TempRounded"]).abs()
    part = part.sort_values(["TempRounded", "TempBucketDistance", "TempDeltaSec", "Timestamp"])

    if temperatures is None:
        selected = part.drop_duplicates(subset=["TempRounded"], keep="first").copy()
        selected = selected.rename(columns={"Temp1": "TempActual"})
        return selected[["TempRounded", "TempActual", "SpeedMiB", "Timestamp", "TempDeltaSec"]].sort_values(
            "TempRounded"
        )

    rows = []
    for requested_temp in temperatures:
        ranked = part.copy()
        ranked["RequestedTemp"] = requested_temp
        ranked["RequestedBucketDistance"] = (ranked["TempRounded"] - requested_temp).abs()
        ranked["RequestedActualDistance"] = (ranked["Temp1"] - requested_temp).abs()
        ranked = ranked.sort_values(
            [
                "RequestedBucketDistance",
                "RequestedActualDistance",
                "TempBucketDistance",
                "TempDeltaSec",
                "Timestamp",
            ]
        )
        if ranked.empty:
            rows.append(
                {
                    "RequestedTemp": requested_temp,
                    "TempRounded": pd.NA,
                    "TempActual": pd.NA,
                    "SpeedMiB": pd.NA,
                    "Timestamp": pd.NaT,
                    "TempDeltaSec": pd.NA,
                }
            )
            continue

        best = ranked.iloc[0]
        rows.append(
            {
                "RequestedTemp": requested_temp,
                "TempRounded": best["TempRounded"],
                "TempActual": best["Temp1"],
                "SpeedMiB": best["SpeedMiB"],
                "Timestamp": best["Timestamp"],
                "TempDeltaSec": best["TempDeltaSec"],
            }
        )

    return pd.DataFrame(rows)


def plot_agg(agg_df: pd.DataFrame, title: str, out_png: Path, show: bool) -> None:
    plt.figure(figsize=(10, 5))
    series_cfg = [
        ("SEQUENTIAL", "read", "Sequential Read", "#1f77b4", "-"),
        ("SEQUENTIAL", "write", "Sequential Write", "#ff7f0e", "-"),
        ("RANDOM", "read", "Random Read", "#2ca02c", "--"),
        ("RANDOM", "write", "Random Write", "#d62728", "--"),
    ]

    for mode, op, label, color, style in series_cfg:
        part = agg_df[(agg_df["Mode"] == mode) & (agg_df["Operation"] == op)]
        if part.empty:
            continue
        plt.plot(
            part["TempRounded"],
            part["SpeedMiB"],
            label=f"{label} (MiB/s)",
            linewidth=2,
            color=color,
            linestyle=style,
        )

    plt.title(title, fontsize=12, fontweight="bold")
    plt.xlabel("Temperature (C)")
    plt.ylabel("Speed (MiB/s)")
    plt.xlim(TEMP_MIN, TEMP_MAX)
    plt.xticks(range(TEMP_MIN, TEMP_MAX + 1, 10))
    plt.grid(True, linestyle="--", alpha=0.6)
    plt.legend()
    plt.tight_layout()
    plt.savefig(out_png, dpi=150)
    if show:
        plt.show()
    plt.close()


def plot_profile_overlay(profile_df: pd.DataFrame, out_png: Path, title: str = "Temperature vs Speed") -> None:
    plt.figure(figsize=(10, 5.5))
    for mode, op, label, color, style in PROFILE_SERIES:
        part = profile_df[(profile_df["Mode"] == mode) & (profile_df["Operation"] == op)]
        if part.empty:
            continue
        plt.plot(
            part["TempRounded"],
            part["SpeedMiB"],
            label=label,
            linewidth=2,
            color=color,
            linestyle=style,
            marker="o",
            markersize=4,
        )

    plt.title(title, fontsize=12, fontweight="bold")
    plt.xlabel("Temperature (C)")
    plt.ylabel("Speed (MiB/s)")
    plt.xlim(TEMP_MIN, TEMP_MAX)
    plt.xticks(range(TEMP_MIN, TEMP_MAX + 1, 10))
    plt.grid(True, linestyle="--", alpha=0.6)
    plt.legend()
    plt.tight_layout()
    out_png.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(out_png, dpi=170)
    plt.close()


def sample_operation_profile(
    agg_df: pd.DataFrame,
    *,
    mode: str,
    operation: str,
    temperatures: list[float] | list[int],
) -> pd.DataFrame:
    part = (
        agg_df[(agg_df["Mode"] == mode) & (agg_df["Operation"] == operation)][["TempRounded", "SpeedMiB"]]
        .dropna()
        .sort_values("TempRounded")
    )
    if part.empty:
        return pd.DataFrame({"TempRounded": temperatures, "SpeedMiB": [pd.NA] * len(temperatures)})

    xs = part["TempRounded"].to_numpy(dtype=float)
    ys = part["SpeedMiB"].to_numpy(dtype=float)
    # Clamp to the chart endpoints so report rows stay inside the plotted profile.
    sampled = np.interp(temperatures, xs, ys)
    return pd.DataFrame({"TempRounded": temperatures, "SpeedMiB": sampled})


def build_snapshot_log_profiles(
    *,
    snapshot_csv: Path,
    log_path: Path,
    max_temp_gap_sec: int = 120,
) -> pd.DataFrame:
    speed_df, _capacity = parse_log_file(log_path)
    if speed_df.empty:
        return pd.DataFrame()

    temp_df = parse_snapshot_csv(snapshot_csv)
    if temp_df.empty:
        return pd.DataFrame()

    merged = merge_speed_temp_nearest(
        temp_df=temp_df,
        speed_df=speed_df,
        temp_offset_hours=0.0,
        max_temp_gap_sec=max_temp_gap_sec,
    )
    merged = filter_merged_rows(merged)
    if merged.empty:
        return pd.DataFrame()

    profiles = []
    for mode, op, _label, _color, _style in PROFILE_SERIES:
        part = select_real_operation_profile(merged, mode=mode, operation=op)
        if part.empty:
            continue
        part = part.copy()
        part["Mode"] = mode
        part["Operation"] = op
        profiles.append(part)

    if not profiles:
        return pd.DataFrame()
    return pd.concat(profiles, ignore_index=True)


def write_snapshot_log_chart_outputs(
    *,
    snapshot_csv: Path,
    log_path: Path,
    profile_csv: Path,
    chart_png: Path,
    max_temp_gap_sec: int = 120,
    title: str = "Temperature vs Speed",
) -> pd.DataFrame:
    profile_df = build_snapshot_log_profiles(
        snapshot_csv=snapshot_csv,
        log_path=log_path,
        max_temp_gap_sec=max_temp_gap_sec,
    )
    if profile_df.empty:
        return profile_df

    profile_csv.parent.mkdir(parents=True, exist_ok=True)
    profile_df.to_csv(profile_csv, index=False)
    plot_profile_overlay(profile_df, chart_png, title=title)
    return profile_df


def plot_profile_csv(profile_csv: Path, chart_png: Path, title: str = "Temperature vs Speed") -> Path:
    profile_df = pd.read_csv(profile_csv)
    plot_profile_overlay(profile_df, chart_png, title=title)
    return chart_png


def process_single_log(
    log_path: Path,
    txt_paths: list[Path],
    out_dir: Path,
    temp_offset_hours: float | None,
    max_temp_gap_sec: int,
    show: bool,
) -> None:
    speed_df, capacity = parse_log_file(log_path)
    if speed_df.empty:
        print(f"[skip] {log_path.name}: no speed rows parsed")
        return

    temp_df, offset_details = load_aligned_temp_df(
        txt_paths=txt_paths,
        speed_df=speed_df,
        temp_offset_hours=temp_offset_hours,
        max_temp_gap_sec=max_temp_gap_sec,
    )
    if temp_df.empty:
        print(f"[skip] {log_path.name}: no temp rows parsed from matched TXT files")
        return

    merged, agg = merge_and_aggregate(temp_df, speed_df, 0.0, max_temp_gap_sec)
    if agg.empty:
        print(f"[skip] {log_path.name}: merged data empty after filtering")
        return

    out_dir.mkdir(parents=True, exist_ok=True)
    stem = log_path.stem
    merged_csv = out_dir / f"{stem}_merged.csv"
    plot_png = out_dir / f"{stem}_temp_speed.png"

    merged.to_csv(merged_csv, index=False)
    summary = (
        merged.groupby(["Mode", "Operation"])["SpeedMiB"]
        .mean()
        .reset_index()
        .sort_values(["Mode", "Operation"])
    )
    quant_parts = [
        f"{row.Mode[:3]}-{row.Operation[0].upper()} {row.SpeedMiB:.1f}"
        for row in summary.itertuples(index=False)
    ]
    quant_text = " | ".join(quant_parts)
    title = f"{log_path.name} | Capacity: {capacity} | Avg MiB/s: {quant_text}"
    plot_agg(agg, title, plot_png, show=show)

    print(f"[ok] {log_path.name}")
    print(f"  matched txt: {', '.join(p.name for p in txt_paths)}")
    if temp_offset_hours is None and offset_details:
        offsets_text = ", ".join(f"{name}={offset:+.3f}h" for name, offset in offset_details)
        print(f"  temp offset: auto {offsets_text}")
    elif temp_offset_hours not in (None, 0.0):
        print(f"  temp offset: manual {temp_offset_hours:+.3f}h")
    print(f"  merged csv : {merged_csv}")
    print(f"  plot png   : {plot_png}")


def discover_pairs(base_dir: Path) -> list[tuple[Path, list[Path]]]:
    logs = sorted(base_dir.glob("*.log"))
    txt_candidates = sorted(list(base_dir.glob("*.TXT")) + list(base_dir.glob("*.txt")))
    seen_txt = set()
    txts = []
    for txt in txt_candidates:
        key = str(txt).lower()
        if key in seen_txt:
            continue
        seen_txt.add(key)
        txts.append(txt)

    if not logs:
        return []

    txt_ranges = {}
    for txt in txts:
        tdf = parse_temp_file(txt)
        if tdf.empty:
            continue
        txt_ranges[txt] = get_time_range(tdf)

    usable_txts = sorted(txt_ranges.keys())

    pairs = []
    for log in logs:
        speed_df, _ = parse_log_file(log)
        l0, l1 = get_time_range(speed_df)
        if l0 is None or l1 is None:
            l0, l1 = parse_log_time_range(log)
        matched = []
        for txt, (t0, t1) in txt_ranges.items():
            if ranges_overlap(l0, l1, t0, t1):
                matched.append(txt)

        if not matched and usable_txts:
            matched = usable_txts
        pairs.append((log, matched))

    return pairs


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Merge temp TXT + disk test LOG and generate plots.")
    p.add_argument("--dir", default=".", help="Directory for auto mode (default: current dir).")
    p.add_argument("--log", help="Single log file path for targeted mode.")
    p.add_argument("--txt", nargs="+", help="One or more temp TXT files for targeted mode.")
    p.add_argument("--outdir", default="plots_out", help="Output directory for plots and merged CSVs.")
    p.add_argument(
        "--failure-csv",
        help="Write combined failure-temperature CSV (auto mode scans --dir, targeted mode uses --log/--txt).",
    )
    p.add_argument("--failures-only", action="store_true", help="Only export failure CSV, skip plot/merged outputs.")
    p.add_argument(
        "--temp-offset-hours",
        type=parse_temp_offset_arg,
        default=None,
        help="Shift temp timestamps by hours, or 'auto' to detect per TXT file (default: auto).",
    )
    p.add_argument("--max-temp-gap-sec", type=int, default=120, help="Max allowed time gap for timestamp matching.")
    p.add_argument("--show", action="store_true", help="Show plots interactively.")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    out_dir = Path(args.outdir)
    failure_csv_path = Path(args.failure_csv) if args.failure_csv else None

    # Targeted mode: explicit --log + --txt
    if args.log or args.txt:
        if not (args.log and args.txt):
            raise SystemExit("Targeted mode requires both --log and --txt.")
        log_path = Path(args.log)
        txt_paths = [Path(x) for x in args.txt]

        if failure_csv_path is not None:
            export_failure_temps_csv(
                pairs=[(log_path, txt_paths)],
                out_csv=failure_csv_path,
                temp_offset_hours=args.temp_offset_hours,
                max_temp_gap_sec=args.max_temp_gap_sec,
            )
            if args.failures_only:
                return

        process_single_log(
            log_path=log_path,
            txt_paths=txt_paths,
            out_dir=out_dir,
            temp_offset_hours=args.temp_offset_hours,
            max_temp_gap_sec=args.max_temp_gap_sec,
            show=args.show,
        )
        return

    # Auto mode: scan directory and match each log to overlapping txt files
    base_dir = Path(args.dir)
    pairs = discover_pairs(base_dir)
    if not pairs:
        raise SystemExit(f"No .log files found in: {base_dir}")

    if failure_csv_path is not None:
        export_failure_temps_csv(
            pairs=pairs,
            out_csv=failure_csv_path,
            temp_offset_hours=args.temp_offset_hours,
            max_temp_gap_sec=args.max_temp_gap_sec,
        )
        if args.failures_only:
            return

    for log_path, txt_paths in pairs:
        if not txt_paths:
            print(f"[skip] {log_path.name}: no txt files available")
            continue
        process_single_log(
            log_path=log_path,
            txt_paths=txt_paths,
            out_dir=out_dir,
            temp_offset_hours=args.temp_offset_hours,
            max_temp_gap_sec=args.max_temp_gap_sec,
            show=args.show,
        )


if __name__ == "__main__":
    main()
