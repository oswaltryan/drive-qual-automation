#!/usr/bin/env python3
import argparse
import datetime
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, Literal, Protocol, TextIO, TypedDict, overload


class FioError(TypedDict, total=False):
    returncode: int
    stdout: str
    stderr: str
    parse_error: str


class TempArgs(Protocol):
    failure_action: Literal["prompt", "retry", "exit"]
    max_retries: int
    retry_delay: float


TempOperation = tuple[str, str, str, str]
FioJson = dict[str, Any]


def get_platform_ioengine() -> str:
    system = platform.system()
    if system == "Linux":
        return "libaio"
    if system == "Windows":
        return "windowsaio"
    return "posixaio"


def check_fio_installed() -> None:
    if shutil.which("fio") is None:
        print("Error: 'fio' is not installed or not in PATH.")
        sys.exit(1)


def get_fio_version() -> str:
    try:
        result = subprocess.run(
            ["fio", "--version"],
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception:
        return "unknown"
    output = (result.stdout or result.stderr or "").strip()
    return output or "unknown"


def get_test_size(path: str, percentage: float = 90) -> int:
    """
    Calculates the test size.
    If path is a directory, uses free space.
    If path is a file, uses its current size + free space of parent.
    Requirement: 'full disk size and set aside 10%'.
    We interpret this as 90% of *available* capacity (Free + Existing File).
    """
    if os.path.isdir(path):
        check_dir = path
        existing_size = 0
    else:
        check_dir = os.path.dirname(os.path.abspath(path))
        existing_size = os.path.getsize(path) if os.path.exists(path) and os.path.isfile(path) else 0

    if not os.path.exists(check_dir):
        print(f"Error: Directory {check_dir} does not exist.")
        sys.exit(1)

    usage = shutil.disk_usage(check_dir)
    total_available_for_test = usage.free + existing_size
    return int(total_available_for_test * (percentage / 100.0))


def format_bytes(size: int) -> str:
    power = 2**10
    n = float(size)
    power_labels = {0: "", 1: "K", 2: "M", 3: "G", 4: "T"}
    count = 0
    while n > power:
        n /= power
        count += 1
    return f"{n:.2f} {power_labels.get(count, 'P')}B"


def parse_size(size_text: str | None) -> int:
    if size_text is None:
        raise ValueError("size_text is required")
    s = size_text.strip().upper()
    if not s:
        raise ValueError("size_text is empty")
    multiplier = 1
    if s.endswith("G"):
        multiplier = 1024**3
        s = s[:-1]
    elif s.endswith("M"):
        multiplier = 1024**2
        s = s[:-1]
    elif s.endswith("K"):
        multiplier = 1024
        s = s[:-1]
    try:
        return int(float(s) * multiplier)
    except ValueError as exc:
        raise ValueError(f"Invalid size: {size_text}") from exc


def _truncate(text: str | None, limit: int = 2000) -> str:
    if text is None:
        return ""
    if len(text) <= limit:
        return text
    return text[:limit] + " ... [truncated]"


def _extract_json_block(text: str | None) -> str | None:
    if not text:
        return None
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    return text[start : end + 1]


def _load_fio_json(stdout: str | None, stderr: str | None) -> FioJson:
    candidates = []
    if stdout and stdout.strip():
        candidates.append(("stdout", stdout))
    if stderr and stderr.strip():
        candidates.append(("stderr", stderr))

    for _, data in candidates:
        stripped = data.strip()
        if not stripped:
            continue
        try:
            loaded: object = json.loads(stripped)
            if not isinstance(loaded, dict):
                raise ValueError("fio JSON root was not an object")
            return loaded
        except json.JSONDecodeError:
            json_block = _extract_json_block(stripped)
            if json_block:
                try:
                    loaded = json.loads(json_block)
                    if not isinstance(loaded, dict):
                        raise ValueError("fio JSON root was not an object")
                    return loaded
                except json.JSONDecodeError:
                    pass

    raise ValueError("fio did not return valid JSON on stdout or stderr")


def _escape_fio_path(path: str) -> str:
    if platform.system() != "Windows":
        return path
    drive_prefix_length = 2
    if len(path) >= drive_prefix_length and path[1] == ":" and path[0].isalpha():
        return path[0] + "\\:" + path[2:]
    return path


def _now_ts() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _log_line(message: str, log_handle: TextIO | None = None, also_print: bool = True) -> None:
    line = f"[{_now_ts()}] {message}"
    if also_print:
        print(line)
    if log_handle:
        log_handle.write(line + "\n")
        log_handle.flush()


def _log_json(label: str, payload: object, log_handle: TextIO | None = None) -> None:
    if not log_handle:
        return
    try:
        serialized = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    except (TypeError, ValueError):
        serialized = json.dumps({"error": "unserializable fio json"})
    log_handle.write(f"[{_now_ts()}] {label} {serialized}\n")
    log_handle.flush()


def _log_fio_summary(label: str, fio_json: FioJson | None, log_handle: TextIO | None = None) -> None:
    if not fio_json:
        return
    try:
        job = fio_json["jobs"][0]
    except (KeyError, IndexError, TypeError):
        return
    metrics = {}
    if "read" in job:
        metrics["read"] = job["read"]
    if "write" in job:
        metrics["write"] = job["write"]
    if not metrics:
        return
    for op, data in metrics.items():
        bw_mib = data.get("bw", 0) / 1024
        iops = data.get("iops", 0)
        if bw_mib == 0 and iops == 0:
            continue
        clat_ns = data.get("clat_ns", {}).get("mean")
        clat_ms = (clat_ns / 1_000_000) if clat_ns else None
        if clat_ms is None:
            _log_line(f"{label} {op}: {bw_mib:.2f} MiB/s, {iops:.0f} IOPS", log_handle)
        else:
            _log_line(
                f"{label} {op}: {bw_mib:.2f} MiB/s, {iops:.0f} IOPS, clat_avg={clat_ms:.2f} ms",
                log_handle,
            )


def _resolve_target_path(path: str) -> str:
    normalized = os.path.abspath(path)
    drive, tail = os.path.splitdrive(normalized)
    if os.path.isdir(normalized):
        return os.path.join(normalized, "disk_test.dat")
    if drive and tail in ("", "\\", "/"):
        return os.path.join(drive + "\\", "disk_test.dat")
    if normalized.endswith(":"):
        return normalized + "\\disk_test.dat"
    return normalized


def _ensure_file_size(path: str, size_bytes: int, log_handle: TextIO | None = None) -> None:
    try:
        if os.path.isdir(path):
            path = os.path.join(path, "disk_test.dat")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "ab"):
            pass
        current = os.path.getsize(path)
        if current < size_bytes:
            with open(path, "r+b") as handle:
                handle.truncate(size_bytes)
            _log_line(
                f"Preallocated temp file to {format_bytes(size_bytes)}",
                log_handle,
            )
    except Exception as exc:
        _log_line(f"Temp file preallocation failed: {exc}", log_handle)


