"""Reuse stock directory reports for a narrow, session-local file plan."""

from __future__ import annotations

import hashlib
import inspect
from pathlib import Path

from _pytest.main import Dir, Session
from _pytest.python import Package

MIN_FILES = 32
_METHODS = (Session.collect, Session._collect_one_node, Dir.collect, Package.collect)
_METHOD_HASHES = (
    "059b4635fb9e56688b817887ea750616b10738cb6d29571f5b7721f401dc32d6",
    "41c0b9cb38ec89c9157f5df1c6d6af9b3986f45de538c02366c5887e63065225",
    "f314ca1c43aa632c04b5570c9b273419aa848c3dcf9275aa58d6091a8bd36848",
    "2dc823bfc8facccd8af8e0b2c61363202832efd0feee92d7ebacc8c70e9f1ff8",
)
_HOOKS = (
    "pytest_collect_directory",
    "pytest_collect_file",
    "pytest_pycollect_makemodule",
    "pytest_ignore_collect",
    "pytest_collectstart",
    "pytest_make_collect_report",
    "pytest_collectreport",
)
_HOOK_HASHES = {
    "_pytest.python.pytest_pycollect_makemodule": "942b7cdbbcf74ea989b5b373f8429c1b0570f26c31c3d084330e0c3f6fe83f15",
    "_pytest.main.Session.pytest_collectstart": "bcd2d6b3082c4a77f602a5453a9e551669491ef8a505ee9f8efab75710de15ac",
    "_pytest.main.Session.pytest_runtest_logreport": "d3003ff2a48eccec1ec963a0786c4619b1775d95e78dd081a31ccbbe0d5e7473",
    "_pytest.main.pytest_collect_directory": "681454321faaf96bc7fd65e5eceb0e55b4f4825e63e4bc7c9a4ec971f850d0a6",
    "_pytest.python.pytest_collect_directory": "7d337767579e97d39cf47b6abe040675a80a967bf39e27e1aa309c3fc4c7372a",
    "_pytest.python.pytest_collect_file": "8812fc7a1632f71df0f2aaea1e61b011e8293b41166135b9e8561088a7ff22f3",
    "_pytest.doctest.pytest_collect_file": "674f6e18c5e7e3596fbadd8c77f6f6e78f409fa931e48e3bc113b340ed0596ba",
    "_pytest.main.pytest_ignore_collect": "7329f1c31d9a480829163bd7d1a3083b3ffe434553edbc2c3ff7a3636b41cf08",
    "_pytest.runner.pytest_make_collect_report": "dd5756e160df76070b1cdbabf033ce39b5a5392320106eb42409b2bd82022d08",
    "_pytest.capture.CaptureManager.pytest_make_collect_report": "d2f4f10b82e12a841c41bd07310902cd727c044ac502611f99afd6b8f81de122",
    "_pytest.fixtures.FixtureManager.pytest_make_collect_report": "29629dfaf02a19320d591003af61b89743f472fb2e370dc23067ee71f0b786d3",
    "_pytest.cacheprovider.LFPlugin.pytest_collectreport": "52a840fb38a24163aa35e4adea902fe4e1206c19d4b8b51a2984b27c71129bc9",
    "_pytest.terminal.TerminalReporter.pytest_collectreport": "1e4d932bbc21fa9f4b68e25bdbd0cf5dce6ff8d6c508a19463083dc532e8e946",
}


def _hash(function):
    return hashlib.sha256(inspect.getsource(function).encode()).hexdigest()


def _hooks(config):
    return tuple(
        (
            impl.function,
            getattr(impl.function, "__code__", None),
            impl.wrapper,
            impl.hookwrapper,
        )
        for name in _HOOKS
        for impl in getattr(config.hook, name).get_hookimpls()
    )


def _options(config):
    return (
        tuple(config.args),
        tuple(config.getini("python_files")),
        tuple(config.option.ignore or ()),
        tuple(config.option.ignore_glob or ()),
        config.option.collect_in_virtualenv,
        getattr(config.option, "doctestmodules", False),
        tuple(getattr(config.option, "doctestglob", ()) or ()),
        tuple(
            getattr(config.option, name, False)
            for name in ("pyargs", "keepduplicates", "lf", "failedfirst", "debug")
        ),
    )


