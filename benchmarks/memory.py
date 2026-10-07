"""Measure fresh-process peak RSS for the same duplicate-ID workload."""

import argparse
import json
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path

from run import CONFTEXT, MODES, command, environment

RUNNER = """
import json
import resource
import sys
import pytest

state = None
class Observe:
    def pytest_sessionfinish(self, session):
        global state
        plugin = session.config.pluginmanager.get_plugin("boorst")
        if plugin:
            state = dict(session.config.stash[plugin.STATE_KEY])

code = pytest.main(sys.argv[1:], plugins=[Observe()])
usage = resource.getrusage(resource.RUSAGE_SELF)
peak = usage.ru_maxrss
print("BOORST_MEMORY=" + json.dumps({
    "peak_rss_bytes": peak if sys.platform == "darwin" else peak * 1024,
    "cpu_seconds": usage.ru_utime + usage.ru_stime,
    "exit_code": int(code), "state": state,
}))
raise SystemExit(code)
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--size", type=int, default=10000)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument(
        "--scenario", choices=("duplicate", "unique", "small"), default="duplicate"
    )
    parser.add_argument(
        "--output", type=Path, default=Path("benchmark-results-memory.json")
    )
    args = parser.parse_args()
    if sys.platform not in {"darwin", "linux"}:
        parser.error("peak RSS measurement currently supports macOS and Linux")
    if args.size < 64 or args.repeats < 1:
        parser.error("use size >= 64 and repeats >= 1")
    measurements = {mode: [] for mode in MODES}
    ids = {
        "duplicate": ["case"] * args.size,
        "unique": [f"case{i}" for i in range(args.size)],
        "small": ["case"] * 8,
    }[args.scenario]
    with tempfile.TemporaryDirectory(prefix="boorst-memory-") as temporary:
        directory = Path(temporary)
        (directory / "conftest.py").write_text(CONFTEXT, encoding="utf-8")
        (directory / "test_values.py").write_text(
            "import pytest\n"
            f"@pytest.mark.parametrize('value', range({len(ids)}), ids={ids!r})\n"
            "def test_value(value):\n    assert value >= 0\n",
            encoding="utf-8",
        )
        for round_number in range(args.repeats):
            order = MODES[round_number % 3 :] + MODES[: round_number % 3]
            for mode in order:
                result = subprocess.run(
                    [sys.executable, "-c", RUNNER, *command(mode, False)[3:]],
                    cwd=directory,
                    env=environment(mode),
                    capture_output=True,
                    text=True,
                    check=True,
                    timeout=180,
                )
                line = next(
                    line
                    for line in result.stdout.splitlines()
                    if line.startswith("BOORST_MEMORY=")
                )
                measurement = json.loads(line.removeprefix("BOORST_MEMORY="))
                if mode != "stock":
                    state = measurement["state"]
                    expected_calls = 1 if args.scenario == "duplicate" else 0
                    if (
                        state["status"] != "active"
                        or state["native_calls"] != expected_calls
                    ):
                        raise AssertionError(f"Unexpected accelerator state for {mode}")
                measurements[mode].append(measurement)
    result = {
        "size": len(ids),
        "scenario": args.scenario,
        "repeats": args.repeats,
        "platform": sys.platform,
        "measurements": measurements,
        "median_peak_rss_bytes": {
            mode: statistics.median(item["peak_rss_bytes"] for item in samples)
            for mode, samples in measurements.items()
        },
        "median_cpu_seconds": {
            mode: statistics.median(item["cpu_seconds"] for item in samples)
            for mode, samples in measurements.items()
        },
    }
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result["median_peak_rss_bytes"]))


if __name__ == "__main__":
    main()
