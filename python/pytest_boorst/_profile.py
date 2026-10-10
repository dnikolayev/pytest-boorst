"""Optional timing observations; pytest retains collection and execution."""

from __future__ import annotations

import importlib
import sys
import sysconfig
import time
from collections import defaultdict

import pytest
from _pytest.python import Module, Package

PLUGIN_NAME = "boorst_profile"
WORKER_KEY = "boorst_profile"
PHASES = ("setup", "call", "teardown")
PHASE_INDEX = {phase: index for index, phase in enumerate(PHASES)}
BATCH_SIZE = 256


def _batch_function():
    if (
        pytest.__version__.split(".", 1)[0] not in {"7", "8", "9"}
        or sys.implementation.name != "cpython"
        or not (3, 10) <= sys.version_info[:2] <= (3, 14)
        or sysconfig.get_config_var("Py_GIL_DISABLED")
    ):
        return None, "unsupported runtime"
    try:
        native = importlib.import_module("pytest_boorst._native")
        function = native.sum_report_batch
    except (ImportError, OSError, AttributeError):
        return None, "native batch helper unavailable"
    if not callable(function):
        return None, "native batch helper unavailable"
    return function, ""


class Profiler:
    def __init__(self, config, *, batch_reporting=False):
        self.config = config
        self.started = None
        self.finished = None
        self.collection = 0.0
        self.execution = 0.0
        self.modules = defaultdict(float)
        self.reports = dict.fromkeys(PHASES, 0.0)
        self.workers = {}
        self.collect_stack = []
        self.pending_reports = []
        self.batch_function = None
        self.batch_state = None
        if batch_reporting:
            self.batch_function, reason = _batch_function()
            self.batch_state = {
                "status": "native" if self.batch_function else "fallback",
                "reason": reason,
                "native_batches": 0,
                "native_reports": 0,
            }

    def pytest_sessionstart(self, session):
        self.started = time.perf_counter()

    @pytest.hookimpl(hookwrapper=True)
    def pytest_collection(self, session):
        started = time.perf_counter()
        try:
            yield
        finally:
            self.collection += time.perf_counter() - started

    @pytest.hookimpl(hookwrapper=True)
    def pytest_make_collect_report(self, collector):
        started = time.perf_counter()
        frame = [0.0]
        self.collect_stack.append(frame)
        try:
            yield
        finally:
            elapsed = time.perf_counter() - started
            self.collect_stack.pop()
            if self.collect_stack:
                self.collect_stack[-1][0] += elapsed
            owner = collector
            while owner is not None:
                if isinstance(owner, Module) and not isinstance(owner, Package):
                    self.modules[owner.nodeid] += max(0.0, elapsed - frame[0])
                    break
                owner = owner.parent

    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtestloop(self, session):
        started = time.perf_counter()
        try:
            yield
        finally:
            self.execution += time.perf_counter() - started

    def pytest_runtest_logreport(self, report):
        when = report.when
        if when in self.reports:
            duration = report.duration
            if self.batch_function is not None:
                if type(when) is str and type(duration) is float:
                    self.pending_reports.append((PHASE_INDEX[when], duration))
                    if len(self.pending_reports) == BATCH_SIZE:
                        self._flush_reports()
                    return
                self._flush_reports()
                self._batch_fallback("custom report values")
            self.reports[when] += duration

    def _batch_fallback(self, reason):
        self.batch_function = None
        self.batch_state.update(status="fallback", reason=reason)

    def _flush_reports(self):
        pending, self.pending_reports = self.pending_reports, []
        if not pending:
            return
        try:
            initial = tuple(self.reports[phase] for phase in PHASES)
            if any(type(value) is not float for value in initial):
                raise ValueError("custom phase totals")
            totals = self.batch_function(initial, tuple(pending))
            if type(totals) is not tuple or len(totals) != len(PHASES):
                raise ValueError("invalid native totals")
            if any(type(value) is not float for value in totals):
                raise ValueError("invalid native totals")
        except BaseException as error:
            self._batch_fallback("native batch failed")
            for phase, duration in pending:
                self.reports[PHASES[phase]] += duration
            # Keep received reports accounted for before honoring interruption.
            if not isinstance(error, Exception):
                raise
        else:
            self.reports.update(zip(PHASES, totals, strict=True))
            self.batch_state["native_batches"] += 1
            self.batch_state["native_reports"] += len(pending)

    def pytest_sessionfinish(self, session, exitstatus):
        self._flush_reports()
        self.finished = time.perf_counter()
        if hasattr(self.config, "workeroutput"):
            self.config.workeroutput[WORKER_KEY] = self.snapshot()

    @pytest.hookimpl(optionalhook=True)
    def pytest_testnodedown(self, node, error):
        output = getattr(node, "workeroutput", {}).get(WORKER_KEY)
        if output is not None:
            self.workers[node.gateway.id] = output

    def snapshot(self):
        self._flush_reports()
        modules = dict(self.modules)
        for worker in self.workers.values():
            for name, duration in worker["modules"].items():
                modules[name] = modules.get(name, 0.0) + duration
        wall = (
            (self.finished or time.perf_counter()) - self.started
            if self.started is not None
            else 0.0
        )
        data = {
            "session_wall": wall,
            "collection_wall": self.collection,
            "test_loop_wall": self.execution,
            "worker_collection_sum": sum(
                worker["collection_wall"] for worker in self.workers.values()
            ),
            "workers": len(self.workers),
            "reported_phase_sum": dict(self.reports),
            "modules": modules,
        }
        if self.batch_state is not None:
            data["batch_reporting"] = dict(self.batch_state)
        return data

    def pytest_terminal_summary(self, terminalreporter):
        if hasattr(self.config, "workerinput"):
            return
        data = self.snapshot()
        terminalreporter.section("boorst profile")
        if self.batch_state is not None:
            state = self.batch_state
            detail = state["reason"] or f"{state['native_batches']} Rust batches"
            terminalreporter.write_line(
                f"Batch phase aggregation: {state['status']} ({detail})"
            )
            if self.workers:
                fallbacks = sum(
                    worker.get("batch_reporting", {}).get("status") != "native"
                    for worker in self.workers.values()
                )
                terminalreporter.write_line(
                    f"Worker batch aggregation: {len(self.workers) - fallbacks} "
                    f"native, {fallbacks} fallback"
                )
        rows = [
            ("Session wall (since sessionstart)", data["session_wall"]),
            ("Collection wall (this process)", data["collection_wall"]),
            ("Test loop wall (this process)", data["test_loop_wall"]),
        ]
        if data["workers"]:
            rows.append(
                ("Worker collection seconds (sum)", data["worker_collection_sum"])
            )
        rows.extend(
            (f"Reported {phase} seconds (sum)", duration)
            for phase, duration in data["reported_phase_sum"].items()
        )
        for name, duration in rows:
            terminalreporter.write_line(f"{name:<38} {duration:9.3f}")
        terminalreporter.write_line(
            "Phase sums overlap under xdist; setup/teardown include pytest hooks."
        )
        terminalreporter.write_line(
            "Startup imports precede these hooks. Measure them with: "
            "python -X importtime -m pytest --boorst-profile"
        )
        if data["modules"]:
            terminalreporter.write_line(
                "Top module collection seconds (sum across workers):"
            )
            for name, duration in sorted(
                data["modules"].items(), key=lambda row: (-row[1], row[0])
            )[:10]:
                terminalreporter.write_line(f"{duration:9.3f}  {name}")


def install(config, *, batch_reporting=False):
    observer = Profiler(config, batch_reporting=batch_reporting)
    config.pluginmanager.register(observer, PLUGIN_NAME)

    def restore():
        if config.pluginmanager.get_plugin(PLUGIN_NAME) is observer:
            config.pluginmanager.unregister(observer)

    config.add_cleanup(restore)
