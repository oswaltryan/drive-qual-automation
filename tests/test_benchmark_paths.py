from __future__ import annotations

from _pytest.monkeypatch import MonkeyPatch

from drive_qual.benchmarks import benchmark_directory, benchmark_file_path


def test_benchmark_file_path_normalizes_windows_drive_roots(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr("drive_qual.benchmarks.common.sys.platform", "win32")

    assert benchmark_directory("D") == "D:\\"
    assert benchmark_directory("D:") == "D:\\"
    assert benchmark_directory("D:\\") == "D:\\"
    assert benchmark_file_path("D", "benchmark_file.dat") == r"D:\benchmark_file.dat"
    assert benchmark_file_path("D:", "benchmark_file.dat") == r"D:\benchmark_file.dat"
    assert benchmark_file_path("D:\\", "benchmark_file.dat") == r"D:\benchmark_file.dat"
