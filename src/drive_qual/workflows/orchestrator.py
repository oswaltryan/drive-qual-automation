from __future__ import annotations

import json
import time
from pathlib import Path, PureWindowsPath
from typing import Any

from drive_qual.core.report_session import current_session_folder_name, sanitize_dir_name
from drive_qual.core.storage_paths import SCOPE_ARTIFACT_ROOT, localize_windows_path

WORKFLOW_PROFILES: dict[str, tuple[str, ...]] = {
    "core_perf_v1": ("drive_info", "equipment", "power_measurements", "performance"),
}
STEP_DEPENDENCIES: dict[str, tuple[str, ...]] = {
    "equipment": ("drive_info",),
    "power_measurements": ("equipment",),
    "performance": ("equipment", "power_measurements"),
}
MANIFEST_FILENAME = "workflow_run_manifest.json"
STATUS_PENDING = "pending"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"


def _utc_timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def resolve_selected_steps(
    *,
    explicit_steps: list[str] | None,
    default_steps: tuple[str, ...],
    profile: str | None,
) -> tuple[str, ...]:
    if explicit_steps is not None and profile is not None:
        raise ValueError("Use either --steps or --profile, not both.")
    if explicit_steps is not None:
        return tuple(explicit_steps)
    if profile is None:
        return default_steps
    profile_steps = WORKFLOW_PROFILES.get(profile)
    if profile_steps is None:
        raise ValueError(f"Unknown workflow profile: {profile}")
    return profile_steps


def _resolve_folder_name_for_manifest(part_number: str | None) -> str | None:
    if part_number:
        folder_name = sanitize_dir_name(part_number)
        return folder_name or None
    return current_session_folder_name()


def _manifest_path_for_folder(folder_name: str) -> Path:
    return Path(str(PureWindowsPath(SCOPE_ARTIFACT_ROOT, folder_name, MANIFEST_FILENAME)))


def _load_manifest(path: Path) -> dict[str, Any]:
    local_path = localize_windows_path(path)
    if not local_path.exists():
        return {}
    data = json.loads(local_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return {}
    return data


def _save_manifest(path: Path, data: dict[str, Any]) -> None:
    local_path = localize_windows_path(path)
    local_path.parent.mkdir(parents=True, exist_ok=True)
    local_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _step_entries(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw = manifest.get("steps")
    if not isinstance(raw, list):
        return {}
    indexed: dict[str, dict[str, Any]] = {}
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        if not isinstance(name, str) or not name:
            continue
        indexed[name] = entry
    return indexed


def _new_manifest(
    *,
    profile: str,
    part_number: str | None,
    selected_steps: tuple[str, ...],
) -> dict[str, Any]:
    now = _utc_timestamp()
    return {
        "run_id": now,
        "profile": profile,
        "part_number": part_number,
        "started_at": now,
        "ended_at": None,
        "steps": [
            {"name": step, "status": STATUS_PENDING, "updated_at": now, "message": None} for step in selected_steps
        ],
    }


def _update_step_status(
    manifest: dict[str, Any],
    step_name: str,
    status: str,
    *,
    message: str | None = None,
) -> None:
    entries = _step_entries(manifest)
    entry = entries.get(step_name)
    if entry is None:
        entry = {"name": step_name}
        raw_steps = manifest.setdefault("steps", [])
        if isinstance(raw_steps, list):
            raw_steps.append(entry)
    entry["status"] = status
    entry["updated_at"] = _utc_timestamp()
    entry["message"] = message


def _completed_steps_from_manifest(manifest: dict[str, Any]) -> set[str]:
    entries = _step_entries(manifest)
    return {step_name for step_name, entry in entries.items() if entry.get("status") == STATUS_COMPLETED}


def _validate_dependencies(
    step_name: str,
    *,
    completed_steps: set[str],
) -> None:
    required = STEP_DEPENDENCIES.get(step_name, ())
    missing = [dep for dep in required if dep not in completed_steps]
    if missing:
        missing_csv = ",".join(missing)
        raise RuntimeError(f"Step '{step_name}' requires completed step(s): {missing_csv}.")


def _initialize_manifest(
    *,
    selected_steps: tuple[str, ...],
    effective_profile: str,
    part_number: str | None,
    resume: bool,
) -> tuple[Path, dict[str, Any]]:
    folder_name = _resolve_folder_name_for_manifest(part_number)
    if folder_name is None:
        raise ValueError("Orchestrated runs require --part-number or an active session marker.")

    manifest_path = _manifest_path_for_folder(folder_name)
    manifest = _load_manifest(manifest_path) if resume else {}
    if not manifest:
        manifest = _new_manifest(profile=effective_profile, part_number=part_number, selected_steps=selected_steps)
        return manifest_path, manifest

    existing_profile = manifest.get("profile")
    if existing_profile != effective_profile:
        raise ValueError(
            "Resume requested for profile "
            f"'{effective_profile}', but existing manifest profile is '{existing_profile}'."
        )
    return manifest_path, manifest


def _execute_selected_step(
    *,
    step_name: str,
    step_runners: dict[str, Any],
    manifest: dict[str, Any],
    manifest_path: Path,
    completed_steps: set[str],
    resume: bool,
) -> None:
    _validate_dependencies(step_name, completed_steps=completed_steps)
    step_entries = _step_entries(manifest)
    if resume and step_entries.get(step_name, {}).get("status") == STATUS_COMPLETED:
        _update_step_status(
            manifest,
            step_name,
            STATUS_COMPLETED,
            message="Already completed in prior run; skipped during resume.",
        )
        _save_manifest(manifest_path, manifest)
        completed_steps.add(step_name)
        return

    try:
        step_runners[step_name]()
    except Exception as exc:
        _update_step_status(manifest, step_name, STATUS_FAILED, message=str(exc))
        manifest["ended_at"] = _utc_timestamp()
        _save_manifest(manifest_path, manifest)
        raise

    _update_step_status(manifest, step_name, STATUS_COMPLETED)
    _save_manifest(manifest_path, manifest)
    completed_steps.add(step_name)


def execute_orchestrated_workflow(
    *,
    selected_steps: tuple[str, ...],
    step_runners: dict[str, Any],
    profile: str | None,
    part_number: str | None,
    resume: bool,
) -> None:
    if profile is None and not resume:
        for step_name in selected_steps:
            runner = step_runners[step_name]
            runner()
        return

    if profile is None and resume:
        raise ValueError("--resume requires --profile.")

    effective_profile = profile or "adhoc"
    manifest_path, manifest = _initialize_manifest(
        selected_steps=selected_steps,
        effective_profile=effective_profile,
        part_number=part_number,
        resume=resume,
    )
    _save_manifest(manifest_path, manifest)
    completed_steps = _completed_steps_from_manifest(manifest)

    for step_name in selected_steps:
        _execute_selected_step(
            step_name=step_name,
            step_runners=step_runners,
            manifest=manifest,
            manifest_path=manifest_path,
            completed_steps=completed_steps,
            resume=resume,
        )

    manifest["ended_at"] = _utc_timestamp()
    _save_manifest(manifest_path, manifest)
