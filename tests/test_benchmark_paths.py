from __future__ import annotations

from _pytest.monkeypatch import MonkeyPatch

from drive_qual.benchmarks import benchmark_directory, benchmark_file_path, require_fio


def test_benchmark_file_path_normalizes_windows_drive_roots(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr("drive_qual.benchmarks.common.sys.platform", "win32")

    assert benchmark_directory("D") == "D:\\"
    assert benchmark_directory("D:") == "D:\\"
    assert benchmark_directory("D:\\") == "D:\\"
    assert benchmark_file_path("D", "benchmark_file.dat") == r"D:\benchmark_file.dat"
    assert benchmark_file_path("D:", "benchmark_file.dat") == r"D:\benchmark_file.dat"
    assert benchmark_file_path("D:\\", "benchmark_file.dat") == r"D:\benchmark_file.dat"


def test_require_fio_prefers_tools_binary_on_windows(monkeypatch: MonkeyPatch) -> None:
    called_with: list[tuple[str, ...]] = []

    def fake_resolve_tool(*candidates: str) -> str | None:
        called_with.append(candidates)
        return "C:/repo/tools/fio-windows.exe"

    monkeypatch.setattr("drive_qual.benchmarks.common.sys.platform", "win32")
    monkeypatch.setattr("drive_qual.benchmarks.common._resolve_tool", fake_resolve_tool)

    assert require_fio() == "C:/repo/tools/fio-windows.exe"
    assert called_with
    assert called_with[0][0] == "tools/fio-windows.exe"


def test_require_fio_prefers_tools_binary_on_macos(monkeypatch: MonkeyPatch) -> None:
    called_with: list[tuple[str, ...]] = []

    def fake_resolve_tool(*candidates: str) -> str | None:
        called_with.append(candidates)
        return "/repo/tools/fio-macOS"

    monkeypatch.setattr("drive_qual.benchmarks.common.sys.platform", "darwin")
    monkeypatch.setattr("drive_qual.benchmarks.common._resolve_tool", fake_resolve_tool)

    assert require_fio() == "/repo/tools/fio-macOS"
    assert called_with
    assert called_with[0][0] == "tools/fio-macOS"


def test_require_fio_prefers_tools_binary_on_linux(monkeypatch: MonkeyPatch) -> None:
    called_with: list[tuple[str, ...]] = []

    def fake_resolve_tool(*candidates: str) -> str | None:
        called_with.append(candidates)
        return "/repo/tools/fio-linux"

    monkeypatch.setattr("drive_qual.benchmarks.common.sys.platform", "linux")
    monkeypatch.setattr("drive_qual.benchmarks.common._resolve_tool", fake_resolve_tool)

    assert require_fio() == "/repo/tools/fio-linux"
    assert called_with
    assert called_with[0][0] == "tools/fio-linux"
    assert "tools/fio-macOS" not in called_with[0]
