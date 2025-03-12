#tektronix.py
import socket
import time
# CONFIG
#################################################
HOST = "169.254.8.130"  # Instrument IP
PORT = 4000            # SCPI socket port

inrush_path = 'C:/Drive Qual In-Rush Current Voltage'
maxio_path = 'C:/Drive Qual IO Current Voltage'

# FUNCTIONS
#################################################
def scpi_command(cmd, read_response=False):
    """
    Sends a SCPI command to the instrument over TCP.
    If read_response is True, returns the instrument's response.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.connect((HOST, PORT))
        s.sendall((cmd + "\n").encode("ascii"))
        if read_response:
            return s.recv(4096).decode("ascii").strip()

def recall_setup(setup_type="Max IO", device_type="Portable"):
    """
    Recalls a saved setup on the instrument.
    
    Args:
        setup_type (str): Must be either "Max IO" or "InRush".
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

def mk_dir(path):
    scpi_command(f"FILESystem:MKDir '{path}'")
    print(f"Created folder '{path}'")

def backup_session(path):
    scpi_command(f'SAVe:IMAGe "{path}"')
    print("Saved session screen capture.")

def save_measurements(path):
    scpi_command(f'SAVe:EVENTtable:MEASUrement "{path}"')
    print("Saved session measurements.")
