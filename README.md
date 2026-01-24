# Drive Qualification Automation

This project automates Apricorn drive qualification workflows using a Tektronix
scope, benchmark tools, and a signed `usb` discovery CLI. It is designed as a
scripted, interactive CLI experience for technicians running repeatable tests.

## What the CLI does

When you run the CLI, you will be prompted to:
- Enter the Apricorn part number.
- Choose the device type (Portables or Secure Key).
- Connect or remove the device when prompted.

The flow then:
- Recalls the appropriate Tektronix scope setup.
- Runs IO benchmarks on the attached drive.
- Saves scope measurements and screenshots to the configured output paths.

## Inventory and Baseline

Scripts and CLI entry points:
- `drive-qual` CLI -> `src/drive_qual/__main__.py`
- Standalone runners: `src/drive_qual/win_fio.py`, `src/drive_qual/win_diskspd.py`
- Data setup helper: `src/drive_qual/setup_directories.py`
- Post-processing helper: `src/drive_qual/post_process_measurements.py`

External tools and integrations:
- Signed `usb` CLI (`usb --json`) for device discovery (must be on PATH).
- Tektronix scope over SCPI/TCP at `169.254.8.130:5025`.
- Benchmark binaries: `fio.exe` and `diskspd.exe` (from `tools/` or PATH).
- PowerShell disk tooling (`Get-Disk`, `Get-Partition`, `Get-Volume`, `wmic`).

Hardware dependencies:
- Tektronix scope with saved setups for InRush and Max IO.
- Apricorn devices (Portables and Secure Key).
- Data drive with expected output pathing (uses `E:\` in scripts; QUAL_DATA label for setup helper).

Environment assumptions:
- Windows host with drive letters and PowerShell available.
- Python 3.12 and `uv` installed for running the CLI.
- Network access to the scope and permissions to query disks.

Expected outputs and file artifacts:
- Measurements CSVs: `E:\{part_number}\Windows\In Rush Current\{iProduct}.csv` and `E:\{part_number}\Windows\Max IO\{iProduct}.csv`
- Scope screenshots: matching `.png` files in the same folders as the CSVs.
- Temporary benchmark files on the DUT: `benchmark_file.dat` (fio) or `testfile.dat` (diskspd), deleted after runs.
- Data drive structure and tracker: `<project>\Linux`, `<project>\macOS`, `<project>\Windows`, and `progress_tracker.json`.
- Post-processing output (when run): `current_measurements.json`.

## Setup (uv)

This repo uses `uv` to manage dependencies and the virtual environment.

## Create the venv and install deps

```
uv venv
uv sync --group dev
```

## Run tools

```
uv run pre-commit install
uv run pre-commit run --all-files
```

## Run CLI

```
uv run drive-qual
```

## Windows USB tool note

The signed `usb` CLI must be available on `PATH`.

## Benchmark binaries

Windows benchmarks use `tools/fio.exe` and `tools/diskspd.exe` (or copies available on `PATH`).
