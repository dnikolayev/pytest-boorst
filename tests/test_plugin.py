import builtins
import functools
import inspect
import json
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from _pytest.mark import ParameterSet
from _pytest.python import IdMaker
from pytest_boorst import plugin

HAS_STRICT_IDS = hasattr(IdMaker, "_strict_parametrization_ids_enabled")


@pytest.fixture
def config():
    cleanups = []
    config = SimpleNamespace(
        stash=pytest.Stash(),
        add_cleanup=cleanups.append,
        cleanups=cleanups,
        getoption=lambda name, default=False: default,
    )
    yield config
    for cleanup in reversed(cleanups):
        cleanup()


def make_ids(ids, *, config=None, idfn=None, strict=False):
    options = {
        "strict_parametrization_ids": strict,
        "disable_test_id_escaping_and_forfeit_all_rights_to_community_support": True,
    }
    if config is None:
        config = SimpleNamespace()
    config.getini = options.__getitem__
    extra = (
        {"func_name": "test_example"}
        if "func_name" in inspect.signature(IdMaker).parameters
        else {}
    )
    return IdMaker(
        argnames=["value"],
        parametersets=[ParameterSet.param(index) for index in range(len(ids))],
        idfn=idfn,
        ids=ids if idfn is None else None,
        config=config,
        nodeid="test_example",
        **extra,
    )


def activate(monkeypatch, config):
    monkeypatch.setenv("PYTEST_BOORST", "1")
    plugin.pytest_configure(config)
    assert config.stash[plugin.STATE_KEY]["status"] == "active"


def test_default_is_disabled(config, monkeypatch):
    monkeypatch.delenv("PYTEST_BOORST", raising=False)
    plugin.pytest_configure(config)
    assert config.stash[plugin.STATE_KEY]["status"] == "disabled"
    assert IdMaker.make_unique_parameterset_ids is plugin._ORIGINAL


@pytest.mark.parametrize("enabled", ["0", "1"])
def test_missing_stash_keeps_plugin_quiet(monkeypatch, enabled):
    source = Path(plugin.__file__).read_text(encoding="utf-8")
    monkeypatch.delattr(pytest, "StashKey")
    module = ModuleType("pytest_boorst._legacy")
    exec(compile(source, plugin.__file__, "exec"), module.__dict__)
    monkeypatch.setenv("PYTEST_BOORST", enabled)

    def unexpected(*args):
        raise AssertionError("legacy fallback must not load native code or report")

    monkeypatch.setattr(module.importlib, "import_module", unexpected)
    config = SimpleNamespace()
    module.pytest_configure(config)
    assert module.pytest_report_header(config) is None
    module.pytest_terminal_summary(SimpleNamespace(write_line=unexpected), config)
    assert vars(config) == {}
    assert IdMaker.make_unique_parameterset_ids is plugin._ORIGINAL


@pytest.mark.parametrize("missing", ["class", "method"])
def test_missing_private_api_does_not_break_plugin_loading(
    config, monkeypatch, missing
):
    source = Path(plugin.__file__).read_text(encoding="utf-8")
    if missing == "class":
        original_import = builtins.__import__

        def without_idmaker(name, *args, **kwargs):
            if name == "_pytest.python":
                raise ImportError("ID API unavailable")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", without_idmaker)
    else:
        monkeypatch.delattr(IdMaker, "make_unique_parameterset_ids")
    module = ModuleType("pytest_boorst._unsupported")
    exec(compile(source, plugin.__file__, "exec"), module.__dict__)
    monkeypatch.delenv("PYTEST_BOORST", raising=False)
    module.pytest_configure(config)
    assert config.stash[module.STATE_KEY]["status"] == "disabled"
    monkeypatch.setenv("PYTEST_BOORST", "1")
    module.pytest_configure(config)
    assert config.stash[module.STATE_KEY]["status"] == "fallback"
    assert config.cleanups == []


