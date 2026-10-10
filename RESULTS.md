# Evidence and optimization decisions

Boorst currently targets duplicate ASCII parameter-ID bookkeeping and a narrow
explicit-file directory-discovery plan. Enabling it is not evidence of a speedup.
See [README measurements](README.md#performance-evidence) for three-run full-pytest
synthetic results. These results do not predict application CI duration.

## Proposal review

| Proposal | Decision and evidence |
| --- | --- |
| Python-first package with a native extra | Deferred. The universal wheel already installs without Rust and retains Python directory reuse. An extra cannot select another wheel of the same distribution; splitting the native distribution needs installation and full-run evidence. |
| Linear IDs and directory reuse upstream | Algorithms are relevant. The ID helper already avoids rebuilding the occupied-ID set per collision. Broader directory changes must preserve collector identity and fixture visibility. No upstream change is included. |
| Replace implementation fingerprints with sample probes | Rejected. A few examples cannot establish arbitrary callback, hidden-ID, strict-ID, or large-batch equivalence. Source verification is retained and runtime code is checked too. Unchanged recognized implementations within pytest 7/8/9 can activate across patch releases. |
| Explain or retune the 64-ID / 32-file cutoffs | Explained as conservative eligibility bounds. Sparse and dense collisions have different costs; no universal crossover or new cutoff is claimed. |
| Attribute stock fallbacks and show largest batches | Implemented. Reasons are counted without repeating ID callbacks; `-v` reports a bounded list of the 10 largest observed batches. Unsupported activation stays unpatched. |
| Aggregate xdist counters | Implemented. Worker snapshots replace prior snapshots, and totals exclude controller counters. Counts represent actual repeated worker collection. Missing output from crashed workers cannot be counted. |
| Check discovery guards once per epoch | Rejected. A plugin or collector method can change within the same collection epoch. Live checks preserve stock fallback for those changes. |
| Enable Windows directory reuse | Deferred pending parity validation. Windows native-ID wheels remain supported; there is no established Windows-specific discovery defect. |
| Borrow Rust keys and reduce allocations | Deferred. Borrowing immutable input keys can reduce allocations, but changes must preserve the evolving occupied-ID set. No additional whole-run gain of at least 5% is demonstrated. |
| Add phase and module profiling | Implemented as `--boorst-profile`. Reports collection, test loop, setup/call/teardown sums, and the 10 largest module collection totals. Reported wall times cover observed hook spans, and module totals are exclusive collect-report work. Outer plugin wrappers may add work outside those spans. Startup imports require Python's separate import-time tracing. |
| Public-project corpus and regression evidence | A prepared-checkout harness is included. It alternates three stock/enabled collection pairs and verifies exact ordered IDs, collection errors and exit status. Public controls and unmeasured candidates are listed below. Existing full-run synthetic CI gates remain. There is no ten-project zero-regression guarantee. |
| Collect once / partition files under xdist | Deferred. Stock xdist relies on matching worker inventories and numeric item indices. Partitioning would require a scheduler and change collection-hook inputs, rather than being a transparent adapter. |
| Rewrite `--lf` to failing files | Rejected. Stock already skips unrelated imports in supported cases; stale cached node IDs can make unconditional file narrowing select a different set of tests. |
| Lazy-load third-party plugins by option use | Rejected as a default. Plugins may supply autouse fixtures or hooks without any command-line flag. Option use cannot establish that a plugin is unnecessary. |

The callback-mutation regressions cover both native ASCII and stock Unicode
paths: the current batch preserves the code a stock frame entered, while the
next batch observes the replacement and restores stock dispatch. Worker reporting,
errors, repeated invocation, and profiler cleanup have focused compatibility
coverage. GitHub CI supplies the full interpreter/platform validation gate.

## Public collection controls

Measurements below are collection-only and include interpreter startup and the
same receipt observer. They do not execute tests or establish fixture, runtime,
or end-to-end CI savings. Timed runs exclude the optional profiler; its observation
is collected separately. Bytecode writes are disabled in both modes and pytest's
cache is redirected outside each checkout. Three samples do not establish
statistical non-regression.

Measured on macOS ARM64 / CPython 3.14.7 with candidate Python adapters and the
unchanged alpha8 native helper. Both source checkouts remained clean.

| Public source revision | Pytest | Items | Stock median | Enabled median | Native batches / directory reuses |
| --- | --- | ---: | ---: | ---: | ---: |
| [httpx b5addb6](https://github.com/encode/httpx/tree/b5addb64f0161ff6bfe94c124ef76f6a1fba5254) | 8.4.1 | 1,418 | 2.147 s | 2.249 s | 0 / 0 |
| [attrs 644b4e1](https://github.com/python-attrs/attrs/tree/644b4e165bfbeee7e127de6fcbda08b64014316f) | 9.1.1 | 1,413 | 1.904 s | 1.635 s | 0 / 0 |

Exact ordered-ID, collection-error and exit-code parity passed in all timed runs
and the separate profile runs. Httpx observed 157 below-cutoff batches and one
already-unique batch; attrs observed 206 below-cutoff batches. Neither exercised
an acceleration path. The faster attrs median therefore does **not** establish a
Boorst speedup, and the slower httpx median is retained without a non-regression
claim. [Sanitized samples and hashes](benchmarks/results/alpha9-public-collection-local.json)
bind the candidate sources, native helper, harness and public project revisions.


The following public repositories were inventoried as additional corpus
candidates. They were not measured in this bounded screen; no timing or parity
claim is made for them.

| Repository | Status |
| --- | --- |
| [Rich](https://github.com/Textualize/rich) | Source download timed out; unmeasured. |
| [Hypothesis](https://github.com/HypothesisWorks/hypothesis) | Unmeasured. |
| [Pydantic](https://github.com/pydantic/pydantic) | Unmeasured. |
| [Black](https://github.com/psf/black) | Unmeasured. |
| [NumPy](https://github.com/numpy/numpy) | Unmeasured. |
| [pandas](https://github.com/pandas-dev/pandas) | Unmeasured. |
| [SQLAlchemy](https://github.com/sqlalchemy/sqlalchemy) | Unmeasured. |
| [Home Assistant](https://github.com/home-assistant/core) | Unmeasured. |

## Non-daemon acceleration experiments

Three ideas from the [rpytest architecture](https://github.com/neul-labs/rpytest/tree/db91fdde90f8b8e9e70420168b52ec872a61248c)
were tested as isolated prototypes. **None passed the final 5% full-run
improvement gate.** The preliminary 10.72%
scheduling result was excluded from acceptance because the guarded five-pair
comparison did not reproduce it. These measurements do not establish speedups
available with `--boorst`. Duration ordering and bounded phase aggregation are now
available separately as `--boorst-schedule` and `--boorst-batch-reporting`;
the original measurements remain unchanged.
The linked JSON retains the original prototype decision at measurement time.

All full runs used the same [attrs revision](https://github.com/python-attrs/attrs/tree/644b4e165bfbeee7e127de6fcbda08b64014316f),
macOS ARM64, CPython 3.14.7 and pytest 9.1.1. Timings include fresh interpreter
startup. Runs used a fixed Hypothesis seed and isolated caches; comparisons were
run sequentially. Positive improvement means a lower candidate median.

| Experiment | Baseline | Candidate | Improvement | Decision |
| --- | ---: | ---: | ---: | --- |
| Rust batch `-k 'not pickle'` matching | 7.067 s | 7.208 s | -1.99% | Reject: matching itself was only 0.11% of baseline time. |
| Rust batch `-m 'not slow'` matching | 7.231 s | 7.480 s | -3.44% | Reject: matching itself was only 0.04% of baseline time. |
| Rust batched phase totals | 7.223 s | 7.177 s | +0.63% | Prototype only; bounded implementation is a separate experimental opt-in below. |
| Cached duration ordering of xdist scope groups | 4.098 s | 4.073 s | +0.61% | Experimental opt-in only; five pairs did not reproduce the preliminary gain. |

Filtering used two runs per mode and selector. The keyword case selected 1,302
tests; the marker case selected all 1,413. All measured selected IDs, deselection
batches, phase outcomes and exit codes matched. An additional 84,588 expression
comparisons and 60 fresh-process pairs covered pytest 7.4.4, 8.4.1 and 9.1.1.
These checks do not establish compatibility with arbitrary plugins or custom
items: those production guards were incomplete. Stock matching took about 8 ms
for keywords and 3 ms for markers. Eliminating it entirely would still fall far
short of the full-run target on this corpus. Two samples cannot reliably attribute
the observed whole-process slowdowns to the matching implementation.

Phase aggregation kept pytest's regular reporting hooks and compared two Python
runs around one batched Rust run. All 1,413 test IDs and 4,235 phase records
matched, including outcomes and xfail status. A separate 300,000-record component
test, with five trials per variant, took 46 ms in Python, 49 ms with one Rust call
per record and 60 ms with Rust batching. Existing Boorst aggregation already uses
simple Python additions; allocating and converting a batch adds work.

Scheduling used four workers with xdist 3.8.0 and preserved `loadscope` grouping,
worker inventories and within-group ordering. It intentionally changed group
execution order, so it uses a separate opt-in. A preliminary three-pair
screen suggested 10.72%, but five alternating pairs with the guarded installed
wheel measured only 0.61%. Every candidate run confirmed activation; all runs
matched ordered collections and sorted node/phase/outcome/xfail records, with
successful exits. The learning run took another 4.490 s and is excluded from the
comparison. Duration history was frozen for the comparison; the receipt retains
its hash, not its values or per-worker timing. This Python scheduling policy did
not demonstrate a qualifying gain, and it is not a Rust acceleration claim.

[Samples, parity hashes and prototype identities](benchmarks/results/rpytest-ideas-local.json)
retain the preliminary result alongside the longer comparison. The summary is
evidence for these local decisions, not a standalone reproduction package or a
prediction for another project's CI. Native AST-only collection and cross-run
fixture reuse remain outside the transparent-plugin scope: they would need to
preserve dynamic collectors, hooks, fixture visibility and teardown behavior.

## Bounded reporting implementation

`--boorst-batch-reporting` is an explicit experimental profiler option. Its bounded
256-record buffer replaces the unbounded feasibility prototype measured above.
It retains pytest's normal reporting and uses Python when the native helper is
unavailable or cannot handle the values.

Three rotating trials on macOS ARM64, CPython 3.14.7 and pytest 9.1.1 fed 300,000
prebuilt synthetic report objects through the profiler and its final snapshot:

| Aggregation implementation | Median |
| --- | ---: |
| Existing direct Python accumulation | 39.698 ms |
| Bounded batching with an equivalent Python helper | 60.447 ms |
| Bounded batching with the Rust helper | 58.863 ms |

All totals matched exactly. The Rust variant processed 300,000 records in 1,172
batches. The Python batching comparison substitutes an equivalent Python helper
behind the same dispatcher; its counters count helper calls, not Rust calls.
Rust batching was slower than existing direct Python accumulation in this test.
This component result does not establish an end-to-end benefit.
[Samples and source identities](benchmarks/results/batched-reporting-component.json)
record this comparison; the earlier full-run result belongs to the prototype.

A combined installed-wheel check on the attrs revision above used four xdist
workers with `loadscope`. Stock profiling, first-run learning and warm duration
ordering collected the same 1,413 items and produced identical outcomes for all
4,235 phase reports. Both enabled runs confirmed native aggregation of every
report, with totals matching an independent observer. This was a compatibility
check, not a speed measurement. A universal-wheel smoke check also confirmed
Python reporting fallback and learning followed by warm duration ordering.

## Reproduce collection controls

Prepare the project's own test dependencies in an isolated environment and keep
its pytest version and configuration. From a Boorst checkout, pass that environment's
Python and store the raw receipt outside the project checkout:

```sh
python benchmarks/corpus.py path/to/public-project --python path/to/environment/python --output path/to/private-receipt.json -- tests/
```

Receipts contain commands, dependency versions, source commit and dirty status,
raw timings, Boorst counters, ordered IDs and hashes. They can include local paths
and exception text; review and sanitize a summary before sharing it. A failed
collection is retained explicitly and never presented as a successful benchmark.
