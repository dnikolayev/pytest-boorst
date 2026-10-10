"""Guarded batching of locations in freshly parsed pytest assertion trees."""

import ast
import builtins
import gc
import hashlib
import importlib
import inspect
import itertools
import sys
import textwrap
import threading
from collections import defaultdict
from types import (
    BuiltinFunctionType,
    CodeType,
    FunctionType,
    GetSetDescriptorType,
    MethodDescriptorType,
    WrapperDescriptorType,
)

import _pytest.config as config_module
import pytest
from _pytest.assertion import rewrite
from _pytest.config import Config
from _pytest.config.argparsing import Parser

from . import _assertion_fingerprints as fingerprints
from ._assertion_schema import MISSING, SPECIALS, schemas
from .plugin import _same_code


def make_plan(native):
    rows, assert_type, field_maps = schemas()
    return native.location_plan(
        rows,
        (
            str,
            bytes,
            int,
            float,
            complex,
            bool,
            tuple,
            frozenset,
            type(None),
            type(Ellipsis),
        ),
        assert_type,
        field_maps,
    )


def _child_code(code, name):
    return next(
        value
        for value in code.co_consts
        if type(value) is CodeType and value.co_name == name
    )


def _compiled_module(module, digest):
    source = inspect.getsource(module)
    if hashlib.sha256(source.encode()).hexdigest() != digest:
        raise ValueError("unrecognized assertion implementation")
    return source, compile(
        source,
        "<verified assertion source>",
        "exec",
        dont_inherit=True,
        optimize=sys.flags.optimize,
    )


def _plain_builtin(value, name):
    return (
        type(value) is BuiltinFunctionType
        and value.__module__ == "builtins"
        and value.__name__ == name
    ) or (
        type(value) is type
        and value.__module__ == "builtins"
        and value.__name__ == name
    )


def _native_counter(value):
    if (
        type(value) is not type
        or value.__module__ != "itertools"
        or value.__name__ != "count"
    ):
        return False
    next_method = vars(value).get("__next__")
    return (
        type(next_method) is WrapperDescriptorType
        and next_method.__objclass__ is value
        and next_method.__name__ == "__next__"
    )


def _native_defaultdict(value):
    if (
        type(value) is not type
        or value.__module__ != "collections"
        or value.__name__ != "defaultdict"
    ):
        return False
    missing = vars(value).get("__missing__")
    return (
        type(missing) is MethodDescriptorType
        and missing.__objclass__ is value
        and missing.__name__ == "__missing__"
    )


def _observed_runtime():
    return (
        bool(sys.gettrace())
        or bool(sys.getprofile())
        or bool(gc.callbacks)
        or any(sys.monitoring.get_tool(tool) is not None for tool in range(6))
    )


def _plain_defaults(actual, expected):
    if actual is expected:
        return True
    if type(actual) is not type(expected) or type(actual) not in (tuple, dict):
        return False
    if type(actual) is dict:
        if (
            any(type(key) is not str for key in actual)
            or actual.keys() != expected.keys()
        ):
            return False
        pairs = ((actual[key], expected[key]) for key in expected)
    else:
        if len(actual) != len(expected):
            return False
        pairs = zip(actual, expected, strict=True)
    return all(
        type(value) is type(pristine)
        and type(value) in (str, int, bool, type(None))
        and value == pristine
        for value, pristine in pairs
    )


