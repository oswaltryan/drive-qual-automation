import argparse
import sys
import time
from collections.abc import Callable
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1] / "src"))

from drive_qual.core import io_utils
from drive_qual.integrations.instruments import tektronix


def _normalize_scope_path(path: str) -> str:
    normalized = path.replace("\\", "/")
    return normalized.rstrip("/")


def _prompt_result(step_name: str) -> tuple[str, str]:
    while True:
        raw = input(f"Result for {step_name} (w=worked, f=failed, s=skip): ").strip().lower()
        if raw in {"w", "f", "s"}:
            break
        print("Please enter w, f, or s.")
    status = {"w": "worked", "f": "failed", "s": "skipped"}[raw]
    notes = input("Notes (optional): ").strip()
    return status, notes


def _record_result(results: list[dict[str, str]], step: str, status: str, notes: str) -> None:
    results.append({"step": step, "status": status, "notes": notes})


def _run_step(
    results: list[dict[str, str]],
    step: str,
    action: Callable[[], object],
    skip_reason: str | None = None,
) -> None:
    print(f"\n--- {step} ---")
    if skip_reason:
        print(f"Skipping call: {skip_reason}")
    else:
        action()
    status, notes = _prompt_result(step)
    if skip_reason and status == "worked":
        notes = (notes + " " if notes else "") + f"(Skipped: {skip_reason})"
        status = "skipped"
    _record_result(results, step, status, notes)


def _save_results(results: list[dict[str, str]], log_path: str | None) -> None:
    print("\nAudit results:")
    for entry in results:
        print(f"- {entry['step']}: {entry['status']}" + (f" ({entry['notes']})" if entry["notes"] else ""))

    if not log_path:
        return

    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    lines = [f"Phase 3 Tektronix audit results - {timestamp}"]
    for entry in results:
        notes = f" | {entry['notes']}" if entry["notes"] else ""
        lines.append(f"{entry['step']} | {entry['status']}{notes}")
    Path(log_path).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nSaved audit log to {log_path}")


def _run_setup_steps(results: list[dict[str, str]], setup: str, device_type: str) -> None:
    if setup in ("InRush", "Both"):
        _run_step(
            results,
            "recall_setup(InRush)",
            lambda: tektronix.recall_setup("InRush", device_type),
        )
    if setup in ("Max IO", "Both"):
        _run_step(
            results,
            "recall_setup(Max IO)",
            lambda: tektronix.recall_setup("Max IO", device_type),
        )


def _run_local_dir_step(results: list[dict[str, str]], local_dir: str) -> None:
    _run_step(
        results,
        "mk_dir()",
        lambda: io_utils.mk_dir(local_dir),
        skip_reason=None if local_dir else "--local-dir not provided",
    )


def _run_save_steps(results: list[dict[str, str]], output_dir: str) -> None:
    if output_dir:
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        measurements_path = f"{output_dir}/phase3_measurements_{timestamp}.csv"
        screenshot_path = f"{output_dir}/phase3_screenshot_{timestamp}.png"
        report_path = f"{output_dir}/phase3_report_{timestamp}.pdf"
    else:
        measurements_path = ""
        screenshot_path = ""
        report_path = ""

    _run_step(
        results,
        "save_measurements()",
        lambda: tektronix.save_measurements(measurements_path),
        skip_reason=None if measurements_path else "--output-dir not provided",
    )
    _run_step(
        results,
        "backup_session()",
        lambda: tektronix.backup_session(screenshot_path),
        skip_reason=None if screenshot_path else "--output-dir not provided",
    )
    _run_step(
        results,
        "save_report()",
        lambda: tektronix.save_report(report_path),
        skip_reason=None if report_path else "--output-dir not provided",
    )


def _run_list_dir_step(results: list[dict[str, str]], list_dir: str) -> None:
    _run_step(
        results,
        "tektronix_list_dir()",
        lambda: tektronix.tektronix_list_dir(list_dir),
        skip_reason=None if list_dir else "--list-dir not provided",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase 3 audit: Tektronix scope functions with operator confirmation.")
    parser.add_argument(
        "--device-type",
        choices=("Portable", "Secure Key"),
        default="Portable",
        help="Device type used for the InRush setup path.",
    )
    parser.add_argument(
        "--setup",
        choices=("Max IO", "InRush", "Both"),
        default="Both",
        help="Which setup recall(s) to test.",
    )
    parser.add_argument(
        "--list-dir",
        default="",
        help='Scope directory to list (example: "C:/Temp").',
    )
    parser.add_argument(
        "--copy-dest",
        default="",
        help='Scope destination path for filesystem copy (example: "C:/Temp/b.csv").',
    )
    parser.add_argument(
        "--output-dir",
        default="",
        help='Scope directory for saved artifacts (example: "C:/Temp").',
    )
    parser.add_argument(
        "--local-dir",
        default="",
        help='Local directory to create via io_utils.mk_dir (example: "C:/temp/out").',
    )
    parser.add_argument(
        "--log",
        default="",
        help="Optional local path to write the audit log.",
    )
    args = parser.parse_args()

    results: list[dict[str, str]] = []

    def _idn() -> None:
        response = tektronix.scpi_command("*IDN?", read_response=True)
        print(f"Scope ID: {response}")

    _run_step(results, "scpi_command(*IDN?)", _idn)
    _run_step(results, "check_error()", tektronix.check_error)
    _run_setup_steps(results, args.setup, args.device_type)
    _run_step(results, "stop_run()", tektronix.stop_run)
    _run_local_dir_step(results, args.local_dir.strip())

    output_dir = _normalize_scope_path(args.output_dir) if args.output_dir else ""
    _run_save_steps(results, output_dir)

    list_dir = _normalize_scope_path(args.list_dir) if args.list_dir else ""
    _run_list_dir_step(results, list_dir)

    _save_results(results, args.log or None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
