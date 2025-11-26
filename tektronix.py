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
            s.settimeout(0.1) 
            try:
                s.recv(4096) # Dump the banner if it exists
            except socket.timeout:
                pass # No banner, safe to proceed
            
            s.settimeout(10) # Restore robust timeout for the actual query
            # -----------------------------------

            # Send Command
            s.sendall((cmd + "\n").encode("ascii"))

            if not read_response:
                return None

            # --- Read Response ---
            chunks = []
            while True:
                try:
                    chunk = s.recv(4096)
                    if not chunk:
                        break
                    chunks.append(chunk)
                    
                    # SCPI text responses always end in newline.
                    # If we are in text mode and see a newline, stop reading 
                    # to prevent hanging on open sockets.
                    if not raw and b'\n' in chunk:
                        break
                except socket.timeout:
                    # If the read times out but we have data, return what we have
                    if chunks: 
                        break
                    else: 
                        raise # Real timeout (no data)

            data = b"".join(chunks)

            if raw:
                return data
            else:
                # --- Binary-Safe Decoding ---
                # 'latin-1' maps bytes 1:1, preventing UnicodeDecodeError 
                # even if the scope sends weird symbols or binary garbage.
                return data.decode("latin-1").strip().strip('"')

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

def tek_filesystem_copy(source_path, dest_path):
    """
    Instructs the Tektronix scope to copy a file from its local disk 
    to another location using SCPI commands, with extended timeout handling.
    """
    # 1. Normalize paths for Windows (Scope OS)
    src = source_path.replace('/', '\\')
    dst = dest_path.replace('/', '\\')
    
    cmd = f'FILESYSTEM:COPY "{src}", "{dst}"'
    print(f"Sending Copy Command: {cmd}")

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(10)
            s.connect((HOST, PORT))

            # --- Flush Welcome Banner (Matches scpi_command logic) ---
            s.settimeout(0.1)
            try:
                s.recv(4096)
            except socket.timeout:
                pass
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

            if response != '1':
                print(f"Warning: *OPC? returned unexpected value: {response}")
            else:
                print(" -> Copy operation confirmed complete by Scope.")

    except socket.timeout:
        print(f"Error: Copy operation timed out (Limit: 60s). Check network/file size.")
        raise
    except socket.error as e:
        print(f"SCPI Copy Error: {e}")
        raise

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