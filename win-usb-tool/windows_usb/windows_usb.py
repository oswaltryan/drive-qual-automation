import libusb as usb
import ctypes as ct
from dataclasses import dataclass
import subprocess
from pprint import pprint
import win32com.client

# Configure libusb to use the included libusb-1.0.dll
usb.config(LIBUSB=None)

# --- WMI + Utility Code for Listing USB Drives ---
def bytes_to_gb(bytes_value):
    """Convert bytes to gigabytes."""
    return bytes_value / (1024 ** 3)

def find_closest(target, options):
    """Find the closest value in 'options' to 'target'."""
    return min(options, key=lambda x: abs(x - target))

closest_values = [16, 30, 60, 120, 240, 480, 1000, 2000]

locator = win32com.client.Dispatch("WbemScripting.SWbemLocator")
service = locator.ConnectServer(".", "root\\cimv2")

def list_usb_drives():
    """
    Returns a list of USB drives with their caption, size in GB,
    and the closest matching size from a predefined list.
    """
    query = "SELECT * FROM Win32_DiskDrive WHERE InterfaceType='USB'"
    usb_drives = service.ExecQuery(query)
    drives_info = []
    for drive in usb_drives:
        if getattr(drive, "Size", None) is None:
            continue
        try:
            size_bytes = int(drive.Size)
        except (TypeError, ValueError):
            continue
        size_gb = bytes_to_gb(size_bytes)
        closest_match = find_closest(size_gb, closest_values)
        drives_info.append({
            "caption": drive.Caption,
            "size_gb": size_gb,
            "closest_match": closest_match,
        })
    return drives_info

# --- USB Device Information Using libusb ---
class UsbTreeError(Exception):
    """Custom exception for USB tree errors."""
    pass

@dataclass
class WinUsbDeviceInfo:
    """Dataclass representing a USB device information structure."""
    idProduct: str
    idVendor: str
    bcdDevice: str
    bcdUSB: str
    iManufacturer: str
    iProduct: str
    iSerial: str
    device_id: str
    vendor: str
    usb_protocol: str
    usbController: str = ""
    SCSIDevice: str = ""
    driveSize: str = ""

def parse_usb_version(bcd):
    """Convert a BCD USB version to a human-readable string (e.g., '2.0', '3.1')."""
    major = (bcd & 0xFF00) >> 8
    minor = (bcd & 0x00F0) >> 4
    subminor = bcd & 0x000F
    if subminor:
        return f"{major}.{minor}{subminor}"
    return f"{major}.{minor}"

def read_string_descriptor_ascii(handle, index):
    """Read a string descriptor from a USB device and return it as ASCII."""
    if index == 0:
        return ""
    buf = (ct.c_ubyte * 256)()
    rc = usb.get_string_descriptor_ascii(handle, index, buf, ct.sizeof(buf))
    if rc < 0:
        return ""
    return bytes(buf[:rc]).decode("utf-8", errors="replace")
def get_usb_devices_from_wmi():
    query = "SELECT * FROM Win32_PnPEntity WHERE DeviceID LIKE 'USB%'"
    usb_devices = service.ExecQuery(query)

    devices_info = []
    for device in usb_devices:
        device_id = device.DeviceID  # e.g. "USB\\VID_0984&PID_1407\\SERIAL"
        if not device_id.upper().startswith("USB\\VID_"):
            continue

        parts = device_id.split("\\", 2)  # ["USB", "VID_0984&PID_1407", "SERIAL"]
        if len(parts) < 2:
            continue

        vid_pid = parts[1].split("&")
        vid = vid_pid[0].replace('VID_', '').lower()
        pid = vid_pid[1].replace('PID_', '').lower()
        serial = parts[2] if len(parts) > 2 else ""

        devices_info.append({
            "vid": vid,
            "pid": pid,
            "manufacturer": device.Manufacturer or "",
            "description": device.Description or "",
            "serial": serial
        })

    return devices_info

def dump_device_config(handle):
    """Dumps the active configuration and its endpoints for debugging."""
    print("\n  [*] Dumping Device Configuration...")
    dev = usb.get_device(handle)
    dev_desc = usb.device_descriptor()
    rc = usb.get_device_descriptor(dev, ct.byref(dev_desc))
    if rc < 0:
        print(f"  - Failed to get device descriptor: {rc}")
        return

    print(f"  - Total Configurations Available: {dev_desc.bNumConfigurations}")

    config_ptr = ct.POINTER(usb.config_descriptor)()
    rc = usb.get_active_config_descriptor(dev, ct.byref(config_ptr))
    if rc < 0:
        print(f"  - Failed to get configuration descriptor: {rc}")
        return

    try:
        config = config_ptr.contents
        print(f"  - Active Configuration: {config.bConfigurationValue}")
        print(f"  - Number of Interfaces: {config.bNumInterfaces}")

        for i in range(config.bNumInterfaces):
            interface = config.interface[i]
            for alt in range(interface.num_altsetting):
                intf_desc = interface.altsetting[alt]
                print(f"  - Interface {intf_desc.bInterfaceNumber}, Alt Setting {intf_desc.bAlternateSetting}")
                print(f"    Number of Endpoints: {intf_desc.bNumEndpoints}")

                for ep_idx in range(intf_desc.bNumEndpoints):
                    ep = intf_desc.endpoint[ep_idx]
                    ep_addr = ep.bEndpointAddress
                    ep_type = ep.bmAttributes & 0x03
                    direction = "IN" if (ep_addr & 0x80) else "OUT"
                    types = {0: "Control", 1: "Isochronous", 2: "Bulk", 3: "Interrupt"}
                    print(f"    - Endpoint 0x{ep_addr:02x} ({direction}, {types.get(ep_type, 'Unknown')})")
    finally:
        usb.free_config_descriptor(config_ptr)

