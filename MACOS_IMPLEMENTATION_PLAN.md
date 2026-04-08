# macOS Implementation Plan

## Goal

Bring macOS to the same engineering standard as the maintained `drive-qual-report` workflow while avoiding premature GUI automation work.

The immediate goal is a reliable, test-covered, operator-assisted macOS path. Full Blackmagic GUI automation should be saved for the final phase because it is likely to be the most brittle part of the platform work.

## Current Baseline

This repository already has partial macOS implementation work in progress:

- `drive_info` and `equipment` are portable enough for macOS.
- `drive_qual.platforms.performance` dispatches macOS to `drive_qual.platforms.macos.performance`.
- `drive_qual.platforms.macos.performance` provides a first-pass Blackmagic Disk Speed Test workflow.
- The current macOS performance flow is operator-assisted:
  - launches Blackmagic Disk Speed Test if possible
  - waits for the operator to run the benchmark
  - captures a screenshot with `screencapture`
  - prompts for read/write MB/s values
  - writes JSON and CSV artifacts
  - updates `performance -> DUT -> macOS`
- `drive_qual.platforms.power_measurements` exists as a neutral dispatcher, but it still delegates internally to `drive_qual.platforms.windows.power_measurements`.
- `pywinauto` is scoped to Windows with an environment marker.
- README/defaults/test fixtures have been updated toward the normalized `Blackmagic Disk Speed Test` name.

## Remaining Gaps

- The current Blackmagic flow is not fully automated.
- The manual-assisted macOS performance fallback needs to be hardened.
- Power-measurement implementation internals still live under a Windows-named module.
- The updated tests have not been verified with the intended `uv`/`pytest` environment.
- Platform parity tests still need cleanup so Linux/macOS shared behavior is not represented through Windows-named module imports.
- Final operator documentation should be revisited after the automation strategy is settled.

## Constraints

- Preserve the report JSON contract unless an intentional migration is planned.
- Preserve artifact naming and directory layout unless tests and downstream workflow are updated together.
- Shared CLI paths must remain importable on Linux, macOS, and Windows without importing Windows-only packages at module import time.
- macOS performance must always produce both:
  - a screenshot artifact
  - a structured result artifact in CSV or JSON
- Full Blackmagic GUI automation must remain optional until it is proven reliable.
- Any macOS-specific GUI automation dependency or permission requirement must be isolated to macOS execution paths.

## Phase 1: Stabilize The Manual-Assisted macOS Performance Flow

### Objective

Make the current operator-assisted Blackmagic path reliable enough to serve as the default implementation and future fallback.

### Work Items

- Confirm artifact layout:
  `Z:/<part>/macOS/Blackmagic Disk Speed Test/<dut>_<timestamp>.png`
- Confirm structured JSON fields:
  `tool`, `dut`, `read_mb_s`, `write_mb_s`, `captured_at`
- Confirm structured CSV fields:
  `Metric,Value`, `Read MB/s`, `Write MB/s`
- Reject invalid, zero, or negative read/write values before report writeback.
- Improve prompts to explain:
  - the benchmark must be complete before continuing
  - values must be entered in MB/s
  - macOS Screen Recording permission may be required
  - manual launch is acceptable if `open -a` fails
- Keep this path available permanently as a fallback for future automation.

### Acceptance Criteria

- `drive-qual-report --steps performance --part-number <part>` on macOS can produce a screenshot, JSON artifact, CSV artifact, and report update.
- The flow remains usable if the app cannot be launched automatically.
- Invalid read/write values do not write partial or bad report data.

## Phase 2: Verify Test Environment And Current Changes

### Objective

Validate the current work in the supported project environment before deeper refactors or GUI automation.

### Work Items

- Restore or install the expected dev environment:
  `uv venv`
- Sync dependencies:
  `uv sync --group dev`
- Run:
  `uv run pytest`
- Run:
  `uv run pre-commit run --all-files`
- If `uv` is unavailable, document the blocker and run an equivalent Python 3.12 virtualenv with `pytest`.
- Fix failures that expose real contract or import-boundary issues.

### Acceptance Criteria

- `uv run pytest` passes.
- `uv run pre-commit run --all-files` either passes or has documented, actionable failures.
- Import-boundary tests prove shared CLI imports do not eagerly import Windows performance or power modules.

## Phase 3: Finish Platform Naming And Dispatch Boundaries

### Objective

Complete the platform-boundary cleanup without changing lab behavior.

### Work Items

- Keep `src/drive_qual/platforms/power_measurements.py` as the neutral power-measurements entrypoint.
- Split shared or mixed behavior out of `src/drive_qual/platforms/windows/power_measurements.py` into a neutral implementation module, for example:
  `src/drive_qual/platforms/power_measurements_mixed.py`
- Keep Windows-only helpers in the Windows module, including:
  - Disk Management prompts
  - PowerShell safe eject
  - Windows drive-letter normalization
- Move Linux/macOS native disk prep and safe removal branches to neutral or platform-specific helpers.
- Update tests so shared Linux/macOS power-measurement behavior is not monkeypatched through a Windows-named module.
- Keep compatibility shims only if needed for downstream imports.

### Acceptance Criteria

