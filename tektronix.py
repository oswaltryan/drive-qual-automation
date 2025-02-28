import socket

# CONFIG
#################################################
HOST = "169.254.8.130"  # Instrument IP
PORT = 4000            # SCPI socket port

inrush_path = 'C:/Drive Qual In-Rush Current Voltage.set'
maxio_path = 'C:/Drive Qual IO Current Voltage.set'

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

def recall_setup(setup_type="Max IO"):
    """
    Recalls a saved setup on the instrument.
    
    Args:
        setup_type (str): Must be either "Max IO" or "InRush".
    """
    if setup_type == "Max IO":
        path = maxio_path
    elif setup_type == "InRush":
        path = inrush_path
    else:
        raise ValueError("Invalid setup_type. Choose 'Max IO' or 'InRush'.")
    
    scpi_command(f'RECAll:SETUp "{path}"')
    print(f'Recalled setup from "{path}"')

def stop_run():
    """
    Sends the command to stop the instrument's run.
    """
    scpi_command("STOP")
    print("STOP command sent.")