def install(session, state):
    config = session.config
    state.update(discovery_status="fallback", directory_reuses=0)
    # ponytail: one sibling directory only; expand after a measured workload needs it.
    if len(config.args) < MIN_FILES or any(
        getattr(config.option, name, False)
        for name in (
            "pyargs",
            "keepduplicates",
            "lf",
            "failedfirst",
            "doctestmodules",
            "debug",
        )
    ):
        return
    try:
        paths = [Path(arg).absolute() for arg in config.args]
        parent = paths[0].parent
        if len(set(paths)) != len(paths) or any(
            "::" in arg
            or path.suffix != ".py"
            or path.parent != parent
            or path.resolve() != path
            or not path.is_file()
            for arg, path in zip(config.args, paths, strict=True)
        ):
            return
        if (
            (Session.collect, Session._collect_one_node, Dir.collect, Package.collect)
            != _METHODS
            or "_collect_one_node" in session.__dict__
            or tuple(map(_hash, _METHODS)) != _METHOD_HASHES
        ):
            return
        hooks = _hooks(config)
        for function, _, _, _ in hooks:
            name = f"{function.__module__}.{function.__qualname__}"
            if hasattr(function, "__wrapped__") or _hash(function) != _HOOK_HASHES.get(
                name
            ):
                return
        options = _options(config)
        plugins = frozenset(config.pluginmanager.get_plugins())
        codes = tuple(function.__code__ for function in _METHODS)
    except (OSError, TypeError, AttributeError, ValueError):
        return
    original = session._collect_one_node
    cached = None
    cached_node = None
    cache_epoch = None
    validated_epoch = None
    signature = None

    def accelerated(node, handle_dupes=True):
        nonlocal cached, cached_node, cache_epoch, validated_epoch, signature
        if (
            state["discovery_status"] != "active"
            or Session._collect_one_node is not _METHODS[1]
        ):
            state["discovery_status"] = "fallback"
            restore()
            return session._collect_one_node(node, handle_dupes)
        if handle_dupes or type(node) not in (Dir, Package) or node.path != parent:
            return original(node, handle_dupes)
        if session._collection_cache is not validated_epoch:
            parts = session._initial_parts
            if len(parts) != len(paths) or any(
                part.path != path
                or part.parts
                or part.parametrization
                or part.module_name
                for part, path in zip(parts, paths, strict=True)
            ):
                state["discovery_status"] = "fallback"
            validated_epoch = session._collection_cache
        if (
            state["discovery_status"] != "active"
            or _hooks(config) != hooks
            or _options(config) != options
            or frozenset(config.pluginmanager.get_plugins()) != plugins
            or tuple(function.__code__ for function in _METHODS) != codes
            or (
                Session.collect,
                Session._collect_one_node,
                Dir.collect,
                Package.collect,
            )
            != _METHODS
            or "collect" in node.__dict__
        ):
            cached = None
            state["discovery_status"] = "fallback"
            restore()
            return session._collect_one_node(node, handle_dupes)
        try:
            stat = parent.stat()
            current = (stat.st_dev, stat.st_ino, stat.st_mtime_ns, stat.st_ctime_ns)
        except OSError:
            cached = None
            return original(node, handle_dupes)
        if (
            cached is not None
            and node is cached_node
            and session._collection_cache is cache_epoch
            and current == signature
        ):
            node.ihook.pytest_collectstart(collector=node)
            state["directory_reuses"] += 1
            # This is still a new file argument, not a duplicate argument.
            return cached, False
        report, duplicate = original(node, handle_dupes)
        cached = report if report.passed else None
        cached_node = node
        cache_epoch = session._collection_cache
        signature = current
        return report, duplicate

    def restore():
        if session.__dict__.get("_collect_one_node") is accelerated:
            del session._collect_one_node

    config.add_cleanup(restore)
    session._collect_one_node = accelerated
    state["discovery_status"] = "active"
