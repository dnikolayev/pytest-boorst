import ast
import builtins
import json
import sys
import threading
import warnings
from contextlib import contextmanager
from types import CodeType, FunctionType

import pytest
from _pytest.assertion import rewrite
from pytest_boorst import _assertions, _native

NATIVE_RUNTIME = (
    sys.implementation.name == "cpython"
    and sys.version_info[:2] == (3, 14)
    and getattr(sys, "_is_gil_enabled", lambda: True)()
)
SUPPORTED = NATIVE_RUNTIME and pytest.__version__ == "9.1.1"
LOCATIONS = ("lineno", "col_offset", "end_lineno", "end_col_offset")
STOCK_REWRITE = rewrite._rewrite_test
SOURCE = b'''"""Example module."""
from __future__ import annotations

def check(value):
    assert value != 0, f"value={value}"
    assert (seen := value) == 2
    def inner(other):
        assert other and other + 1 == value
        assert seen == other
    class Nested:
        async def check(self, expected):
            assert await compute(expected) == expected, "async"
            assert expected > 0
    return inner, Nested

assert 1 + 1 == 2
'''


@contextmanager
def activated(*, required=True, config=None):
    controller = _assertions.install_native(_native, config=config)
    try:
        if required:
            assert controller.active, controller.stats()
        yield controller
    finally:
        controller.restore()


@pytest.fixture
def native_plan():
    if not NATIVE_RUNTIME:
        pytest.skip("native assertion schema requires supported CPython 3.14")
    return _assertions.make_plan(_native)


def forest(line=17):
    roots = [
        ast.Assign(
            [ast.Name("output", ast.Store())],
            ast.Call(
                ast.Name("work", ast.Load()),
                [ast.BinOp(ast.Name("value", ast.Load()), ast.Add(), ast.Constant(1))],
                [],
            ),
        )
    ]
    source = ast.Assert(ast.Constant(True), None)
    for name, value in zip(LOCATIONS, (line, 3, 19, 12), strict=True):
        setattr(source, name, value)
    return roots, source


def fill_stock(batches):
    for roots, source in batches:
        for root in roots:
            for node in rewrite.traverse_node(root):
                if getattr(node, "lineno", None) is None:
                    ast.copy_location(node, source)


def snapshot(value):
    """Inspect dictionary contents without invoking custom AST accessors."""
    seen, records = {}, []

    def freeze(item):
        kind = type(item)
        if issubclass(kind, (ast.AST, list)):
            pointer = id(item)
            if pointer not in seen:
                seen[pointer] = len(records)
                records.append(None)
                if issubclass(kind, ast.AST):
                    contents = tuple(
                        (freeze(k), freeze(v))
                        for k, v in dict.items(
                            object.__getattribute__(item, "__dict__")
                        )
                    )
                else:
                    contents = tuple(freeze(v) for v in list.__iter__(item))
                records[seen[pointer]] = (kind, contents)
            return ("reference", seen[pointer])
        if kind is tuple:
            return tuple(freeze(v) for v in item)
        if kind in (str, bytes, int, float, complex, bool, type(None)):
            return kind, item
        return kind, id(item)

    result = freeze(value)
    return result, records


@pytest.mark.parametrize(
    "shared,first_none", [(False, False), (True, False), (True, True)]
)
def test_batch_locations_preserve_source_order_and_shared_children(
    native_plan, shared, first_none
):
    def batches():
        first, second = forest(None if first_none else 11), forest(37)
        if shared:
            second[0][0].value = first[0][0].value
            second[0].append(first[0][0])
        return [first, second]

    expected, actual = batches(), batches()
    fill_stock(expected)
    assert native_plan.fill_batches(actual) is True
    assert snapshot(actual) == snapshot(expected)


