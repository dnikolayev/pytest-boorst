"""Verify a packaged alpha or its unsupported-version fallback."""

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expect", choices=("active", "fallback"), default="active")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="boorst-smoke-") as temporary:
        directory = Path(temporary)
        (directory / "test_values.py").write_text(
            "import pytest\n"
            "@pytest.mark.parametrize('value', range(128), ids=['case'] * 128)\n"
            "def test_value(value):\n    assert value >= 0\n",
            encoding="utf-8",
        )
        (directory / "conftest.py").write_text(
            "import json\nfrom pathlib import Path\n"
            "from pytest_boorst import plugin\n"
            "def pytest_sessionfinish(session, exitstatus):\n"
            "    state = dict(session.config.stash[plugin.STATE_KEY])\n"
            "    state['ids'] = [item.nodeid for item in session.items]\n"
            "    Path('receipt.json').write_text(json.dumps(state))\n",
            encoding="utf-8",
        )
        env = os.environ.copy()
        env.pop("PYTEST_ADDOPTS", None)
        env.pop("PYTEST_DISABLE_PLUGIN_AUTOLOAD", None)
        env["PYTEST_BOORST"] = "1"
        subprocess.run(
            [sys.executable, "-m", "pytest", "-q"],
            cwd=directory,
            env=env,
            check=True,
            timeout=60,
        )
        receipt = json.loads((directory / "receipt.json").read_text(encoding="utf-8"))
        assert receipt["status"] == args.expect, receipt
        assert receipt["native_calls"] == (1 if args.expect == "active" else 0)
        assert receipt["ids"] == [
            f"test_values.py::test_value[case{i}]" for i in range(128)
        ]
        print(f"Verified {args.expect}: 128 identical IDs and passing tests")


if __name__ == "__main__":
    main()
