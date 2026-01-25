import os


def mk_dir(path: str | os.PathLike[str]) -> None:
    os.makedirs(path, exist_ok=True)
