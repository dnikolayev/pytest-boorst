"""Opt-in adapters for verified pytest implementations."""

from __future__ import annotations
import __future__

import hashlib
import importlib
import inspect
import os
import sys
import sysconfig
from types import CodeType, FunctionType

import pytest

try:
    from _pytest.python import IdMaker
except ImportError:
    IdMaker = None

STATE_KEY = pytest.StashKey[dict]() if hasattr(pytest, "StashKey") else None
MIN_IDS = 64
MAX_REPORTED_BATCHES = 10
_ORIGINAL = getattr(IdMaker, "make_unique_parameterset_ids", None)
_SOURCE_SHA256 = {
    "7.4.4": "26868322ec888e4833ac5a992ab1e31f09d9f0e55d94711e9b5976b586e6525b",
    "8.4.2": "24d0e59cba8e190379a1e64af4f88234a0859024971648d0c54826919946675c",
    "9.0.2": "6baee487481ac9da41d36fee0c8870f093aab91b9f507434d5c89620ddf588b8",
    "9.0.3": "6baee487481ac9da41d36fee0c8870f093aab91b9f507434d5c89620ddf588b8",
    "9.1.1": "6baee487481ac9da41d36fee0c8870f093aab91b9f507434d5c89620ddf588b8",
}


def _id_hashes(version):
    major = version.split(".", 1)[0]
    if major not in {"7", "8", "9"}:
        return set()
    if version in _SOURCE_SHA256:
        return {_SOURCE_SHA256[version]}
    return {
        digest
        for known, digest in _SOURCE_SHA256.items()
        if known.split(".", 1)[0] == major
    }


def _same_code(actual, expected):
    fields = (
        "co_argcount",
        "co_posonlyargcount",
        "co_kwonlyargcount",
        "co_nlocals",
        "co_stacksize",
        "co_flags",
        "co_code",
        "co_names",
        "co_varnames",
        "co_name",
        "co_freevars",
        "co_cellvars",
        "co_exceptiontable",
    )
    if any(
        getattr(actual, name, None) != getattr(expected, name, None) for name in fields
    ):
        return False

    def constant(value):
        kind = type(value)
        if kind is CodeType:
            return (
                kind,
                tuple(getattr(value, name, None) for name in fields),
                tuple(constant(item) for item in value.co_consts),
            )
        if kind is tuple:
            return kind, tuple(constant(item) for item in value)
        if kind is slice:
            return (
                kind,
                constant(value.start),
                constant(value.stop),
                constant(value.step),
            )
        if kind is frozenset:
            return kind, frozenset(constant(item) for item in value)
        if kind in (str, bytes, int, float, complex, bool, type(None), type(Ellipsis)):
            return kind, value
        raise ValueError("unsupported code constant")

    return tuple(map(constant, actual.co_consts)) == tuple(
        map(constant, expected.co_consts)
    )


def _verified_code(function, source):
    code = function.__code__
    flags = sum(
        getattr(__future__, name).compiler_flag
        for name in __future__.all_feature_names
        if code.co_flags & getattr(__future__, name).compiler_flag
    )
    # Preserve literal indentation, class context and module-call compilation.
    module = compile(
        "import textwrap\nclass IdMaker:\n" + source,
        "<verified pytest source>",
        "exec",
        flags=flags,
        dont_inherit=True,
        optimize=sys.flags.optimize,
    )
    cls = next(value for value in module.co_consts if type(value) is CodeType)
    compiled = next(
        value
        for value in cls.co_consts
        if type(value) is CodeType and value.co_name == function.__name__
    )
    return _same_code(code, compiled)


class _ResolvedIds:
    """Let the original method consume IDs without repeating user callbacks."""

    def __init__(self, maker, ids, strict=None):
        self.maker = maker
        self.ids = ids
        self.strict = strict

    def _resolve_ids(self):
        return iter(self.ids)

    def _strict_parametrization_ids_enabled(self):
        if self.strict is not None:
            return self.strict
        return self.maker._strict_parametrization_ids_enabled()

    def __getattr__(self, name):
        return getattr(self.maker, name)


def pytest_addoption(parser):
    group = parser.getgroup("boorst")
    group.addoption(
        "--boorst",
        action="store_true",
        default=False,
        help="Enable guarded Boorst acceleration for this pytest run.",
    )
    group.addoption(
        "--boorst-profile",
        action="store_true",
        default=False,
        help="Report collection and execution timings without enabling acceleration.",
    )
    group.addoption(
        "--boorst-schedule",
        action="store_true",
        default=False,
        help="Use cached durations to order xdist loadscope groups (opt-in).",
    )


