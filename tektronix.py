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
def scpi_command(cmd, read_response=False):
    """
    Sends a SCPI command to the instrument over TCP.
    If read_response is True, returns the instrument's response.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(5) # Safety timeout
            s.connect((HOST, PORT))
            s.sendall((cmd + "\n").encode("ascii"))
            if read_response:
                return s.recv(4096).decode("ascii").strip().strip('"')
    except socket.error as e:
        print(f"SCPI Communication Error: {e}")
        return None

def detect_scope_drive():
    """
    Probes the Tektronix MSO for available USB host drive: E:, F:, or G:.
    This uses scpi_command internal to this library.

    Returns:
        'E:', 'F:', or 'G:' when found.
        Raises Exception if none found.
    """
    for drive in ["E:", "F:", "G:"]:
        # Try setting the working directory to that drive
        scpi_command(f'FILESYSTEM:CWD "{drive}"')
        
        # Confirm by querying the CWD back
        current = scpi_command("FILESYSTEM:CWD?", read_response=True)
        
        if current and drive in current:
            print(f"Scope Storage Detected: {drive}")
            return drive
            
    raise IOError("No USB drive detected on Tektronix Scope (Checked E, F, G)")

def mk_dir(path):
    """
    Attempts to create a directory on the Scope.
    """
    # Note: SCPI often throws an error if the dir exists, 
    # but we can just proceed as it doesn't crash the python script.
    scpi_command(f"FILESystem:MKDir '{path}'")

def ensure_scope_directory_structure(drive_letter, project_name, sub_folders):
    """
    Creates the folder hierarchy on the Scope one level at a time.
    Example: E:/ -> E:/Project -> E:/Project/Windows -> E:/Project/Windows/Max IO
    
    Returns:
        str: The base project path on the scope (e.g., "E:/ProjectName")
    """
    # 1. Create Project Folder
    base_project_path = f"{drive_letter}/{project_name}"
    mk_dir(base_project_path) 
    print(f"Verifying Scope path: {base_project_path}")
    
    # 2. Create Subfolders
    for folder in sub_folders:
        # Create OS folder (e.g., Windows)
        current_path = f"{base_project_path}/{folder}"
        mk_dir(current_path) 
        
        # Create Test specific folders within that OS folder
        mk_dir(f"{current_path}/Max IO")
        mk_dir(f"{current_path}/In Rush Current")
    
    return base_project_path

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