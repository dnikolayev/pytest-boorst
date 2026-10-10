"""Optional duration ordering within stock xdist scope groups."""

from __future__ import annotations

import ast
import hashlib
import inspect
import math
import sys
import sysconfig
from importlib.metadata import PackageNotFoundError, version
from statistics import median
from types import CodeType

import pytest

CACHE_KEY = "boorst/schedule-v1"
_SCOPE_SOURCE = "51f0d11f85b73c4a784587349dacc49692913b759c989cf7109287d792fe3013"
_PROVIDER_SOURCE = "4c5461d8afbb8712605dd45d1a80813660c5534a23eab7ddda3b1a5b959d4ca6"


def _valid_duration(value):
    if type(value) not in (float, int):
        return False
    try:
        return math.isfinite(value) and value >= 0
    except OverflowError:
        return False


def _history(raw):
    if not isinstance(raw, dict):
        return {}
    return {
        key: value
        for key, value in raw.items()
        if isinstance(key, str) and _valid_duration(value)
    }


def _verified_scope(base):
    from .plugin import _same_code

    try:
        source = inspect.getsource(base)
        if hashlib.sha256(source.encode()).hexdigest() != _SCOPE_SOURCE:
            return False
        source = "from __future__ import annotations\nimport pytest\n" + source
        tree = ast.parse(source)
        if "@pytest_ar" in base.schedule.__globals__:
            from _pytest.assertion.rewrite import rewrite_asserts

            rewrite_asserts(tree, source.encode())
        code = compile(
            tree,
            "<verified xdist source>",
            "exec",
            dont_inherit=True,
        )
        cls = next(item for item in code.co_consts if type(item) is CodeType)
        methods = {
            item.co_name: item
            for item in cls.co_consts
            if type(item) is CodeType and item.co_name != "__annotate__"
        }
        for name, expected in methods.items():
            actual = vars(base)[name]
            if isinstance(actual, property):
                actual = actual.fget
            if not inspect.isfunction(actual) or not _same_code(
                actual.__code__, expected
            ):
                return False
        return True
    except (
        OSError,
        TypeError,
        ValueError,
        KeyError,
        AttributeError,
        StopIteration,
        SyntaxError,
    ):
        return False


def _verified_provider(provider, base):
    from .plugin import _same_code

    try:
        function = provider.pytest_xdist_make_scheduler
        if not inspect.isfunction(function):
            return False
        source = inspect.getsource(function)
        if hashlib.sha256(source.encode()).hexdigest() != _PROVIDER_SOURCE:
            return False
        if function.__globals__.get("LoadScopeScheduling") is not base:
            return False
        code = compile(
            "from __future__ import annotations\nimport pytest\nclass DSession:\n"
            + source,
            "<verified xdist provider>",
            "exec",
            dont_inherit=True,
        )
        cls = next(item for item in code.co_consts if type(item) is CodeType)
        expected = next(
            item
            for item in cls.co_consts
            if type(item) is CodeType and item.co_name == function.__name__
        )
        return _same_code(function.__code__, expected)
    except (OSError, TypeError, ValueError, AttributeError, StopIteration, SyntaxError):
        return False


def _order_workqueue(workqueue, history):
    known = [
        history[nodeid]
        for unit in workqueue.values()
        for nodeid in unit
        if nodeid in history
    ]
    if not known:
        return False
    try:
        default = median(known)
        weights = {
            scope: sum(history.get(nodeid, default) for nodeid in unit)
            for scope, unit in workqueue.items()
        }
    except OverflowError:
        return False
    if not _valid_duration(default) or not all(map(_valid_duration, weights.values())):
        return False
    ordered = sorted(workqueue.items(), key=lambda item: -weights[item[0]])
    workqueue.clear()
    workqueue.update(ordered)
    return True


