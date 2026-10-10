"""Compare complete pytest runs with cold and warm assertion bytecode caches."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from run import CONFTEXT, command, environment

MODES = ("stock", "enabled")


def invoke(directory, mode, *, receipt=None, write_bytecode=False):
    env = environment(mode)
    if write_bytecode:
        env.pop("PYTHONDONTWRITEBYTECODE", None)
    else:
        env["PYTHONDONTWRITEBYTECODE"] = "1"
    if receipt is not None:
        env["BOORST_RECEIPT"] = str(receipt)
    started = time.perf_counter()
    result = subprocess.run(
        command(mode, False),
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--files", type=int, default=32)
    parser.add_argument("--tests", type=int, default=8)
    parser.add_argument("--assertions", type=int, default=16)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument(
        "--output", type=Path, default=Path("benchmark-results-assertions.json")
    )
    args = parser.parse_args()
    if min(args.files, args.tests, args.assertions) < 1 or args.repeats < 3:
        parser.error("use positive workload sizes and at least three repetitions")
    import pytest_boorst
    from pytest_boorst import _native

    package = Path(pytest_boorst.__file__).parent
    result = {
        "python": sys.version.split()[0],
        "pytest": importlib.metadata.version("pytest"),
        "package": importlib.metadata.version("pytest-boorst"),
        "platform": f"{platform.system()} {platform.machine()}",
        "files": args.files,
        "tests_per_file": args.tests,
        "assertions_per_test": args.assertions,
        "repeats": args.repeats,
        "timing": "fresh full-run processes; parity receipts excluded from timing",
        "package_source_sha256": {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(package.glob("*.py"))
        },
        "native_sha256": hashlib.sha256(
            Path(_native.__file__).read_bytes()
        ).hexdigest(),
        "benchmark_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "scenarios": {},
    }
    with tempfile.TemporaryDirectory(prefix="boorst-assertion-benchmark-") as temporary:
        directory = Path(temporary)
        (directory / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
        (directory / "conftest.py").write_text(CONFTEXT, encoding="utf-8")
        source = "\n".join(
            f"def test_value_{test}():\n    value = {test}\n"
            + "".join(
                f"    assert value + {number} == {test + number}\n"
                for number in range(args.assertions)
            )
            for test in range(args.tests)
        )
        for number in range(args.files):
            (directory / f"test_values_{number:04}.py").write_text(
                source, encoding="utf-8"
            )
        expected = None
        for cache in ("cold", "warm"):
            if cache == "warm":
                invoke(directory, "stock", write_bytecode=True)
            states = {}
            for mode in MODES:
                destination = directory / f"{mode}.json"
                invoke(directory, mode, receipt=destination)
                receipt = json.loads(destination.read_text(encoding="utf-8"))
                states[mode] = receipt.pop("state")
                if expected is None:
                    expected = receipt
                if (
                    receipt != expected
                    or len(receipt["nodes"]) != args.files * args.tests
                ):
                    raise AssertionError(
                        f"Ordered node/phase parity failed: {cache}/{mode}"
                    )
            assertion_state = states["enabled"]["assertions"]
            batches = assertion_state["native_batches"]
            if cache == "cold" and not max(1, args.files - 1) <= batches <= args.files:
                raise AssertionError(
                    f"Expected native batches after config warmup: {assertion_state}"
                )
            if cache == "warm" and batches:
                raise AssertionError(
                    f"Warm cache unexpectedly rewrote tests: {assertion_state}"
                )
            timings = {mode: [] for mode in MODES}
            for number in range(args.repeats):
                for mode in MODES[:: 1 if number % 2 == 0 else -1]:
                    timings[mode].append(invoke(directory, mode))
            medians = {
                mode: statistics.median(samples) for mode, samples in timings.items()
            }
            result["scenarios"][cache] = {
                "parity": True,
                "parity_sha256": hashlib.sha256(
                    json.dumps(expected).encode()
                ).hexdigest(),
                "state": states,
                "seconds": timings,
                "median_seconds": medians,
                "improvement_percent": 100
                * (1 - medians["enabled"] / medians["stock"]),
            }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    for cache, scenario in result["scenarios"].items():
        print(cache, json.dumps(scenario["median_seconds"]))


if __name__ == "__main__":
    main()
