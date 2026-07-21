from __future__ import annotations

import sys
from collections.abc import Callable

KEYBOARD_INTERRUPT_EXIT_CODE = 130
KEYBOARD_INTERRUPT_MESSAGE = "Cancelled by operator."


def run_cli_with_interrupt_handling(action: Callable[[], None]) -> int:
    try:
        action()
    except KeyboardInterrupt:
        print(f"\n{KEYBOARD_INTERRUPT_MESSAGE}", file=sys.stderr)
        return KEYBOARD_INTERRUPT_EXIT_CODE
    return 0
