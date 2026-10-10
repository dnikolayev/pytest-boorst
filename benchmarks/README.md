# Benchmark methodology

Build the extension in release mode, then run:

```sh
uv run --no-sync maturin develop --release --locked
uv run --no-sync python benchmarks/run.py --size 10000 --repeats 7
```

The ID adapter supports verified implementations on pytest 7/8/9. Use a separate
environment for each version, install the built wheel without changing that version, and run
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
Prepared-suite trials are compatibility controls when they do not exercise large
duplicate-ID batches.

## Peak memory and CPU controls

On macOS or Linux, record fresh-process peak RSS and CPU time separately:

```sh
uv run --no-sync python benchmarks/memory.py --scenario duplicate
uv run --no-sync python benchmarks/memory.py --scenario unique --repeats 5
```

These runs use the same generated tests and compare all three modes. The resource
recorder adds an identical observer to each mode. Small and unique workloads must
report zero native ID batches; duplicate workloads must report one. CPU time helps
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
advantage over optimized Python. Unique and small batches made zero native ID calls.
Three repetitions on a shared host cannot establish universal control overhead.

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

## Static discovery

Run the bounded synthetic comparison with an installed wheel or the matching
source checkout on `PYTHONPATH`:

```sh
uv run --no-sync python benchmarks/static_discovery.py --output static-discovery-results.json
```

The script compares three alternating fresh-process pairs in serial mode. One
workload has 64 test-pattern files that each simulate import cost with a 15 ms
sleep and have no static test names, plus a retained parametrized test. A second
has 64 ordinary test files plus the same parametrized test, exposing the extra
parsing cost. Both modes use identical
source, plugin loading and environment, with bytecode writes disabled.

The receipt records raw times, medians, interpreter/pytest versions, measured
source hashes from modules actually loaded by the selected interpreter, actual
prefilter counts, and ordered-ID/phase-outcome parity. Changed source hashes across
samples invalidate the comparison.
These synthetic full-run comparisons illustrate this mode's tradeoff. They do not
establish a general speedup or that static discovery retains every real test.

Local CPython 3.14.7 / pytest 9.1.1 medians from five alternating pairs:

| Synthetic workload | Stock median | Static median | Change in wall time |
| --- | ---: | ---: | ---: |
| 64 empty modules with a simulated 15 ms import delay; 2 retained tests | 1.5069 s | 0.1474 s | 90.22% less |
| 64 ordinary modules; 66 tests | 0.1751 s | 0.1802 s | 2.89% more |

Both comparisons preserved exact ordered test IDs, phase outcomes and exit codes.
[Raw samples and measured source hashes](results/static-discovery-local.json)
retain the negative control as well as the targeted benefit.

The first workload skips all 64 empty modules; the control skips none. The delay
is artificial, and these short local samples do not establish performance on a
real suite. The receipt also retains an earlier shared-host comparison whose ordinary control
was 41.74% slower with substantial timing variability. The final comparison ran
without concurrent local checks or builds; short local timings remain noisy.
Static discovery can omit runtime-only tests; outcome parity in these synthetic
examples does not establish complete collection elsewhere.

## Assertion-location batches

The 0.1.0 assertion adapter batches generated locations at module boundaries on
pytest 9.1.1 and GIL-enabled CPython 3.14. Existing alpha ID/discovery
receipts predate this path and must keep their original versions and labels.

```sh
uv run --no-sync python benchmarks/assertions.py --repeats 3
```

This synthetic full-run comparison uses 32 modules with 4,096 assertions in 256
tests. It compares fresh processes with cold and warm rewritten-bytecode caches,
checks ordered IDs and phase outcomes separately from timing, and records native
batch counts. CI retains both controls alongside the existing benchmark receipts.

Compare the same source revision, interpreter, dependencies, pytest arguments and
bytecode-cache conditions in fresh stock/enabled processes. Run profiling separately
from timing. Check exact ordered IDs, setup/call/teardown outcomes, errors and exit
codes, plus assertion native-batch/fallback counters. Differential AST-location and
mutation checks establish the guarded operation's behavior; component timings alone
cannot establish a full-run or CI improvement.

[Local candidate samples](results/assertion-batches-local.json) record five pairs:
cold runs used 17.25% less time; warm runs used 13.74% more (31 ms).

Warm bytecode caches can avoid rewriting, and execution-heavy suites can spend
little time in this operation. Include those controls and retain slower or null
results. Native activation establishes eligible work, rather than a speed guarantee.