def _enabled(config):
    return config.getoption("boorst", default=False) or (
        os.environ.get("PYTEST_BOORST") == "1"
    )


def pytest_configure(config):
    if STATE_KEY is None:
        return
    if config.getoption("boorst_schedule", default=False):
        from ._schedule import install as install_schedule

        install_schedule(config)
    if config.getoption("boorst_profile", default=False):
        from ._profile import install

        install(config)
    state = {
        "status": "disabled",
        "reason": "use --boorst or set PYTEST_BOORST=1 to enable the alpha",
        "native_calls": 0,
        "native_ids": 0,
        "fallback_calls": 0,
        "fallback_reasons": {},
        "largest_batches": [],
    }
    config.stash[STATE_KEY] = state
    if not _enabled(config):
        return
    state.update(status="fallback", reason="unsupported interpreter or pytest version")
    if (
        not _id_hashes(pytest.__version__)
        or sys.implementation.name != "cpython"
        or not (3, 10) <= sys.version_info[:2] <= (3, 14)
        or sysconfig.get_config_var("Py_GIL_DISABLED")
    ):
        return
    state["reason"] = "pytest ID method was changed or cannot be verified"
    if (
        IdMaker is None
        or _ORIGINAL is None
        or getattr(IdMaker, "make_unique_parameterset_ids", None) is not _ORIGINAL
        or not inspect.isfunction(_ORIGINAL)
        or hasattr(_ORIGINAL, "__wrapped__")
        or _ORIGINAL.__module__ != "_pytest.python"
        or _ORIGINAL.__qualname__ != "IdMaker.make_unique_parameterset_ids"
    ):
        return
    try:
        source = inspect.getsource(_ORIGINAL)
        source_hash = hashlib.sha256(source.encode()).hexdigest()
    except (OSError, TypeError):
        return
    if source_hash not in _id_hashes(pytest.__version__):
        return
    try:
        if not _verified_code(_ORIGINAL, source):
            return
    except (ValueError, SyntaxError, StopIteration, TypeError, RecursionError):
        return
    code = _ORIGINAL.__code__
    # A running stock frame retains this code even if an ID callback replaces it.
    resolved_original = FunctionType(
        code,
        _ORIGINAL.__globals__,
        _ORIGINAL.__name__,
        _ORIGINAL.__defaults__,
        _ORIGINAL.__closure__,
    )
    state["reason"] = "native extension unavailable"
    try:
        native = importlib.import_module("pytest_boorst._native")
    except (ImportError, OSError):
        return
    unique_ids = (
        native.unique_ids_pytest7
        if pytest.__version__.startswith("7.")
        else native.unique_ids
    )
    strict_ids = pytest.__version__.startswith("9.")
    verbose = config.getoption("verbose", default=0) > 0

    def record(maker, reason, *, stock=True):
        if stock:
            state["fallback_calls"] += 1
            reasons = state["fallback_reasons"]
            reasons[reason] = reasons.get(reason, 0) + 1
        if verbose:
            batches = state["largest_batches"]
            nodeid = maker.nodeid
            batches.append(
                {
                    "nodeid": nodeid if type(nodeid) is str else "<unknown nodeid>",
                    "size": len(maker.parametersets),
                    "reason": reason,
                }
            )
            batches.sort(key=lambda batch: -batch["size"])
            del batches[MAX_REPORTED_BATCHES:]

    def accelerated(maker):
        if maker.config is not config:
            return _ORIGINAL(maker)
        if _ORIGINAL.__code__ is not code:
            record(maker, "pytest method changed")
            restore()
            state.update(
                status="fallback", reason="pytest ID method changed during run"
            )
            return _ORIGINAL(maker)
        # ponytail: small inputs use pytest; revisit the cutoff with real workloads.
        if len(maker.parametersets) < MIN_IDS:
            record(maker, "below cutoff")
            return _ORIGINAL(maker)
        try:
            ids = list(maker._resolve_ids())
        except BaseException:
            record(maker, "ID resolution failed")
            raise
        if not all(type(value) is str and value.isascii() for value in ids):
            reason = (
                "non-ASCII"
                if all(type(value) is str for value in ids)
                else "unsupported ID type"
            )
            record(maker, reason)
            return resolved_original(_ResolvedIds(maker, ids))
        if len(ids) == len(set(ids)):
            record(maker, "already unique")
            return ids
        if strict_ids and maker._strict_parametrization_ids_enabled():
            record(maker, "strict IDs")
            return resolved_original(_ResolvedIds(maker, ids, strict=True))
        result = unique_ids(ids)
        state["native_calls"] += 1
        state["native_ids"] += len(ids)
        record(maker, "native", stock=False)
        return result

    def restore():
        if IdMaker.make_unique_parameterset_ids is accelerated:
            IdMaker.make_unique_parameterset_ids = _ORIGINAL

    config.add_cleanup(restore)
    IdMaker.make_unique_parameterset_ids = accelerated
    state.update(status="active", reason="ASCII parameter ID deduplication")


