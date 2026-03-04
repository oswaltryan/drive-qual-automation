from __future__ import annotations

import contextlib
import socket
from typing import Literal, overload

# CONFIG
#################################################
HOST = "169.254.8.130"  # Instrument IP
PORT = 5025  # SCPI socket port

# These are base paths for the setup files stored on the Scope's internal C: drive
inrush_path = "C:/Drive Qual In-Rush Current Voltage"
maxio_path = "C:/Drive Qual IO Current Voltage"


# FUNCTIONS
#################################################
def _flush_banner(sock: socket.socket) -> None:
    sock.settimeout(0.1)
    with contextlib.suppress(TimeoutError):
        sock.recv(4096)  # Dump the banner if it exists


def _read_response(sock: socket.socket, raw: bool) -> bytes:
    chunks: list[bytes] = []
    while True:
        try:
            chunk = sock.recv(4096)
            if not chunk:
                break
            chunks.append(chunk)
            if not raw and b"\n" in chunk:
                break
        except TimeoutError:
            if chunks:
                break
            raise
    return b"".join(chunks)


@overload
def scpi_command(cmd: str, read_response: Literal[False] = False, raw: bool = False) -> None: ...


@overload
def scpi_command(cmd: str, read_response: Literal[True], raw: Literal[False] = False) -> str | None: ...


@overload
def scpi_command(cmd: str, read_response: Literal[True], raw: Literal[True]) -> bytes | None: ...


