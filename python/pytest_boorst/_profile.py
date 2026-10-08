"""Optional timing observations; pytest retains collection and execution."""

from __future__ import annotations

import time
from collections import defaultdict

import pytest
from _pytest.python import Module, Package

PLUGIN_NAME = "boorst_profile"
WORKER_KEY = "boorst_profile"


class Profiler:
    def __init__(self, config):
        self.config = config
        self.started = None
        self.finished = None
        self.collection = 0.0
        self.execution = 0.0
        self.modules = defaultdict(float)
        self.reports = dict.fromkeys(("setup", "call", "teardown"), 0.0)
        self.workers = {}
        self.collect_stack = []

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
        if report.when in self.reports:
            self.reports[report.when] += report.duration

    def pytest_sessionfinish(self, session, exitstatus):
        self.finished = time.perf_counter()
        if hasattr(self.config, "workeroutput"):
            self.config.workeroutput[WORKER_KEY] = self.snapshot()

    @pytest.hookimpl(optionalhook=True)
    def pytest_testnodedown(self, node, error):
        output = getattr(node, "workeroutput", {}).get(WORKER_KEY)
        if output is not None:
            self.workers[node.gateway.id] = output

    def snapshot(self):
        modules = dict(self.modules)
        for worker in self.workers.values():
            for name, duration in worker["modules"].items():
                modules[name] = modules.get(name, 0.0) + duration
        wall = (
            (self.finished or time.perf_counter()) - self.started
            if self.started is not None
            else 0.0
        )
        return {
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

    def pytest_terminal_summary(self, terminalreporter):
        if hasattr(self.config, "workerinput"):
            return
        data = self.snapshot()
        terminalreporter.section("boorst profile")
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


def install(config):
    observer = Profiler(config)
    config.pluginmanager.register(observer, PLUGIN_NAME)

    def restore():
        if config.pluginmanager.get_plugin(PLUGIN_NAME) is observer:
            config.pluginmanager.unregister(observer)

    config.add_cleanup(restore)