def pytest_report_header(config):
    if STATE_KEY is None:
        return
    state = config.stash[STATE_KEY]
    if state["status"] != "disabled":
        return f"boorst: {state['status']} ({state['reason']})"


@pytest.hookimpl(trylast=True)
def pytest_sessionstart(session):
    if (
        STATE_KEY is None
        or not _enabled(session.config)
        or pytest.__version__ != "9.1.1"
        or sys.platform == "win32"
        or os.environ.get("PYTEST_DEBUG")
        or sys.implementation.name != "cpython"
        or not (3, 10) <= sys.version_info[:2] <= (3, 14)
        or sysconfig.get_config_var("Py_GIL_DISABLED")
    ):
        return
    from ._discovery import install

    install(session, session.config.stash[STATE_KEY])


def pytest_terminal_summary(terminalreporter, config):
    if STATE_KEY is None:
        return
    state = _summary_state(config.stash[STATE_KEY])
    if state["status"] == "active":
        terminalreporter.write_line(
            f"boorst: {state['native_calls']} native ID batches "
            f"({state['native_ids']} IDs), {state['fallback_calls']} stock batches"
        )
    elif state["status"] == "fallback":
        terminalreporter.write_line(f"boorst: fallback ({state['reason']})")
    if state.get("worker_states"):
        terminalreporter.write_line(
            f"boorst: counters summed across {len(state['worker_states'])} workers"
        )
    if state["fallback_reasons"]:
        terminalreporter.write_line(
            "boorst: stock batch reasons: "
            + ", ".join(
                f"{reason}={count}"
                for reason, count in sorted(state["fallback_reasons"].items())
            )
        )
    if config.getoption("verbose", default=0) > 0:
        for batch in state["largest_batches"]:
            worker = f" [{batch['worker']}]" if "worker" in batch else ""
            terminalreporter.write_line(
                f"boorst: {batch['size']} IDs{worker}: {batch['nodeid']} "
                f"({batch['reason']})"
            )
    if state.get("directory_reuses"):
        terminalreporter.write_line(
            f"boorst: {state['directory_reuses']} directory reports reused"
        )


@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session):
    config = session.config
    if STATE_KEY is None or not hasattr(config, "workerinput"):
        return
    state = config.stash[STATE_KEY]
    if state["status"] == "disabled":
        return
    config.workeroutput["pytest_boorst"] = {
        name: state[name]
        for name in (
            "status",
            "reason",
            "native_calls",
            "native_ids",
            "fallback_calls",
            "fallback_reasons",
            "largest_batches",
        )
    }
    config.workeroutput["pytest_boorst"]["directory_reuses"] = state.get(
        "directory_reuses", 0
    )


@pytest.hookimpl(optionalhook=True)
def pytest_testnodedown(node, error):
    if STATE_KEY is None:
        return
    state = node.config.stash[STATE_KEY]
    worker = getattr(node, "workeroutput", {}).get("pytest_boorst")
    if state["status"] == "disabled" or worker is None:
        return
    state.setdefault("worker_states", {})[node.gateway.id] = worker


def _summary_state(state):
    workers = state.get("worker_states")
    if not workers:
        return state
    summary = dict(state)
    # Worker collection repeats the suite; report actual worker work separately.
    for name in ("native_calls", "native_ids", "fallback_calls", "directory_reuses"):
        summary[name] = sum(worker.get(name, 0) for worker in workers.values())
    reasons = summary["fallback_reasons"] = {}
    batches = summary["largest_batches"] = []
    for workerid, worker in workers.items():
        for reason, count in worker["fallback_reasons"].items():
            reasons[reason] = reasons.get(reason, 0) + count
        batches.extend(
            dict(batch, worker=workerid) for batch in worker["largest_batches"]
        )
    batches.sort(key=lambda batch: -batch["size"])
    del batches[MAX_REPORTED_BATCHES:]
    summary["status"] = (
        "active"
        if any(worker["status"] == "active" for worker in workers.values())
        else "fallback"
    )
    summary["reason"] = "; ".join(
        sorted({worker["reason"] for worker in workers.values()})
    )
    return summary