@pytest.mark.parametrize("kind", ["ascii", "unicode", "subclass", "small"])
def test_callbacks_run_once_and_fallback_matches_stock(config, monkeypatch, kind):
    class Label(str):
        pass

    value = {"ascii": "x", "unicode": "é", "subclass": Label("x"), "small": "x"}[kind]
    size = 4 if kind == "small" else 80
    calls = []
    maker = make_ids(
        [None] * size, config=config, idfn=lambda item: calls.append(item) or value
    )
    expected = plugin._ORIGINAL(maker)
    calls.clear()
    activate(monkeypatch, config)
    assert maker.make_unique_parameterset_ids() == expected
    assert calls == list(range(size))
    state = config.stash[plugin.STATE_KEY]
    assert state["native_calls"] == (kind in {"ascii", "subclass"})
    # idfn values are joined by pytest into exact str objects before deduplication.
    assert state["fallback_calls"] == (kind in {"unicode", "small"})


def test_explicit_string_subclasses_use_stock(config, monkeypatch):
    class Label(str):
        pass

    maker = make_ids([Label("x")] * 80, config=config)
    expected = plugin._ORIGINAL(maker)
    activate(monkeypatch, config)
    assert maker.make_unique_parameterset_ids() == expected
    assert config.stash[plugin.STATE_KEY]["native_calls"] == 0
    assert config.stash[plugin.STATE_KEY]["fallback_calls"] == 1


def test_unique_ascii_ids_do_not_cross_native_boundary(config, monkeypatch):
    ids = [f"case_{index}" for index in range(80)]
    maker = make_ids(ids, config=config)
    activate(monkeypatch, config)
    assert maker.make_unique_parameterset_ids() == ids
    assert config.stash[plugin.STATE_KEY]["native_calls"] == 0
    assert config.stash[plugin.STATE_KEY]["fallback_calls"] == 1


@pytest.mark.skipif(not HAS_STRICT_IDS, reason="strict IDs require pytest 9")
def test_strict_setting_is_read_after_callbacks_once(config, monkeypatch):
    calls = []
    strict_reads = []

    def identify(value):
        calls.append(value)
        if value == 79:

            def getini(name):
                if name == "strict_parametrization_ids":
                    strict_reads.append(len(calls))
                return True

            config.getini = getini
        return "same"

    maker = make_ids([None] * 80, config=config, idfn=identify)
    with pytest.raises(pytest.Collector.CollectError) as stock:
        plugin._ORIGINAL(maker)
    calls.clear()
    strict_reads.clear()
    maker = make_ids([None] * 80, config=config, idfn=identify)
    activate(monkeypatch, config)
    with pytest.raises(pytest.Collector.CollectError) as accelerated:
        maker.make_unique_parameterset_ids()
    assert str(accelerated.value) == str(stock.value)
    assert calls == list(range(80))
    assert strict_reads == [80]
    assert config.stash[plugin.STATE_KEY]["native_calls"] == 0


@pytest.mark.parametrize(
    "strict,hidden",
    [
        pytest.param(
            True,
            False,
            marks=pytest.mark.skipif(
                not HAS_STRICT_IDS, reason="strict IDs require pytest 9"
            ),
        ),
        pytest.param(
            False,
            True,
            marks=pytest.mark.skipif(
                not hasattr(pytest, "HIDDEN_PARAM"),
                reason="hidden IDs require pytest 8.4 or newer",
            ),
        ),
    ],
)
def test_error_parity(config, monkeypatch, strict, hidden):
    ids = [pytest.HIDDEN_PARAM] * 80 if hidden else ["same"] * 80
    maker = make_ids(ids, config=config, strict=strict)
    with pytest.raises((pytest.fail.Exception, pytest.Collector.CollectError)) as stock:
        plugin._ORIGINAL(maker)
    activate(monkeypatch, config)
    with pytest.raises(type(stock.value)) as accelerated:
        maker.make_unique_parameterset_ids()
    assert str(accelerated.value) == str(stock.value)
    assert config.stash[plugin.STATE_KEY]["native_calls"] == 0


