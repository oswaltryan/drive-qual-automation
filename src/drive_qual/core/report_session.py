from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Any
from uuid import uuid4

from filelock import FileLock

from drive_qual.core.storage_paths import SCOPE_ARTIFACT_ROOT, localize_windows_path

REPORT_ROOT = Path(str(PureWindowsPath(SCOPE_ARTIFACT_ROOT)))
CURRENT_MARKER = Path(str(PureWindowsPath(SCOPE_ARTIFACT_ROOT, ".current")))
CURRENT_MARKER_LOCK = Path(str(PureWindowsPath(SCOPE_ARTIFACT_ROOT, ".current.lock")))
CURRENT_MARKER_VERSION = 2
TEMPLATE_NAME = "drive_qualification_report_atomic_tests.json"


@dataclass(frozen=True, slots=True)
class SessionEntry:
    folder: str
    product: str | None = None


_selection_resolved = False
_selected_session_folder: str | None = None


def sanitize_dir_name(value: str) -> str:
    cleaned = []
    for ch in value.strip():
        if ch.isalnum() or ch in ("-", "_"):
            cleaned.append(ch)
        else:
            cleaned.append("_")
    return "".join(cleaned).strip("_")


def _write_text_by_replacing(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temp_path.write_text(content, encoding="utf-8")
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise

    try:
        temp_path.replace(path)
    except PermissionError:
        if path.exists():
            path.unlink()
            temp_path.replace(path)
            return
        raise
    finally:
        temp_path.unlink(missing_ok=True)


def _session_entry(data: Any) -> SessionEntry:
    if not isinstance(data, dict):
        raise ValueError("Current-session registry entries must be JSON objects.")
    raw_folder = data.get("folder")
    if not isinstance(raw_folder, str) or not raw_folder.strip():
        raise ValueError("Current-session registry entries require a non-empty 'folder'.")
    raw_product = data.get("product")
    if raw_product is not None and not isinstance(raw_product, str):
        raise ValueError("Current-session registry entry 'product' values must be strings or null.")
    product = raw_product.strip() if isinstance(raw_product, str) else None
    return SessionEntry(folder=raw_folder.strip(), product=product or None)


def _deduplicate_sessions(sessions: list[SessionEntry]) -> list[SessionEntry]:
    deduplicated: list[SessionEntry] = []
    indexes: dict[str, int] = {}
    for session in sessions:
        index = indexes.get(session.folder)
        if index is None:
            indexes[session.folder] = len(deduplicated)
            deduplicated.append(session)
        else:
            deduplicated[index] = session
    return deduplicated


def _parse_session_registry(raw_text: str) -> list[SessionEntry]:
    if not raw_text:
        return []
    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError:
        if raw_text.startswith(("{", "[")):
            raise ValueError("Current-session registry contains malformed JSON.") from None
        return [SessionEntry(folder=raw_text)]

    if isinstance(data, str):
        folder = data.strip()
        return [SessionEntry(folder=folder)] if folder else []
    if not isinstance(data, dict):
        raise ValueError("Current-session registry must be a JSON object.")
    if "sessions" not in data:
        return [_session_entry(data)]

    raw_sessions = data.get("sessions")
    if not isinstance(raw_sessions, list):
        raise ValueError("Current-session registry 'sessions' must be a JSON array.")
    return _deduplicate_sessions([_session_entry(entry) for entry in raw_sessions])


def _read_sessions(marker_path: Path) -> list[SessionEntry]:
    if not marker_path.exists():
        return []
    return _parse_session_registry(marker_path.read_text(encoding="utf-8").strip())


def _write_sessions(marker_path: Path, sessions: list[SessionEntry]) -> None:
    if not sessions:
        marker_path.unlink(missing_ok=True)
        return
    payload = {
        "version": CURRENT_MARKER_VERSION,
        "sessions": [
            {
                "folder": session.folder,
                "product": session.product,
            }
            for session in sessions
        ],
    }
    _write_text_by_replacing(marker_path, json.dumps(payload, indent=2) + "\n")


def _localized_marker_paths() -> tuple[Path, Path]:
    return localize_windows_path(CURRENT_MARKER), localize_windows_path(CURRENT_MARKER_LOCK)


def list_current_sessions() -> tuple[SessionEntry, ...]:
    marker_path = localize_windows_path(CURRENT_MARKER)
    return tuple(_read_sessions(marker_path))


def bind_current_session(folder_name: str | None) -> None:
    global _selected_session_folder, _selection_resolved
    _selected_session_folder = folder_name.strip() if folder_name is not None else None
    _selection_resolved = True


def reset_current_session_selection() -> None:
    global _selected_session_folder, _selection_resolved
    _selected_session_folder = None
    _selection_resolved = False


def set_current_session(folder_name: str, product_name: str | None = None) -> None:
    normalized_folder = folder_name.strip()
    if not normalized_folder:
        raise ValueError("Current-session folder name is required.")

    marker_path, lock_path = _localized_marker_paths()
    marker_path.parent.mkdir(parents=True, exist_ok=True)
    with FileLock(str(lock_path)):
        sessions = _read_sessions(marker_path)
        updated: list[SessionEntry] = []
        found = False
        for session in sessions:
            if session.folder != normalized_folder:
                updated.append(session)
                continue
            product = product_name if product_name is not None else session.product
            updated.append(SessionEntry(folder=normalized_folder, product=product))
            found = True
        if not found:
            updated.append(SessionEntry(folder=normalized_folder, product=product_name))
        _write_sessions(marker_path, updated)
    bind_current_session(normalized_folder)


def replace_current_session(
    folder_name: str,
    replacement_folder_name: str,
    product_name: str | None = None,
) -> None:
    normalized_folder = folder_name.strip()
    normalized_replacement = replacement_folder_name.strip()
    if not normalized_folder or not normalized_replacement:
        raise ValueError("Current-session folder names are required.")

    marker_path, lock_path = _localized_marker_paths()
    marker_path.parent.mkdir(parents=True, exist_ok=True)
    with FileLock(str(lock_path)):
        sessions = _read_sessions(marker_path)
        source = next((session for session in sessions if session.folder == normalized_folder), None)
        existing = next((session for session in sessions if session.folder == normalized_replacement), None)
        product = product_name or (source.product if source else None) or (existing.product if existing else None)
        replacement = SessionEntry(folder=normalized_replacement, product=product)
        updated: list[SessionEntry] = []
        replacement_added = False
        for session in sessions:
            if session.folder == normalized_folder:
                if not replacement_added:
                    updated.append(replacement)
                    replacement_added = True
                continue
            if session.folder == normalized_replacement:
                if source is None and not replacement_added:
                    updated.append(replacement)
                    replacement_added = True
                continue
            updated.append(session)
        if not replacement_added:
            updated.append(replacement)
        _write_sessions(marker_path, updated)
    bind_current_session(normalized_replacement)


def clear_current_session(folder_name: str | None = None) -> None:
    marker_path, lock_path = _localized_marker_paths()
    marker_path.parent.mkdir(parents=True, exist_ok=True)
    with FileLock(str(lock_path)):
        sessions = _read_sessions(marker_path)
        selected_folder = folder_name.strip() if folder_name is not None else _selected_session_folder
        if selected_folder is None and len(sessions) == 1:
            selected_folder = sessions[0].folder
        if selected_folder is None:
            return
        remaining = [session for session in sessions if session.folder != selected_folder]
        _write_sessions(marker_path, remaining)

    if _selection_resolved and _selected_session_folder == selected_folder:
        reset_current_session_selection()


def _print_session_menu(sessions: tuple[SessionEntry, ...], *, allow_new: bool) -> None:
    print("Available drive sessions:")
    for index, session in enumerate(sessions, start=1):
        product_suffix = f" ({session.product})" if session.product else ""
        print(f"  {index}. {session.folder}{product_suffix}")
    if allow_new:
        print(f"  {len(sessions) + 1}. Create a new drive")


def _prompt_for_session(sessions: tuple[SessionEntry, ...], *, allow_new: bool) -> str | None:
    _print_session_menu(sessions, allow_new=allow_new)
    maximum = len(sessions) + int(allow_new)
    while True:
        raw_choice = input(f"Select a drive session [1-{maximum}]: ").strip()
        if raw_choice.isdigit():
            choice = int(raw_choice)
            if 1 <= choice <= len(sessions):
                return sessions[choice - 1].folder
            if allow_new and choice == maximum:
                return None
        print(f"Enter a number from 1 to {maximum}.")


def select_current_session(
    *,
    preferred_folder: str | None = None,
    allow_new: bool = False,
) -> str | None:
    if preferred_folder is not None:
        folder_name = sanitize_dir_name(preferred_folder)
        if not folder_name:
            raise ValueError("Apricorn Part Number produced an empty directory name after sanitizing.")
        bind_current_session(folder_name)
        return folder_name
    if _selection_resolved:
        return _selected_session_folder

    sessions = list_current_sessions()
    if not sessions:
        bind_current_session(None)
        return None
    if len(sessions) == 1 and not allow_new:
        bind_current_session(sessions[0].folder)
        return sessions[0].folder

    selected_folder = _prompt_for_session(sessions, allow_new=allow_new)
    bind_current_session(selected_folder)
    return selected_folder


def current_session_folder_name(*, allow_new: bool = False) -> str | None:
    return select_current_session(allow_new=allow_new)


def resolve_folder_name(part_number: str | None) -> str:
    if part_number:
        folder_name = sanitize_dir_name(part_number)
        if not folder_name:
            raise ValueError("Apricorn Part Number produced an empty directory name after sanitizing.")
        bind_current_session(folder_name)
        return folder_name

    current_folder = current_session_folder_name()
    if current_folder is not None:
        return current_folder

    entry = input("Apricorn Part Number (for report folder): ").strip()
    if not entry:
        raise ValueError("Apricorn Part Number is required.")
    folder_name = sanitize_dir_name(entry)
    if not folder_name:
        raise ValueError("Apricorn Part Number produced an empty directory name after sanitizing.")
    bind_current_session(folder_name)
    return folder_name


def report_path_for(folder_name: str) -> Path:
    return Path(str(PureWindowsPath(SCOPE_ARTIFACT_ROOT, folder_name, TEMPLATE_NAME)))


def load_report(report_path: Path) -> dict[str, Any]:
    local_path = localize_windows_path(report_path)
    if not local_path.exists():
        raise FileNotFoundError(f"Report template not found at {report_path}. Run drive_info_prompt.py first.")
    data = json.loads(local_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Report JSON is not an object.")
    return data


def save_report(report_path: Path, data: dict[str, Any]) -> None:
    local_path = localize_windows_path(report_path)
    _write_text_by_replacing(local_path, json.dumps(data, indent=2) + "\n")
