from __future__ import annotations

import re

from drive_qual.reports.evaluation import Status

DEFAULT_OUTPUT_NAME = "drive_qualification_report.docx"
OS_COLUMNS = (("linux", "Linux"), ("macos", "macOS"), ("windows", "Windows"))
MA_PER_A = 1000.0
MAX_IO_RMS_FAIL_MA = 1000.0
MAX_IO_RMS_WARN_MA = 900.0
INRUSH_WARN_MA = 900.0
APPENDIX_IMAGE_WIDTH_INCHES = 5.7
APPENDIX_OS_LABEL_WIDTH_INCHES = 1.18
APPENDIX_OS_ARTIFACT_WIDTH_INCHES = 6.12
APPENDIX_MEASUREMENT_COLUMN_WIDTH_FRACTION = 0.97
IMAGE_EXTENSIONS = {".bmp", ".gif", ".jpeg", ".jpg", ".png", ".tif", ".tiff"}
MEASUREMENT_LABELS = {"Inrush Summary", "Max IO Summary"}
PERFORMANCE_LABEL = "Performance"
EXCLUDED_ACCUM_FIELDS = {"Accum-Pk-Pk", "Accum-Std Dev", "Accum-Population"}
EXCLUDED_MEASUREMENT_ROWS = {"Meas9"}
CSV_ENCODING_CANDIDATES = ("utf-8", "utf-8-sig", "cp1252", "latin-1")
KEY_VALUE_CSV_ROW_WIDTH = 2
LINUX_DISKS_SUMMARY_COLUMN_COUNT = 3
TEMPERATURE_TABLE_POINTS_C = tuple(range(-40, 61, 10))
EMU_PER_TWIP = 635
OBJECT_ICON_WIDTH_INCHES = 0.72
WINDOWS_PERFORMANCE_BLANK_LINES_BEFORE_FIRST_OBJECT = 5
WINDOWS_PERFORMANCE_BLANK_LINES_BETWEEN_OBJECTS = 4
TWO_SECTION_COUNT = 2
CFB_SECTOR_SIZE = 512
CFB_MINI_SECTOR_SIZE = 64
CFB_MINI_STREAM_CUTOFF = 4096
CFB_END_OF_CHAIN = -2
CFB_FREE_SECTOR = -1
CFB_FAT_SECTOR = -3
CFB_NO_STREAM = -1
OLE_MARKER_BYTES = b"\x01\x00\x00\x02" + (b"\x00" * 16)
PACKAGE_CLSID = bytes.fromhex("0c00030000000000c000000000000046")
STATUS_COLORS = {
    Status.PASS: "C6EFCE",
    Status.WARN: "FFEB9C",
    Status.FAIL: "FFC7CE",
    Status.MISSING: "FFC7CE",
    Status.NOT_APPLICABLE: "E7E6E6",
}
COMPATIBILITY_ROWS = (
    ("recognized_by_os", "Recognized by OS"),
    ("hot_pluggable", "Hot Pluggable"),
    ("safely_remove", "Safely Remove"),
    ("device_manager_disk_mgmt", "Native Disk Utility"),
    ("partition_drive", "Partition Drive"),
    ("format_drive", "Format Drive"),
    ("copy_to_drive", "Copy to Drive"),
    ("copy_from_drive", "Copy from Drive"),
    ("delete_data", "Delete Data"),
)
POWER_ROWS = (
    ("Max in-rush current", ("max_inrush_current", "max_inrush_current_5v", "max_inrush_current_12v")),
    ("Max read/write current", ("max_read_write_current", "max_read_write_current_5v", "max_read_write_current_12v")),
    (
        "RMS during read/write test",
        ("rms_read_write_current", "rms_read_write_current_5v", "rms_read_write_current_12v"),
    ),
)
TEMP_RE = re.compile(r"(?P<value>-?\d+(?:\.\d+)?)\s*c", re.IGNORECASE)
