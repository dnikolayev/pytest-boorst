"""Compare full pytest runs over explicit sibling files in fresh processes."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from run import CONFTEXT, command, environment

MODES = ("stock", "enabled")


def invoke(directory: Path, mode: str, paths: list[str], receipt: Path):
    env = environment(mode)
    env.update(BOORST_RECEIPT=str(receipt), PYTHONDONTWRITEBYTECODE="1")
    started = time.perf_counter()
    completed = subprocess.run(
        [*command(mode, False), *paths],
        cwd=directory,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )
    elapsed = time.perf_counter() - started
    if completed.returncode:
        raise RuntimeError(f"{mode} failed:\n{completed.stdout}\n{completed.stderr}")
    return elapsed, json.loads(receipt.read_text(encoding="utf-8"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--files", type=int, default=384)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--package", action="store_true")
    parser.add_argument(
        "--output", type=Path, default=Path("benchmark-results-discovery.json")
    )
    args = parser.parse_args()
    if args.files < 64 or args.repeats < 1:
        parser.error("use files >= 64 and repeats >= 1")
    version = importlib.metadata.version("pytest")
    if version != "9.1.1":
        parser.error("discovery acceleration currently requires pytest 9.1.1")
    import pytest_boorst

    package_root = Path(pytest_boorst.__file__).parent
    result = {
        "python": sys.version.split()[0],
        "pytest": version,
        "package": importlib.metadata.version("pytest-boorst"),
        "package_source_sha256": {
            str(path.relative_to(package_root)): hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
            for path in sorted(package_root.glob("*.py"))
        },
        "benchmark_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "files": args.files,
        "package_directory": args.package,
        "repeats": args.repeats,
        "baseline": "installed package blocked with -p no:boorst",
        "timing": "fresh full-run subprocesses; receipts included; bytecode writes off",
    }
    timings = {mode: [] for mode in MODES}
    states = {mode: [] for mode in MODES}
    expected = None
    with tempfile.TemporaryDirectory(prefix="boorst-discovery-benchmark-") as temporary:
        directory = Path(temporary)
        (directory / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
        (directory / "conftest.py").write_text(
            CONFTEXT
            + "\nimport pytest\n"
            + "@pytest.fixture\ndef answer():\n    yield 42\n",
            encoding="utf-8",
        )
        tests = directory / "tests"
        tests.mkdir()
        if args.package:
            (tests / "__init__.py").write_text("", encoding="utf-8")
        paths = [f"tests/test_{number:04}.py" for number in range(args.files)]
        for path in paths:
            (directory / path).write_text(
                "def test_answer(answer):\n    assert answer == 42\n", encoding="utf-8"
            )
        for round_number in range(args.repeats):
            for mode in MODES[:: 1 if round_number % 2 == 0 else -1]:
                elapsed, receipt = invoke(
                    directory, mode, paths, directory / f"{mode}.json"
                )
                state = receipt.pop("state")
                if expected is None:
                    expected = receipt
                if receipt != expected:
                    raise AssertionError(
                        f"Ordered node/report parity failed for {mode}"
                    )
                if len(receipt["nodes"]) != args.files:
                    raise AssertionError("Unexpected collected test count")
                if mode == "enabled" and (
                    state["discovery_status"] != "active"
                    or state["directory_reuses"] < 1
                ):
                    raise AssertionError(f"Directory reuse inactive: {state}")
                timings[mode].append(elapsed)
                states[mode].append(state)
    medians = {mode: statistics.median(samples) for mode, samples in timings.items()}
    result.update(
        parity=True,
        parity_sha256=hashlib.sha256(json.dumps(expected).encode()).hexdigest(),
        seconds=timings,
        median_seconds=medians,
        improvement_percent=100 * (1 - medians["enabled"] / medians["stock"]),
        state=states,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(medians), flush=True)


if __name__ == "__main__":
    main()