def _function_guard(function, expected_code, defaults=None, kwdefaults=None):
    if (
        type(function) is not FunctionType
        or hasattr(function, "__wrapped__")
        or not _same_code(function.__code__, expected_code)
        or not _plain_defaults(function.__defaults__, defaults)
        or not _plain_defaults(function.__kwdefaults__, kwdefaults)
    ):
        raise ValueError("modified assertion function")
    if function.__closure__:
        if (
            function.__code__.co_freevars != ("__class__",)
            or function.__closure__[0].cell_contents is not rewrite.AssertionRewriter
        ):
            raise ValueError("modified assertion closure")
    globals_checks = []
    for name in function.__code__.co_names:
        namespace = function.__globals__
        builtin_namespace = function.__builtins__
        if name in vars(builtins) and not name.startswith("__"):
            value = vars(builtins)[name]
            if not _plain_builtin(value, name):
                raise ValueError("modified assertion builtin")
            if (
                namespace.get(name, value) is not value
                or builtin_namespace.get(name) is not value
            ):
                raise ValueError("shadowed assertion builtin")
            globals_checks.append((builtin_namespace, name, True, value))
        globals_checks.append((namespace, name, name in namespace, namespace.get(name)))
    return (
        function,
        function.__code__,
        function.__defaults__,
        dict(function.__kwdefaults__) if function.__kwdefaults__ else None,
        function.__globals__,
        function.__builtins__,
        tuple(globals_checks),
    )


def _unchanged_function(check):
    (
        function,
        code,
        defaults,
        kwdefaults,
        namespace,
        builtin_namespace,
        globals_checks,
    ) = check
    if (
        function.__code__ is not code
        or function.__defaults__ is not defaults
        or not _plain_defaults(function.__kwdefaults__, kwdefaults)
        or function.__globals__ is not namespace
        or function.__builtins__ is not builtin_namespace
    ):
        return False
    return all(
        (name in owner) == present and owner.get(name) is value
        for owner, name, present, value in globals_checks
    )


def _operator_map(value, expected):
    if type(value) is not dict or len(value) != len(expected):
        return False
    return all(
        type(symbol) is str and key is vars(ast).get(name) and symbol == expected_symbol
        for (key, symbol), (name, expected_symbol) in zip(
            value.items(), expected, strict=True
        )
    )


def _class_guard(cls, keys):
    if type(cls) is not type or tuple(vars(cls)) != keys:
        raise ValueError("modified assertion class")
    return cls, cls.__mro__, tuple(vars(cls).items())


def _unchanged_class(check):
    cls, mro, items = check
    return (
        cls.__mro__ is mro
        and len(vars(cls)) == len(items)
        and all(vars(cls).get(name, MISSING) is value for name, value in items)
    )


def _lookup_checks(cls, fields):
    if type(cls) is not type or cls.__bases__ != (object,):
        raise ValueError("modified config inheritance")
    checks = []
    for owner in cls.__mro__:
        own = vars(owner)
        for key in (
            "__getattribute__",
            "__getattr__",
            "__dict__",
            "__class__",
        ) + fields:
            value = own.get(key, MISSING)
            if value is not MISSING:
                descriptor_type = (
                    WrapperDescriptorType
                    if key == "__getattribute__"
                    else GetSetDescriptorType
                )
                if (
                    key not in ("__getattribute__", "__dict__", "__class__")
                    or type(value) is not descriptor_type
                    or value.__objclass__ is not owner
                    or value.__name__ != key
                ):
                    raise ValueError("modified config lookup")
            checks.append((own, key, value))
    return checks


def _cached_config(config):
    if config is None:
        return True
    if type(config) is not Config:
        return False
    contents = vars(config)
    if "getini" in contents:
        return False
    cache, parser = contents.get("_inicache"), contents.get("_parser")
    if (
        type(cache) is not dict
        or any(type(key) is not str for key in cache)
        or type(parser) is not Parser
    ):
        return False
    aliases = vars(parser).get("_ini_aliases")
    if type(aliases) is not dict or any(
        type(key) is not str or type(value) is not str for key, value in aliases.items()
    ):
        return False
    name = "enable_assertion_pass_hook"
    return aliases.get(name, name) == name and cache.get(name) is False


class Controller:
    def __init__(self, state=None):
        self.active = False
        self.reason = "unsupported assertion runtime"
        self.original = self.replacement = None
        self.counts = dict(
            attempted=0, accepted=0, guard_fallback=0, native_fallback=0, assertions=0
        )
        self.state = state

    def stats(self):
        return dict(active=self.active, reason=self.reason, **self.counts)

    def _report(self):
        if self.state is not None:
            self.state.update(
                status="active" if self.active else "fallback",
                reason=self.reason,
                native_batches=self.counts["accepted"],
                assertions=self.counts["assertions"],
                fallback_batches=self.counts["guard_fallback"]
                + self.counts["native_fallback"],
            )

    def restore(self):
        if (
            self.replacement is not None
            and vars(rewrite).get("_rewrite_test") is self.replacement
        ):
            rewrite._rewrite_test = self.original
        self.active = False


