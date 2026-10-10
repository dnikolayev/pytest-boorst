"""Compare experimental prefiltering and stock collection on synthetic full runs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import statistics
import subprocess
import tempfile
import time
from pathlib import Path

OBSERVER = """
import hashlib, json, sys
from pathlib import Path
import pytest
from pytest_boorst import _static, plugin
nodes, phases = [], []
@pytest.fixture
def answer():
    yield 42

def pytest_collection_finish(session):
    nodes.extend(item.nodeid for item in session.items)

def pytest_runtest_logreport(report):
    phases.append([report.nodeid, report.when, report.outcome])

def pytest_sessionfinish(session, exitstatus):
    static = session.config.pluginmanager.get_plugin('boorst_static_discovery')
    Path('receipt.json').write_text(json.dumps(dict(
        nodes=nodes, phases=phases, exitstatus=int(exitstatus),
        counts=static.counts if static else None,
        python=sys.version.split()[0], pytest=pytest.__version__,
        source_sha256={name: hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
                       for name, module in [('_static.py', _static), ('plugin.py', plugin)]})))
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", default=os.sys.executable)
    parser.add_argument("--pairs", type=int, default=3)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.pairs < 3:
        parser.error("at least three alternating fresh-process pairs are required")
    env = dict(
        os.environ,
        PYTEST_DISABLE_PLUGIN_AUTOLOAD="1",
        PYTEST_BOORST="0",
        PYTHONDONTWRITEBYTECODE="1",
        PYTEST_ADDOPTS="",
    )
    command = [
        args.python,
        "-m",
        "pytest",
        "-p",
        "pytest_boorst.plugin",
        "-q",
        "-p",
        "no:cacheprovider",
    ]
    results = {}
    source_hashes = None
    for name in ("expensive_empty_modules", "ordinary_tests"):
        with tempfile.TemporaryDirectory(prefix="boorst-static-") as directory:
            root = Path(directory)
            (root / "pytest.ini").write_text("[pytest]\n")
            (root / "conftest.py").write_text(OBSERVER)
            for index in range(64):
                source = (
                    "import time\ntime.sleep(0.015)\nVALUE = 42\n"
                    if name == "expensive_empty_modules"
                    else "def test_answer(answer):\n    assert answer == 42\n"
                )
                (root / f"test_{index:03}.py").write_text(source)
            (root / "test_real.py").write_text(
                "import pytest\n@pytest.mark.parametrize('value', [1, 2])\n"
                "def test_real(answer, value):\n    assert answer == 42 and value > 0\n"
            )
            raw, expected, counts, versions = (
                {"stock": [], "static": []},
                None,
                None,
                None,
            )
            for pair in range(args.pairs):
                order = ("stock", "static") if pair % 2 == 0 else ("static", "stock")
                for mode in order:
                    option = ["--boorst-static-discovery"] if mode == "static" else []
                    started = time.perf_counter()
                    run = subprocess.run(
                        command + option,
                        cwd=root,
                        env=env,
                        capture_output=True,
                        text=True,
                        timeout=180,
                    )
                    raw[mode].append(time.perf_counter() - started)
                    receipt = json.loads((root / "receipt.json").read_text())
                    if source_hashes is None:
                        source_hashes = receipt["source_sha256"]
                    elif source_hashes != receipt["source_sha256"]:
                        raise RuntimeError(
                            "benchmark loaded source changed between samples"
                        )
                    manifest = [
                        receipt[key] for key in ("nodes", "phases", "exitstatus")
                    ]
                    if run.returncode != 0 or (
                        expected is not None and manifest != expected
                    ):
                        raise RuntimeError("benchmark outcome/ordered-ID parity failed")
                    expected = manifest
                    versions = dict(python=receipt["python"], pytest=receipt["pytest"])
                    if mode == "static":
                        counts = receipt["counts"]
            medians = {mode: statistics.median(times) for mode, times in raw.items()}
            results[name] = dict(
                versions=versions,
                raw_seconds=raw,
                median_seconds=medians,
                improvement_percent=100 * (1 - medians["static"] / medians["stock"]),
                collected=len(expected[0]),
                ordered_ids_sha256=hashlib.sha256(
                    json.dumps(expected[0]).encode()
                ).hexdigest(),
                phase_outcomes_sha256=hashlib.sha256(
                    json.dumps(expected[1]).encode()
                ).hexdigest(),
                parity=True,
                counts=counts,
            )
    output = dict(
        workloads=results,
        arguments=command[2:],
        pairs=args.pairs,
        benchmark_script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        workload_import_delay_seconds=0.015,
        source_sha256=source_hashes,
        limits="Synthetic serial full runs; not a general speedup or complete-test guarantee.",
    )
    args.output.write_text(json.dumps(output, indent=2) + "\n")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
