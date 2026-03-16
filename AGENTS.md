<!--
waldo - image region of interest tracker
Copyright (C) 2026 notweerdmonk

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
-->

# Repository Guidelines

## Project Structure & Module Organization

Core application code lives in [`waldo/`](/home/weerdmonk/Projects/waldo/waldo), with the CLI in [`waldo/cli.py`](/home/weerdmonk/Projects/waldo/waldo/cli.py) and package metadata in [`waldo/__init__.py`](/home/weerdmonk/Projects/waldo/waldo/__init__.py). [`waldo.py`](/home/weerdmonk/Projects/waldo/waldo.py) is a thin wrapper entrypoint. Packaging files are [`pyproject.toml`](/home/weerdmonk/Projects/waldo/pyproject.toml), [`setup.py`](/home/weerdmonk/Projects/waldo/setup.py), [`MANIFEST.in`](/home/weerdmonk/Projects/waldo/MANIFEST.in), and [`pep517_backend.py`](/home/weerdmonk/Projects/waldo/pep517_backend.py). Example artifacts for documentation live under [`examples/`](/home/weerdmonk/Projects/waldo/examples). Local-only outputs such as `build/`, `dist/`, `tmp/`, and `testing/` are not release content.

## Build, Test, and Development Commands

Install runtime dependencies with ` .venv/bin/pip install -r requirements.txt `. Install build tooling with ` .venv/bin/pip install -r requirements-dev.txt `. Run the CLI locally with ` .venv/bin/python -m waldo --help ` or ` .venv/bin/waldo --version `. Build release artifacts with ` TMPDIR=/home/weerdmonk/Projects/waldo/tmp .venv/bin/python -m build --no-isolation `. For this environment, install the built wheel with ` .venv/bin/pip install --no-deps dist/waldo-1.0.0-py3-none-any.whl ` or use ` ./scripts/install_local_pep517.sh `.

## Coding Style & Naming Conventions

Use Python 3.10+ and 4-space indentation. Prefer clear dataclass-based configuration and small focused functions. Use `snake_case` for modules, functions, and variables; use `PascalCase` for classes. Keep user-facing artifact names aligned with the project name `waldo`. Follow existing OpenCV-based implementation patterns before introducing new dependencies.

## Testing Guidelines

There is no dedicated automated test suite yet, so every change should include at least a runnable verification step. Minimum checks are ` .venv/bin/python -m py_compile waldo.py waldo/cli.py waldo/__main__.py waldo/__init__.py ` and ` .venv/bin/python -m waldo --help `. For tracking changes, run the CLI on sample frames or video and verify CSV/debug outputs.

## Commit & Pull Request Guidelines

This repository currently has no commit history, so use short imperative commit messages such as `Add debug frame throttling` or `Fix PEP 517 wheel install docs`. Pull requests should include a concise summary, the commands used for verification, and updated docs when behavior, packaging, or release steps change. Include screenshots only when README/example assets or debug-image output change.