def install_native(native, config=None, *, state=None):
    controller = Controller(state)
    if (
        sys.implementation.name != "cpython"
        or sys.version_info[:2] != (3, 14)
        or pytest.__version__ != "9.1.1"
        or not sys._is_gil_enabled()
        or _observed_runtime()
    ):
        controller._report()
        return controller
    try:
        if not _plain_builtin(builtins.compile, "compile"):
            raise ValueError("modified parser compiler")
        plan = make_plan(native)
        if not callable(getattr(plan, "valid_classes", None)) or not callable(
            getattr(plan, "fill_batches", None)
        ):
            raise ValueError("assertion native helper unavailable")
        rewrite_source, rewrite_code = _compiled_module(
            rewrite, fingerprints.REWRITE_SHA256
        )
        _, ast_code = _compiled_module(ast, fingerprints.AST_SHA256)
        rewriter_type = rewrite.AssertionRewriter
        class_code = _child_code(rewrite_code, "AssertionRewriter")
        visitor_code = _child_code(ast_code, "NodeVisitor")
        class_checks = [
            _class_guard(rewriter_type, fingerprints.REWRITER_KEYS),
            _class_guard(ast.NodeVisitor, fingerprints.VISITOR_KEYS),
            _class_guard(rewrite.Sentinel, fingerprints.SENTINEL_KEYS),
        ]
        if rewriter_type.__bases__ != (
            ast.NodeVisitor,
        ) or ast.NodeVisitor.__bases__ != (object,):
            raise ValueError("modified assertion inheritance")
        if type(rewrite._SCOPE_END_MARKER) is not rewrite.Sentinel or vars(
            rewrite._SCOPE_END_MARKER
        ):
            raise ValueError("modified assertion sentinel")
        functions = []
        bindings = []

        def bind(owner, name, code, defaults=None, kwdefaults=None):
            value = vars(owner)[name]
            function = value.__func__ if type(value) is staticmethod else value
            namespace = vars(
                ast
                if owner is ast or owner is ast.NodeVisitor
                else config_module
                if owner is Config
                else rewrite
            )
            if (
                type(function) is not FunctionType
                or function.__globals__ is not namespace
                or function.__builtins__ is not vars(builtins)
            ):
                raise ValueError("modified assertion namespace")
            functions.append(_function_guard(function, code, defaults, kwdefaults))
            bindings.append((owner, name, value))

        for name, value in vars(rewriter_type).items():
            if type(value) in (FunctionType, staticmethod):
                bind(rewriter_type, name, _child_code(class_code, name))
        for name in ("visit", "generic_visit"):
            bind(ast.NodeVisitor, name, _child_code(visitor_code, name))
        for name in ("iter_fields", "iter_child_nodes", "copy_location"):
            bind(ast, name, _child_code(ast_code, name))
        bind(
            ast,
            "parse",
            _child_code(ast_code, "parse"),
            ("<unknown>", "exec"),
            dict(type_comments=False, feature_version=None, optimize=-1),
        )
        for name in ("_rewrite_test", "traverse_node"):
            bind(rewrite, name, _child_code(rewrite_code, name))
        bind(
            rewrite,
            "rewrite_asserts",
            _child_code(rewrite_code, "rewrite_asserts"),
            (None, None),
        )
        config_checks = []
        if config is not None:
            _, config_code = _compiled_module(config_module, fingerprints.CONFIG_SHA256)
            config_class_code = _child_code(config_code, "Config")
            for name in ("getini",):
                bind(Config, name, _child_code(config_class_code, name))
            config_checks.extend(_lookup_checks(Config, ("_parser", "_inicache")))
            config_checks.extend(_lookup_checks(Parser, ("_ini_aliases",)))
            if any(
                name in vars(Config)
                for name in SPECIALS
                if name not in ("__dict__", "__init__")
            ):
                raise ValueError("modified config lookup")
        modules = (
            (rewrite, "ast", ast),
            (rewrite, "itertools", itertools),
            (rewrite, "defaultdict", defaultdict),
            (rewrite, "Config", Config),
            (itertools, "count", itertools.count),
        )
        if not _native_counter(itertools.count) or not _native_defaultdict(defaultdict):
            raise ValueError("modified assertion constructor")
        if any(
            vars(owner).get(name) is not expected for owner, name, expected in modules
        ):
            raise ValueError("modified assertion dependency")
        parser_flags = fingerprints.PARSER_FLAGS
        if any(
            type(vars(ast).get(name)) is not int or vars(ast)[name] != value
            for name, value in parser_flags
        ):
            raise ValueError("modified parser flags")
        if not _operator_map(
            rewrite.BINOP_MAP, fingerprints.BINOPS
        ) or not _operator_map(rewrite.UNARY_MAP, fingerprints.UNARYOPS):
            raise ValueError("modified assertion operator map")
        binops, unaryops = rewrite.BINOP_MAP, rewrite.UNARY_MAP
        thread_count = threading.active_count
        thread_source = inspect.getsource(thread_count)
        if (
            type(thread_count) is not FunctionType
            or thread_count.__globals__ is not vars(threading)
            or thread_count.__builtins__ is not vars(builtins)
            or hashlib.sha256(thread_source.encode()).hexdigest()
            != fingerprints.THREAD_COUNT_SHA256
        ):
            raise ValueError("modified thread guard")
        thread_module = compile(
            thread_source,
            "<verified thread guard>",
            "exec",
            dont_inherit=True,
            optimize=sys.flags.optimize,
        )
        functions.append(
            _function_guard(thread_count, _child_code(thread_module, "active_count"))
        )
        thread_code = thread_count.__code__
        callbacks = gc.callbacks
        if type(callbacks) is not list:
            raise ValueError("modified collection callbacks")
        original = rewrite._rewrite_test
        original_visit = rewriter_type.visit_Assert
        original_run = rewriter_type.run

        def eligible(*, cached=True):
            return (
                threading.active_count is thread_count
                and thread_count.__code__ is thread_code
                and thread_count() == 1
                and gc.callbacks is callbacks
                and not callbacks
                and not sys.gettrace()
                and not sys.getprofile()
                and sys._is_gil_enabled()
                and all(sys.monitoring.get_tool(tool) is None for tool in range(6))
                and all(
                    vars(owner).get(name) is value for owner, name, value in bindings
                )
                and all(_unchanged_function(check) for check in functions)
                and all(_unchanged_class(check) for check in class_checks)
                and all(
                    owner.get(key, MISSING) is value
                    for owner, key, value in config_checks
                )
                and all(
                    vars(owner).get(name) is value for owner, name, value in modules
                )
                and all(
                    type(vars(ast).get(name)) is int and vars(ast)[name] == value
                    for name, value in parser_flags
                )
                and rewrite.BINOP_MAP is binops
                and rewrite.UNARY_MAP is unaryops
                and _operator_map(binops, fingerprints.BINOPS)
                and _operator_map(unaryops, fingerprints.UNARYOPS)
                and (not cached or _cached_config(config))
                and plan.valid_classes()
            )

        def flush(writer):
            batches = writer._boorst_location_batches
            writer._boorst_location_batches = []
            if not batches:
                return
            controller.counts["attempted"] += 1
            controller.counts["assertions"] += len(batches)
            if plan.fill_batches(batches):
                controller.counts["accepted"] += 1
            else:
                controller.counts["native_fallback"] += 1
                for statements, assertion in batches:
                    for statement in statements:
                        for node in rewrite.traverse_node(statement):
                            if getattr(node, "lineno", None) is None:
                                ast.copy_location(node, assertion)
            controller._report()

        visit_source = textwrap.dedent(inspect.getsource(original_visit))
        start = visit_source.index(
            "    # Fix locations (line numbers/column offsets).\n"
        )
        end = visit_source.index("    return self.statements\n", start)
        queued_source = (
            visit_source[:start]
            + "    self._boorst_location_batches.append((self.statements, assert_))\n"
            + visit_source[end:]
        )
        candidate_source = rewrite_source.replace(
            inspect.getsource(original_visit), textwrap.indent(queued_source, "    "), 1
        )
        candidate_code = compile(
            candidate_source,
            "<batched assertion locations>",
            "exec",
            dont_inherit=True,
            optimize=sys.flags.optimize,
        )
        candidate_visit = FunctionType(
            _child_code(
                _child_code(candidate_code, "AssertionRewriter"), "visit_Assert"
            ),
            original_visit.__globals__,
            "visit_Assert",
        )

        def visit_assert(writer, assertion):
            if type(assertion.test) is ast.Tuple and assertion.test.elts:
                # Warnings can call user code; finish earlier forests first.
                flush(writer)
                writer.__class__ = rewriter_type
                return original_visit(writer, assertion)
            return candidate_visit(writer, assertion)

        class BatchedRewriter(rewriter_type):
            __slots__ = ()
            visit_Assert = visit_assert

        def current_builtin(namespace, builtin_namespace, name):
            return namespace[name] if name in namespace else builtin_namespace[name]

        def rewrite_test(fn, current_config):
            scoped = current_config is config
            if not scoped or not eligible():
                controller.counts["guard_fallback"] += 1
                controller._report()
                return original(fn, current_config)
            namespace, builtin_namespace = original.__globals__, original.__builtins__
            stat = namespace["os"].stat(fn)
            source = fn.read_bytes()
            filename = current_builtin(namespace, builtin_namespace, "str")(fn)
            trusted = type(source) is bytes and type(filename) is str and eligible()
            tree = namespace["ast"].parse(source, filename=filename)
            if not trusted or not eligible():
                controller.counts["guard_fallback"] += 1
                controller._report()
                namespace["rewrite_asserts"](tree, source, filename, current_config)
            else:
                writer = rewriter_type(filename, current_config, source)
                if (
                    type(writer.enable_assertion_pass_hook) is not bool
                    or writer.enable_assertion_pass_hook
                    or not eligible()
                ):
                    controller.counts["guard_fallback"] += 1
                    controller._report()
                    writer.run(tree)
                else:
                    writer.__class__ = BatchedRewriter
                    writer._boorst_location_batches = []
                    try:
                        original_run(writer, tree)
                    finally:
                        flush(writer)
                        del writer._boorst_location_batches
            code = current_builtin(namespace, builtin_namespace, "compile")(
                tree, filename, "exec", dont_inherit=True
            )
            return stat, code

        # Keep the verified stock entry binding in its guard; our wrapper owns it now.
        bindings.remove((rewrite, "_rewrite_test", original))
        if not eligible(cached=False):
            raise ValueError("assertion runtime guard declined")
        controller.original, controller.replacement = original, rewrite_test
        rewrite._rewrite_test = rewrite_test
        controller.active = True
        controller.reason = "verified assertion location batching"
    except (
        AttributeError,
        ImportError,
        OSError,
        ValueError,
        TypeError,
        SyntaxError,
        StopIteration,
        RecursionError,
    ):
        controller.reason = (
            "assertion implementation or native helper could not be verified"
        )
    controller._report()
    return controller


def install(config, state):
    details = state["assertions"] = dict(
        status="fallback",
        reason="unsupported assertion runtime",
        native_batches=0,
        assertions=0,
        fallback_batches=0,
    )
    if (
        sys.implementation.name != "cpython"
        or sys.version_info[:2] != (3, 14)
        or pytest.__version__ != "9.1.1"
        or type(config) is not Config
        or not sys._is_gil_enabled()
        or _observed_runtime()
    ):
        return None
    try:
        native = importlib.import_module("pytest_boorst._native")
    except (ImportError, OSError):
        details["reason"] = "assertion native helper unavailable"
        return None
    controller = install_native(native, config, state=details)
    if controller.active:
        config.add_cleanup(controller.restore)
    return controller
