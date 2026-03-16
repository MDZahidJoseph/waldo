"""PEP 517 backend wrapper with an EXDEV-safe rename fallback.

This keeps setuptools as the actual backend but avoids failing builds in
environments where the final artifact rename crosses an unexpected boundary.
"""

from __future__ import annotations

import errno
import os
import shutil
from contextlib import contextmanager

from setuptools import build_meta as _setuptools_backend


def _safe_rename(src: str, dst: str) -> None:
    try:
        _ORIGINAL_RENAME(src, dst)
    except OSError as exc:
        if exc.errno != errno.EXDEV:
            raise
        if os.path.isdir(src):
            shutil.copytree(src, dst, dirs_exist_ok=True)
            shutil.rmtree(src)
        else:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
            os.unlink(src)


@contextmanager
def _rename_fallback():
    os.rename = _safe_rename
    try:
        yield
    finally:
        os.rename = _ORIGINAL_RENAME


def get_requires_for_build_sdist(config_settings=None):
    return _setuptools_backend.get_requires_for_build_sdist(config_settings)


def get_requires_for_build_wheel(config_settings=None):
    return _setuptools_backend.get_requires_for_build_wheel(config_settings)


def prepare_metadata_for_build_wheel(metadata_directory, config_settings=None):
    return _setuptools_backend.prepare_metadata_for_build_wheel(
        metadata_directory, config_settings
    )


def build_sdist(sdist_directory, config_settings=None):
    with _rename_fallback():
        return _setuptools_backend.build_sdist(sdist_directory, config_settings)


def build_wheel(wheel_directory, config_settings=None, metadata_directory=None):
    with _rename_fallback():
        return _setuptools_backend.build_wheel(
            wheel_directory, config_settings, metadata_directory
        )


_ORIGINAL_RENAME = os.rename
