import sys
import os
import json
import subprocess
import time
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any

# --- Configuration Constants ---
# Centralizing constants makes it easier to change folder names later.
TARGET_VOLUME_NAME = 'QUAL_DATA'
REQUIRED_SUBDIRS = ['Linux', 'macOS', 'Windows']
PROGRESS_FILENAME = 'progress_tracker.json'

def get_current_os() -> str:
    """
    Determines the current operating system.
    
    Returns:
        str: One of 'Windows', 'macOS', 'Linux', or raises an error if unsupported.
    """
    platform_name = sys.platform
    
    if platform_name.startswith('win'):
        return 'Windows'
    elif platform_name == 'darwin':
        return 'macOS'
    elif platform_name.startswith('linux'):
        return 'Linux'
    else:
        # We raise an error here because the rest of the script relies on 
        # knowing the specific OS structure.
        raise OSError(f"Unsupported operating system detected: {platform_name}")

def find_drive_path(os_name: str, volume_name: str) -> Optional[Path]:
    """
    Attempts to locate the mount point/path of a drive based on its Volume Name.
    
    Args:
        os_name (str): The operating system ('Windows', 'macOS', 'Linux').
        volume_name (str): The name of the volume to find (e.g., 'QUAL_DATA').
        
    Returns:
        Path: The path object to the drive root if found.
        None: If the drive is not found.
    """
    if os_name == 'Windows':
        # On Windows, we need to map the Volume Name to a Drive Letter (e.g., E:)
        # We use wmic via subprocess to avoid external dependencies like win32api
        try:
            cmd = 'wmic logicaldisk get caption,volumename'
            output = subprocess.check_output(cmd, shell=True).decode()
            
            for line in output.splitlines():
                parts = line.strip().split()
                if len(parts) >= 2:
                    # Output format is usually: Caption (C:) VolumeName (Label)
                    drive_letter = parts[0]
                    label = " ".join(parts[1:])
                    if label == volume_name:
                        return Path(f"{drive_letter}\\")
        except Exception as e:
            print(f"Warning: Could not query Windows drives: {e}")
            
    elif os_name == 'macOS':
        # macOS mounts volumes in /Volumes/
        candidate = Path(f"/Volumes/{volume_name}")
        if candidate.exists():
            return candidate
            
    elif os_name == 'Linux':
        # Linux varies, but usually found in /media/username/ or /mnt/
        # We check common locations.
        user = os.environ.get('USER', '')
        candidates = [
            Path(f"/media/{user}/{volume_name}"),
            Path(f"/media/{volume_name}"),
            Path(f"/mnt/{volume_name}")
        ]
        for path in candidates:
            if path.exists():
                return path

    return None

def wait_for_drive(os_name: str) -> Path:
    """
    Loops indefinitely until the user connects the required drive.
    
    Returns:
        Path: The path to the connected drive.
    """
    while True:
        drive_path = find_drive_path(os_name, TARGET_VOLUME_NAME)
        
        if drive_path:
            print(f"Success: Drive '{TARGET_VOLUME_NAME}' detected at {drive_path}")
            return drive_path
        
        print(f"Drive '{TARGET_VOLUME_NAME}' not detected.")
        input("Please attach the drive and press Enter to try again...")

def get_most_recent_folder(drive_path: Path) -> Optional[Path]:
    """
    Identifies the most recently modified directory on the drive.
    
    Args:
        drive_path (Path): Root of the drive.
        
    Returns:
        Path: The path to the most recent folder, or None if drive is empty.
    """
    try:
        # List all items, filter for directories only
        all_items = [x for x in drive_path.iterdir() if x.is_dir()]
        
        if not all_items:
            return None
            
        # Find max based on modification time (st_mtime)
        latest_folder = max(all_items, key=lambda p: p.stat().st_mtime)
        return latest_folder
        
    except PermissionError:
        print(f"Error: Permission denied when accessing {drive_path}")
        return None

def setup_project_folders(project_path: Path) -> None:
    """
    Ensures the required subdirectory structure exists within the project folder.
    """
    print(f"Verifying structure for: {project_path.name}")
    
    for folder in REQUIRED_SUBDIRS:
        sub_path = project_path / folder
        if not sub_path.exists():
            try:
                sub_path.mkdir(parents=True, exist_ok=True)
                print(f"  - Created missing folder: {folder}")
            except OSError as e:
                print(f"  - Error creating {folder}: {e}")
        else:
            print(f"  - Verified exists: {folder}")