@pytest.mark.parametrize("case", ["partial", "none", "zero", "missing"])
def test_batch_preserves_partial_and_missing_coordinates(native_plan, case):
    def batch():
        roots, source = forest()
        if case == "partial":
            roots[0].lineno = 0
            roots[0].col_offset = None
            roots[0].value.end_lineno = 8
        elif case == "none":
            source.__dict__.update(dict.fromkeys(LOCATIONS))
            roots[0].col_offset = 0
        elif case == "zero":
            source.__dict__.update(dict.fromkeys(LOCATIONS, 0))
        else:
            for name in LOCATIONS:
                del source.__dict__[name]
        return [(roots, source)]

    expected, actual = batch(), batch()
    fill_stock(expected)
    assert native_plan.fill_batches(actual) is True
    assert snapshot(actual) == snapshot(expected)


@pytest.mark.parametrize(
    "case",
    [
        "subclass",
        "list",
        "fields",
        "attributes",
        "key",
        "scalar",
        "collision",
        "coordinate",
        "deep",
    ],
)
def test_late_unsupported_batch_does_not_write_earlier_trees(native_plan, case):
    first, second = forest(), forest(37)
    roots, _ = second
    callbacks = []
    if case == "subclass":

        class Name(ast.Name):
            def __getattribute__(self, name):
                callbacks.append(name)
                return super().__getattribute__(name)

        roots.append(ast.Expr(Name("custom", ast.Load())))
    elif case == "list":

        class Arguments(list):
            def __iter__(self):
                callbacks.append("iteration")
                return super().__iter__()

        roots[0].value.args = Arguments(roots[0].value.args)
    elif case == "fields":
        roots[0]._fields = ("value",)
    elif case == "attributes":
        roots[0]._attributes = ("lineno",)
    elif case == "key":
        roots[0].__dict__["\ud800"] = 1
    elif case == "scalar":

        class Scalar:
            @property
            def __class__(self):
                callbacks.append("scalar type")
                return int

        roots[0].value.args.append(ast.Constant(Scalar()))
    elif case == "collision":

        class Key:
            def __hash__(self):
                return hash("lineno")

            def __eq__(self, other):
                callbacks.append("key comparison")
                raise RuntimeError("custom key comparison")

        roots[0].__dict__[Key()] = None
    elif case == "coordinate":

        class Coordinate:
            def __del__(self):
                callbacks.append("coordinate finalized")

        roots[0].value.col_offset = Coordinate()
    else:
        node = ast.Name("bottom", ast.Load())
        for _ in range(66):
            node = ast.UnaryOp(ast.Not(), node)
        roots.append(ast.Expr(node))
    batches = [first, second]
    before = snapshot(batches)
    assert native_plan.fill_batches(batches) is False
    assert snapshot(batches) == before
    assert callbacks == []


@pytest.mark.parametrize("field,value", [("_fields", ("id",)), ("end_lineno", 123)])
def test_native_plan_rechecks_ast_class_metadata(
    native_plan, monkeypatch, field, value
):
    assert native_plan.valid_classes() is True
    assert native_plan.fill_batches([forest()]) is True
    batches = [forest()]
    before = snapshot(batches)
    with monkeypatch.context() as changed:
        changed.setattr(ast.Name, field, value)
        assert native_plan.valid_classes() is False
        assert native_plan.fill_batches(batches) is False
        assert snapshot(batches) == before
    assert native_plan.fill_batches([forest()]) is True
    assert native_plan.valid_classes() is True


def test_source_assertion_alias_declines_without_writes(native_plan):
    first, second = forest(), forest(37)
    second[0].append(first[1])
    batches = [first, second]
    before = snapshot(batches)
    assert native_plan.fill_batches(batches) is False
    assert snapshot(batches) == before


def test_native_plan_rechecks_constructor_mapping_contents(native_plan, monkeypatch):
    batches = [forest()]
    before = snapshot(batches)
    with monkeypatch.context() as changed:
        changed.setitem(ast.Constant._field_types, "kind", int)
        assert native_plan.valid_classes() is False
        assert native_plan.fill_batches(batches) is False
        assert snapshot(batches) == before
    assert native_plan.valid_classes() is True


