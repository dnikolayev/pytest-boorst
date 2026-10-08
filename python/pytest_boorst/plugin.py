"""Opt-in adapters for verified pytest implementations."""

from __future__ import annotations

import hashlib
import importlib
import inspect
import os
import sys
import sysconfig

import pytest

try:
    from _pytest.python import IdMaker
except ImportError:
    IdMaker = None

STATE_KEY = pytest.StashKey[dict]() if hasattr(pytest, "StashKey") else None
MIN_IDS = 64
_ORIGINAL = getattr(IdMaker, "make_unique_parameterset_ids", None)
_SOURCE_SHA256 = "6baee487481ac9da41d36fee0c8870f093aab91b9f507434d5c89620ddf588b8"


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
    parser.getgroup("boorst").addoption(
        "--boorst",
        action="store_true",
        default=False,
        help="Enable guarded Boorst acceleration for this pytest run.",
    )


def _enabled(config):
    return config.getoption("boorst", default=False) or (
        os.environ.get("PYTEST_BOORST") == "1"
    )


def pytest_configure(config):
    if STATE_KEY is None:
        return
    state = {
        "status": "disabled",
        "reason": "use --boorst or set PYTEST_BOORST=1 to enable the alpha",
        "native_calls": 0,
        "native_ids": 0,
        "fallback_calls": 0,
    }
    config.stash[STATE_KEY] = state
    if not _enabled(config):
        return
    state.update(status="fallback", reason="unsupported interpreter or pytest version")
    if (
        pytest.__version__ not in {"9.0.2", "9.0.3", "9.1.1"}
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
        source_hash = hashlib.sha256(inspect.getsource(_ORIGINAL).encode()).hexdigest()
    except (OSError, TypeError):
        return
    if source_hash != _SOURCE_SHA256:
        return
    state["reason"] = "native extension unavailable"
    try:
        native = importlib.import_module("pytest_boorst._native")
    except (ImportError, OSError):
        return
    unique_ids = native.unique_ids

    def accelerated(maker):
        if maker.config is not config:
            return _ORIGINAL(maker)
        # ponytail: small inputs use pytest; revisit the cutoff with real workloads.
        if len(maker.parametersets) < MIN_IDS:
            state["fallback_calls"] += 1
            return _ORIGINAL(maker)
        ids = list(maker._resolve_ids())
        if not all(type(value) is str and value.isascii() for value in ids):
            state["fallback_calls"] += 1
            return _ORIGINAL(_ResolvedIds(maker, ids))
        if len(ids) == len(set(ids)):
            state["fallback_calls"] += 1
            return ids
        if maker._strict_parametrization_ids_enabled():
            state["fallback_calls"] += 1
            return _ORIGINAL(_ResolvedIds(maker, ids, strict=True))
        result = unique_ids(ids)
        state["native_calls"] += 1
        state["native_ids"] += len(ids)
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
    state = config.stash[STATE_KEY]
    if state["status"] == "active":
        terminalreporter.write_line(
            f"boorst: {state['native_calls']} native ID batches "
            f"({state['native_ids']} IDs), {state['fallback_calls']} stock batches"
        )
    elif state["status"] == "fallback":
        terminalreporter.write_line(f"boorst: fallback ({state['reason']})")
    if state.get("directory_reuses"):
        terminalreporter.write_line(
            f"boorst: {state['directory_reuses']} directory reports reused"
        )