def initialize_tracker(project_path: Path) -> None:
    """
    Creates or updates the JSON progress tracking file.
    PRESERVES existing data if the file already exists.
    """
    tracker_file = project_path / PROGRESS_FILENAME
    
    # This is the 'Master Template'
    # If you add new requirements in the future, add them here.
    default_status = {
        "Linux": {
            "Disks Benchmark Screenshot": False,
            "In-Rush PDF": False,
            "Max I/O PDF": False
        },
        "macOS": {
           "Blackmagic Benchmark Screenshot": False,
            "In-Rush PDF": False,
            "Max I/O PDF": False 
        },
        "Windows": {
            "ATTO Benchmark Screenshot": False,
            "CrystalDiskInfo Screenshot": False,
            "CrystalDiskMark Benchmark Screenshot": False,
            "In-Rush PDF": False,
            "Max I/O PDF": False
        },
        "Misc": {
            "USB-IF MSC": False,
            "Temperature Testing": False
        }
    }

    final_status = default_status.copy()

    # 1. Check if file exists to prevent overwriting progress
    if tracker_file.exists():
        try:
            with open(tracker_file, 'r') as f:
                existing_data = json.load(f)
                
            # 2. Merge logic: Update default template with existing values
            # This ensures if we added new keys to default_status, they appear,
            # but we keep the 'True' values from the file.
            for category, tasks in existing_data.items():
                if category in final_status:
                    for task, is_complete in tasks.items():
                        # Only update if the task exists in our current template
                        if task in final_status[category]:
                            final_status[category][task] = is_complete
            
            print(f"  - Loaded existing progress from: {PROGRESS_FILENAME}")
            
        except (json.JSONDecodeError, IOError):
            print(f"  - Warning: Existing JSON corrupted. Creating new file.")

    # 3. Write the merged data back to disk
    try:
        with open(tracker_file, 'w') as f:
            json.dump(final_status, f, indent=4)
        print(f"Progress tracker synced at: {tracker_file}")
    except IOError as e:
        print(f"Critical Error: Could not write JSON file. {e}")

def data_drive_setup():
    """
    The main orchestrator function executing the requirements step-by-step.
    """
    print("--- Starting Qualification Data Setup ---")
    
    # 1. Check Operating System
    try:
        current_os = get_current_os()
        print(f"Operating System Detected: {current_os}")
    except OSError as e:
        print(f"Fatal Error: {e}")
        return

    # 2. Check for Drive (Loop until found)
    drive_root = wait_for_drive(current_os)

    # 2a. Check for most recently modified folder
    latest_folder = get_most_recent_folder(drive_root)
    
    project_path = None
    
    # 3. Prompt user about the project
    if latest_folder:
        response = input(f"Is the folder '{latest_folder.name}' the current project? (y/n): ").lower().strip()
        acceptable_input = ['y', 'yes', 'yeah', 'ye']
        
        if response in acceptable_input:
            project_path = latest_folder
            # Validate structure
            setup_project_folders(project_path)
        else:
            # Logic flows to "create new" below
            pass
    
    # If no folder existed, or user said 'no'
    if project_path is None:
        while True:
            new_project_name = input("Please enter the name for the new project: ").strip()
            if new_project_name:
                break # Exit loop if name is valid
            print("Error: Project name cannot be empty. Please try again.")
            
        project_path = drive_root / new_project_name
        
        if not project_path.exists():
            try:
                project_path.mkdir()
                print(f"Created new project folder: {project_path}")
            except OSError as e:
                print(f"Error creating folder: {e}")
                return
            
        # Create subfolders
        setup_project_folders(project_path)

    # 4. Create JSON tracker
    initialize_tracker(project_path)
    
    print("--- Setup Complete ---")

if __name__ == "__main__":
    # This block ensures the script runs only when executed directly,
    # not when imported as a module.
    try:
        data_drive_setup()
    except KeyboardInterrupt:
        print("\nOperation cancelled by user.")
        sys.exit(0)