def test_initial_ast_descriptor_is_rejected_without_calling_it(
    native_plan, monkeypatch
):
    calls = []

    def read_name(self):
        calls.append("read")
        return "custom"

    with monkeypatch.context() as changed:
        changed.setattr(ast.AST, "id", property(read_name), raising=False)
        with pytest.raises(ValueError):
            _assertions.make_plan(_native)
        assert calls == []
    assert native_plan.fill_batches([forest()]) is True


def rewritten_file(path, function=STOCK_REWRITE, config=None):
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        _, code = function(path, config)
    return code, [(type(w.message).__name__, str(w.message), w.lineno) for w in caught]


def bytecode(code):
    # Marshal reference flags vary even between two identical stock compilations.
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
        "co_filename",
        "co_name",
        "co_qualname",
        "co_firstlineno",
        "co_linetable",
        "co_exceptiontable",
        "co_freevars",
        "co_cellvars",
    )
    return (
        tuple(getattr(code, field, None) for field in fields),
        tuple(
            bytecode(value) if type(value) is CodeType else value
            for value in code.co_consts
        ),
        tuple(code.co_positions()),
    )


@pytest.mark.skipif(not SUPPORTED, reason="native assertion adapter boundary")
def test_fresh_modules_match_bytecode_and_failure_diagnostics(tmp_path):
    path = tmp_path / "test_example.py"
    path.write_bytes(SOURCE)
    expected, expected_warnings = rewritten_file(path)
    with activated() as controller:
        actual, actual_warnings = rewritten_file(path, rewrite._rewrite_test)
        assert bytecode(actual) == bytecode(expected)
        assert actual_warnings == expected_warnings
        assert controller.counts["accepted"] == 1
        assert controller.counts["assertions"] >= 6
    errors = []
    for code in (expected, actual):
        namespace = {}
        exec(code, namespace)
        with pytest.raises(AssertionError) as error:
            namespace["check"](0)
        errors.append(str(error.value))
    assert errors[0] == errors[1]


@pytest.mark.skipif(not SUPPORTED, reason="native assertion adapter boundary")
@pytest.mark.parametrize(
    "source",
    [
        b"def check(x):\n    assert (x, 'message')\n",
        b"def check(x):\n    assert \\\n        (x, 'message')\n",
    ],
)
def test_tuple_assertion_warning_keeps_stock_location(tmp_path, source):
    path = tmp_path / "test_warning.py"
    path.write_bytes(source)
    expected, messages = rewritten_file(path)
    with activated() as controller:
        actual, actual_messages = rewritten_file(path, rewrite._rewrite_test)
        assert actual_messages == messages
        assert bytecode(actual) == bytecode(expected)
        assert controller.counts["accepted"] == 0


@pytest.mark.skipif(not SUPPORTED, reason="native assertion adapter boundary")
def test_direct_rewriter_calls_and_shared_input_keep_stock_behavior():
    def run():
        tree = ast.parse("def check(x):\n    assert x\n    assert x\n")
        tree.body[0].body[1].test = tree.body[0].body[0].test
        rewrite.rewrite_asserts(tree, b"def check(x):\n    assert x\n    assert x\n")
        writer = rewrite.AssertionRewriter("example.py", None, b"assert value\n")
        direct = writer.visit_Assert(ast.parse("assert value").body[0])
        return ast.dump(tree, include_attributes=True), ast.dump(
            ast.Module(direct, []), include_attributes=True
        )

    expected = run()
    with activated() as controller:
        assert run() == expected
        assert controller.counts["attempted"] == 0


