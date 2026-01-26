# Drive Qualification Automation

This project automates Apricorn drive qualification workflows using a Tektronix
scope, benchmark tools, and a signed `usb` discovery CLI. It is designed as a
scripted, interactive CLI experience for technicians running repeatable tests.

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

## Phase 1: End-to-End Workflow

Step-by-step operator flow (current scripts):
1) Run `uv run drive-qual`.
2) Enter the Apricorn part number when prompted.
3) Select device type (Portables or Secure Key) if running `drive-qual`.
4) Remove the Apricorn device when prompted; script waits until no device is detected.
5) In Rush Current: recall the InRush scope setup, create the output directory, then unlock/connect the device.
6) Save the In Rush Current measurements and screenshot, then stop acquisition.
7) Max IO: unlock/connect the device, recall the Max IO setup, run benchmarks, then delete the benchmark file.
8) Save the Max IO measurements and screenshot, stop acquisition, and remove the device.

Device states the scripts handle:
- Connected vs removed (polling `usb --json` until the state changes).

Inputs and outputs by step:
- Inputs: part number, device type (in `drive-qual`), device connect/remove actions, scope network access, `usb` CLI.
- Benchmark inputs: target drive letter, test type, size/loops (fio) or fixed diskspd params.
- Outputs: CSV measurements, PNG screenshots, stdout benchmark logs, and a deleted benchmark temp file.

Artifacts, locations, and naming conventions:
- In Rush outputs: `E:\{part_number}\Windows\In Rush Current\{iProduct}.csv` and `.png`.
- Max IO outputs: `E:\{part_number}\Windows\Max IO\{iProduct}.csv` and `.png`.
- Benchmark temp files: `{drive}\benchmark_file.dat` (fio) or `{drive}\testfile.dat` (diskspd).
- Data drive scaffold: `<project>\Linux`, `<project>\macOS`, `<project>\Windows`, plus `progress_tracker.json`.

## Setup (uv)

This repo uses `uv` to manage dependencies and the virtual environment.

**Note:** The scope's LAN implementation is brittle and only supports its default IPv4 address; manually setting a different scope IP will cause issues. Any machine that interfaces with the scope must be configured with a manual IPv4 address on the same subnet `169.254.8.xxx`.

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
