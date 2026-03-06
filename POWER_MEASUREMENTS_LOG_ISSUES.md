# Power Measurements Run Issues And Fixes

Source log: `uv run drive-qual-report --steps power_measurements` on March 4, 2026.

## 1) CSV saved on scope, but parsed on host path that does not exist

- Evidence:
  - `Saved session measurements to Z:/69-420/Windows/Max IO/Padlock 3.0.csv`
  - `Failed to read measurements CSV Z:\69-420\Windows\Max IO\Padlock 3.0.csv: [Errno 2] No such file or directory`
- Root cause:
  - `tektronix.save_measurements()` saves on the scope filesystem via SCPI.
  - Parsing code assumes the same `Z:` path is immediately visible on the Windows host.
- Fix:
  - Save measurements and screenshots directly to mounted fileshare `Z:`.
  - Keep the report/JSON import logic pointed at that same `Z:/...` artifact path.
  - Example flow:
    - Ensure organized share structure exists first:
      - `Z:/<ApricornPartNumber>/linux/`
      - `Z:/<ApricornPartNumber>/macOS/`
      - `Z:/<ApricornPartNumber>/windows/`
    - Save directly to share path visible to scope, for example:
      - `Z:/<ApricornPartNumber>/windows/Max IO/<dut>.csv`
      - `Z:/<ApricornPartNumber>/windows/In Rush Current/<dut>.csv`
    - Parse/update report JSON from that same `Z:/...` artifact.
  - Rationale:
    - Keeps report artifacts consistently organized by part number and operating system.

## 2) DUT key mismatch blocks JSON power updates

- Evidence:
  - `Skipping CSV ... could not map DUT 'Padlock 3.0' in report power section.`
- Root cause:
  - Report `power` section DUT keys do not match runtime USB product string.
- Fix:
  - Add canonical DUT mapping:
    - Normalize names (casefold, trim, collapse spaces, remove punctuation variants).
    - Maintain alias map (for example, known product string variants).
    - If exactly one DUT exists in report and runtime DUT is unknown, prompt once or apply safe single-key fallback with warning.
  - Persist resolved mapping in session metadata to avoid remapping every run.

## 3) Benchmark temp-file cleanup path mismatch

- Evidence:
  - `Error cleaning up test file: ... 'D:\\benchmark_file.dat'`
- Root cause:
  - Cleanup path does not consistently match where fio created the file (drive-root/path normalization mismatch).
- Fix:
  - Normalize the fio target path once and reuse it for both run and cleanup.
  - Pre-check `os.path.exists(test_file)` before delete; log `not found` as warning, not generic error.
  - Log the exact fio `--filename` used so cleanup target can be validated.

## 4) Step reports benchmark success despite cleanup failure

- Evidence:
  - `Benchmark completed successfully` printed after cleanup error.
- Root cause:
  - Success condition only checks fio return codes; ignores post-run cleanup result.
- Fix:
  - Track benchmark status as composite:
    - `fio_write_ok`
    - `fio_read_ok`
    - `cleanup_ok`
  - Print final status with explicit warning if cleanup failed.
  - Write this status into backup JSON for auditability.

## 5) Backup JSON written without usable numeric redundancy

- Evidence:
  - Read failures occur before `Wrote capture backup entry...`
- Root cause:
  - Backup writes metadata even when CSV values cannot be parsed.
- Fix:
  - Include `capture_state` in backup entry:
    - `captured_and_parsed`
    - `captured_not_readable`
    - `capture_failed`
  - If parse fails, store reason and scope-side source path.
  - Retry parse after copy/sync step before writing final backup entry.

## 6) Workflow pauses at manual removal prompt (operator can interpret as hang)

- Evidence:
  - Final line: `Remove Apricorn device..`
- Root cause:
  - Intended interactive wait state has no timeout/progress messaging.
- Fix:
  - Print explicit state message:
    - `Waiting for device removal to continue... (Ctrl+C to abort)`
  - Add periodic heartbeat log every few seconds.
  - Optional timeout argument (`--device-wait-timeout`) with controlled failure mode.

## Recommended implementation order

1. Fix storage boundary: ensure measurement data is host-readable (Issue 1).
2. Fix DUT mapping robustness (Issue 2).
3. Fix path normalization/cleanup consistency (Issue 3).
4. Improve status signaling and backup semantics (Issues 4 and 5).
5. Improve operator wait UX/timeouts (Issue 6).

## Acceptance checks after fixes

- Running `uv run drive-qual-report --steps power_measurements` should:
  - Save CSV and PNG artifacts.
  - Successfully parse measurement values.
  - Update `logs/<part>/drive_qualification_report_atomic_tests.json` power fields.
  - Write `logs/<part>/power_measurements_backup.json` with numeric values and capture status.
  - Show explicit, non-ambiguous final status including warnings when non-fatal issues occur.
