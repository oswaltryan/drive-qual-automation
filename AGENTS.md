# AGENTS.md

> A concise, agent-oriented guide to working in this repository.

You are working on **drive-qual-automation**, a Python 3.12 storage qualification and report-generation suite for Apricorn devices. The repo is intended to be cross-platform for shared logic and tests, but the technician workflow is only partly cross-platform today: report/session/path helpers should be portable, while power measurement and software automation steps are Windows and lab specific. If a Linux or macOS host cannot run a shared or metadata-only command because a Windows-only dependency was imported too early, treat that as a bug.

## Ground Rules

1. **Keep shared logic portable**: isolate Windows-only behavior instead of leaking it into common modules.
2. **Protect import boundaries**: shared CLI paths and metadata-only commands must not import Windows-only modules at module import time.
3. **Treat workflow data as contract**: report JSON shape, step names, artifact naming, and storage layout affect tests and lab workflows.
4. **Prefer the report workflow**: `drive-qual-report` is the maintained entrypoint; `drive-qual` is legacy.
5. **Use current code as source of truth**: `README.md` is useful, but reconcile it with the actual modules and tests if they differ.
6. **Respect the validation boundary**: tests cover path/report logic and mocked workflows, not real GUI automation or hardware validation.

## Project Snapshot

- Package: **drive-qual-automation**
- Python: **>=3.12**
- Source root: `src/drive_qual/`
- Primary CLI:
  - `drive-qual-report` -> `drive_qual.cli.report:run_report_workflow_cli`
- Legacy CLI:
  - `drive-qual` -> `drive_qual.cli.legacy:main`
- Main workflow steps, in current order:
  - `drive_info`
  - `equipment`
  - `power_measurements`
  - `performance`

## Setup

Recommended setup:

```bash
uv venv
uv sync --group dev
uv run --group dev python -m pre_commit install
```

Common commands:

```bash
uv run pytest
uv run --group dev python -m pre_commit run --all-files
uv run drive-qual-report --list-steps
uv run drive-qual-report --steps drive_info,equipment
uv run drive-qual-report --steps power_measurements,performance --part-number 69-420
uv run python -m drive_qual.workflows.setup_directories
uv run python -m drive_qual.cli.post_process_measurements
```

## Platform Boundaries

- Cross-platform:
  report/session helpers, path normalization, data-drive setup, post-processing helpers, and the shared parts of benchmarking.
- Mixed:
  the `drive_qual.benchmarks` package supports `fio` on Windows, Linux, and macOS, while `diskspd` is Windows-only.
- Windows and lab specific:
  `platforms/windows/power_measurements.py`, `platforms/windows/performance.py`, PowerShell disk operations, `pywinauto`, CrystalDiskInfo, CrystalDiskMark, ATTO, and most end-to-end technician runs.
- Boundary rule:
  shared modules may reference Windows-only modules, but they must not require them merely to import a cross-platform command path. Use lazy imports or platform-gated execution paths.

## Module Map

- `src/drive_qual/cli/report.py`
  - Thin maintained CLI entrypoint for `drive-qual-report`.
- `src/drive_qual/workflows/report.py`
  - Main orchestrator.
  - `run_report_workflow()` maps step names to runners.
  - `run_report_workflow_cli()` exposes `--steps`, `--list-steps`, `--part-number`, and `--scope-profile`.
- `src/drive_qual/workflows/drive_info.py`
  - `run_drive_info_prompt()` collects drive metadata, creates the report, and sets the current session marker.
- `src/drive_qual/workflows/equipment.py`
  - `run_equipment_prompt()` fills host/scope metadata, applies optional scope profiles, derives DUT sections, and ensures `power`, `performance`, and `temperature` sections exist.
- `src/drive_qual/platforms/windows/power_measurements.py`
  - `run_power_measurements_step()` handles Apricorn device selection/reconnect, partition and format checks, safe eject, In Rush and Max IO flows, Tektronix capture, and Windows compatibility flag updates.
- `src/drive_qual/platforms/windows/performance.py`
  - `run_software_step()` automates CrystalDiskInfo, CrystalDiskMark, and ATTO, captures screenshots and exports, and writes Windows performance results back into the report.
- `src/drive_qual/core/power_measurements.py`
  - Parses saved scope CSVs and updates `power` entries in the report JSON.