@pytest.mark.skipif(not SUPPORTED, reason="native assertion adapter boundary")
@pytest.mark.parametrize(
    "change", ["helper", "constructor", "mapping", "global", "code", "defaults"]
)
def test_runtime_changes_use_current_stock_implementation(
    tmp_path, monkeypatch, change
):
    path = tmp_path / "test_changed.py"
    path.write_bytes(
        b"def check(value):\n    assert value + 1 == 2\n    assert value\n"
    )
    with activated() as controller, monkeypatch.context() as altered:
        if change == "helper":
            original = ast.copy_location
            altered.setattr(
                ast, "copy_location", lambda target, source: original(target, source)
            )
        elif change == "constructor":
            original = ast.Name.__init__

            def initialize(self, *args, **kwargs):
                original(self, *args, **kwargs)

            altered.setattr(ast.Name, "__init__", initialize)
        elif change == "mapping":
            altered.setitem(rewrite.BINOP_MAP, ast.Add, "added")
        elif change == "global":
            altered.setitem(
                vars(rewrite), "getattr", lambda *args: builtins.getattr(*args)
            )
        elif change == "code":
            original = ast.copy_location
            altered.setattr(
                original,
                "__code__",
                original.__code__.replace(co_name="copy_location_changed"),
            )
        else:
            altered.setattr(ast.copy_location, "__defaults__", (None,))
        expected, messages = rewritten_file(path)
        actual, actual_messages = rewritten_file(path, rewrite._rewrite_test)
        assert actual_messages == messages
        assert bytecode(actual) == bytecode(expected)
        assert controller.counts["accepted"] == 0


@pytest.mark.skipif(not SUPPORTED, reason="native assertion adapter boundary")
def test_helper_modified_before_install_keeps_current_behavior(tmp_path, monkeypatch):
    path = tmp_path / "test_modified.py"
    path.write_bytes(b"assert 1 == 1\nassert 2 == 2\n")
    original = ast.copy_location
    calls = []

    def copy_location(target, source):
        calls.append(type(target).__name__)
        return original(target, source)

    monkeypatch.setattr(ast, "copy_location", copy_location)
    expected, messages = rewritten_file(path)
    expected_calls = calls[:]
    calls.clear()
    with activated(required=False) as controller:
        actual, actual_messages = rewritten_file(path, rewrite._rewrite_test)
        assert bytecode(actual) == bytecode(expected)
        assert actual_messages == messages
        assert calls == expected_calls
        assert controller.counts["accepted"] == 0


@pytest.mark.skipif(not SUPPORTED, reason="native assertion adapter boundary")
@pytest.mark.parametrize("when", ["before", "after"])
@pytest.mark.parametrize("name", ["count", "defaultdict"])
def test_modified_iteration_dependencies_keep_current_behavior(
    tmp_path, monkeypatch, when, name
):
    path = tmp_path / "test_dependencies.py"
    path.write_bytes(b"assert 1 == 1\nassert 2 == 2\n")
    owner = rewrite.itertools if name == "count" else rewrite
    original = getattr(owner, name)
    calls = []

    def replacement(*args, **kwargs):
        calls.append((args, kwargs))
        return original(*args, **kwargs)

    with monkeypatch.context() as changed:
        if when == "before":
            changed.setattr(owner, name, replacement)
        with activated(required=when == "after") as controller:
            if when == "after":
                changed.setattr(owner, name, replacement)
            calls.clear()
            expected, messages = rewritten_file(path)
            expected_calls = calls[:]
            calls.clear()
            actual, actual_messages = rewritten_file(path, rewrite._rewrite_test)
            assert bytecode(actual) == bytecode(expected)
            assert actual_messages == messages
            assert calls == expected_calls
            assert controller.counts["accepted"] == 0


