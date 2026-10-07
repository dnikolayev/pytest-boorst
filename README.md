# pytest-boorst

Experimental Rust-powered acceleration for pytest.

This alpha accelerates duplicate parameter-ID bookkeeping and repeated directory
discovery while pytest keeps control of test collection, fixtures, execution, and
reporting. Acceleration is
opt-in and guarded by a tested pytest version and implementation fingerprint.

## Try the alpha

Download a wheel matching your platform from this repository's GitHub Actions
artifacts, then install it into an isolated environment with your project dependencies:

```sh
uv pip install ./pytest_boorst-0.1.0a2-<wheel-tags>.whl
PYTEST_BOORST=1 uv run --no-sync pytest
```

The alpha is disabled unless `PYTEST_BOORST=1`. On PowerShell, set
`$env:PYTEST_BOORST = "1"` before invoking pytest. Existing test configuration
does not need editing. Use `pytest -p no:boorst` to prevent the plugin loading;
removing the package also restores ordinary pytest behavior.

No package has been published to PyPI yet. Wheel artifacts are experimental;
the Linux artifacts currently target the native CI runner's platform.

## Compatibility boundary

The parameter-ID adapter currently accelerates **pytest 9.0.2, 9.0.3, and 9.1.1 on CPython
3.10–3.14 with the GIL enabled**. It checks the original method's source fingerprint
before changing it and restores its owned patch at session cleanup. Other pytest versions,
modified methods, and missing or unloadable native extensions use stock parameter IDs.
Installation does not require changing an already-installed pytest version.
On older releases without pytest's Stash API, the plugin falls back quietly.

Only duplicate batches of at least 64 resolved, exact ASCII strings enter Rust.
Small batches, unique IDs, Unicode, string subclasses, hidden IDs, and strict-ID
errors use pytest behavior. Pytest still resolves custom IDs and calls user hooks
exactly once. Unexpected native computation errors propagate rather than rerunning
callbacks or hiding a bug.

On **pytest 9.1.1, CPython 3.10–3.14, Linux and macOS**, directory discovery can
reuse a successful report when at least 32 distinct `.py` files in one directory
are passed as plain arguments. This Python optimization avoids recreating every
sibling collector for each requested file. It needs no native extension and does
not change the arguments, import unrequested tests, or replace file collection.

Directory reuse requires verified stock directory methods and discovery/report
hooks. Custom discovery/report hooks, modified methods, selectors, duplicate paths, symlinks,
mixed directories, doctest-module mode, last-failed/failed-first modes, and debug
tracing use stock discovery. Changed hooks, plugins, or collection options stop
reuse; changed directory metadata invalidates the report. Windows currently uses
stock discovery. Plugins inspecting discarded collectors or pytest's private
collection-cache layout are outside this experimental compatibility boundary.

This uses a narrowly guarded private pytest method. The tested compatibility
boundary does not establish compatibility with every possible third-party plugin
or modification of pytest internals. Tests cover ordered IDs, phase outcomes,
coverage, asyncio, xdist, callbacks, errors, and repeated invocation.

On releases with the Stash API, the header reports activation or fallback.
The summary reports native ID batches, stock batches, and reused directory reports.
Counters are per process; xdist workers collect their own batches, so the
controller can report zero native calls.

## Development

Install uv and Rust, then:

```sh
uv sync --locked
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
The Linux Python 3.12 wheel lane also runs the complete suite and installed-wheel
smoke checks with pytest 9.0.2 and 9.0.3, and verifies stock fallback on pytest 8.4.2.
Normal wheel-installation checks preserve pytest 6.2.5 and 7.4.4 in separate
environments and compare fallback IDs and phase outcomes against stock pytest.
An independent benchmark job retains raw timings and CPU/memory observations.

## Performance evidence

```sh
uv run --no-sync python benchmarks/run.py --size 10000 --repeats 7
```

The benchmark compares stock pytest, a linear-time Python implementation, and the
Rust helper. It verifies exact ordered IDs and per-phase outcomes before timing,
then runs collection and full execution in fresh, rotating-order subprocesses.
Receipts include raw timings, source and native binary hashes, and native call counts.

Stock's duplicate-ID collision loop repeatedly rebuilds a set. Removing that
algorithmic cost is the main expected gain; Rust's separate contribution is
measured against the optimized Python helper, including conversion overhead.
Duplicate-heavy synthetic suites are the initial target. Ordinary suites can see
little benefit. Component results alone do not establish a whole-suite speedup.

```sh
uv run --no-sync python benchmarks/discovery.py --repeats 3
```

A first local paired trial over 384 synthetic sibling files reduced full-process
time from 14.00 s to 1.09 s (92.2%), with identical ordered tests and phase outcomes.
This is one file-heavy workload, not a forecast for ordinary suites or overall CI.
The CI benchmark repeats the comparison and requires at least 5% improvement.

The first local experiment reduced full-run time by 27–34% on 10,000 duplicate
IDs. Most of this gain is algorithmic: Rust improved the helper over optimized
Python, but did not demonstrate an additional whole-suite advantage. The unchanged
async-unzip suite passed all 89 tests with exact outcome parity; it exercised no
native batches, so it provides compatibility evidence only.

See [benchmarks/README.md](benchmarks/README.md) for methodology and receipts.