@pytest.mark.parametrize(
    "unsupported", ["version", "patched", "source", "wrapped", "native"]
)
def test_unsupported_activation_leaves_method_alone(config, monkeypatch, unsupported):
    monkeypatch.setenv("PYTEST_BOORST", "1")
    if unsupported == "version":
        monkeypatch.setattr(pytest, "__version__", "9.0.1")
    elif unsupported == "patched":
        monkeypatch.setattr(IdMaker, "make_unique_parameterset_ids", lambda self: [])
    elif unsupported == "source":
        monkeypatch.setitem(plugin._SOURCE_SHA256, pytest.__version__, "different")
    elif unsupported == "wrapped":

        @functools.wraps(plugin._ORIGINAL)
        def wrapped(self):
            return plugin._ORIGINAL(self)

        monkeypatch.setattr(IdMaker, "make_unique_parameterset_ids", wrapped)
        monkeypatch.setattr(plugin, "_ORIGINAL", wrapped)
    else:

        def missing(name):
            raise ImportError("native unavailable")

        monkeypatch.setattr(plugin.importlib, "import_module", missing)
    if unsupported != "native":

        def unexpected(name):
            raise AssertionError("unsupported activation must not load native code")

        monkeypatch.setattr(plugin.importlib, "import_module", unexpected)
    before = IdMaker.make_unique_parameterset_ids
    plugin.pytest_configure(config)
    assert config.stash[plugin.STATE_KEY]["status"] == "fallback"
    assert IdMaker.make_unique_parameterset_ids is before


def test_native_error_propagates_without_repeating_callbacks(config, monkeypatch):
    from pytest_boorst import _native

    def broken(ids):
        raise RuntimeError("native failure")

    helper = "unique_ids_pytest7" if pytest.__version__ == "7.4.4" else "unique_ids"
    monkeypatch.setattr(_native, helper, broken)
    activate(monkeypatch, config)
    calls = []
    maker = make_ids(
        [None] * 80, config=config, idfn=lambda value: calls.append(value) or "x"
    )
    with pytest.raises(RuntimeError, match="native failure"):
        maker.make_unique_parameterset_ids()
    assert calls == list(range(80))


def test_cleanup_preserves_a_later_patch(config, monkeypatch):
    activate(monkeypatch, config)

    def later(self):
        return ["later"]

    monkeypatch.setattr(IdMaker, "make_unique_parameterset_ids", later)
    for cleanup in config.cleanups:
        cleanup()
    assert IdMaker.make_unique_parameterset_ids is later


def test_foreign_config_uses_original(config, monkeypatch):
    maker = make_ids(["x"] * 80)
    expected = plugin._ORIGINAL(maker)
    activate(monkeypatch, config)
    assert maker.make_unique_parameterset_ids() == expected
    assert config.stash[plugin.STATE_KEY]["native_calls"] == 0


def test_source_fingerprint_matches_supported_pytest():
    assert (
        plugin.hashlib.sha256(inspect.getsource(plugin._ORIGINAL).encode()).hexdigest()
        == plugin._SOURCE_SHA256[pytest.__version__]
    )


