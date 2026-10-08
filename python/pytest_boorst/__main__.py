"""Run pytest with Boorst enabled for this process."""

import os
import sys

import pytest


def main():
    os.environ["PYTEST_BOORST"] = "1"
    return pytest.main(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
