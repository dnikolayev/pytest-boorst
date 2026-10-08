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