@pytest.mark.skipif(not SUPPORTED, reason="native assertion adapter boundary")
def test_cloned_helper_globals_keep_stock_rewriter(tmp_path, monkeypatch):
    path = tmp_path / "test_cloned_globals.py"
    path.write_bytes(b"assert 1 == 1\nassert 2 == 2\n")
    original = ast.copy_location
    cloned = FunctionType(
        original.__code__,
        dict(original.__globals__),
        original.__name__,
        original.__defaults__,
        original.__closure__,
    )
    monkeypatch.setattr(ast, "copy_location", cloned)
    expected, messages = rewritten_file(path)
    with activated(required=False) as controller:
        actual, actual_messages = rewritten_file(path, rewrite._rewrite_test)
        assert bytecode(actual) == bytecode(expected)
        assert actual_messages == messages
        assert controller.counts["accepted"] == 0


@pytest.mark.skipif(not SUPPORTED, reason="native assertion adapter boundary")
def test_deeply_modified_field_metadata_declines_without_error(monkeypatch):
    field_type = int
    for _ in range(sys.getrecursionlimit() + 10):
        field_type = list[field_type]
    monkeypatch.setitem(ast.Constant._field_types, "kind", field_type)
    original = rewrite._rewrite_test
    with activated(required=False) as controller:
        assert not controller.active
        assert rewrite._rewrite_test is original


@pytest.mark.skipif(not SUPPORTED, reason="native assertion adapter boundary")
def test_modified_thread_guard_code_keeps_stock_rewriter(monkeypatch):
    original = rewrite._rewrite_test
    active_count = threading.active_count
    monkeypatch.setattr(
        active_count,
        "__code__",
        active_count.__code__.replace(co_name="modified_count"),
    )
    with activated(required=False) as controller:
        assert not controller.active
        assert rewrite._rewrite_test is original


@pytest.mark.skipif(not SUPPORTED, reason="native assertion adapter boundary")
@pytest.mark.parametrize("when", ["before", "after"])
def test_constructor_field_type_mutation_preserves_stock_warnings(
    tmp_path, monkeypatch, when
):
    path = tmp_path / "test_field_types.py"
    path.write_bytes(b"assert 1 == 1\nassert 2 == 2\n")
    with monkeypatch.context() as changed:
        if when == "before":
            changed.setitem(ast.Constant._field_types, "kind", int)
        with activated(required=when == "after") as controller:
            if when == "after":
                changed.setitem(ast.Constant._field_types, "kind", int)
            expected, messages = rewritten_file(path)
            actual, actual_messages = rewritten_file(path, rewrite._rewrite_test)
            assert bytecode(actual) == bytecode(expected)
            assert actual_messages == messages
            assert controller.counts["accepted"] == 0


@pytest.mark.skipif(not SUPPORTED, reason="native assertion adapter boundary")
@pytest.mark.parametrize("instrument", ["trace", "profile"])
def test_instrumentation_enabled_after_install_uses_stock(tmp_path, instrument):
    path = tmp_path / "test_traced.py"
    path.write_bytes(b"assert 1 == 1\nassert 2 == 2\n")
    expected, messages = rewritten_file(path)
    set_instrument = sys.settrace if instrument == "trace" else sys.setprofile
    get_instrument = sys.gettrace if instrument == "trace" else sys.getprofile
    previous = get_instrument()

    def observe(frame, event, arg):
        return observe

    with activated() as controller:
        try:
            set_instrument(observe)
            actual, actual_messages = rewritten_file(path, rewrite._rewrite_test)
        finally:
            set_instrument(previous)
        assert actual_messages == messages
        assert bytecode(actual) == bytecode(expected)
        assert controller.counts["accepted"] == 0


def test_unsupported_runtime_does_not_replace_pytest(monkeypatch):
    original = rewrite._rewrite_test
    monkeypatch.setattr(sys, "version_info", (3, 13, 0, "final", 0))
    with activated(required=False) as controller:
        assert not controller.active
        assert rewrite._rewrite_test is original


def test_missing_native_api_keeps_stock_rewriter(monkeypatch):
    original = rewrite._rewrite_test
    monkeypatch.delattr(_native, "location_plan")
    with activated(required=False) as controller:
        assert not controller.active
        assert rewrite._rewrite_test is original