def test_collection_and_plugin_integration(pytester, monkeypatch):
    pytester.makeconftest("""
        import json
        from pathlib import Path
        import pytest
        calls = []
        order = []
        reports = []
        def pytest_make_parametrize_id(config, val, argname):
            calls.append(val)
            return "case"
        @pytest.hookimpl(wrapper=True)
        def pytest_collection_modifyitems(items):
            order.append("before")
            yield
            order.append("after")
        def pytest_collection_finish(session):
            Path("manifest.json").write_text(json.dumps({
                "ids": [item.nodeid for item in session.items],
                "calls": calls, "order": order,
            }))
        def pytest_runtest_logreport(report):
            reports.append((report.nodeid, report.when, report.outcome,
                            getattr(report, "wasxfail", None)))
        def pytest_sessionfinish(session):
            Path("reports.json").write_text(json.dumps(reports))
            if hasattr(session.config, "workerinput"):
                from pytest_boorst.plugin import STATE_KEY
                worker = session.config.workerinput["workerid"]
                Path(f"boorst-{worker}.json").write_text(json.dumps(
                    session.config.stash[STATE_KEY]
                ))
    """)
    pytester.makepyfile("""
        import pytest
        @pytest.fixture(params=range(80))
        def value(request):
            yield request.param
        def test_value(value):
            assert value >= 0
        @pytest.mark.asyncio
        async def test_async():
            assert True
        def test_failure():
            assert 1 == 2
        @pytest.mark.skip(reason="example")
        def test_skip():
            pass
        @pytest.mark.xfail(reason="example")
        def test_xfail():
            assert False
        @pytest.mark.xfail(reason="example")
        def test_xpass():
            pass
    """)
    monkeypatch.delenv("PYTEST_BOORST", raising=False)
    coverage = ["--cov=.", "--cov-report=json:coverage.json"]
    outcomes = dict(passed=81, failed=1, skipped=1, xfailed=1, xpassed=1)
    disabled = pytester.runpytest_subprocess("-q", "-p", "no:boorst", *coverage)
    disabled.assert_outcomes(**outcomes)
    baseline = json.loads((pytester.path / "manifest.json").read_text())
    reports = json.loads((pytester.path / "reports.json").read_text())
    covered = json.loads((pytester.path / "coverage.json").read_text())["files"]
    active = pytester.runpytest_subprocess("-q", "--boorst", *coverage)
    active.assert_outcomes(**outcomes)
    assert active.ret == disabled.ret
    assert json.loads((pytester.path / "manifest.json").read_text()) == baseline
    assert json.loads((pytester.path / "reports.json").read_text()) == reports
    assert json.loads((pytester.path / "coverage.json").read_text())["files"] == covered
    active.stdout.fnmatch_lines(
        ["boorst: 1 native ID batches (80 IDs), 0 stock batches"]
    )
    distributed = pytester.runpytest_subprocess("-q", "--boorst", "-n", "2")
    distributed.assert_outcomes(**outcomes)
    for worker in ("gw0", "gw1"):
        state = json.loads((pytester.path / f"boorst-{worker}.json").read_text())
        assert state["status"] == "active"
        assert state["native_calls"] == 1


def test_repeated_main_restores_method(pytester):
    script = pytester.makepyfile(
        check="""
        import os
        import pytest
        from _pytest.python import IdMaker
        from pytest_boorst import plugin
        original = IdMaker.make_unique_parameterset_ids
        states = []
        class Observe:
            def pytest_sessionfinish(self, session):
                states.append(dict(session.config.stash[plugin.STATE_KEY]))
        for enabled in ("1", "0", "1"):
            os.environ["PYTEST_BOORST"] = enabled
            assert pytest.main(["-q", "test_case.py"], plugins=[Observe()]) == 0
            assert IdMaker.make_unique_parameterset_ids is original
        assert [state["status"] for state in states] == ["active", "disabled", "active"]
        assert [state["native_calls"] for state in states] == [1, 0, 1]
        assert pytest.main(["-q", "test_broken.py"]) == pytest.ExitCode.INTERRUPTED
        assert IdMaker.make_unique_parameterset_ids is original
    """
    )
    pytester.makepyfile(
        test_case="""
        def pytest_generate_tests(metafunc):
            metafunc.parametrize("value", range(80), ids=["case"] * 80)
        def test_value(value):
            assert value >= 0
    """
    )
    pytester.makepyfile(test_broken="raise ValueError('collection error')")
    result = pytester.runpython(script)
    assert result.ret == 0, result.stdout.str() + result.stderr.str()
