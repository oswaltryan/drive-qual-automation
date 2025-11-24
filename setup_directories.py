import sys
import os
import json
import subprocess
import time
from pathlib import Path
from datetime import datetime
from typing import Optional, Tuple

# --- Configuration Constants ---
TARGET_VOLUME_NAME = 'QUAL_DATA'
REQUIRED_SUBDIRS = ['Linux', 'macOS', 'Windows']
PROGRESS_FILENAME = 'progress_tracker.json'

def get_current_os() -> str:
    platform_name = sys.platform
    if platform_name.startswith('win'): return 'Windows'
    elif platform_name == 'darwin': return 'macOS'
    elif platform_name.startswith('linux'): return 'Linux'
    raise OSError(f"Unsupported operating system detected: {platform_name}")

def find_drive_path(os_name: str, volume_name: str) -> Optional[Path]:
    if os_name == 'Windows':
        try:
            cmd = 'wmic logicaldisk get caption,volumename'
            output = subprocess.check_output(cmd, shell=True).decode()
            for line in output.splitlines():
                parts = line.strip().split()
                if len(parts) >= 2:
                    if " ".join(parts[1:]) == volume_name:
                        return Path(f"{parts[0]}\\")
        except Exception:
            pass
    elif os_name == 'macOS':
        candidate = Path(f"/Volumes/{volume_name}")
        if candidate.exists(): return candidate
    elif os_name == 'Linux':
        user = os.environ.get('USER', '')
        candidates = [Path(f"/media/{user}/{volume_name}"), Path(f"/mnt/{volume_name}")]
        for path in candidates:
            if path.exists(): return path
    return None

def wait_for_drive(os_name: str) -> Path:
    while True:
        drive_path = find_drive_path(os_name, TARGET_VOLUME_NAME)
        if drive_path:
            print(f"Success: Drive '{TARGET_VOLUME_NAME}' detected at {drive_path}")
            return drive_path
        print(f"Drive '{TARGET_VOLUME_NAME}' not detected.")
        input("Please attach the drive and press Enter to try again...")

def get_most_recent_folder(drive_path: Path) -> Optional[Path]:
    try:
        all_items = [x for x in drive_path.iterdir() if x.is_dir()]
        if not all_items: return None
        return max(all_items, key=lambda p: p.stat().st_mtime)
    except PermissionError:
        return None

def setup_project_folders(project_path: Path) -> None:
    print(f"Verifying structure for: {project_path.name}")
    for folder in REQUIRED_SUBDIRS:
        sub_path = project_path / folder
        if not sub_path.exists():
            sub_path.mkdir(parents=True, exist_ok=True)

def initialize_tracker(project_path: Path) -> None:
    tracker_file = project_path / PROGRESS_FILENAME
    default_status = {
        "Linux": { "Disks Benchmark Screenshot": False, "In-Rush PDF": False, "Max I/O PDF": False },
        "macOS": { "Blackmagic Benchmark Screenshot": False, "In-Rush PDF": False, "Max I/O PDF": False },
        "Windows": { 
            "ATTO Benchmark Screenshot": False, "CrystalDiskInfo Screenshot": False, 
            "CrystalDiskMark Benchmark Screenshot": False, "In-Rush PDF": False, "Max I/O PDF": False 
        },
        "Misc": { "USB-IF MSC": False, "Temperature Testing": False }
    }
    
    final_status = default_status.copy()
    
    # Smart Merge: Preserve existing data
    if tracker_file.exists():
        try:
            with open(tracker_file, 'r') as f:
                existing = json.load(f)
            for cat, tasks in existing.items():
                if cat in final_status:
                    for task, val in tasks.items():
                        if task in final_status[cat]:
                            final_status[cat][task] = val
        except Exception:
            pass

    with open(tracker_file, 'w') as f:
        json.dump(final_status, f, indent=4)

def update_progress(project_path: Path, category: str, task: str, status: bool = True):
    """Updates a specific task in the JSON file to True/False."""
    tracker_file = project_path / PROGRESS_FILENAME
    if not tracker_file.exists():
        print(f"Error: Tracker file not found at {tracker_file}")
        return

    try:
        with open(tracker_file, 'r') as f:
            data = json.load(f)
        
        if category in data and task in data[category]:
            data[category][task] = status
            with open(tracker_file, 'w') as f:
                json.dump(data, f, indent=4)
            print(f" >> Tracker Updated: [{category}][{task}] = {status}")
        else:
            print(f"Error: Key {category}/{task} not found in tracker.")
    except Exception as e:
        print(f"Failed to update tracker: {e}")

def data_drive_setup() -> Tuple[Path, Path]:
    """
    Orchestrates the setup and RETURNS (drive_root, project_path).
    """
    print("--- Qualification Data Setup ---")
    os_name = get_current_os()
    drive_root = wait_for_drive(os_name)
    latest_folder = get_most_recent_folder(drive_root)
    
    project_path = None
    
    if latest_folder:
        response = input(f"Is '{latest_folder.name}' the current project? (y/n): ").lower().strip()
        if response in ['y', 'yes', 'yeah']:
            project_path = latest_folder
            setup_project_folders(project_path)
            
    if project_path is None:
        while True:
            new_name = input("Enter new project name: ").strip()
            if new_name: break
        
        project_path = drive_root / new_name
        if not project_path.exists():
            project_path.mkdir()
        setup_project_folders(project_path)

    initialize_tracker(project_path)
    print(f"--- Setup Complete: {project_path.name} ---")
    
    return drive_root, project_path

if __name__ == "__main__":
    # If run directly, just perform setup
    try:
        data_drive_setup()
    except KeyboardInterrupt:
        sys.exit(0)