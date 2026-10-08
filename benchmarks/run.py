"""Compare stock pytest, optimized Python, and Rust in fresh processes."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import inspect
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

MODES = ("stock", "python", "rust")
CONFTEXT = """
import json
import os
from pathlib import Path
import sys
from types import ModuleType

if os.environ.get("BOORST_COMPARE_PYTHON") == "1":
    from pytest_boorst._ids import unique_ids, unique_ids_pytest7
    module = ModuleType("pytest_boorst._native")
    module.unique_ids = unique_ids
    module.unique_ids_pytest7 = unique_ids_pytest7
    sys.modules[module.__name__] = module

nodes = []
reports = []

def pytest_collection_finish(session):
    if os.environ.get("BOORST_RECEIPT"):
        nodes.extend(item.nodeid for item in session.items)

def pytest_runtest_logreport(report):
    if os.environ.get("BOORST_RECEIPT"):
        reports.append([report.nodeid, report.when, report.outcome,
                        getattr(report, "wasxfail", None)])

def pytest_sessionfinish(session, exitstatus):
    destination = os.environ.get("BOORST_RECEIPT")
    if not destination:
        return
    plugin = session.config.pluginmanager.get_plugin("boorst")
    state = dict(session.config.stash[plugin.STATE_KEY]) if plugin else None
    Path(destination).write_text(json.dumps({"nodes": nodes, "reports": reports,
        "exitstatus": int(exitstatus), "state": state}), encoding="utf-8")