- `src/drive_qual/benchmarks/`
  - Shared benchmark path helpers plus `fio` and Windows-only `diskspd` execution.
- `src/drive_qual/core/report_session.py`
  - Session and report-path helpers: current marker, template name, folder-name sanitization, report load/save.
- `src/drive_qual/core/storage_paths.py`
  - Scope artifact path helpers. `SCOPE_ARTIFACT_ROOT` is currently `Z:/`.
- `src/drive_qual/integrations/apricorn/usb_cli.py`
  - Wraps external `usb --json`, defines `ApricornDevice`, and provides Apricorn device selection and matching helpers.
- `src/drive_qual/integrations/instruments/tektronix.py`
  - SCPI TCP client, setup recall/save helpers, scope-side path handling, and CSV capture hooks.
- `src/drive_qual/integrations/instruments/watlow.py`
  - Modbus RTU helper for the Watlow controller.
- `scripts/`
  - Audit and smoke helpers for USB, Tektronix, and Watlow integration.

## Workflow Reality

Primary operator flow:

1. Run `drive_info`.
2. Run `equipment`.
3. Run `power_measurements` on a Windows host with the scope and target device attached.
4. Run `performance` on a Windows host with the GUI benchmark tools installed.
5. Review the updated report JSON and captured artifacts.

The report is enriched incrementally. Later steps assume the earlier report and session scaffolding already exist.

## Storage And Artifacts

- Report root and artifact root currently both derive from `SCOPE_ARTIFACT_ROOT = "Z:/"`.
- `report_session.py` writes the current session marker to `Z:/.current`.
- Report JSON path format:
  `Z:\{part_number}\drive_qualification_report_atomic_tests.json`
- Artifact path format for Windows captures:
  `Z:\{part_number}\Windows\...`

Path behavior that matters:

- The code uses `PureWindowsPath` heavily, even when tests run on non-Windows hosts.
- Tests assert the current `Z:/` root and Windows-style path rendering.
- Some helpers normalize paths to POSIX-style strings for SCPI and file-transfer calls; preserve the existing conversions unless you also update the tests.

## External Dependencies And Lab Assumptions

Python/runtime dependencies from `pyproject.toml`:

- `requests`
- `pyyaml`
- `pymodbus`
- `pywinauto`
- `pillow`

Lab/tooling assumptions for real workflow runs:

- external `usb` CLI available on `PATH`
- Tektronix scope reachable over SCPI/TCP
- scope-visible artifact share mounted at `Z:\`
- `fio` available on `PATH` or bundled at `tools/fio.exe`
- `diskspd.exe` available on Windows or bundled at `tools/diskspd.exe`
- CrystalDiskInfo, CrystalDiskMark, and ATTO installed at their expected Windows paths

Connectivity note:

- The current Tektronix integration defaults the scope host to `10.10.10.3`. Verify actual lab networking before changing instrument connectivity code.

## Tests

Run the suite with:

```bash
uv run pytest
```

High-value tests:

- `tests/test_power_measurements_step.py`
- `tests/test_power_measurements_paths.py`
- `tests/test_benchmark_paths.py`
- `tests/test_apricorn_usb_cli.py`

The suite mostly covers path normalization, JSON/report updates, and mocked workflow behavior. It does not validate real GUI automation or hardware integration.

## Sharp Edges

- `src/drive_qual/__main__.py` is a thin wrapper around the legacy CLI; the maintained entrypoint is still `drive-qual-report`.
- `drive-qual-report` is the maintained entrypoint; `drive-qual` is older and Windows-focused.
- `platforms/windows/power_measurements.py` and `platforms/windows/performance.py` assume Windows semantics such as drive letters, GUI apps, and operator/device interaction.
- Eager imports are a known failure mode. If a shared command path breaks on Linux or macOS because it imports `platforms/windows/performance.py`, `pywinauto`, or other Windows-only dependencies before they are needed, that is a bug to fix, not an acceptable limitation.
- If you change report keys, path casing, screenshot names, or artifact directories, expect tests and downstream lab workflows to care.

## Where To Start Reading

1. `src/drive_qual/workflows/report.py`
2. `src/drive_qual/workflows/drive_info.py`
3. `src/drive_qual/workflows/equipment.py`
4. `src/drive_qual/platforms/windows/power_measurements.py`
5. `src/drive_qual/platforms/windows/performance.py`

That mirrors the active workflow from top-level orchestration down into the Windows-specific implementation.
