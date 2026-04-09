from __future__ import annotations

import json
from pathlib import Path

import pytest
from _pytest.monkeypatch import MonkeyPatch

from drive_qual.workflows import orchestrator


def test_resolve_selected_steps_defaults() -> None:
    selected = orchestrator.resolve_selected_steps(
        explicit_steps=None,
        default_steps=("drive_info", "equipment"),
        profile=None,
    )

    assert selected == ("drive_info", "equipment")


def test_resolve_selected_steps_uses_profile() -> None:
    selected = orchestrator.resolve_selected_steps(
        explicit_steps=None,
        default_steps=("drive_info",),
        profile="core_perf_v1",
    )

    assert selected == orchestrator.WORKFLOW_PROFILES["core_perf_v1"]


def test_resolve_selected_steps_rejects_steps_and_profile() -> None:
    with pytest.raises(ValueError, match="Use either --steps or --profile"):
        orchestrator.resolve_selected_steps(
            explicit_steps=["performance"],
            default_steps=("drive_info",),
            profile="core_perf_v1",
        )


def test_execute_orchestrated_workflow_resume_requires_profile() -> None:
    with pytest.raises(ValueError, match="--resume requires --profile"):
        orchestrator.execute_orchestrated_workflow(
            selected_steps=("performance",),
            step_runners={"performance": lambda: None},
            profile=None,
            part_number="69-420",
            resume=True,
        )


def test_execute_orchestrated_workflow_enforces_dependencies(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    manifest_path = tmp_path / "workflow_run_manifest.json"
    monkeypatch.setattr(orchestrator, "_resolve_folder_name_for_manifest", lambda _part_number: "69-420")
    monkeypatch.setattr(orchestrator, "_manifest_path_for_folder", lambda _folder_name: manifest_path)

    calls: list[str] = []

    with pytest.raises(RuntimeError, match="requires completed step"):
        orchestrator.execute_orchestrated_workflow(
            selected_steps=("performance",),
            step_runners={"performance": lambda: calls.append("performance")},
            profile="core_perf_v1",
            part_number="69-420",
            resume=False,
        )

    assert calls == []


def test_execute_orchestrated_workflow_resume_skips_completed_step(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    manifest_path = tmp_path / "workflow_run_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "run_id": "2026-04-09T00:00:00Z",
                "profile": "core_perf_v1",
                "part_number": "69-420",
                "started_at": "2026-04-09T00:00:00Z",
                "ended_at": None,
                "steps": [
                    {
                        "name": "drive_info",
                        "status": "completed",
                        "updated_at": "2026-04-09T00:00:01Z",
                        "message": None,
                    },
                    {
                        "name": "equipment",
                        "status": "pending",
                        "updated_at": "2026-04-09T00:00:01Z",
                        "message": None,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(orchestrator, "_resolve_folder_name_for_manifest", lambda _part_number: "69-420")
    monkeypatch.setattr(orchestrator, "_manifest_path_for_folder", lambda _folder_name: manifest_path)

    calls: list[str] = []

    orchestrator.execute_orchestrated_workflow(
        selected_steps=("drive_info", "equipment"),
        step_runners={
            "drive_info": lambda: calls.append("drive_info"),
            "equipment": lambda: calls.append("equipment"),
        },
        profile="core_perf_v1",
        part_number="69-420",
        resume=True,
    )

    assert calls == ["equipment"]

    updated = json.loads(manifest_path.read_text(encoding="utf-8"))
    steps = {entry["name"]: entry for entry in updated["steps"]}
    assert steps["drive_info"]["status"] == "completed"
    assert "skipped during resume" in (steps["drive_info"]["message"] or "").lower()
    assert steps["equipment"]["status"] == "completed"
