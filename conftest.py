from __future__ import annotations

import os
import shutil
import tempfile
import uuid
from pathlib import Path

import pytest

_TMP_ROOT = Path(__file__).resolve().parent / ".tmp_test"
_ORIGINAL_MKDTEMP = tempfile.mkdtemp
_ORIGINAL_TEMPORARY_DIRECTORY = tempfile.TemporaryDirectory


def _workspace_tmp_root() -> Path:
    _TMP_ROOT.mkdir(parents=True, exist_ok=True)
    return _TMP_ROOT


def _workspace_mkdtemp(suffix: str | None = None, prefix: str | None = None, dir: str | None = None) -> str:
    base_dir = Path(dir) if dir else _workspace_tmp_root()
    base_dir.mkdir(parents=True, exist_ok=True)
    name_prefix = prefix or "tmp"
    name_suffix = suffix or ""
    while True:
        path = base_dir / f"{name_prefix}{uuid.uuid4().hex}{name_suffix}"
        try:
            path.mkdir()
            return str(path)
        except FileExistsError:
            continue


class _WorkspaceTemporaryDirectory:
    def __init__(
        self,
        suffix: str | None = None,
        prefix: str | None = None,
        dir: str | None = None,
        ignore_cleanup_errors: bool = False,
        **_: object,
    ) -> None:
        self.name = _workspace_mkdtemp(suffix=suffix, prefix=prefix, dir=dir)
        self._ignore_cleanup_errors = ignore_cleanup_errors

    def __enter__(self) -> str:
        return self.name

    def __exit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
        self.cleanup()

    def cleanup(self) -> None:
        shutil.rmtree(self.name, ignore_errors=True)


def pytest_configure(config) -> None:  # noqa: ANN001
    temp_root = str(_workspace_tmp_root())
    os.environ["TMPDIR"] = temp_root
    os.environ["TEMP"] = temp_root
    os.environ["TMP"] = temp_root
    tempfile.tempdir = temp_root
    tempfile.mkdtemp = _workspace_mkdtemp
    tempfile.TemporaryDirectory = _WorkspaceTemporaryDirectory


def pytest_unconfigure(config) -> None:  # noqa: ANN001
    tempfile.mkdtemp = _ORIGINAL_MKDTEMP
    tempfile.TemporaryDirectory = _ORIGINAL_TEMPORARY_DIRECTORY
    tempfile.tempdir = None


@pytest.fixture(autouse=True)
def _restore_environment():
    original = dict(os.environ)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(original)
