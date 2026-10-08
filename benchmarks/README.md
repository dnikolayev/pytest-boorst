# Benchmark methodology

Build the extension in release mode, then run:

```sh
uv run --no-sync maturin develop --release --locked
uv run --no-sync python benchmarks/run.py --size 10000 --repeats 7
```

The adapter supports pytest 9.0.2, 9.0.3, and 9.1.1. Use a separate environment
for each version, install the built wheel without changing that version, and run
the same harness. Each receipt identifies its installed pytest version; the
initial observations below apply only to pytest 9.1.1.

Run the experiment while other builds and benchmarks are idle. The command creates
synthetic suites in a temporary directory and removes them when it finishes.

Three modes use the same interpreter, test inputs, and dependencies:

- Stock: installed package blocked with `-p no:boorst`.
- Python: the same adapter uses the optimized Python helper; the native module is
  replaced before configuration, so this mode does not pay native startup cost.
- Rust: the adapter uses the native release extension.

Before timing, the harness compares exact ordered node IDs, ordered setup/call/teardown
reports, and exit codes. It checks native call counters for duplicate workloads.
Receipt recording is disabled during timing. Each timed run starts a fresh process;
mode order rotates between repetitions. Collection-only and complete test execution
are measured separately.

The four scenarios are duplicate IDs, colliding numeric suffixes, unique IDs, and
small parametrizations. Component measurements include Python/Rust input and output
conversion. They exclude user callbacks equally across all three implementations.

Receipts record every timing sample, medians, versions, source digest, and loaded
native binary digest. A receipt applies only to the measured environment and inputs.
The full-run benefit over stock includes the algorithmic improvement; the Python
comparison identifies how much additional benefit Rust contributes.

Acceptance target: at least 10% less full-run time on the declared duplicate-heavy
workload, repeatable outside measurement noise, with no material control regression.
The Rust helper must also improve on optimized Python including conversion cost.
Public-project trials are compatibility controls when they do not exercise large
duplicate-ID batches.

## Peak memory and CPU controls

On macOS or Linux, record fresh-process peak RSS and CPU time separately:

```sh
uv run --no-sync python benchmarks/memory.py --scenario duplicate
uv run --no-sync python benchmarks/memory.py --scenario unique --repeats 5
```

These runs use the same generated tests and compare all three modes. The resource
recorder adds an identical observer to each mode. Small and unique workloads must
report zero native batches; duplicate workloads must report one. CPU time helps
investigate shared-host scheduling noise but does not replace end-to-end wall time.

The Python comparison's `native_calls` counter represents calls through the adapter
to its substituted Python helper. Only Rust-mode counters establish native execution.

## Initial alpha observations

[Local receipt](results/initial-alpha.json): release build, CPython 3.12.12,
pytest 9.1.1, macOS ARM64, 10,000 parameters, three rotating repetitions.
All four scenarios passed exact ordered ID, phase outcome, and exit-code parity.
Times below are full-run medians in seconds.

| Scenario | Stock | Optimized Python | Rust |
| --- | ---: | ---: | ---: |
| Duplicate IDs | 7.542 | 4.942 | 4.978 |
| Numeric suffix collisions | 5.798 | 4.115 | 4.242 |
| Unique IDs | 4.393 | 4.356 | 4.477 |
| Small batch (8 IDs) | 0.263 | 0.256 | 0.239 |

Duplicate collection was about four times faster than stock. Full-run time fell
34% for duplicate IDs and 27% for collisions. The Rust helper took 3.63 ms versus
7.04 ms in Python for duplicates, including conversion; collision helper times
were 3.11 ms versus 6.68 ms. Most gain comes from avoiding stock's repeated set
construction. The experiment does **not** demonstrate an extra whole-suite Rust
advantage over optimized Python. Unique and small batches made zero native calls.
Three repetitions on a shared host cannot establish universal control overhead.

[Public-project receipt](results/async-unzip.json): the unchanged async-unzip suite
at the recorded source commit produced 89 ordered test IDs and 267 passed phases
in every mode. Twenty receipts cover absent, disabled, enabled, blocked-plugin,
and uninstall controls. The installed wheel's files matched its archive exactly.
Enabled runs made zero native calls and four stock batches; this is compatibility
evidence only. The five-sample timing spread is recorded without a speedup claim.

GitHub CI repeats the synthetic experiment on a separate Linux runner, checks the
declared duplicate target and conversion-inclusive helper benefit, and uploads
raw timing and resource receipts. These gates apply to this workload and do not
authorize default-on activation or broader compatibility claims.

## Explicit sibling-file discovery

```sh
uv run --no-sync python benchmarks/discovery.py --repeats 3
```

This pytest 9.1.1 workload passes 384 separate sibling `.py` files to stock pytest
and enabled Boorst. Each fresh subprocess runs all tests, including a shared
yield fixture. Every timed run includes the same ordered-ID and phase observer;
bytecode writes are disabled equally. Mode order alternates between repetitions.
The receipt records timings, source hashes, parity, and directory-reuse counters.
`--package` checks the same workload with a Python package directory.

CI requires enabled full-run median time to be at least 5% below stock. This is
a Python directory-report optimization, separate from Rust parameter-ID work.
It still performs pytest's ordinary file import, collection, fixtures, and test
execution, and still scans cached report contents to match each requested file.
Directory arguments and execution-heavy workloads can see little benefit.

## Python 3.14 CI snapshot

The README's compact comparison uses the three-repeat Ubuntu 24.04 / CPython
3.14.8 / pytest 9.1.1 / Boorst 0.1.0a2
[CI run](https://github.com/dnikolayev/pytest-boorst/actions/runs/37696156274).
[ID receipt](results/alpha2-python314-ids-ci.json) and
[directory receipt](results/alpha2-python314-discovery-ci.json) retain every timing
sample, parity result, activation counter and source digest. The observed controls
are included in the README table; no general suite-speedup claim is made.

The earlier CPython 3.12.3 snapshot is retained in the
[ID receipt](results/alpha2-ids-ci.json) and
[directory receipt](results/alpha2-discovery-ci.json) from its
[CI run](https://github.com/dnikolayev/pytest-boorst/actions/runs/37692487737).
Different runners and interpreter versions prevent using these snapshots as a
controlled Python-version comparison.

## Multiple explicit directories

```sh
uv run --no-sync python benchmarks/discovery.py --directories 4 --repeats 3 --output benchmark-results-multiple-directories.json
```

The same full-run harness splits 384 files into four groups of 96 and interleaves
the arguments. Successful reports are retained separately for each exact
directory collector; per-directory metadata and the same session/option/hook
guards still apply. Selected parents that contain one another use stock discovery
to preserve pytest's fixture registration order. Groups below 32 files use stock discovery. CI requires at
least 5% full-run improvement for this workload as well as the single-directory
workload. Raw receipts report exact parity and the reuse count.
