"""Compare collection in a prepared checkout; receipts may contain private paths."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

AUDIT = """
import json
import os
from pathlib import Path
import pytest

nodes, errors = [], []

def pytest_collectreport(report):
    if report.failed:
        errors.append([report.nodeid, report.longreprtext])

def pytest_collection_finish(session):
    nodes.extend(item.nodeid for item in session.items)

@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session, exitstatus):
    manager = session.config.pluginmanager
    plugin = manager.get_plugin("boorst")
    profiler = manager.get_plugin("boorst_profile")
    state = dict(session.config.stash[plugin.STATE_KEY]) if plugin else None
    Path(os.environ["BOORST_CORPUS_RECEIPT"]).write_text(json.dumps({
        "nodes": nodes, "errors": errors, "exitstatus": int(exitstatus),
        "state": state, "profile": profiler.snapshot() if profiler else None,
    }), encoding="utf-8")
"""
METADATA = """
import hashlib
import importlib.metadata as metadata
import importlib.util
import json
import sys
from pathlib import Path
package = importlib.util.find_spec("pytest_boorst")
directory = Path(package.origin).parent
paths = [directory / name for name in ("plugin.py", "_discovery.py", "_profile.py")]
native = importlib.util.find_spec("pytest_boorst._native")
if native is not None:
    paths.append(Path(native.origin))
print(json.dumps({"python": sys.version, "versions": {
    dist.metadata["Name"]: dist.version for dist in metadata.distributions()
}, "boorst_files_sha256": {
    path.name: hashlib.sha256(path.read_bytes()).hexdigest()
    for path in paths if path.is_file()
}}))
"""


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=True).encode()).hexdigest()


def invoke(checkout, command, env, receipt):
    receipt.unlink(missing_ok=True)
    started = time.perf_counter()
    completed = subprocess.run(
        command, cwd=checkout, env=env, capture_output=True, text=True, timeout=600
    )
    elapsed = time.perf_counter() - started
    data = json.loads(receipt.read_text(encoding="utf-8")) if receipt.exists() else {}
    data.update(seconds=elapsed, command=command, returncode=completed.returncode)
    data.update(stdout=completed.stdout, stderr=completed.stderr)
    return data


def compare(checkout, python, pytest_args, output):
    checkout, output = checkout.resolve(), output.resolve()
    # Preserve the venv executable path: resolving its symlink loses the environment.
    python = python.absolute()
    if output.is_relative_to(checkout):
        raise ValueError("Store the private receipt outside the prepared checkout")
    env = os.environ.copy()
    env.update(PYTEST_BOORST="0", PYTHONDONTWRITEBYTECODE="1")
    result = {
        "source_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=checkout, text=True
        ).strip(),
        "source_dirty": bool(
            subprocess.check_output(
                ["git", "status", "--porcelain"], cwd=checkout, text=True
            )
        ),
        "environment": json.loads(
            subprocess.check_output(
                [str(python), "-c", METADATA], cwd=checkout, env=env, text=True
            )
        ),
        "benchmark_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "limits": "Collection only; no execution or full-CI speed claim. Audit overhead "
        "is included. Bytecode writes are off and pytest cache is temporary; project "
        "plugins/hooks may still have side effects. Raw receipt is private.",
        "samples": [],
    }
    with tempfile.TemporaryDirectory(prefix="boorst-corpus-") as temporary:
        directory = Path(temporary)
        (directory / "boorst_corpus_audit.py").write_text(AUDIT, encoding="utf-8")
        env["PYTHONPATH"] = os.pathsep.join(
            filter(None, [env.get("PYTHONPATH"), temporary])
        )
        receipt = directory / "receipt.json"
        env["BOORST_CORPUS_RECEIPT"] = str(receipt)
        base = [str(python), "-m", "pytest", "-q", "--collect-only"]
        base += ["-o", f"cache_dir={directory / 'cache'}", "-p", "boorst_corpus_audit"]
        help_run = subprocess.run(
            [*base, "-p", "boorst", "--help", *pytest_args],
            cwd=checkout,
            env=env,
            capture_output=True,
            text=True,
            timeout=600,
        )
        for index in range(3):
            for mode in (
                ("stock", "enabled") if index % 2 == 0 else ("enabled", "stock")
            ):
                options = (
                    ["-p", "no:boorst"]
                    if mode == "stock"
                    else ["-p", "boorst", "--boorst"]
                )
                sample = invoke(checkout, [*base, *options, *pytest_args], env, receipt)
                sample["mode"] = mode
                result["samples"].append(sample)
        result["profile_available"] = (
            help_run.returncode == 0 and "--boorst-profile" in help_run.stdout
        )
        if result["profile_available"]:
            result["profile_run"] = invoke(
                checkout,
                [*base, "-p", "boorst", "--boorst-profile", *pytest_args],
                env,
                receipt,
            )
    records = result["samples"].copy()
    if "profile_run" in result:
        records.append(result["profile_run"])
    expected = {
        name: result["samples"][0].get(name)
        for name in ("nodes", "errors", "exitstatus", "returncode")
    }
    result["parity"] = all(
        "nodes" in row and {name: row.get(name) for name in expected} == expected
        for row in records
    )
    result["timed_runs_unprofiled"] = all(
        row.get("profile") is None for row in result["samples"]
    )
    result.update(
        collected_count=len(expected["nodes"] or []),
        collection_error_count=len(expected["errors"] or []),
        collection_success=expected["exitstatus"] == expected["returncode"] == 0,
        ordered_ids_sha256=digest(expected["nodes"]),
        collection_errors_sha256=digest(expected["errors"]),
    )
    result["median_seconds"] = {
        mode: statistics.median(
            row["seconds"] for row in result["samples"] if row["mode"] == mode
        )
        for mode in ("stock", "enabled")
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    if not result["parity"] or not result["timed_runs_unprofiled"]:
        raise AssertionError(
            "Collection parity failed or timed profiling was active; inspect the private receipt"
        )
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checkout", type=Path)
    parser.add_argument("--python", type=Path, default=Path(sys.executable))
    parser.add_argument("--output", type=Path, required=True)
    arguments = sys.argv[1:]
    split = arguments.index("--") if "--" in arguments else len(arguments)
    args = parser.parse_args(arguments[:split])
    result = compare(args.checkout, args.python, arguments[split + 1 :], args.output)
    print(
        json.dumps(
            {
                name: result[name]
                for name in (
                    "parity",
                    "collection_success",
                    "collected_count",
                    "ordered_ids_sha256",
                    "median_seconds",
                )
            }
        )
    )


if __name__ == "__main__":
    main()
