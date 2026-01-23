# Setup (uv)

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

For Windows, you must set up `win-usb-tool`. For macOS and Linux, no extra setup is required beyond Python.
