import ast
import csv
import json
import sys
from typing import Any


def extract_from_null_field(null_field: Any) -> Any:
    """
    Attempts to convert the CSV 'null' field into a Python list if it isn't already.
    Tries using ast.literal_eval and falls back to manual processing if needed.
    """
    if isinstance(null_field, list):
        return null_field
    if isinstance(null_field, str):
        try:
            result = ast.literal_eval(null_field)
            if isinstance(result, list):
                return result
        except Exception:
            # Fallback: if the string is in list format, manually parse it.
            stripped = null_field.strip()
            if stripped.startswith("[") and stripped.endswith("]"):
                inner = stripped[1:-1]  # remove the surrounding brackets
                items = [item.strip(" '\"") for item in inner.split(",")]
                return items
    return null_field  # Return as is if it cannot be converted.


def process_csv_to_json_and_print_meas1(file_path: str, measurement: str, index: int) -> Any:
    """
    Reads a CSV file, converts it to JSON, and prints everything for the row where
    'TekScope' equals 'measurement'.

    The CSV file is expected to have a fixed format.

    Parameters:
        file_path (str): The path to the CSV file.

    Returns:
        dict: Contains:
              - 'json_data': JSON string of the processed CSV data.
              - 'parsed_data': The dictionary for the 'measurement' row (or None if not found).
    """
    # Read the CSV file into a list of dictionaries.
    with open(file_path, newline="") as csvfile:
        reader = csv.DictReader(csvfile)
        data: list[dict[str, Any]] = list(reader)

    # Optional: if a 'session_id' column exists, group rows by that key.
    if data and "session_id" in data[0]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in data:
            session_id = row["session_id"]
            grouped.setdefault(session_id, []).append(row)
        json_data = json.dumps(grouped, indent=4)
    else:
        json_data = json.dumps(data, indent=4)

    # Find the entry for "measurement" and convert its "null" field if necessary.
    parsed_data: Any = None
    for entry in data:
        if entry.get("TekScope", "").strip() == measurement:
            if "null" in entry:
                entry["null"] = extract_from_null_field(entry["null"])
            parsed_data = entry
            break

    # Print the processed JSON (all CSV data) and the full "measurement" entry.
    # print("Processed JSON:")
    # print(json_data)
    # print(f"\nFull entry for '{measurement}':")
    if parsed_data:
        # print(json.dumps(parsed_data, indent=4))
        value = parsed_data[None][index]
        # print(value)
        return value
    else:
        print(f"No entry with 'TekScope' equal to '{measurement}' was found.")

    return {"json_data": json_data, "parsed_data": parsed_data}


def save_currents_to_json(
    max_current: Any,
    rms_current: Any,
    output_filename: str = "currents.json",
) -> None:
    """
    Saves the max_current and rms_current values to a JSON file.

    If the file already exists and contains an entry for the current operating system,
    the entry is updated (overwritten) with the new values. Otherwise, a new key/value pair
    is added. This way, the data for different OS's is preserved and new measurements
    are only updated for the matching OS.

    Parameters:
        max_current: The value representing maximum current (any JSON-serializable type).
        rms_current: The value representing RMS current (any JSON-serializable type).
        output_filename (str): The path to the output JSON file. Defaults to "currents.json".
    """
    # Map sys.platform to a more friendly OS name.
    os_name = sys.platform
    if os_name == "win32":
        os_name = "Windows"
    elif os_name == "darwin":
        os_name = "macOS"
    elif os_name == "linux":
        os_name = "Linux"

    os_name = "Windows"

    new_entry = {"max_current": max_current, "rms_current": rms_current}

    # Attempt to read the existing data from the file.
    try:
        with open(output_filename) as f:
            data = json.load(f)
        # Ensure the data is a dictionary.
        if not isinstance(data, dict):
            data = {}
    except (FileNotFoundError, json.JSONDecodeError):
        data = {}

    # Update (or add) the entry for the OS.
    data[os_name] = new_entry

    # Write the updated data back to the file.
    with open(output_filename, "w") as f:
        json.dump(data, f, indent=4)


# Example usage:
if __name__ == "__main__":
    file_path = "session_measurements.csv"
    max_current = process_csv_to_json_and_print_meas1(file_path, "Meas1", 10)
    rms_current = process_csv_to_json_and_print_meas1(file_path, "Meas3", 8)
    save_currents_to_json(max_current, rms_current, output_filename="current_measurements.json")
