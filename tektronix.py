import socket
import time

# CONFIG
#################################################
HOST = "169.254.8.130"  # Instrument IP
PORT = 4000             # SCPI socket port

# These are base paths for the setup files stored on the Scope's internal C: drive
inrush_path = 'C:/Drive Qual In-Rush Current Voltage'
maxio_path = 'C:/Drive Qual IO Current Voltage'

# FUNCTIONS
#################################################
def scpi_command(cmd, read_response=False, raw=False):
    """
    Sends a SCPI command to the instrument over TCP.
    
    Args:
        cmd (str): SCPI command (without trailing newline).
        read_response (bool): If True, read a response from the instrument.
        raw (bool): If True, return raw bytes and read until EOF.
                    If False, read a single ASCII chunk (up to 4096 bytes).

    Returns:
        - None if read_response is False or on error.
        - str if read_response is True and raw is False.
        - bytes if read_response is True and raw is True.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(5)  # Safety timeout
            s.connect((HOST, PORT))
            s.sendall((cmd + "\n").encode("ascii"))

            if not read_response:
                return None

            if raw:
                # Read until the instrument closes the connection
                chunks = []
                while True:
                    chunk = s.recv(4096)
                    if not chunk:
                        break
                    chunks.append(chunk)
                return b"".join(chunks)
            else:
                # Simple ASCII response for normal SCPI queries
                return s.recv(4096).decode("ascii").strip().strip('"')

    except socket.error as e:
        print(f"SCPI Communication Error: {e}")
        return None
    
def tektronix_copy(remote_path, local_path):
    """
    Copies a file FROM the Tektronix MSO TO the host machine.

    Args:
        remote_path (str): Path as seen by the scope, e.g. 'E:/waveforms/tek0001CH1.csv'
        local_path  (str): Local path on the host, e.g. './tek0001CH1.csv'

    Returns:
        local_path on success, or raises RuntimeError on failure.
    """
    data = scpi_command(f'FILESystem:READFile "{remote_path}"', read_response=True, raw=True)
    if data is None:
        raise RuntimeError(f"Failed to read remote file '{remote_path}' from Tektronix (no data returned).")

    try:
        with open(local_path, "wb") as f:
            f.write(data)
    except OSError as e:
        raise RuntimeError(f"Failed to save file to '{local_path}': {e}")

    return local_path

def recall_setup(setup_type="Max IO", device_type="Portable"):
    """
    Recalls a saved setup on the instrument.
    """
    if setup_type == "Max IO":
        path = maxio_path
    elif setup_type == "InRush":
        if device_type == "Secure Key":
            path = inrush_path + ' Secure Keys'
        else:
            path = inrush_path + ' Portables'
    else:
        raise ValueError("Invalid setup_type. Choose 'Max IO' or 'InRush'.")
    
    scpi_command(f'RECAll:SETUp "{path}.set"')
    print(f'Recalled setup from "{path}.set"')

def stop_run():
    scpi_command("ACQUIRE:STATE STOP")
    print("Acquisition stopped.")

def backup_session(path):
    scpi_command(f'SAVe:IMAGe "{path}"')
    print(f"Saved session screen capture to {path}")

def save_measurements(path):
    scpi_command(f'SAVe:EVENTtable:MEASUrement "{path}"')
    print(f"Saved session measurements to {path}")