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
