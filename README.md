# Drive Qualification Automation

Drive Qualification Automation is a Python-based qualification and report
generation project for Apricorn devices. It combines:

- interactive report-building steps
- USB device discovery
- Tektronix scope integration
- benchmark execution
- platform-specific performance collection
- JSON report updates and post-processing helpers

The important distinction is that the repository is intended to be cross-platform
at the code and test level, but not every workflow is cross-platform today.
Shared logic should run on Windows, Linux, and macOS. Some technician-facing
steps depend on Windows-only tools such as PowerShell, `pywinauto`,
CrystalDiskInfo, CrystalDiskMark, ATTO, and `diskspd.exe`.

Cross-platform behavior is a hard engineering requirement, not an aspiration.
Shared CLI entrypoints, metadata-only commands, report/session helpers, and
other common modules must import and run without requiring Windows-only
dependencies. Platform-specific integrations belong behind runtime-gated or
lazy imports inside the Windows-only execution paths that actually need them.

## What This Repo Does

At a high level, the project supports two related jobs:

1. Create and enrich a qualification report JSON for a specific Apricorn part
   number.
2. Run measurement and performance steps that collect artifacts and write
   results back into that report.

The report workflow is driven from a sequence of named steps:

- `drive_info`
- `equipment`
- `power_measurements`
- `performance`

You can list them directly with:

```bash
uv run drive-qual-report --list-steps
```

## Platform Support

- Cross-platform:
  report-session helpers, report generation, path normalization logic,
  post-processing, a large portion of the benchmark wrapper logic, and the test
  suite.
- Windows-only:
  GUI automation via `pywinauto`, CrystalDiskInfo, CrystalDiskMark, ATTO, and
  `diskspd`.
- Mixed:
  `power_measurements` dispatches through a platform-neutral entrypoint to a
  shared mixed-platform implementation with Windows-only helpers isolated in a
  Windows module; `performance` dispatches to Windows, Linux, and macOS
  implementations; `benchmark.py` supports `fio` on Windows, Linux, and macOS,
  while `diskspd` is Windows-only.
- Engineering rule:
  cross-platform commands such as `uv run drive-qual-report --list-steps` must
  not fail because a shared import path eagerly pulls in Windows-only modules.

## Quick Start

### Prerequisites

- Python 3.12
- `uv`
- For Windows workflow runs:
  `usb` CLI on `PATH`, access to the Tektronix scope, and the required Windows
  benchmark/GUI tools installed

### Install Dependencies

```bash
uv venv
uv sync --group dev
```

### Common Commands

```bash
uv run pre-commit install
uv run pre-commit run --all-files
uv run pytest
uv run drive-qual-report --list-steps
```

## Main Workflows

### 1. Report Workflow

This is the main structured workflow for building or updating a report:

```bash
uv run drive-qual-report
```

You can also run only selected steps:

```bash
uv run drive-qual-report --steps drive_info,equipment
uv run drive-qual-report --steps power_measurements,performance --part-number 69-420
```

Available workflow steps:

1. `drive_info`
   Prompts for core drive metadata, creates the report directory, writes the
   initial report JSON, and sets the current session marker.
2. `equipment`
   Fills host and scope metadata, derives DUT families from form factor, and
   ensures the report has the expected `power`, `performance`, and
   `temperature` sections.
3. `power_measurements`
   Runs the In Rush and Max IO scope/measurement flow, updates compatibility
   flags, saves measurement CSVs, and updates report power fields.
4. `performance`
   Dispatches by platform:
   Windows automates CrystalDiskInfo, CrystalDiskMark, and ATTO;
   Linux records native Disks benchmark results;
   macOS uses an automation-first Blackmagic Disk Speed Test flow that runs the
   benchmark, captures a screenshot, extracts MB/s values via OCR, and writes
   JSON/CSV results (with manual fallback).

### 2. Legacy CLI

There is also a `drive-qual` CLI:

```bash
uv run drive-qual
```

This entry point is older and Windows-focused. It coordinates device prompts,
Tektronix setup recall, fio-based benchmarking, and artifact capture. The
current report-oriented workflow is centered on `drive-qual-report`.

### 3. Data Drive Setup

To prepare or validate the qualification data drive structure:

```bash
uv run python -m drive_qual.workflows.setup_directories
```

This script:

- detects the current OS
- uses the configured platform path from `drive_qual.toml`
- creates missing `Linux`, `macOS`, and `Windows` directories
- initializes or merges `progress_tracker.json`

### 4. Post-Process Measurements

To extract current values from saved scope CSV output:

```bash
uv run python -m drive_qual.cli.post_process_measurements
```

This is a helper-oriented script for turning measurement CSV rows into a
smaller JSON summary.

## macOS Performance (Current Automation-First Mode)

The macOS `performance` step expects a host entry for `Blackmagic Disk Speed
Test`.

