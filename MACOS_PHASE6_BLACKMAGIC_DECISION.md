# macOS Phase 6 Decision: Blackmagic Automation Strategy

Date: 2026-04-09

## Decision

Use a macOS-only AppleScript strategy (via `osascript`) to automate Blackmagic Disk Speed Test setup and benchmark toggling, with workflow-level fallback to the existing manual-assisted path.

The automation is integrated into `src/drive_qual/platforms/macos/performance.py` and implemented in `src/drive_qual/platforms/macos/blackmagic.py`.

## Selected Approach

1. Close stale Blackmagic process state.
2. Launch and focus Blackmagic.
3. Open `Select Target Drive...` and choose the fixed DUT volume path `/Volumes/DUT`.
4. Start benchmark by coordinate click in the Blackmagic main window.
5. Run for a fixed duration.
6. Stop benchmark by the same coordinate click.
7. Continue with existing workflow behavior:
   - capture screenshot artifact
   - prompt operator for read/write MB/s values
   - write JSON and CSV artifacts
   - update report JSON

## Hard-Coded Values (Phase 6)

- Duration: `60` seconds.
- Target volume path: `/Volumes/DUT`.
- Toggle interaction: coordinate mode only.
- Relative click location: `x=0.50`, `y=0.31`.

No controls-index fallback is included.

## Required Permissions

- Accessibility permission for UI scripting through `System Events`.
- Screen Recording permission for screenshot capture (`screencapture`).

## Dependency Notes

- Uses macOS-native commands (`osascript`, `open`, `pkill`, `screencapture`).
- No new third-party Python dependencies were added.

## Fallback Contract

If automation fails at any point, the workflow logs the failure and falls back to the existing manual-assisted Blackmagic flow. This preserves artifact/report behavior and prevents partial report corruption.