- `drive_qual.workflows.report` imports only platform-neutral dispatch modules for mixed-platform steps.
- Linux/macOS power-measurement tests target neutral or platform-specific modules instead of `platforms.windows.power_measurements`.
- Windows-only behavior remains isolated to Windows modules.
- Shared CLI import paths do not import Windows-only modules at module import time.

## Phase 4: Build Platform Test Parity

### Objective

Make Linux, macOS, and Windows first-class platforms in tests for maintained workflow behavior.

### Required Coverage

For `power_measurements`:

- workflow dispatch through the platform-neutral import path
- compatibility field updates for Linux, macOS, and Windows
- artifact OS path selection for Linux, macOS, and Windows
- native disk prep and safe-removal branch behavior for Linux and macOS
- Windows-only Disk Management behavior remains isolated

For `performance`:

- dispatcher routes Linux, macOS, and Windows correctly
- report performance section is updated for Linux, macOS, and Windows
- artifact paths and file generation are correct per platform
- macOS Blackmagic path produces screenshot plus structured result artifacts
- manual fallback is tested and intentionally preserved

### Acceptance Criteria

- Each maintained mixed-platform step has explicit Linux, macOS, and Windows tests.
- No platform is represented only indirectly through another platform's module.
- Tests use shared fixtures/helpers where practical instead of duplicating platform setup.

## Phase 5: Documentation And Operator Handoff For The Manual Path

### Objective

Make the currently supported macOS workflow clear to operators before pursuing harder GUI automation.

### Work Items

- Update README with the current manual-assisted macOS mode.
- Document required macOS permissions:
  - Screen Recording for screenshots
  - Accessibility only if later automation requires it
- Document recovery behavior if Blackmagic cannot be launched automatically.
- Document expected artifact paths and report fields.
- Document that read/write values are manually entered in the current mode.

### Acceptance Criteria

- A macOS operator can tell exactly what prerequisites are required.
- A macOS operator can tell what artifacts will be produced.
- A developer can tell which modules own macOS performance, shared power measurement logic, and Windows-only automation.

## Phase 6: Evaluate Blackmagic GUI Automation Strategy

### Objective

Choose a macOS automation strategy only after the manual path, tests, and platform boundaries are stable.

### Options To Evaluate

- AppleScript via `osascript`
- Accessibility scripting via AppleScript UI scripting
- A small macOS-specific helper script that uses native commands
- OCR or screenshot analysis only if app scripting is not feasible
- Keeping manual entry as the documented long-term path if automation is too brittle

### Evaluation Checklist

- Can it launch and focus Blackmagic Disk Speed Test?
- Can it select the target drive if multiple disks are present?
- Can it start the benchmark reliably?
- Can it detect benchmark completion?
- Can it read or export write/read values directly?
- Does it require Accessibility permission, Screen Recording permission, or both?
- Does it fail safely back to the manual-assisted flow?
- Can it be tested without a real GUI session?

### Acceptance Criteria

- A decision note is committed to the repo.
- Required permissions and any macOS-only dependency are documented before implementation.
- The selected approach has a clear fallback to the manual-assisted flow.

## Phase 7: Implement Optional Blackmagic GUI Automation

### Objective

Add true Blackmagic automation behind a fallback-capable boundary, without making it mandatory for all macOS runs.

### Work Items

- Add an automation mode flag or internal strategy selection:
  - `manual`
  - `auto`
  - `auto-with-manual-fallback`
- Keep `auto-with-manual-fallback` as the default only if automation proves stable. Otherwise keep `manual` as default.
- Encapsulate automation in a small macOS-specific module, for example:
  `src/drive_qual/platforms/macos/blackmagic.py`
- Keep GUI scripting calls out of module import time.
- Return a structured result object containing:
  - screenshot path
  - JSON/CSV artifact paths
  - read MB/s
  - write MB/s
  - collection method
- Update `src/drive_qual/platforms/macos/performance.py` to consume that result object and perform report writeback.

### Acceptance Criteria

- The automated path can launch/focus Blackmagic, start a benchmark, capture a screenshot, and populate read/write MB/s without manual value entry on a configured macOS host.
- The manual-assisted path remains available and tested.
- Automation failures do not corrupt the report or write partial results.

## Recommended Execution Order

1. Stabilize the current manual-assisted Blackmagic path.
2. Run and fix the test environment.
3. Finish platform naming and dispatch boundaries.
4. Build platform test parity.
5. Update documentation for the current manual-supported mode.
6. Evaluate Blackmagic GUI automation.
7. Implement optional GUI automation last.

This order keeps the working macOS fallback intact while reducing risk around GUI automation and module refactoring.

## Success Definition

macOS is complete enough when all of the following are true:

- maintained workflow code does not describe mixed-platform steps through Windows-only module names
- macOS `power_measurements` is first-class and tested
- macOS `performance` runs through a dedicated implementation
- Blackmagic produces both screenshot and structured result artifacts
- report writeback is tested for Linux, macOS, and Windows
- Windows-only dependencies stay confined to Windows-only code paths
- full Blackmagic GUI automation is either implemented behind a fallback boundary or explicitly deferred with a documented reason