The macOS report/artifact root is not hardcoded in the workflow. It comes from
`drive_qual.toml`:

```toml
[paths]
macos = "/Volumes/..."
```

For SMB shares, this value must match the actual mounted path shown under
`/Volumes` on the Mac that is running the workflow.

Operator prerequisites:

- Blackmagic Disk Speed Test installed on the macOS host
- terminal Screen Recording permission so `screencapture` can write benchmark
  screenshots
- `drive_qual.toml` `paths.macos` value set to the actual mounted share path
  on that Mac (typically under `/Volumes`)

Current supported behavior (automation-first):

1. the workflow closes stale app state, launches Blackmagic, and selects
   `/Volumes/DUT`
2. the workflow starts/stops benchmark by coordinate click after a fixed run
   duration
3. the workflow waits briefly for UI settle and captures a screenshot artifact
4. the workflow extracts read/write MB/s from the screenshot using OCR
5. if OCR extraction fails, the workflow prompts for manual read/write MB/s
6. the workflow writes JSON and CSV artifacts, then updates
   `performance -> <DUT> -> macOS`

Permission scope for handoff:

- required for automation mode: Accessibility (UI scripting) and Screen
  Recording (screenshot capture)
- manual fallback still works for value entry if OCR extraction fails

macOS Blackmagic artifacts written per run:

- screenshot:
  `Z:\<part_number>\macOS\Blackmagic Disk Speed Test\<dut>_<timestamp>.png`
- structured JSON:
  `Z:\<part_number>\macOS\Blackmagic Disk Speed Test\<dut>_<timestamp>.json`
  with fields `tool`, `dut`, `read_mb_s`, `write_mb_s`, `captured_at`
- structured CSV:
  `Z:\<part_number>\macOS\Blackmagic Disk Speed Test\<dut>_<timestamp>.csv`
  with rows `Metric,Value`, `Read MB/s`, and `Write MB/s`

Report writeback fields:

- `performance -> <DUT> -> macOS -> Blackmagic Disk Speed Test -> read`
- `performance -> <DUT> -> macOS -> Blackmagic Disk Speed Test -> write`

Recovery behavior:

- if automation fails, the workflow falls back to manual-assisted benchmark mode
- if OCR value extraction fails, the workflow prompts for manual MB/s entry
- if screenshot capture is blocked, grant Screen Recording and rerun the step

## Step-by-Step Report Flow

If you are trying to understand the intended operator flow, this is the
current sequence across the main report workflow:

1. Run `drive_info` to create the report for the Apricorn part number.
2. Run `equipment` to populate lab host metadata, scope metadata, DUT mapping,
   and report sections.
3. Run `power_measurements` on the target host with the scope and Apricorn
   device attached. Windows, Linux, and macOS are supported through the shared
   maintained workflow path.
4. Run `performance` on the target host:
   Windows uses the GUI benchmark tools,
   Linux uses the native Disks wrapper,
   macOS uses the automation-first Blackmagic workflow with manual fallback.
5. Review the generated report JSON and collected CSV/PNG artifacts.

The maintained measurement/performance phases generally do the following:

1. detect or confirm the target Apricorn device
2. wait for disconnect/reconnect events when required
3. prepare scope state or benchmark state
4. collect CSV/screenshot artifacts
5. update the report JSON with compatibility, power, and performance results

## Project Layout

Important files and modules:

- `src/drive_qual/workflows/report.py`
  orchestration for the named report steps and the maintained `drive-qual-report` CLI
- `src/drive_qual/workflows/drive_info.py`
  prompts for drive metadata and creates the per-part-number report
- `src/drive_qual/workflows/equipment.py`
  fills host/scope defaults and ensures DUT-related report sections exist
- `src/drive_qual/platforms/power_measurements.py`
  platform-neutral entrypoint for the mixed-platform power measurements step
- `src/drive_qual/platforms/power_measurements_mixed.py`
  shared power-measurement workflow for Linux, macOS, and Windows with
  cross-platform compatibility/report updates
- `src/drive_qual/platforms/windows/power_measurements.py`
  Windows-only power-measurement helpers (Disk Management confirmation,
  PowerShell safe-eject, and Windows drive-target handling)
- `src/drive_qual/platforms/performance.py`
  platform-neutral dispatcher for the performance step
- `src/drive_qual/platforms/macos/performance.py`
  macOS manual-assisted Blackmagic Disk Speed Test capture, artifact generation,
  and report writeback
- `src/drive_qual/platforms/windows/performance.py`
  Windows-only GUI automation for CrystalDiskInfo, CrystalDiskMark, and ATTO
- `src/drive_qual/benchmarks/`
  split benchmark helpers for shared path handling plus `fio` and Windows-only `diskspd` execution
- `src/drive_qual/workflows/setup_directories.py`
  data-drive scaffolding and progress tracker initialization