def scpi_command(cmd: str, read_response: bool = False, raw: bool = False) -> bytes | str | None:
    """
    Sends a SCPI command to the instrument over TCP.

    Fixes applied:
    1. Flushes "Terminal Session" banners upon connection (Port 4000 fix).
    2. Uses 'latin-1' decoding to prevent UnicodeDecodeError on special characters.
    3. improved read loop to ensure full directory listings are captured.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(10)  # Standard timeout
            s.connect((HOST, PORT))

            # --- Flush Welcome Banner ---
            # If the scope sends a "Terminal Session" message on connect,
            # we must read and discard it before sending our command.
            _flush_banner(s)

            s.settimeout(10)  # Restore robust timeout for the actual query
            # -----------------------------------

            # Send Command
            s.sendall((cmd + "\n").encode("ascii"))

            if not read_response:
                return None

            # --- Read Response ---
            data = _read_response(s, raw)

            if raw:
                return data
            else:
                # --- Binary-Safe Decoding ---
                # 'latin-1' maps bytes 1:1, preventing UnicodeDecodeError
                # even if the scope sends weird symbols or binary garbage.
                return data.decode("latin-1").strip().strip('"')

    except OSError as e:
        print(f"SCPI Communication Error: {e}")
        return None


def check_error() -> None:
    # SYSTem:ERRor? returns the next error in the queue
    err = scpi_command("SYSTem:ERRor?", read_response=True)
    print(f"Instrument Error: {err}")


def get_identity() -> str | None:
    """Return the SCPI *IDN? response from the scope."""
    return scpi_command("*IDN?", read_response=True)


def get_firmware_version() -> str | None:
    """Return the firmware/system version string."""
    return scpi_command("SYSTem:VERSion?", read_response=True)


def get_acquire_state() -> str | None:
    """Return the acquisition state (RUN/STOP) if available."""
    return scpi_command("ACQuire:STATE?", read_response=True)


def _normalize_scope_path(path: str) -> str:
    return path.replace("\\", "/").strip()


def _validate_scope_path(path: str, *, allow_empty: bool = False) -> str:
    normalized = _normalize_scope_path(path)
    if not normalized and allow_empty:
        return normalized
    if not normalized:
        raise ValueError("Scope path is required.")
    if not (normalized[1:3] == ":/" and normalized[0].isalpha()):
        raise ValueError(f"Invalid scope path: {path!r}")
    return normalized


def _validate_scope_file_path(path: str) -> str:
    normalized = _validate_scope_path(path)
    if normalized.endswith("/"):
        raise ValueError(f"Scope file path must not be a directory: {path!r}")
    return normalized


def tektronix_list_dir(remote_path: str = "") -> str | None:
    """
    Lists the contents of a directory on the instrument.

    Args:
        remote_path (str): The directory to list. Defaults to the CWD.
                           Use a path like 'C:/' or 'E:/Waveforms/'.

    Returns:
        str: A CSV string of files/directories, or None on error.
    """
    # Set the CWD (optional, but good practice for specific path listing)
    normalized_path = _validate_scope_path(remote_path, allow_empty=True)
    scpi_command(f'FILESystem:CWD "{normalized_path}"')

    # Query the directory contents
    cmd = "FILESystem:DIR?"
    response = scpi_command(cmd, read_response=True, raw=False)

    if response:
        (f"\n--- Directory Listing for '{normalized_path}' ---")
        print(response)
        print("-------------------------------------------\n")
    else:
        print(f"Failed to get directory listing for '{normalized_path}'.")

    return response


def tek_filesystem_copy(source_path: str, dest_path: str) -> None:
    """
    Instructs the Tektronix scope to copy a file from its local disk
    to another location using SCPI commands, with extended timeout handling.
    """
    # 1. Normalize paths for Windows (Scope OS)
    src = _validate_scope_file_path(source_path).replace("/", "\\")
    dst = _validate_scope_file_path(dest_path).replace("/", "\\")

    cmd = f'FILESYSTEM:COPY "{src}", "{dst}"'
    print(f"Sending Copy Command: {cmd}")

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(10)
            s.connect((HOST, PORT))

            # --- Flush Welcome Banner (Matches scpi_command logic) ---
            _flush_banner(s)
            # ---------------------------------------------------------

            # 2. Send the Copy Command
            s.sendall((cmd + "\n").encode("ascii"))

            # 3. Synchronization (*OPC?)
            # We send *OPC? immediately to make the socket wait until the
            # copy operation is finished before returning.
            s.sendall(b"*OPC?\n")

            # 4. Set Extended Timeout
            # File copies over network can take time. We override the default
            # 10s timeout to 60s for this specific operation.
            s.settimeout(60.0)

            # 5. Read Response
            # We expect '1' when the operation is complete.
            response = s.recv(1024).decode("latin-1").strip()

            if response != "1":
                print(f"Warning: *OPC? returned unexpected value: {response}")
            else:
                print(" -> Copy operation confirmed complete by Scope.")

    except TimeoutError:
        print("Error: Copy operation timed out (Limit: 60s). Check network/file size.")
        raise
    except OSError as e:
        print(f"SCPI Copy Error: {e}")
        raise


def recall_setup(setup_type: str = "Max IO", device_type: str = "Portable") -> None:
    """
    Recalls a saved setup on the instrument.
    """
    if setup_type == "Max IO":
        path = maxio_path
    elif setup_type == "InRush":
        path = inrush_path + " Secure Keys" if device_type == "Secure Key" else inrush_path + " Portables"
    else:
        raise ValueError("Invalid setup_type. Choose 'Max IO' or 'InRush'.")

    scpi_command(f'RECAll:SETUp "{path}.set"')
    print(f'Recalled setup from "{path}.set"')


def stop_run() -> None:
    scpi_command("ACQUIRE:STATE STOP")
    print("Acquisition stopped.")


def backup_session(path: str) -> None:
    normalized_path = _validate_scope_file_path(path)
    scpi_command(f'SAVe:IMAGe "{normalized_path}"')
    print(f"Saved session screen capture to {normalized_path}")


def save_measurements(path: str) -> None:
    normalized_path = _validate_scope_file_path(path)
    scpi_command(f'SAVe:EVENTtable:MEASUrement "{normalized_path}"')
    print(f"Saved session measurements to {normalized_path}")


def save_report(path: str) -> None:
    normalized_path = _validate_scope_file_path(path)
    scpi_command(f'SAVe:REPOrt "{normalized_path}"')
    print(f"Saved session screen capture to {normalized_path}")