def find_apricorn_device():
    """Searches for an Apricorn device (VID '0984') and returns its info."""
    wmi_usb_devices = get_usb_devices_from_wmi()  # Get WMI data upfront

    ctx = ct.POINTER(usb.context)()
    rc = usb.init(ct.byref(ctx))
    if rc != 0:
        raise UsbTreeError("Failed to initialize libusb")

    try:
        dev_list = ct.POINTER(ct.POINTER(usb.device))()
        cnt = usb.get_device_list(ctx, ct.byref(dev_list))
        if cnt < 0:
            raise UsbTreeError("Failed to get device list")

        for i in range(cnt):
            dev = dev_list[i]
            desc = usb.device_descriptor()
            rc = usb.get_device_descriptor(dev, ct.byref(desc))
            if rc != 0:
                continue

            idVendor = f"{desc.idVendor:04x}"
            idProduct = f"{desc.idProduct:04x}"
            if idVendor != '0984':  # Skip non-Apricorn devices
                continue
            if idProduct == '0351':  # Skip specific product ID
                continue

            bcdDevice = f"{desc.bcdDevice:04x}"
            bcdUSB = parse_usb_version(desc.bcdUSB)

            # Try to open the device with libusb
            iManufacturer = ""
            iProduct = ""
            iSerial = ""
            handle = ct.POINTER(usb.device_handle)()
            rc = usb.open(dev, ct.byref(handle))
            if rc == 0:
                try:
                    iManufacturer = read_string_descriptor_ascii(handle, desc.iManufacturer)
                    iProduct = read_string_descriptor_ascii(handle, desc.iProduct)
                    iSerial = read_string_descriptor_ascii(handle, desc.iSerialNumber)
                    dump_device_config(handle)
                finally:
                    usb.close(handle)
            else:
                # Fall back to WMI if libusb fails
                matching_wmi = [d for d in wmi_usb_devices if d['vid'] == idVendor and d['pid'] == idProduct]
                if matching_wmi:
                    wmi_device = matching_wmi[0]  # Take first match
                    iManufacturer = wmi_device['manufacturer']
                    iProduct = wmi_device['description']
                    iSerial = wmi_device['serial']

            device_id = f"USB\\VID_{idVendor}&PID_{idProduct}\\{iSerial}"
            usb_protocol = f"USB {bcdUSB.split('.')[0]}.0"

            dev_info = WinUsbDeviceInfo(
                idProduct=idProduct,
                idVendor=idVendor,
                bcdDevice=bcdDevice,
                bcdUSB=bcdUSB,
                iManufacturer=iManufacturer,
                iProduct=iProduct,
                iSerial=iSerial,
                device_id=device_id,
                vendor=iManufacturer,
                usb_protocol=usb_protocol
            )

            # Add additional fields
            dev_info.SCSIDevice = "True" if "MSFT30" in dev_info.device_id else "False"
            dev_info.usbController = _get_usb_controller_name(dev_info.idVendor)
            drives = list_usb_drives()
            if drives:
                dev_info.driveSize = str(drives[0]['closest_match'])
            if 'Intel' in dev_info.usbController:
                dev_info.usbController = 'Intel'
            elif 'ASMedia' in dev_info.usbController:
                dev_info.usbController = 'ASMedia'

            usb.free_device_list(dev_list, 1)
            return dev_info

        usb.free_device_list(dev_list, 1)
        return None  # No Apricorn device found
    finally:
        usb.exit(ctx)# --- PowerShell Utility to Get USB Controller Name ---
def _get_usb_controller_name(idVendor: str) -> str:
    """Retrieve the USB controller name for a given vendor ID using PowerShell."""
    ps_script = rf'''
        $vendor = "{idVendor}"
        Get-CimInstance Win32_USBControllerDevice | ForEach-Object {{
            $device = Get-CimInstance -CimInstance $_.Dependent
            if (($device.DeviceID -like "*VID_$vendor*") -and ($device.DeviceID -notlike "*0351*")) {{
                $controller = Get-CimInstance -CimInstance $_.Antecedent
                Write-Output $controller.Name
            }}
        }}
    '''
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", ps_script],
        capture_output=True, text=True
    )
    return result.stdout.strip()

# --- Main Function ---
def main():
    """Find and display information about an Apricorn device."""
    dev = find_apricorn_device()
    if dev:
        pprint(vars(dev))
    else:
        print("No Apricorn device found.")

if __name__ == '__main__':
    main()