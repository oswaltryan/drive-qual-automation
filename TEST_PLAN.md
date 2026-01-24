# Test Plan (Multi-Phase)

This plan documents how we will validate existing functionality, define the
end-to-end flow, and capture gaps before new development begins.

## Phase 0: Inventory and Baseline

- [x] List all scripts, CLI entry points, and external tools used.
- [x] Identify hardware dependencies (Tektronix scope, Apricorn devices).
- [x] Record required environment assumptions (OS, admin privileges, PATH tools).
- [x] Capture current expected outputs and file artifacts.

## Phase 1: Define the End-to-End Workflow

- [x] Write a step-by-step operator flow (prompts, actions, expected results).
- [x] Document device states (connected, removed, locked/unlocked).
- [x] Define inputs and outputs for each step (files, screenshots, CSVs).
- [x] Specify where artifacts are stored and naming conventions.

## Phase 2: Validate USB Discovery and Device State Handling

- [x] Verify `usb --json` output parsing for device info and drive letter.
- [x] Confirm behavior when no device is present (retry loops).
- [x] Confirm behavior when device is present but locked/OOB.
- [x] Record observed exit codes and terminal messages.

Observed runs:
- No device: `usb --json did not return parseable JSON.` (exit code 1).
- Device present, locked/OOB: `driveLetter: None` with device metadata present (exit code 0).
- Device present, unlocked: `driveLetter: D:` with device metadata present (exit code 0).

## Phase 3: Validate Tektronix Scope Integration

- Verify connectivity to the scope over TCP.
- Confirm setup recall paths and expected scope state changes.
- Validate measurement and screenshot save operations.
- Note any timeouts, banner behavior, or connection issues.

## Phase 4: Validate Benchmark Tools

- Confirm `fio.exe` and `diskspd.exe` are callable from `tools/` or PATH.
- Validate read/write benchmarks run and return codes are captured.
- Confirm cleanup of benchmark files on the drive.
- Compare expected vs observed throughput metrics (if applicable).

## Phase 5: Verify Output Artifacts

- Confirm measurement CSVs and screenshots are saved correctly.
- Validate output paths and file naming conventions.
- Ensure data consistency across repeated runs.

## Phase 6: Document Gaps and Stabilization Tasks

- List any steps with unclear behavior or missing documentation.
- Record failures, flaky behaviors, and required fixes.
- Prioritize follow-up tasks for reliability and automation.

## Deliverables

- A written, step-by-step workflow guide.
- A checklist for operators and reviewers.
- A log of issues and proposed fixes.
