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
Installation checks use normal dependency resolution over existing pytest versions;
keep the installed version unchanged and compare fallback behavior with stock pytest.

## Platform wheels

CI builds and tests these native wheels with CPython 3.12. The `abi3` wheels also
support newer GIL-enabled CPython versions; separate compatibility jobs cover
Python 3.10 through 3.14.

| System | Native architectures | Compatibility |
| --- | --- | --- |
| macOS | Intel x86-64, Apple ARM64 | Separate architecture wheels |
| Windows | x86-64, x86, ARM64 | MSVC wheels |
| Linux with glibc | x86-64, x86, ARM64 | manylinux2014 (glibc 2.17+) |
| Linux with musl | x86-64, x86, ARM64 | musllinux 1.2 (Alpine and similar) |

Every platform job installs its wheel, runs the compatibility suite, compares
native execution with stock pytest, and verifies `pytest --boorst`, the installed
module command and portable trial command.
Linux wheels are tested inside the matching pinned PyPA runtime, including musl.
ARM64 jobs use native ARM64 runners; x86 jobs run 32-bit Python on x86-64 hosts.
The universal Python wheel remains available as a fallback. This matrix describes
CI builds; released files are listed on each release page.

## Publishing

Bump the Python version in `pyproject.toml`, `uv.lock` and `scripts/try.py`, the Rust
version in `Cargo.toml` and `Cargo.lock`, and the pinned README commands and links together.
After the version change passes PR CI and lands on `main`, publish a GitHub release
with the exact `v<Python version>` tag. Stable and prerelease publications both
trigger `.github/workflows/publish.yml`.

The workflow checks the tag/version and main-branch ancestry, runs the complete CI
matrix on the release commit, and selects one tested wheel per platform plus the
universal wheel and source distribution. Publishing runs in a separate job with
OIDC permission and the `pypi` environment; it does not check out or execute project
code. GitHub release assets receive the same distributions and checksum manifest.

The one-time PyPI Trusted Publisher configuration must use project `pytest-boorst`,
owner `dnikolayev`, repository `pytest-boorst`, workflow `publish.yml`, and environment
`pypi`. Use a pending publisher when creating the project. No API token is needed.
If a release upload partially fails, inspect the uploaded files before retrying;
existing distributions are not silently skipped or overwritten.
