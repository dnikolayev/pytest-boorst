"""Experimental source prefilter; retained modules use normal pytest collection."""

from __future__ import annotations

import ast
import fnmatch
import sys
import tokenize

import pytest

NOTICE = (
    "boorst static discovery (experimental): runtime-generated, imported or "
    "plugin-defined tests may be omitted; retained tests run normally"
)


def _matches(name, patterns):
    return any(
        name.startswith(pattern) or fnmatch.fnmatchcase(name, pattern)
        for pattern in patterns
    )


class StaticDiscovery:
    def __init__(self, config):
        self.config = config
        self.counts = dict(examined=0, candidates=0, skipped=0, fallback=0)

    def pytest_sessionstart(self):
        terminal = self.config.pluginmanager.get_plugin("terminalreporter")
        if terminal is None:
            print(NOTICE, file=sys.stderr)
        else:
            terminal.write_line(NOTICE, yellow=True)

    @pytest.hookimpl(trylast=True)
    def pytest_ignore_collect(self, collection_path, config):
        if config.getoption("doctestmodules", default=False):
            return None
        path = collection_path
        if path.suffix != ".py" or path.name in {"__init__.py", "conftest.py"}:
            return None
        if not any(
            fnmatch.fnmatch(path.name, pattern) or fnmatch.fnmatch(str(path), pattern)
            for pattern in config.getini("python_files")
        ):
            return None
        if not path.is_file() or path.is_symlink():
            return None
        self.counts["examined"] += 1
        try:
            with tokenize.open(path) as source:
                tree = ast.parse(source.read(), filename=str(path))
        except (OSError, SyntaxError, UnicodeError, ValueError, RecursionError):
            self.counts["fallback"] += 1
            return None
        functions = config.getini("python_functions")
        classes = config.getini("python_classes")
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if _matches(node.name, functions):
                    self.counts["candidates"] += 1
                    return None
            elif isinstance(node, ast.ClassDef):
                if _matches(node.name, classes):
                    self.counts["candidates"] += 1
                    return None
        self.counts["skipped"] += 1
        return True

    def pytest_terminal_summary(self, terminalreporter):
        counts = self.counts
        terminalreporter.write_line(
            "boorst static discovery: "
            f"{counts['skipped']} files skipped, "
            f"{counts['candidates']} candidate files retained, "
            f"{counts['fallback']} files retained after source errors "
            f"({counts['examined']} examined); incomplete collection is possible"
        )


def install(config):
    if pytest.__version__.split(".", 1)[0] not in {"7", "8", "9"}:
        raise pytest.UsageError("--boorst-static-discovery requires pytest 7, 8 or 9")
    if (
        config.getoption("numprocesses", default=None)
        or config.getoption("tx", default=None)
        or config.getoption("dist", default="no") != "no"
        or hasattr(config, "workerinput")
    ):
        raise pytest.UsageError(
            "--boorst-static-discovery currently requires serial pytest"
        )
    config.pluginmanager.register(StaticDiscovery(config), "boorst_static_discovery")
