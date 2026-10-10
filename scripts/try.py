"""Install the pinned release into an existing test environment and run pytest."""

import importlib.metadata
import importlib.util
import os
import subprocess
import sys

VERSION = "0.1.0"
WHEELS = (
    "https://github.com/dnikolayev/pytest-boorst/releases/download/"
    f"v{VERSION}/wheels.html"
)


def main():
    if sys.prefix == sys.base_prefix:
        raise SystemExit(
            "Run this trial in your project's existing virtual environment."
        )
    if importlib.util.find_spec("pytest") is None:
        raise SystemExit(
            "Install your project's test dependencies before trying Boorst."
        )
    try:
        installed = importlib.metadata.version("pytest-boorst")
    except importlib.metadata.PackageNotFoundError:
        installed = None
    if installed != VERSION:
        subprocess.run(
            [
                "uv",
                "pip",
                "install",
                "--python",
                sys.executable,
                "--no-deps",
                "--only-binary",
                ":all:",
                "--no-index",
                "--find-links",
                WHEELS,
                f"pytest-boorst=={VERSION}",
            ],
            check=True,
        )
    os.environ["PYTEST_BOORST"] = "1"
    import pytest

    return pytest.main(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