- `src/drive_qual/cli/post_process_measurements.py`
  ad hoc CSV-to-JSON helper for saved measurements
- `src/drive_qual/core/report_session.py`
  session marker and report path helpers
- `src/drive_qual/core/storage_paths.py`
  artifact path construction for the scope share

## External Dependencies and Lab Assumptions

The repo depends on a mix of Python packages and lab-specific tooling.

Python/runtime dependencies:

- `requests`
- `pyyaml`
- `pymodbus`
- `pillow`

Windows-only runtime dependency:

- `pywinauto`

Lab/tooling assumptions for technician workflow runs:

- signed `usb` CLI available on `PATH`
- Tektronix scope reachable over SCPI/TCP
- scope-visible artifact share mounted at `Z:\`
- on macOS, the SMB share mount path in `drive_qual.toml` matches the actual
  path under `/Volumes`
- `fio` available on `PATH` for cross-platform benchmarking
- `diskspd.exe` available on Windows when that path is used
- CrystalDiskInfo installed at
  `C:/Program Files/CrystalDiskInfo/DiskInfo64.exe`
- CrystalDiskMark installed at
  `C:/Program Files/CrystalDiskMark8/DiskMark64.exe`
- ATTO installed at
  `C:/Program Files (x86)/ATTO Technology/Disk Benchmark/ATTODiskBenchmark.exe`
- Blackmagic Disk Speed Test installed on macOS when that path is used

Scope networking note:

The current Tektronix integration defaults to `10.10.10.3`. Verify the actual
lab network configuration before changing instrument connectivity settings.

## Reports and Artifacts

The project writes two broad categories of output:

- report JSON under the configured report root
- measurement and performance artifacts under the scope artifact root

The configured platform roots come from `drive_qual.toml`. On macOS, that means
the workflow reads and writes through the configured `/Volumes/...` mount path
while preserving the Windows-style report/artifact contract in the JSON and
path helpers.

Examples:

- report JSON:
  `Z:\69-420\drive_qualification_report_atomic_tests.json`
- In Rush Current CSV:
  `Z:\69-420\Windows\In Rush Current\Secure Key 3.0.csv`
- Max IO CSV:
  `Z:\69-420\Windows\Max IO\Secure Key 3.0.csv`
- CrystalDiskInfo screenshot:
  `Z:\69-420\Windows\CrystalDiskInfo\Secure Key 3.0_YYYYMMDD_HHMMSS.png`
- CrystalDiskMark outputs:
  `Z:\69-420\Windows\CrystalDiskMark\...`
- ATTO outputs:
  `Z:\69-420\Windows\ATTO\...`
- macOS Blackmagic outputs:
  `Z:\69-420\macOS\Blackmagic Disk Speed Test\<dut>_<timestamp>.png`
- macOS Blackmagic structured JSON:
  `Z:\69-420\macOS\Blackmagic Disk Speed Test\<dut>_<timestamp>.json`
  with `tool`, `dut`, `read_mb_s`, `write_mb_s`, `captured_at`
- macOS Blackmagic structured CSV:
  `Z:\69-420\macOS\Blackmagic Disk Speed Test\<dut>_<timestamp>.csv`
  with `Metric,Value` plus read/write rows

The report content is progressively enriched by each step rather than generated
all at once.

## Development Notes

### Testing

Run the test suite with:

```bash
uv run pytest
```

The tests cover a meaningful amount of cross-platform path/report logic and
mocked workflow behavior. They do not replace lab validation for Windows GUI
automation or instrument integration.

### Linting and Type Checking

Use:

```bash
uv run pre-commit run --all-files
```

This runs formatting, linting, mypy, and pytest through the configured
pre-commit hooks.

### Cross-Platform Development Rule

Keep these constraints in mind when changing the workflow:

- Shared CLI paths must remain importable on Windows, Linux, and macOS.
- Commands that only inspect metadata or configuration, such as
  `drive-qual-report --list-steps`, must not import Windows-only GUI or device
  automation dependencies at module import time.
- Windows-only packages such as `pywinauto` belong inside Windows-only code
  paths, not in shared top-level imports.
- If a non-Windows machine cannot run a supposedly shared command because of a
  Windows-only import chain, treat that as a bug.

### Where to Start Reading

If you are new to the project, start here:

1. `src/drive_qual/workflows/report.py`
2. `src/drive_qual/workflows/drive_info.py`
3. `src/drive_qual/workflows/equipment.py`
4. `src/drive_qual/platforms/power_measurements.py`
5. `src/drive_qual/platforms/power_measurements_mixed.py`
6. `src/drive_qual/platforms/performance.py`
7. `src/drive_qual/platforms/windows/power_measurements.py`
8. `src/drive_qual/platforms/macos/performance.py`
9. `src/drive_qual/platforms/windows/performance.py`

That path will get you from top-level orchestration into the platform-neutral
dispatch layer and then down into the concrete platform implementations.
