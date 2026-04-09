import json
import os
import subprocess
import sys
from pathlib import Path

# --- Configuration Constants ---
TARGET_VOLUME_NAME = "QUAL_DATA"
REQUIRED_SUBDIRS = ["Linux", "macOS", "Windows"]
PROGRESS_FILENAME = "progress_tracker.json"
MIN_WMIC_PARTS = 2


def get_current_os() -> str:
    """
    Determines the current operating system.
    """
    platform_name = sys.platform
    if platform_name.startswith("win"):
        return "Windows"
    elif platform_name == "darwin":
        return "macOS"
    elif platform_name.startswith("linux"):
        return "Linux"
    else:
        raise OSError(f"Unsupported operating system detected: {platform_name}")


def find_drive_path(os_name: str, volume_name: str) -> Path | None:
    """
    Attempts to locate th  mount point/path of a drive based on its Volume Name.
    """
    if os_name == "Windows":
        try:
            cmd = "wmic logicaldisk get caption,volumename"
            output = subprocess.check_output(cmd, shell=True).decode()

            for line in output.splitlines():
                parts = line.strip().split()
                if len(parts) >= MIN_WMIC_PARTS:
                    drive_letter = parts[0]
                    label = " ".join(parts[1:])
                    if label == volume_name:
                        return Path(f"{drive_letter}\\")
        except Exception as e:
            print(f"Warning: Could not query Windows drives: {e}")

    elif os_name == "macOS":
        candidate = Path(f"/Volumes/{volume_name}")
        if candidate.exists():
            return candidate

    elif os_name == "Linux":
        user = os.environ.get("USER", "")
        candidates = [Path(f"/media/{user}/{volume_name}"), Path(f"/media/{volume_name}"), Path(f"/mnt/{volume_name}")]
        for path in candidates:
            if path.exists():
                return path

    return None


def wait_for_drive(os_name: str) -> Path:
    """
    Loops indefinitely until the user connects the required drive.
    """
    while True:
        drive_path = find_drive_path(os_name, TARGET_VOLUME_NAME)

        if drive_path:
            print(f"Success: Drive '{TARGET_VOLUME_NAME}' detected at {drive_path}")
            return drive_path

        print(f"Drive '{TARGET_VOLUME_NAME}' not detected.")
        input("Please attach the drive and press Enter to try again...")


def get_most_recent_folder(drive_path: Path) -> Path | None:
    """
    Identifies the most recently modified directory on the drive.
    """
    try:
        all_items = [x for x in drive_path.iterdir() if x.is_dir()]
        if not all_items:
            return None
        return max(all_items, key=lambda p: p.stat().st_mtime)
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


def initialize_tracker(project_path: Path) -> None:
    """
    Creates or updates the JSON progress tracking file.
    PRESERVES existing data if the file already exists.
    """
    tracker_file = project_path / PROGRESS_FILENAME

    default_status = {
        "Linux": {"Disks Benchmark Screenshot": False, "In-Rush PDF": False, "Max I/O PDF": False},
        "macOS": {"Blackmagic Disk Speed Test Screenshot": False, "In-Rush PDF": False, "Max I/O PDF": False},
        "Windows": {
            "ATTO Benchmark Screenshot": False,
            "CrystalDiskInfo Screenshot": False,
            "CrystalDiskMark Benchmark Screenshot": False,
            "In-Rush PDF": False,
            "Max I/O PDF": False,
        },
        "Misc": {"USB-IF MSC": False, "Temperature Testing": False},
    }

    final_status = default_status.copy()

    # Merge logic
    if tracker_file.exists():
        try:
            with open(tracker_file) as f:
                existing_data = json.load(f)

            for category, tasks in existing_data.items():
                if category in final_status:
                    for task, is_complete in tasks.items():
                        if task in final_status[category]:
                            final_status[category][task] = is_complete

            print(f"  - Loaded existing progress from: {PROGRESS_FILENAME}")
        except (OSError, json.JSONDecodeError):
            print("  - Warning: Existing JSON corrupted. Creating new file.")

    try:
        with open(tracker_file, "w") as f:
            json.dump(final_status, f, indent=4)
        print(f"Progress tracker synced at: {tracker_file}")
    except OSError as e:
        print(f"Critical Error: Could not write JSON file. {e}")


def update_progress(project_path: Path, category: str, task: str, status: bool = True) -> None:
    """
    Helper to update a specific task in the JSON file.
    """
    tracker_file = project_path / PROGRESS_FILENAME
    if not tracker_file.exists():
        print("Error: Tracker file does not exist.")
        return

    try:
        with open(tracker_file) as f:
            data = json.load(f)

        if category in data and task in data[category]:
            data[category][task] = status

            with open(tracker_file, "w") as f:
                json.dump(data, f, indent=4)
            print(f" >> Tracker Updated: [{category}][{task}] = {status}")
        else:
            print(f"Error: Task '{task}' not found in category '{category}'")

    except Exception as e:
        print(f"Failed to update tracker: {e}")


def _select_existing_project(latest_folder: Path | None) -> Path | None:
    if latest_folder is None:
        return None

    response = input(f"Is the folder '{latest_folder.name}' the current project? (y/n): ").lower().strip()
    acceptable_input = {"y", "yes", "yeah", "ye"}
    if response not in acceptable_input:
        return None

    setup_project_folders(latest_folder)
    return latest_folder


def _create_new_project(drive_root: Path) -> Path:
    while True:
        new_project_name = input("Please enter the name for the new project: ").strip()
        if new_project_name:
            break
        print("Error: Project name cannot be empty. Please try again.")

    project_path = drive_root / new_project_name

    if not project_path.exists():
        try:
            project_path.mkdir()
            print(f"Created new project folder: {project_path}")
        except OSError as e:
            print(f"Error creating folder: {e}")
            sys.exit(1)

    setup_project_folders(project_path)
    return project_path


def data_drive_setup() -> tuple[Path, Path]:
    """
    The main orchestrator function.
    Returns:
        drive_root (Path): The root of the mounted volume.
        project_path (Path): The specific project folder path.
        project_name (str): The name of the project folder.
    """
    print("--- Qualification Data Setup ---")

    try:
        current_os = get_current_os()
    except OSError as e:
        print(f"Fatal Error: {e}")
        sys.exit(1)

    drive_root = wait_for_drive(current_os)
    latest_folder = get_most_recent_folder(drive_root)

    project_path = _select_existing_project(latest_folder)
    if project_path is None:
        project_path = _create_new_project(drive_root)

    initialize_tracker(project_path)

    print("--- Setup Complete ---")
    return drive_root, project_path


if __name__ == "__main__":
    try:
        data_drive_setup()
    except KeyboardInterrupt:
        print("\nOperation cancelled by user.")
        sys.exit(0)
