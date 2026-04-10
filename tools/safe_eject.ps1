<#
.SYNOPSIS
    Safely eject a USB storage device by disk number using the same
    configuration manager request that the system tray invokes.

.DESCRIPTION
    Given a PhysicalDisk index (as shown in Disk Management / diskpart),
    this script locates the corresponding PnP device instance and calls
    CM_Request_Device_Eject via CfgMgr32. This is equivalent to choosing
    "Safely Remove Hardware" from the notification area.

.EXAMPLE
    PS> .\utils\safe_eject_disk.ps1 -DiskNumber 3

    Requests a safe eject for disk 3. If another process still has a handle
    open, the veto reason will be displayed (just as the GUI would warn).

.NOTES
    Requires an elevated PowerShell session.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateRange(0, [int]::MaxValue)]
    [int]$DiskNumber
)

function Write-Step {
    param([string]$Message)
    Write-Host "[STEP] $Message" -ForegroundColor Cyan
}
function Write-Detail {
    param([string]$Message)
    Write-Host "[INFO] $Message" -ForegroundColor Gray
}
function Write-Ok {
    param([string]$Message)
    Write-Host "[OK] $Message" -ForegroundColor Green
}
function Write-Err {
    param([string]$Message)
    Write-Host "[ERROR] $Message" -ForegroundColor Red
}

Write-Step "Validating elevation..."
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]$identity
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Err "This script must run from an elevated PowerShell session."
    throw "Elevation required."
}
Write-Ok "Running with administrative privileges."

Write-Step "Resolving disk $DiskNumber to a physical device..."
$disk = Get-CimInstance -ClassName Win32_DiskDrive -Filter "Index=$DiskNumber"
if (-not $disk) {
    Write-Err "No Win32_DiskDrive entry found with Index=$DiskNumber."
    throw "Disk not found."
}

if ($disk.InterfaceType -notin @('USB', '1394')) {
    Write-Detail "Disk reports InterfaceType '$($disk.InterfaceType)'. Proceeding anyway."
}

$deviceInstanceId = $disk.PNPDeviceID
Write-Detail "Device instance ID: $deviceInstanceId"

if (-not ([System.Management.Automation.PSTypeName]'FlightControl.DeviceEjector').Type) {
    Write-Step "Loading native ejector helper..."
    Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
using System.Text;

namespace FlightControl {
    public static class DeviceEjector {
        private const int CR_SUCCESS = 0x00000000;
        private const uint DN_REMOVABLE = 0x00004000;

        [DllImport("CfgMgr32.dll", CharSet = CharSet.Unicode)]
        private static extern int CM_Locate_DevNode(out uint devInst, string pDeviceID, int ulFlags);

        [DllImport("CfgMgr32.dll", CharSet = CharSet.Unicode)]
        private static extern int CM_Get_Parent(out uint pdnDevInst, uint dnDevInst, int ulFlags);

        [DllImport("CfgMgr32.dll", CharSet = CharSet.Unicode)]
        private static extern int CM_Get_DevNode_Status(out uint pulStatus, out uint pulProblemNumber, uint dnDevInst, int ulFlags);

        [DllImport("CfgMgr32.dll", CharSet = CharSet.Unicode)]
        private static extern int CM_Request_Device_Eject(uint devInst, out PNP_VETO_TYPE pVetoType, StringBuilder pszVetoName, int ulNameLength, int ulFlags);

        [DllImport("CfgMgr32.dll", CharSet = CharSet.Unicode)]
        private static extern int CM_Get_Device_ID(uint dnDevInst, StringBuilder buffer, int bufferLen, int ulFlags);

        public enum PNP_VETO_TYPE {
            PNP_VetoTypeUnknown = 0,
            PNP_VetoLegacyDevice,
            PNP_VetoPendingClose,
            PNP_VetoWindowsApp,
            PNP_VetoWindowsService,
            PNP_VetoOutstandingOpen,
            PNP_VetoDevice,
            PNP_VetoDriver,
            PNP_VetoIllegalDeviceRequest,
            PNP_VetoInsufficientPower,
            PNP_VetoNonDisableable,
            PNP_VetoLegacyDriver,
            PNP_VetoInsufficientRights
        }

        public static string GetDeviceId(uint devInst) {
            var sb = new StringBuilder(512);
            if (CM_Get_Device_ID(devInst, sb, sb.Capacity, 0) == CR_SUCCESS) {
                return sb.ToString();
            }
            return "Unknown";
        }

        public static void RequestSafeRemoval(string deviceInstanceId) {
            if (string.IsNullOrWhiteSpace(deviceInstanceId)) {
                throw new ArgumentException("Device instance ID cannot be empty.", "deviceInstanceId");
            }

            uint devInst;
            int cr = CM_Locate_DevNode(out devInst, deviceInstanceId, 0);
            if (cr != CR_SUCCESS) {
                throw new InvalidOperationException(string.Format("CM_Locate_DevNode failed (CR=0x{0:X}) for '{1}'.", cr, deviceInstanceId));
            }

            // Walk up to find the highest removable parent
            uint currentDevInst = devInst;
            uint ejectableDevInst = devInst;

            while (currentDevInst != 0) {
                uint status, problem;
                if (CM_Get_DevNode_Status(out status, out problem, currentDevInst, 0) == CR_SUCCESS) {
                    if ((status & DN_REMOVABLE) != 0) {
                        ejectableDevInst = currentDevInst;
                    }
                }

                uint parentDevInst;
                if (CM_Get_Parent(out parentDevInst, currentDevInst, 0) != CR_SUCCESS) {
                    break;
                }
                currentDevInst = parentDevInst;
            }

            var vetoName = new StringBuilder(512);
            PNP_VETO_TYPE veto;
            cr = CM_Request_Device_Eject(ejectableDevInst, out veto, vetoName, vetoName.Capacity, 0);
            if (cr != CR_SUCCESS) {
                string detail = vetoName.Length > 0 ? vetoName.ToString() : "<none>";
                throw new InvalidOperationException(string.Format("CM_Request_Device_Eject failed (CR=0x{0:X}, Veto={1}, Detail={2}) for device '{3}'.", cr, veto, detail, GetDeviceId(ejectableDevInst)));
            }
        }
    }
}
"@ -ErrorAction Stop | Out-Null
    Write-Ok "Native helper loaded."
}

Write-Step "Requesting safe removal via CM_Request_Device_Eject..."
try {
    [FlightControl.DeviceEjector]::RequestSafeRemoval($deviceInstanceId)
    Write-Ok "Eject request sent successfully. Windows will notify when it is safe to disconnect."
}
catch {
    Write-Err $_.Exception.Message
    exit 1
}
