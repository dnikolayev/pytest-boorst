# Contributing

Keep changes focused on measured pytest overhead while preserving observable
test behavior. Use uv for Python dependencies and Ruff for linting, import sorting,
and formatting. Keep Rust code formatted and checked with Cargo.

Use the development commands in the README. A change to an accelerated operation
needs differential coverage against stock pytest and a benchmark comparing the
stock implementation, an optimized Python implementation, and the native helper.
Confirm that native code was actually exercised and include control workloads.

Keep examples synthetic. Publish only sanitized, reproducible benchmark evidence;
keep project-specific source, configuration, paths, and results outside this repository.

Changes are reviewed through pull requests. GitHub CI verifies wheel installation,
compatibility tests, Rust checks, and source-distribution builds.
