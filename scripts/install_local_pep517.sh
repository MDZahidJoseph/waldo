#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_PYTHON="${ROOT_DIR}/.venv/bin/python"
VENV_PIP="${ROOT_DIR}/.venv/bin/pip"
TMP_DIR="${ROOT_DIR}/tmp"
DIST_DIR="${ROOT_DIR}/dist"

mkdir -p "${TMP_DIR}" "${DIST_DIR}"

TMPDIR="${TMP_DIR}" "${VENV_PYTHON}" -m build --no-isolation
TMPDIR="${TMP_DIR}" "${VENV_PIP}" install --no-deps --force-reinstall "${DIST_DIR}"/waldo-1.0.0-py3-none-any.whl