def _is_transient_io_error(err: FioError | None) -> bool:
    if not err:
        return False
    stderr = (err.get("stderr") or "").lower()
    return "resource temporarily unavailable" in stderr or "error=11" in stderr


def _run_temp_burst(
    label: str,
    category: str,
    burst_args: list[str],
    rw: str,
    bs: str,
    log_handle: TextIO | None,
) -> tuple[FioJson | None, FioError | None]:
    _log_line(f"{label} Burst (5s)", log_handle)
    res, err = run_fio_job(burst_args + [f"--rw={rw}", f"--bs={bs}"], allow_errors=True)
    if err and _is_transient_io_error(err):
        _log_line(
            f"{label} burst hit transient I/O error; retrying with sync engine",
            log_handle,
        )
        fallback_args = [
            arg for arg in burst_args if not arg.startswith("--ioengine=") and not arg.startswith("--direct=")
        ]
        fallback_args += ["--ioengine=sync", "--direct=0"]
        res, err = run_fio_job(fallback_args + [f"--rw={rw}", f"--bs={bs}"], allow_errors=True)

    if res:
        _log_json(f"FIO_JSON {rw}", res, log_handle)
        _log_fio_summary(category, res, log_handle)
    if err:
        _log_json(f"FIO_ERROR {rw}", err, log_handle)
    return res, err


