from pathlib import Path

from setuptools import find_packages, setup
from setuptools import __version__ as setuptools_version


ROOT = Path(__file__).parent
VERSION_NS = {}
exec((ROOT / "waldo" / "__init__.py").read_text(), VERSION_NS)


def _major_version(raw: str) -> int:
    return int(raw.split(".", 1)[0])


if _major_version(setuptools_version) >= 61:
    # Modern setuptools can read metadata from pyproject.toml directly.
    setup()
else:
    # Fallback for older tooling that still relies on setup.py metadata.
    setup(
        name="waldo",
        version=VERSION_NS["__version__"],
        description="Track a moving region of interest across frames or video.",
        packages=find_packages(include=["waldo", "waldo.*"]),
        install_requires=["numpy", "opencv-python"],
        entry_points={"console_scripts": ["waldo=waldo.cli:run"]},
    )
