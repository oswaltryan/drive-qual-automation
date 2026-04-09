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


def test_require_fio_supports_repo_local_native_binary(monkeypatch: MonkeyPatch) -> None:
    called_with: list[tuple[str, ...]] = []

    def fake_resolve_tool(*candidates: str) -> str | None:
        called_with.append(candidates)
        return "/repo/tools/fio"

    monkeypatch.setattr("drive_qual.benchmarks.common._resolve_tool", fake_resolve_tool)

    assert require_fio() == "/repo/tools/fio"
    assert called_with
    assert "tools/fio" in called_with[0]
