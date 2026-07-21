from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path, PureWindowsPath
from typing import Any

import pytest
from _pytest.monkeypatch import MonkeyPatch

from drive_qual.core import report_session

INVALID_SELECTION_COUNT = 2


def _localize_to_tmp(tmp_path: Path, path: str | Path) -> Path:
    windows_path = PureWindowsPath(str(path))
    return tmp_path.joinpath(*windows_path.parts[1:])


@pytest.fixture(autouse=True)
def _isolated_registry(monkeypatch: MonkeyPatch, tmp_path: Path) -> Any:
    monkeypatch.setattr(report_session, "localize_windows_path", lambda path: _localize_to_tmp(tmp_path, path))
    report_session.reset_current_session_selection()
    yield
    report_session.reset_current_session_selection()


def _marker_path(tmp_path: Path) -> Path:
    return _localize_to_tmp(tmp_path, report_session.CURRENT_MARKER)


def test_list_current_sessions_reads_version_two_registry(tmp_path: Path) -> None:
    marker_path = _marker_path(tmp_path)
    marker_path.parent.mkdir(parents=True, exist_ok=True)
    marker_path.write_text(
        json.dumps(
            {
                "version": 2,
                "sessions": [
                    {"folder": "69-420", "product": "Apricorn"},
                    {"folder": "29-0031", "product": None},
                ],
            }
        ),
        encoding="utf-8",
    )

    assert report_session.list_current_sessions() == (
        report_session.SessionEntry("69-420", "Apricorn"),
        report_session.SessionEntry("29-0031"),
    )


@pytest.mark.parametrize(
    "content",
    [
        '{"folder": "69-420", "product": "Apricorn"}',
        "69-420\n",
    ],
)
def test_set_current_session_migrates_legacy_marker(content: str, tmp_path: Path) -> None:
    marker_path = _marker_path(tmp_path)
    marker_path.parent.mkdir(parents=True, exist_ok=True)
    marker_path.write_text(content, encoding="utf-8")

    report_session.set_current_session("29-0031", product_name="Apricorn")

    payload = json.loads(marker_path.read_text(encoding="utf-8"))
    assert payload == {
        "version": 2,
        "sessions": [
            {"folder": "69-420", "product": "Apricorn" if content.startswith("{") else None},
            {"folder": "29-0031", "product": "Apricorn"},
        ],
    }


def test_set_current_session_updates_entry_without_reordering_or_erasing_product() -> None:
    report_session.set_current_session("69-420", product_name="Apricorn")
    report_session.set_current_session("29-0031", product_name="Apricorn")
    report_session.set_current_session("69-420")

    assert report_session.list_current_sessions() == (
        report_session.SessionEntry("69-420", "Apricorn"),
        report_session.SessionEntry("29-0031", "Apricorn"),
    )


def test_clear_current_session_removes_only_requested_entry(tmp_path: Path) -> None:
    report_session.set_current_session("69-420", product_name="Apricorn")
    report_session.set_current_session("29-0031", product_name="Apricorn")

    report_session.clear_current_session("69-420")

    assert report_session.list_current_sessions() == (report_session.SessionEntry("29-0031", "Apricorn"),)
    report_session.clear_current_session("29-0031")
    assert not _marker_path(tmp_path).exists()


def test_replace_current_session_renames_only_source_and_preserves_product() -> None:
    report_session.set_current_session("legacy-folder", product_name="Apricorn")
    report_session.set_current_session("29-0031", product_name="Apricorn")

    report_session.replace_current_session("legacy-folder", "69-420")

    assert report_session.list_current_sessions() == (
        report_session.SessionEntry("69-420", "Apricorn"),
        report_session.SessionEntry("29-0031", "Apricorn"),
    )
    assert report_session.current_session_folder_name() == "69-420"


def test_select_current_session_prompts_once_and_caches_choice(
    monkeypatch: MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    report_session.set_current_session("69-420", product_name="Apricorn")
    report_session.set_current_session("29-0031", product_name="Apricorn")
    report_session.reset_current_session_selection()
    responses = iter(["invalid", "3", "2"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(responses))

    assert report_session.current_session_folder_name() == "29-0031"
    assert report_session.current_session_folder_name() == "29-0031"

    output = capsys.readouterr().out
    assert output.count("Available drive sessions:") == 1
    assert output.count("Enter a number from 1 to 2.") == INVALID_SELECTION_COUNT


def test_drive_info_selection_offers_new_even_with_one_session(monkeypatch: MonkeyPatch) -> None:
    report_session.set_current_session("69-420", product_name="Apricorn")
    report_session.reset_current_session_selection()
    monkeypatch.setattr("builtins.input", lambda _prompt: "2")

    assert report_session.current_session_folder_name(allow_new=True) is None
    assert report_session.current_session_folder_name(allow_new=True) is None


def test_preferred_folder_bypasses_registry_prompt(monkeypatch: MonkeyPatch) -> None:
    report_session.set_current_session("69-420", product_name="Apricorn")
    report_session.set_current_session("29-0031", product_name="Apricorn")
    report_session.reset_current_session_selection()
    monkeypatch.setattr(
        "builtins.input",
        lambda _prompt: pytest.fail("Explicit part number should not prompt."),
    )

    assert report_session.select_current_session(preferred_folder=" 77/900 ") == "77_900"
    assert report_session.current_session_folder_name() == "77_900"


def test_concurrent_session_additions_do_not_lose_entries() -> None:
    folders = [f"69-{index:03d}" for index in range(12)]

    with ThreadPoolExecutor(max_workers=6) as executor:
        list(executor.map(report_session.set_current_session, folders))

    assert {session.folder for session in report_session.list_current_sessions()} == set(folders)


def test_malformed_structured_registry_is_rejected(tmp_path: Path) -> None:
    marker_path = _marker_path(tmp_path)
    marker_path.parent.mkdir(parents=True, exist_ok=True)
    marker_path.write_text('{"version": 2, "sessions": [', encoding="utf-8")

    with pytest.raises(ValueError, match="malformed JSON"):
        report_session.list_current_sessions()
