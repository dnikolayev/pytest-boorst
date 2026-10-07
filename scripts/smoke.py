"""Verify a packaged alpha or its fallback against stock pytest."""

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
    parser.add_argument("--pytest-version", help="Expected installed pytest version")
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
            "import json\nimport sys\nfrom pathlib import Path\nimport pytest\n"
            "from pytest_boorst import plugin\n"
            "reports = []\n"
            "def pytest_runtest_logreport(report):\n"
            "    reports.append((report.nodeid, report.when, report.outcome,\n"
            "                    getattr(report, 'wasxfail', None)))\n"
            "def pytest_sessionfinish(session, exitstatus):\n"
            "    state = (dict(session.config.stash.get(plugin.STATE_KEY, {}))\n"
            "             if plugin.STATE_KEY is not None else {})\n"
            "    state.setdefault('status', 'fallback')\n"
            "    state.setdefault('native_calls', 0)\n"
            "    state['ids'] = [item.nodeid for item in session.items]\n"
            "    state['reports'] = reports\n"
            "    state['pytest_version'] = pytest.__version__\n"
            "    state['registered'] = session.config.pluginmanager.hasplugin('boorst')\n"
            "    state['native_imported'] = 'pytest_boorst._native' in sys.modules\n"
            "    Path('receipt.json').write_text(json.dumps(state))\n",
            encoding="utf-8",
        )
        env = os.environ.copy()
        env.pop("PYTEST_ADDOPTS", None)
        env.pop("PYTEST_DISABLE_PLUGIN_AUTOLOAD", None)
        env["PYTEST_BOORST"] = "1"
        receipts = []
        for options in (["-p", "no:boorst"], []):
            subprocess.run(
                [sys.executable, "-m", "pytest", "-q", *options],
                cwd=directory,
                env=env,
                check=True,
                timeout=60,
            )
            receipts.append(
                json.loads((directory / "receipt.json").read_text(encoding="utf-8"))
            )
        stock, receipt = receipts
        assert not stock["registered"] and not stock["native_imported"], stock
        assert receipt["registered"], receipt
        assert receipt["status"] == args.expect, receipt
        assert receipt["native_calls"] == (1 if args.expect == "active" else 0)
        assert receipt["native_imported"] == (args.expect == "active"), receipt
        if args.pytest_version:
            assert receipt["pytest_version"] == args.pytest_version, receipt
        assert receipt["ids"] == [
            f"test_values.py::test_value[case{i}]" for i in range(128)
        ]
        assert receipt["ids"] == stock["ids"]
        assert receipt["reports"] == stock["reports"]
        assert len(receipt["reports"]) == 3 * 128
        print(
            f"Verified {args.expect} on pytest {receipt['pytest_version']}: "
            "128 identical IDs and stock phase outcomes"
        )


if __name__ == "__main__":
    main()
