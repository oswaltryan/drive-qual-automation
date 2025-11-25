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
    
def check_error():
    # SYSTem:ERRor? returns the next error in the queue
    err = scpi_command("SYSTem:ERRor?", read_response=True)
    print(f"Instrument Error: {err}")
    
def tektronix_list_dir(remote_path=""):
    """
    Lists the contents of a directory on the instrument.
    
    Args:
        remote_path (str): The directory to list. Defaults to the CWD.
                           Use a path like 'C:/' or 'E:/Waveforms/'.

    Returns:
        str: A CSV string of files/directories, or None on error.
    """
    # Set the CWD (optional, but good practice for specific path listing)
    scpi_command(f'FILESystem:CWD "{remote_path}"')
    
    # Query the directory contents
    cmd = 'FILESystem:DIR?'
    response = scpi_command(cmd, read_response=True, raw=False)
    
    if response:
        print(f"\n--- Directory Listing for '{remote_path}' ---")
        print(response)
        print("-------------------------------------------\n")
    else:
        print(f"Failed to get directory listing for '{remote_path}'.")
        
    return response

def tektronix_copy(remote_path, local_path):
    """
    Copies a file FROM the Tektronix MSO TO the host machine
    using FILESystem:READFile, which returns arbitrary block data.

    Args:
        remote_path (str): Path as seen by the scope, e.g. 'E:/data/file.csv'
        local_path  (str): Local path on the host, e.g. './file.csv'

    Returns:
        local_path on success, or raises RuntimeError on failure.
    """
    cmd = f'FILESystem:READFile "{remote_path}"'
    
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(10) # Use a longer timeout for file transfer
            s.connect((HOST, PORT))
            
            # 1. Send the READFile command
            s.sendall((cmd + "\n").encode("ascii"))
            
            # 2. Read the definite-length arbitrary block header
            # Header format: #<A><X...>, where A is length of X, and X is data length
            header = s.recv(1) # Read the '#'
            if header != b'#':
                raise RuntimeError(f"Unexpected start of file transfer response: {header.decode()}")

            len_digits_byte = s.recv(1) # Read 'A' (the number of digits in the length field)
            if not len_digits_byte:
                raise RuntimeError("Failed to read block length digit count.")
            
            len_digits = int(len_digits_byte.decode())
            
            # Read 'X...' (the length of the data block)
            data_length_bytes = s.recv(len_digits)
            data_length = int(data_length_bytes.decode())
            print(f"File transfer detected: {data_length} bytes.")

            # 3. Read the exact data block
            data_buffer = []
            bytes_received = 0
            while bytes_received < data_length:
                # Read the remaining bytes or 4096 (whichever is smaller)
                chunk = s.recv(min(data_length - bytes_received, 4096))
                if not chunk:
                    raise RuntimeError("Socket closed unexpectedly during file transfer.")
                data_buffer.append(chunk)
                bytes_received += len(chunk)
            
            data = b"".join(data_buffer)

            # 4. Read the termination character(s) (e.g., \n or \r\n)
            s.recv(1) # This assumes the termination is a single character (\n)
            
            if len(data) != data_length:
                 raise RuntimeError(f"Data length mismatch. Expected {data_length}, received {len(data)}.")
                 
            # 5. Save the received data locally
            with open(local_path, "wb") as f:
                f.write(data)

    except socket.error as e:
        raise RuntimeError(f"SCPI Communication Error during file transfer: {e}")

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