def _prompt_failure_action() -> Literal["retry", "exit"]:
    while True:
        try:
            choice = input("Failure detected. [R]etry temp test or [E]xit? ").strip().lower()
        except EOFError:
            return "exit"
        if choice in ("r", "retry"):
            return "retry"
        if choice in ("e", "exit"):
            return "exit"


def _run_temp_operation(
    operation: TempOperation,
    burst_args: list[str],
    log_handle: TextIO | None,
    args: TempArgs,
) -> bool:
    label, category, rw, bs = operation
    retry_count = 0
    while True:
        _, err = _run_temp_burst(label, category, burst_args, rw, bs, log_handle)
        if not err:
            return True

        _log_line(f"Failure detected during {rw}.", log_handle)
        if args.failure_action == "prompt":
            if _prompt_failure_action() == "retry":
                continue
            return False
        if args.failure_action == "exit":
            return False
        if retry_count >= args.max_retries:
            _log_line(f"Retry limit reached for {rw}; stopping temperature load.", log_handle)
            return False

        retry_count += 1
        _log_line(
            f"Retrying {rw} after I/O failure ({retry_count}/{args.max_retries}) in {args.retry_delay:g} seconds.",
            log_handle,
        )
        time.sleep(args.retry_delay)


def _default_log_path(target_path: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "_", str(target_path)).strip("_")
    if not cleaned:
        cleaned = "disk_test"
    return f"{cleaned}_{_timestamp_for_filename()}.log"


def _timestamp_for_filename() -> str:
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


@contextmanager
def _optional_log_handle(log_path: str | None) -> Iterator[TextIO | None]:
    if log_path is None:
        yield None
        return

    with open(log_path, "a", encoding="utf-8") as log_handle:
        yield log_handle


@overload
def run_fio_job(job_config: list[str], verbose: bool = False, *, allow_errors: Literal[False] = False) -> FioJson: ...


@overload
def run_fio_job(
    job_config: list[str], verbose: bool = False, *, allow_errors: Literal[True]
) -> tuple[FioJson | None, FioError | None]: ...


def run_fio_job(
    job_config: list[str],
    verbose: bool = False,
    *,
    allow_errors: bool = False,
) -> FioJson | tuple[FioJson | None, FioError | None]:
    """
    Runs fio with the given configuration (list of arguments).
    Returns the JSON output.
    """
    cmd = ["fio", "--output-format=json"] + job_config

    if verbose:
        print(f"Running command: {' '.join(cmd)}")

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        if allow_errors:
            error_info: FioError = {
                "returncode": result.returncode,
                "stdout": _truncate(result.stdout),
                "stderr": _truncate(result.stderr),
            }
            try:
                parsed = _load_fio_json(result.stdout, result.stderr)
                return parsed, error_info
            except (ValueError, json.JSONDecodeError):
                return None, error_info
        print(f"Error running fio: exit code {result.returncode}")
        print(f"Stdout: {_truncate(result.stdout)}")
        print(f"Stderr: {_truncate(result.stderr)}")
        sys.exit(1)

    try:
        parsed = _load_fio_json(result.stdout, result.stderr)
        if allow_errors:
            return parsed, None
        return parsed
    except (ValueError, json.JSONDecodeError) as e:
        if allow_errors:
            error_info = {
                "returncode": result.returncode,
                "stdout": _truncate(result.stdout),
                "stderr": _truncate(result.stderr),
                "parse_error": str(e),
            }
            return None, error_info
        print(f"Error parsing fio JSON output: {e}")
        print(f"Stdout (truncated): {_truncate(result.stdout)}")
        print(f"Stderr (truncated): {_truncate(result.stderr)}")
        sys.exit(1)


