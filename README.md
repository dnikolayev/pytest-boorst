# pytest-boorst

Experimental Rust-powered acceleration for pytest, targeting large batches of
duplicate ASCII parameter IDs and many explicit sibling test-file arguments.
Suites with unique IDs, small batches, ordinary directory arguments, or time spent
mainly importing dependencies and running fixtures/tests can see little gain or
overhead. See the [measured results](#performance-evidence).

Pytest keeps control of test collection, fixtures, execution, and reporting.
Acceleration is opt-in and requires a recognized pytest implementation.

## Try the alpha

From your project directory, with its test dependencies already installed in its
virtual environment, install from PyPI and run with uv:

```sh
uv pip install --no-deps pytest-boorst==0.1.0a9
uv run --no-sync pytest --boorst -q tests/
```

Or, with your project's virtual environment activated, use pip:

```sh
python -m pip install --no-deps pytest-boorst==0.1.0a9
pytest --boorst -q tests/
```

Both work in POSIX shells and PowerShell. Use your usual pytest arguments in place
of `-q tests/`, or omit them to use your project's configured test selection.
`--no-deps` preserves your installed pytest and other dependencies. `--boorst`
enables guarded acceleration for that pytest run, using your existing configuration
and leaving your lockfile unchanged.

Native wheels cover macOS Intel/ARM64, Windows x86-64/x86/ARM64, and Linux
glibc/musl on x86-64/x86/ARM64. See the [platform matrix](https://github.com/dnikolayev/pytest-boorst/blob/v0.1.0a9/CONTRIBUTING.md#platform-wheels).
Other platforms can install the universal Python wheel: it retains the guarded
directory optimization on supported Linux/macOS environments and uses stock IDs.

Acceleration stays disabled when `--boorst` is omitted and `PYTEST_BOORST=1` is unset. Use
`-p no:boorst` to prevent plugin loading; uninstalling the package restores ordinary
pytest behavior. If plugin autoload is disabled, load it explicitly with
`pytest -p boorst --boorst -q tests/`.

The environment variable `PYTEST_BOORST=1` and the portable module command
`python -m pytest_boorst` also enable acceleration for existing integrations.

[GitHub releases](https://github.com/dnikolayev/pytest-boorst/releases) trigger the full CI
matrix, then publish its tested distributions to PyPI using Trusted Publishing.
Release assets contain the same wheels, source distribution and SHA-256 manifest.

## Compatibility boundary

The parameter-ID adapter is explicitly tested on **pytest 7.4.4, 8.4.2, 9.0.2, 9.0.3,
and 9.1.1 on CPython 3.10–3.14 with the GIL enabled**. Other pytest 7/8/9 releases
can activate only when the original method's source matches a verified implementation
from the same major version and its runtime code matches that source. Unknown or
modified implementations and missing or unloadable native extensions use stock
parameter IDs. Replacing the original method's code between batches stops ID
acceleration. The adapter restores its owned patch at session cleanup.
Installation does not require changing an already-installed pytest version.
On older releases without pytest's Stash API, the plugin falls back quietly.

Only duplicate batches of at least 64 resolved, exact ASCII strings enter Rust.
The 64-ID and 32-file cutoffs are conservative eligibility bounds; measurements
have not established them as universal performance crossover points.
Small batches, unique IDs, Unicode, string subclasses, hidden IDs, and strict-ID
errors use pytest behavior. Pytest still resolves custom IDs and calls user hooks
exactly once. Unexpected native computation errors propagate rather than rerunning
callbacks or hiding a bug.

Pytest 7 uses its original suffix rules, including collisions with existing IDs;
pytest 8 and 9 retain their collision-avoidance rules. Strict-ID errors are
preserved on pytest 9, and hidden parameter IDs stay with pytest on releases
that provide them. Pytest 7 already has linear duplicate bookkeeping, so its
native helper may provide little full-run improvement.

On **pytest 9.1.1, CPython 3.10–3.14, Linux and macOS**, directory discovery can
reuse successful reports for directories with at least 32 distinct `.py` files
passed as plain arguments. Groups may be interleaved across several directories;
smaller groups retain stock discovery. Selected parent directories must not
contain one another. This Python optimization avoids recreating every
sibling collector for each requested file. It needs no native extension and does
not change the arguments, import unrequested tests, or replace file collection.

Directory reuse requires verified stock directory methods and discovery/report
hooks. Custom discovery/report hooks, modified methods, selectors, duplicate paths, symlinks,
overlapping parent directories, doctest-module mode, last-failed/failed-first modes, and debug
tracing use stock discovery. Changed hooks, plugins, or collection options stop
reuse; changed directory metadata invalidates the report. Windows currently uses
stock discovery because directory reuse has not been validated there; this does
not establish a Windows-specific defect. Plugins inspecting discarded collectors or pytest's private
collection-cache layout are outside this experimental compatibility boundary.

This uses a narrowly guarded private pytest method. The tested compatibility
boundary does not establish compatibility with every possible third-party plugin
or modification of pytest internals. Tests cover ordered IDs, phase outcomes,
coverage, asyncio, xdist, callbacks, errors, and repeated invocation.

On releases with the Stash API, the header reports activation or fallback.
The summary reports native ID batches, stock batches, and reused directory reports.
An `active` header means the adapter is installed; it does not prove that any batch
qualified or that the run became faster. Stock batches observed by the adapter are
attributed to cutoff, non-ASCII/unsupported IDs, already unique IDs, strict IDs,
resolution errors, or a method change. Unsupported activation reports its reason
without patching pytest merely to count stock batches.

With `-v`, the summary lists up to 10 largest observed ID batches, including their
nodeids, sizes, and native/stock reasons. Under xdist, the controller sums worker
counters and labels verbose batch entries by worker. These counters describe actual
work across workers: each worker normally collects the suite, so the same batch can
be counted more than once. Worker totals exclude controller-local counters. A worker
that crashes before publishing its output cannot contribute its missing counters.

## Inspect a run

Use the optional profiler with the same pytest arguments:

```sh
uv run --no-sync pytest --boorst --boorst-profile -q tests/
```

`--boorst-profile` also works without `--boorst` to observe stock collection.
It reports wall time since session start, collection and test-loop wall time,
reported setup/call/teardown duration sums, and the 10 largest module collection
totals. Collection and test-loop wall times cover the observed hook spans; outer
third-party wrappers can perform additional work outside them. Module totals are
exclusive collect-report work attributed to each module, including its class
collectors, rather than isolated import time. Setup and teardown include pytest hooks; these are not isolated fixture
body timings. Under xdist, worker collection time is a sum and can exceed elapsed
wall time. Module totals include repeated worker collection. Crashed workers may
leave missing collection observations.

Interpreter, plugin and early conftest imports precede these hooks. Use Python's
separate tracing when investigating startup:

```sh
python -X importtime -m pytest --boorst-profile --collect-only
```

Profiling adds observation overhead, so compare stock/enabled timing without the
profiler and inspect phases in a separate run. See [optimization decisions and
public collection controls](RESULTS.md) for the current evidence and limits.

## Development

Install uv and Rust, then:

```sh
uv sync --locked --python 3.14
uv run --no-sync maturin develop --release --locked
uv run --no-sync ruff check .
uv run --no-sync ruff format --check .
uv run --no-sync pytest
cargo fmt --check
cargo clippy --locked --all-targets -- -D warnings
cargo test --locked --lib
```

`uv.lock` and `Cargo.lock` pin the development environments. Maturin builds the
PyO3 extension. GitHub CI installs built wheels and tests Python 3.10–3.14 on Linux,
plus macOS and Windows smoke coverage, and rebuilds the source distribution.
The Linux Python 3.10–3.14 wheel lanes also run ID, plugin-integration, profiler and installed-wheel
smoke checks with pytest 7.4.4 and 8.4.2 in separate environments. The Python 3.12
lane also runs the complete suite with pytest 9.0.2 and 9.0.3.
Normal wheel-installation checks preserve pytest 6.2.5 in a separate environment
and compare fallback IDs and phase outcomes against stock pytest.
An independent benchmark job retains raw timings and CPU/memory observations.

## Performance evidence

Measured on Ubuntu 24.04, CPython 3.14.8, pytest 9.1.1 and Boorst 0.1.0a2.
Times are medians of three fresh **full pytest runs**, including startup,
collection, fixtures and execution. Percentages use unrounded medians.

| Synthetic workload | Stock pytest | Boorst enabled | Time change |
| --- | ---: | ---: | ---: |
| 10,000 duplicate parameter IDs | 8.491 s | 6.685 s | 21.3% less |
| 10,000 colliding numeric-suffix IDs | 8.291 s | 6.495 s | 21.7% less |
| 384 explicit sibling test files | 7.755 s | 1.003 s | 87.1% less |
| 10,000 unique IDs (control) | 6.526 s | 6.511 s | 0.2% less |
| 8 IDs (control) | 0.244 s | 0.248 s | 1.7% more |

| Optimization | Why it helps |
| --- | --- |
| Duplicate-ID bookkeeping | Avoids rebuilding the used-ID set for every collision; PyO3 accelerates the bounded helper. |
| Directory-report reuse | Reuses a successful sibling-collector listing across file arguments, avoiding repeated scans and collector construction. This optimization uses Python. |

Most ID savings come from the algorithm: the optimized Python comparison took
6.739 s for duplicate IDs, versus 6.685 s with Rust. The isolated helper took
6.40 ms in Python and 4.34 ms in Rust; helper timings describe only that component.
Unique and small controls made zero native calls. Ordinary suites can see little
benefit or overhead; these synthetic results do not predict overall project CI.

Both harnesses verify exact ordered node IDs, setup/call/teardown outcomes and
exit codes. The ID harness checks parity before timing; the discovery harness
includes identical receipt recording during timing and disables bytecode writes
for both modes. CI requires at least 10% duplicate-workload improvement and 5%
directory-workload improvement. Separate compatibility tests cover callbacks,
fixtures, errors, coverage, asyncio, xdist and fallback behavior. Multi-directory
checks include interleaved groups, directory-local fixtures, syntax errors,
independent directory invalidation and stock fallback for overlapping groups.

Sources: [ID measurements](https://github.com/dnikolayev/pytest-boorst/blob/v0.1.0a9/benchmarks/results/alpha2-python314-ids-ci.json),
[directory measurements](https://github.com/dnikolayev/pytest-boorst/blob/v0.1.0a9/benchmarks/results/alpha2-python314-discovery-ci.json), and the
[successful CI run](https://github.com/dnikolayev/pytest-boorst/actions/runs/37696156274).

Alpha 4 also covers independent sibling groups. A macOS ARM64 / CPython
3.14.7 / pytest 9.1.1 trial with the universal wheel measured three fresh full runs:

| Additional synthetic workload | Stock pytest | Boorst enabled | Time change |
| --- | ---: | ---: | ---: |
| 384 files across four directories | 1.963 s | 0.973 s | 50.4% less |

[Raw measurements](https://github.com/dnikolayev/pytest-boorst/blob/v0.1.0a9/benchmarks/results/alpha4-multiple-directories-local.json)
record exact ordered-ID, phase and exit-code parity, with 380 directory reuses and
zero native ID calls per run. This measures the Python discovery optimization.
Alpha 3 uses stock discovery for this multi-directory plan. CI repeats the four-directory
workload on Python 3.14.8 and retains its own raw receipt.

The benchmark job uses CPython 3.14.8. Existing projects can keep their own
Python version; the module command uses their existing environment.

Reproduce with Python 3.14 and a release build:

```sh
uv sync --locked --python 3.14
uv run --no-sync maturin develop --release --locked
uv run --no-sync python benchmarks/run.py --size 10000 --repeats 3
uv run --no-sync python benchmarks/discovery.py --repeats 3
uv run --no-sync python benchmarks/discovery.py --directories 4 --repeats 3 --output benchmark-results-multiple-directories.json
```

See [benchmark methodology](https://github.com/dnikolayev/pytest-boorst/blob/v0.1.0a9/benchmarks/README.md) for detailed compatibility
controls and earlier public-project measurements.