"""


def environment(mode: str) -> dict[str, str]:
    env = os.environ.copy()
    for name in ("PYTEST_ADDOPTS", "PYTEST_PLUGINS", "BOORST_RECEIPT"):
        env.pop(name, None)
    env["PYTEST_BOORST"] = "0" if mode == "stock" else "1"
    env["BOORST_COMPARE_PYTHON"] = "1" if mode == "python" else "0"
    return env


def command(mode: str, collect: bool) -> list[str]:
    args = [sys.executable, "-m", "pytest", "-q", "--disable-warnings"]
    if mode == "stock":
        args += ["-p", "no:boorst"]
    if collect:
        args.append("--collect-only")
    return args


def invoke(directory: Path, mode: str, collect: bool, *, receipt: Path | None = None):
    env = environment(mode)
    if receipt:
        env["BOORST_RECEIPT"] = str(receipt)
    started = time.perf_counter()
    result = subprocess.run(
        command(mode, collect),
        cwd=directory,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )
    elapsed = time.perf_counter() - started
    if result.returncode:
        raise RuntimeError(f"{mode} failed:\n{result.stdout}\n{result.stderr}")
    return elapsed


def verify(directory: Path) -> dict[str, dict]:
    receipts = {}
    for mode in MODES:
        destination = directory / f"{mode}.json"
        invoke(directory, mode, False, receipt=destination)
        receipts[mode] = json.loads(destination.read_text(encoding="utf-8"))
    expected = {k: v for k, v in receipts["stock"].items() if k != "state"}
    for mode in MODES[1:]:
        actual = {k: v for k, v in receipts[mode].items() if k != "state"}
        if actual != expected:
            raise AssertionError(f"Behavior mismatch for {mode}")
        if receipts[mode]["state"]["status"] != "active":
            raise AssertionError(f"Adapter inactive for {mode}")
    return {mode: receipt["state"] for mode, receipt in receipts.items()}


def microbenchmark(ids: list[str], repeats: int) -> dict:
    import pytest
    from _pytest.mark import ParameterSet
    from _pytest.python import IdMaker
    from pytest_boorst import _native
    from pytest_boorst._ids import unique_ids, unique_ids_pytest7

    python_ids = unique_ids_pytest7 if pytest.__version__ == "7.4.4" else unique_ids
    native_ids = (
        _native.unique_ids_pytest7
        if pytest.__version__ == "7.4.4"
        else _native.unique_ids
    )

    extra = (
        {"func_name": "test_value"}
        if "func_name" in inspect.signature(IdMaker).parameters
        else {}
    )
    maker = IdMaker(
        argnames=["value"],
        parametersets=[
            ParameterSet.param(index, id=name) for index, name in enumerate(ids)
        ],
        idfn=None,
        ids=None,
        config=None,
        nodeid="test_value",
        **extra,
    )

    # Bind the original resolved-ID tail so callbacks/ID generation are excluded
    # from all three component measurements. Full pytest runs include both.
    class Resolved:
        def _resolve_ids(self):
            return iter(ids)

        def __getattr__(self, name):
            return getattr(maker, name)

    functions = {
        "stock": lambda: IdMaker.make_unique_parameterset_ids(Resolved()),
        "python": lambda: python_ids(ids),
        "rust": lambda: native_ids(ids),
    }
    expected = functions["stock"]()
    for mode, function in functions.items():
        if function() != expected:
            raise AssertionError(f"Component behavior mismatch for {mode}")
    timings = {mode: [] for mode in MODES}
    for round_number in range(repeats):
        order = MODES[round_number % 3 :] + MODES[: round_number % 3]
        for mode in order:
            started = time.perf_counter()
            functions[mode]()
            timings[mode].append(time.perf_counter() - started)
    return {
        "seconds": timings,
        "median_seconds": {
            mode: statistics.median(samples) for mode, samples in timings.items()
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--size", type=int, default=3000)
    parser.add_argument("--repeats", type=int, default=7)
    parser.add_argument("--output", type=Path, default=Path("benchmark-results.json"))
    args = parser.parse_args()
    if args.size < 64 or args.repeats < 3:
        parser.error("use size >= 64 and repeats >= 3")
    scenarios = {
        "duplicate": ["case"] * args.size,
        "collision": ["a0", "a0", "a", "a"] * (args.size // 4),
        "unique": [f"case{i}" for i in range(args.size)],
        "small": ["case"] * 8,
    }
    source_root = Path(__file__).resolve().parents[1]
    digest = hashlib.sha256()
    for name in (
        "Cargo.toml",
        "Cargo.lock",
        "pyproject.toml",
        "src/lib.rs",
        "python/pytest_boorst/plugin.py",
        "python/pytest_boorst/_ids.py",
        "benchmarks/run.py",
    ):
        digest.update(name.encode())
        digest.update((source_root / name).read_bytes())
    from pytest_boorst import _native

    result = {
        "python": sys.version.split()[0],
        "pytest": importlib.metadata.version("pytest"),
        "package": importlib.metadata.version("pytest-boorst"),
        "source_sha256": digest.hexdigest(),
        "native_sha256": hashlib.sha256(
            Path(_native.__file__).read_bytes()
        ).hexdigest(),
        "size": args.size,
        "repeats": args.repeats,
        "baseline": "installed package blocked with -p no:boorst",
        "timing": "fresh subprocesses; receipt recording disabled during timings",
        "scenarios": {},
    }
    with tempfile.TemporaryDirectory(prefix="boorst-benchmark-") as temporary:
        for name, ids in scenarios.items():
            directory = Path(temporary) / name
            directory.mkdir()
            (directory / "conftest.py").write_text(CONFTEXT, encoding="utf-8")
            (directory / "test_values.py").write_text(
                "import pytest\n"
                f"@pytest.mark.parametrize('value', range({len(ids)}), ids={ids!r})\n"
                "def test_value(value):\n    assert value >= 0\n",
                encoding="utf-8",
            )
            state = verify(directory)
            expected_calls = 1 if name in ("duplicate", "collision") else 0
            if state["rust"]["native_calls"] != expected_calls:
                raise AssertionError(f"Unexpected native call count for {name}")
            measurements = {}
            for phase, collect in (("collection", True), ("full_run", False)):
                timings = {mode: [] for mode in MODES}
                for round_number in range(args.repeats):
                    order = MODES[round_number % 3 :] + MODES[: round_number % 3]
                    for mode in order:
                        timings[mode].append(invoke(directory, mode, collect))
                medians = {
                    mode: statistics.median(samples)
                    for mode, samples in timings.items()
                }
                measurements[phase] = {
                    "seconds": timings,
                    "median_seconds": medians,
                    "rust_vs_stock": medians["stock"] / medians["rust"],
                    "rust_vs_python": medians["python"] / medians["rust"],
                }
                print(f"{name} {phase}: {json.dumps(medians)}", flush=True)
            component = microbenchmark(ids, args.repeats)
            result["scenarios"][name] = {
                "count": len(ids),
                "parity": True,
                "state": state,
                "component_seconds": component["seconds"],
                "component_median_seconds": component["median_seconds"],
                **measurements,
            }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