def main() -> int:  # noqa: PLR0912, PLR0915
    parser = argparse.ArgumentParser(description="Disk Tester (Python/fio)")
    subparsers = parser.add_subparsers(dest="command", required=True)

    parent_parser = argparse.ArgumentParser(add_help=False)
    parent_parser.add_argument("--path", default="disk_test.dat", help="Target file path (default: disk_test.dat)")
    parent_parser.add_argument("--direct", action="store_true", default=True, help="Use direct I/O (default: True)")
    parent_parser.add_argument("--no-direct", dest="direct", action="store_false", help="Disable direct I/O")
    parent_parser.add_argument("--size", help="Override test size (e.g., 1G, 500M). Default is 90%% of free space.")
    parent_parser.add_argument(
        "--log", default="disk_test.log", help="Log file path (default: derived from target path name)"
    )
    parent_parser.add_argument("--no-log", dest="log", action="store_const", const=None, help="Disable file logging")

    parser_temp = subparsers.add_parser("temp", parents=[parent_parser], help="Run Temperature Polling Test")
    parser_temp.add_argument("--interval", type=int, default=60, help="Cycle interval in seconds (default: 60)")
    parser_temp.add_argument("--duration", type=int, default=0, help="Total duration in seconds (0 = until failure)")
    parser_temp.add_argument(
        "--failure-action",
        choices=("prompt", "retry", "exit"),
        default="prompt",
        help="Action after a fio failure (default: prompt).",
    )
    parser_temp.add_argument(
        "--max-retries",
        type=int,
        default=3,
        help="Retry count when --failure-action=retry (default: 3).",
    )
    parser_temp.add_argument(
        "--retry-delay",
        type=float,
        default=5.0,
        help="Seconds between retries (default: 5).",
    )

    args = parser.parse_args()

    check_fio_installed()

    target_path = _resolve_target_path(args.path)

    log_path = args.log
    if log_path == "disk_test.log":
        log_path = _default_log_path(target_path)
    with _optional_log_handle(log_path) as log_handle:
        _log_line(f"Starting {get_fio_version()}", log_handle)
        _log_line(
            f"Platform: {platform.system()} {platform.release()} ({platform.machine()})",
            log_handle,
        )
        _log_line(f"Python: {sys.version.split()[0]}", log_handle)
        _log_line(f"Target: {target_path}", log_handle)
        try:
            capacity_dir = target_path if os.path.isdir(target_path) else os.path.dirname(target_path)
            if capacity_dir and os.path.exists(capacity_dir):
                usage = shutil.disk_usage(capacity_dir)
                _log_line(
                    f"Capacity: total={format_bytes(usage.total)}, free={format_bytes(usage.free)}",
                    log_handle,
                )
        except Exception as exc:
            _log_line(f"Capacity probe failed: {exc}", log_handle)
        fio_target_path = _escape_fio_path(target_path)

        if args.size:
            test_size_bytes = parse_size(args.size)
            if args.command == "temp":
                _log_line(
                    f"Test Size: {format_bytes(test_size_bytes)} (User Override, address range only)",
                    log_handle,
                )
            else:
                _log_line(f"Test Size: {format_bytes(test_size_bytes)} (User Override)", log_handle)
        elif args.command == "temp":
            if os.path.exists(target_path) and os.path.isfile(target_path):
                test_size_bytes = os.path.getsize(target_path)
                if test_size_bytes <= 0:
                    test_size_bytes = 1024**3
            else:
                test_size_bytes = 1024**3
            _log_line(
                f"Test Size: {format_bytes(test_size_bytes)}",
                log_handle,
            )
        else:
            test_size_bytes = get_test_size(target_path)
            _log_line(f"Test Size: {format_bytes(test_size_bytes)} (90% of available)", log_handle)

        ioengine = get_platform_ioengine()
        common_args = [
            f"--filename={fio_target_path}",
            f"--ioengine={ioengine}",
            f"--direct={1 if args.direct else 0}",
            f"--size={test_size_bytes}",
            "--group_reporting",
            "--name=disk_test",
        ]

        if args.command == "bench":
            _log_line("Running Sequential Read (1M)", log_handle)
            job = common_args + ["--rw=read", "--bs=1M"]
            res = run_fio_job(job)
            bw = res["jobs"][0]["read"]["bw"] / 1024
            iops = res["jobs"][0]["read"]["iops"]
            _log_line(f"Seq Read: {bw:.2f} MiB/s, {iops:.0f} IOPS", log_handle)

            _log_line("Running Sequential Write (1M)", log_handle)
            job = common_args + ["--rw=write", "--bs=1M"]
            res = run_fio_job(job)
            bw = res["jobs"][0]["write"]["bw"] / 1024
            iops = res["jobs"][0]["write"]["iops"]
            _log_line(f"Seq Write: {bw:.2f} MiB/s, {iops:.0f} IOPS", log_handle)

            _log_line("Running Random Read (4k)", log_handle)
            job = common_args + ["--rw=randread", "--bs=4k"]
            res = run_fio_job(job)
            bw = res["jobs"][0]["read"]["bw"] / 1024
            iops = res["jobs"][0]["read"]["iops"]
            _log_line(f"Rand Read: {bw:.2f} MiB/s, {iops:.0f} IOPS", log_handle)

            _log_line("Running Random Write (4k)", log_handle)
            job = common_args + ["--rw=randwrite", "--bs=4k"]
            res = run_fio_job(job)
            bw = res["jobs"][0]["write"]["bw"] / 1024
            iops = res["jobs"][0]["write"]["iops"]
            _log_line(f"Rand Write: {bw:.2f} MiB/s, {iops:.0f} IOPS", log_handle)

        elif args.command == "stress":
            _log_line("Running Reliability Full Stress Test", log_handle)
            job = common_args + [
                "--rw=write",
                "--bs=1M",
                "--verify=crc32c",
                "--do_verify=1",
                "--verify_dump=1",
                "--verify_fatal=1",
            ]
            _log_line("Writing and Verifying full test area... this may take a while.", log_handle)
            start_time = time.time()
            res = run_fio_job(job, verbose=True)
            duration = time.time() - start_time

            write_bw = res["jobs"][0]["write"]["bw"] / 1024
            errs = res["jobs"][0]["error"]
            _log_line(f"Completed in {duration:.2f}s", log_handle)
            _log_line(f"Write Speed: {write_bw:.2f} MiB/s", log_handle)
            _log_line(f"Errors: {errs}", log_handle)

            if errs == 0:
                _log_line("Reliability Test Passed: No errors detected.", log_handle)
            else:
                _log_line("Reliability Test FAILED.", log_handle)
                sys.exit(1)

        elif args.command == "temp":
            if args.max_retries < 0:
                parser.error("--max-retries must be non-negative")
            if args.retry_delay < 0:
                parser.error("--retry-delay must be non-negative")
            _log_line("Running Temperature Polling Test", log_handle)
            if args.duration:
                _log_line(f"Duration: {args.duration}s, Interval: {args.interval}s", log_handle)
            else:
                _log_line(f"Duration: until failure, Interval: {args.interval}s", log_handle)
            _log_line("Mode: Continuous Random/Sequential read/write bursts.", log_handle)

            _ensure_file_size(target_path, test_size_bytes, log_handle)

            end_time = time.time() + args.duration if args.duration else None

            while end_time is None or time.time() < end_time:
                _log_line("Starting Load Burst", log_handle)

                burst_args = [
                    f"--filename={fio_target_path}",
                    f"--ioengine={ioengine}",
                    f"--direct={1 if args.direct else 0}",
                    f"--size={test_size_bytes}",
                    "--group_reporting",
                    "--name=temp_burst",
                    "--time_based",
                    "--runtime=5",
                ]
                operations = (
                    ("Sequential Write", "SEQUENTIAL", "write", "1M"),
                    ("Sequential Read", "SEQUENTIAL", "read", "1M"),
                    ("Random Write", "RANDOM", "randwrite", "4k"),
                    ("Random Read", "RANDOM", "randread", "4k"),
                )
                for operation in operations:
                    if not _run_temp_operation(operation, burst_args, log_handle, args):
                        return 1

        _log_line("Test Complete.", log_handle)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
