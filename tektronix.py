#tektronix.py
import socket
import time
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
    scpi_command("ACQUIRE:STATE STOP")
    print("Acquisition stopped.")


def stop_run_and_capture_pdf(pdf_filename):
    """
    Attempts to stop the Tektronix instrument run and capture its screen as a PDF.

    The commands below are examples:
      - 'ACQUIRE:STATE STOP' is used to freeze acquisition.
      - 'HARDCOPY:FORMAT PDF' sets the capture format.
      - 'HARDCOPY:DESTINATION INTERNAL' directs the file to be stored locally.
      - 'HARDCOPY:START' initiates the capture.

    Adjust these commands as per your instrument's SCPI reference.
    """
    # Stop the instrument's acquisition (alternative to RSTOP)
    scpi_command("ACQUIRE:STATE STOP")
    print("Acquisition stopped.")

    # Configure hardcopy capture to PDF and local destination.
    scpi_command("HARDCOPY:FORMAT PDF")
    scpi_command("HARDCOPY:DESTINATION INTERNAL")

    # Initiate the capture.
    scpi_command("HARDCOPY:START")
    print("Hardcopy capture initiated.")

    # Allow time for the capture to complete.
    time.sleep(5)

    print(f"Report captured and saved locally as {pdf_filename}")


def stop_cap_pdf(pdf_filename):
    """
    Stops the instrument run/acquisition and saves a screenshot as a PDF file
    on the scope's local or removable storage.
    
    Adjust these commands to match your Tektronix model's SCPI reference.
    """
    # 1) Stop acquisition
    scpi_command("ACQUIRE:STATE STOP")
    print("Acquisition stopped.")

    # 2) Set the port to file output (optional if the scope always defaults to file)
    scpi_command("HARDCOPY:PORT FILE")
    
    # 3) Configure hardcopy format (PDF if supported)
    scpi_command("HARDCOPY:FORMAT PDF")

    # 4) Specify filename + path on the scope (e.g., USB, internal disk)
    scpi_command(f'HARDCOPY:FILENAME "{pdf_filename}"')

    # 5) Start the hardcopy process
    scpi_command("HARDCOPY:START")
    print("Hardcopy capture initiated...")

    # If needed, wait for the scope to finish writing the file
    import time
    time.sleep(3)
    print(f"Screenshot saved as: {pdf_filename}")