class Scheduler:
    def __init__(self, config):
        self.config = config
        self.base = None
        self.provider = None
        self.reason = "stock scheduling"
        self.active = False
        self.complete = True
        self.collection = None
        self.reports = {}
        self.history = {}

    @pytest.hookimpl(optionalhook=True)
    def pytest_xdist_make_scheduler(self, config, log):
        if self.base is None:
            return None
        if not _verified_provider(self.provider, self.base):
            self.reason = "scheduler provider changed; using stock scheduling"
            return None
        for impl in config.hook.pytest_xdist_make_scheduler.get_hookimpls():
            if impl.plugin is self:
                continue
            if (
                type(impl.plugin) is not self.provider
                or getattr(impl.function, "__func__", None)
                is not self.provider.pytest_xdist_make_scheduler
            ):
                self.reason = "another plugin controls scheduling"
                return None
        owner = self
        self.active = True
        self.reason = "learning durations; stock loadscope order"

        class DurationScheduling(self.base):
            ordered = False

            def _assign_work_unit(self, node):
                if not self.ordered:
                    if not _verified_scope(owner.base):
                        owner.reason = "scope scheduler changed; using stock order"
                        owner.active = False
                    elif _order_workqueue(self.workqueue, owner.history):
                        owner.reason = "ordering loadscope groups by cached durations"
                    self.ordered = True
                return super()._assign_work_unit(node)

        return DurationScheduling(config, log)

    @pytest.hookimpl(optionalhook=True)
    def pytest_xdist_node_collection_finished(self, node, ids):
        if not self.active:
            return
        if self.collection is None:
            self.collection = list(ids)
            self.complete &= len(set(ids)) == len(ids)
        elif ids != self.collection:
            self.complete = False

    @pytest.hookimpl(optionalhook=True)
    def pytest_testnodedown(self, node, error):
        if error:
            self.complete = False

    def pytest_runtest_logreport(self, report):
        if not self.active:
            return
        phases = self.reports.setdefault(report.nodeid, {})
        if report.when in phases or not _valid_duration(report.duration):
            self.complete = False
        phases[report.when] = (report.outcome, report.duration)

    def pytest_sessionfinish(self, session, exitstatus):
        if (
            not self.active
            or not self.complete
            or exitstatus != 0
            or not self.collection
        ):
            return
        if set(self.reports) != set(self.collection):
            return
        durations = {}
        for nodeid, phases in self.reports.items():
            expected = {"setup", "call", "teardown"}
            if phases.get("setup", (None,))[0] == "skipped":
                expected.remove("call")
            if set(phases) != expected:
                return
            try:
                total = sum(duration for _, duration in phases.values())
            except OverflowError:
                return
            if not _valid_duration(total):
                return
            durations[nodeid] = total
        try:
            self.config.cache.set(CACHE_KEY, durations)
        except (OSError, pytest.PytestCacheWarning):
            self.reason = (
                "could not save duration history; using existing cache if readable"
            )

    def pytest_terminal_summary(self, terminalreporter):
        terminalreporter.write_line(f"boorst schedule: {self.reason}")


def install(config):
    if hasattr(config, "workerinput") or not config.getoption(
        "boorst_schedule", default=False
    ):
        return None
    scheduler = Scheduler(config)
    if (
        pytest.__version__.split(".", 1)[0] not in {"7", "8", "9"}
        or sys.implementation.name != "cpython"
        or not (3, 10) <= sys.version_info[:2] <= (3, 14)
        or sysconfig.get_config_var("Py_GIL_DISABLED")
    ):
        scheduler.reason = (
            "unsupported interpreter or pytest version; using stock scheduling"
        )
    elif getattr(config, "cache", None) is None:
        scheduler.reason = "cache provider unavailable; using stock scheduling"
    elif not config.getoption("numprocesses", default=None):
        scheduler.reason = "parallel workers required; using stock scheduling"
    elif config.getoption("dist", default=None) != "loadscope":
        scheduler.reason = "requires --dist=loadscope; using stock scheduling"
    elif not config.getoption("loadscopereorder", default=True):
        scheduler.reason = "scope reordering disabled; using stock scheduling"
    else:
        try:
            if version("pytest-xdist") == "3.8.0":
                from xdist.dsession import DSession
                from xdist.scheduler.loadscope import LoadScopeScheduling

                if _verified_scope(LoadScopeScheduling):
                    scheduler.base = LoadScopeScheduling
                    scheduler.provider = DSession
                    scheduler.history = _history(config.cache.get(CACHE_KEY, {}))
        except (PackageNotFoundError, ImportError):
            pass
        if scheduler.base is None:
            scheduler.reason = "unverified xdist implementation; using stock scheduling"
    config.pluginmanager.register(scheduler, "boorst_schedule")

    def cleanup():
        if config.pluginmanager.get_plugin("boorst_schedule") is scheduler:
            config.pluginmanager.unregister(scheduler)

    config.add_cleanup(cleanup)
    return scheduler