@pytest.mark.skipif(not SUPPORTED, reason="native assertion adapter boundary")
def test_cleanup_preserves_other_replacement_and_allows_reinstallation(monkeypatch):
    original = rewrite._rewrite_test
    with activated():
        assert rewrite._rewrite_test is not original
    assert rewrite._rewrite_test is original
    with activated():

        def replacement(*args):
            return None

        monkeypatch.setattr(rewrite, "_rewrite_test", replacement)
    assert rewrite._rewrite_test is replacement


@pytest.mark.parametrize("pass_hook", [False, True])
def test_plugin_activation_and_assertion_pass_hook(pytester, monkeypatch, pass_hook):
    monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    monkeypatch.setenv("PYTHONDONTWRITEBYTECODE", "1")
    monkeypatch.delenv("PYTEST_BOORST", raising=False)
    pytester.makeini(f"[pytest]\nenable_assertion_pass_hook = {str(pass_hook).lower()}")
    pytester.makeconftest("""
        import json
        from pathlib import Path
        from pytest_boorst import plugin
        events = []
        def pytest_assertion_pass(item, lineno, orig, expl):
            events.append((lineno, orig))
        def pytest_sessionfinish(session):
            Path("assertion_receipt.json").write_text(json.dumps({
                "state": session.config.stash[plugin.STATE_KEY]["assertions"],
                "events": events,
            }))
    """)
    source = """
        def test_example():
            assert 1 == 1
            assert 2 == 2
    """
    pytester.makepyfile(test_first=source, test_second=source)
    result = pytester.runpytest_subprocess(
        "-q", "-p", "pytest_boorst.plugin", "--boorst"
    )
    result.assert_outcomes(passed=2)
    receipt = json.loads((pytester.path / "assertion_receipt.json").read_text())
    assert len(receipt["events"]) == (4 if pass_hook else 0)
    state = receipt["state"]
    if SUPPORTED and not pass_hook:
        assert state["native_batches"] > 0
        assert state["assertions"] >= 2
    else:
        assert state["native_batches"] == 0


def test_repeated_pytest_main_restores_original_rewriter(pytester, monkeypatch):
    monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    monkeypatch.setenv("PYTHONDONTWRITEBYTECODE", "1")
    pytester.makepyfile(test_example="def test_example():\n    assert 2 + 2 == 4\n")
    script = pytester.makepyfile(
        runner="""
        import pytest
        from _pytest.assertion import rewrite
        original = rewrite._rewrite_test
        for unused in range(2):
            assert pytest.main(["-q", "-p", "pytest_boorst.plugin", "--boorst",
                                "test_example.py"]) == 0
            assert rewrite._rewrite_test is original
    """
    )
    result = pytester.runpython(script)
    assert result.ret == 0


def test_coverage_reports_match_stock(pytester, monkeypatch):
    pytest.importorskip("pytest_cov")
    monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    monkeypatch.setenv("PYTHONDONTWRITEBYTECODE", "1")
    monkeypatch.delenv("PYTEST_BOORST", raising=False)
    pytester.makepyfile(
        example="""
        def choose(value):
            if value:
                return 1
            return 0
    """
    )
    pytester.makepyfile(
        test_example="""
        from example import choose
        def test_example():
            assert choose(True) == 1
            assert choose(False) == 0
    """
    )
    receipts = []
    for enabled in (False, True):
        options = ["--boorst"] if enabled else []
        result = pytester.runpytest_subprocess(
            "-q",
            "-p",
            "pytest_boorst.plugin",
            "-p",
            "pytest_cov.plugin",
            "--cov=example",
            "--cov=test_example",
            "--cov-branch",
            "--cov-report=json",
            *options,
        )
        result.assert_outcomes(passed=1)
        receipts.append(
            json.loads((pytester.path / "coverage.json").read_text())["files"]
        )
    assert receipts[0] == receipts[1]
