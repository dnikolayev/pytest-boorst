import json
from collections import OrderedDict
from types import SimpleNamespace

import pytest
from pytest_boorst import _schedule


def test_duration_validation_and_missing_history_preserve_stock_order():
    history = _schedule._history(
        {
            "ok": 1.0,
            "bool": True,
            "negative": -1,
            "nan": float("nan"),
            "infinite": float("inf"),
            "huge": 10**1000,
            "text": "2",
        }
    )
    assert history == {"ok": 1.0}
    assert _schedule._history([]) == {}
    queue = OrderedDict([("a", {"a1": False, "a2": False}), ("b", {"b1": False})])
    original = list(queue.items())
    assert not _schedule._order_workqueue(queue, {})
    assert not _schedule._order_workqueue(queue, {"stale": 20})
    assert list(queue.items()) == original
    assert _schedule._order_workqueue(queue, {"a1": 0.1, "a2": 0.1, "b1": 2})
    assert list(queue) == ["b", "a"]
    assert list(queue["a"]) == ["a1", "a2"]


@pytest.mark.parametrize("values", [(10**308, 10**308, 0.1), (1e308, 1e308)])
def test_overflowing_weights_preserve_stock_queue(values):
    history = {str(index): value for index, value in enumerate(values)}
    queue = OrderedDict([("scope", dict.fromkeys(history, False))])
    before = list(queue.items())
    assert not _schedule._order_workqueue(queue, history)
    assert list(queue.items()) == before


def test_stock_implementation_guard_rejects_runtime_changes(monkeypatch):
    from xdist.dsession import DSession
    from xdist.scheduler.loadscope import LoadScopeScheduling

    assert _schedule._verified_scope(LoadScopeScheduling)
    assert _schedule._verified_provider(DSession, LoadScopeScheduling)
    original = LoadScopeScheduling._split_scope
    monkeypatch.setattr(
        LoadScopeScheduling, "_split_scope", lambda self, nodeid: nodeid
    )
    assert not _schedule._verified_scope(LoadScopeScheduling)
    monkeypatch.setattr(LoadScopeScheduling, "_split_scope", original)
    monkeypatch.setattr(
        DSession, "pytest_xdist_make_scheduler", lambda self, config, log: None
    )
    assert not _schedule._verified_provider(DSession, LoadScopeScheduling)


def test_code_comparison_preserves_slice_type_and_fields():
    from pytest_boorst.plugin import _same_code

    code = (lambda: None).__code__
    one = code.replace(co_consts=(slice(1, None, None),))
    assert _same_code(one, code.replace(co_consts=(slice(1, None, None),)))
    assert not _same_code(one, code.replace(co_consts=(slice(2, None, None),)))
    assert not _same_code(one, code.replace(co_consts=((1, None, None),)))


def recorder():
    data = {"previous": 2}
    config = SimpleNamespace(
        cache=SimpleNamespace(set=lambda key, value: data.update({key: value}))
    )
    state = _schedule.Scheduler(config)
    state.active = True
    state.pytest_xdist_node_collection_finished(None, ["test_one", "test_skip"])
    for nodeid, phases in (
        ("test_one", ("setup", "call", "teardown")),
        ("test_skip", ("setup", "teardown")),
    ):
        for phase in phases:
            state.pytest_runtest_logreport(
                SimpleNamespace(
                    nodeid=nodeid,
                    when=phase,
                    duration=0.25,
                    outcome="skipped"
                    if nodeid == "test_skip" and phase == "setup"
                    else "passed",
                )
            )
    return state, data


def test_successful_complete_run_persists_durations():
    state, data = recorder()
    state.pytest_sessionfinish(None, 0)
    assert data[_schedule.CACHE_KEY] == {"test_one": 0.75, "test_skip": 0.5}


@pytest.mark.parametrize(
    "case",
    [
        "failed",
        "interrupted",
        "crashed",
        "missing",
        "duplicate",
        "overflow",
        "mixed_overflow",
        "different_collection",
    ],
)
def test_incomplete_or_invalid_runs_do_not_replace_history(case):
    state, data = recorder()
    status = 0
    if case == "failed":
        status = 1
    elif case == "interrupted":
        status = 2
    elif case == "crashed":
        state.pytest_testnodedown(None, "worker exited")
    elif case == "missing":
        del state.reports["test_one"]["teardown"]
    elif case == "duplicate":
        state.pytest_runtest_logreport(
            SimpleNamespace(
                nodeid="test_one", when="call", duration=1, outcome="passed"
            )
        )
    elif case == "overflow":
        state.reports["test_one"] = {
            phase: ("passed", 1e308) for phase in ("setup", "call", "teardown")
        }
    elif case == "mixed_overflow":
        state.reports["test_one"] = dict(
            zip(
                ("setup", "call", "teardown"),
                (("passed", 10**308), ("passed", 10**308), ("passed", 0.1)),
                strict=True,
            )
        )
    else:
        state.pytest_xdist_node_collection_finished(None, ["different"])
    state.pytest_sessionfinish(None, status)
    assert data == {"previous": 2}


def test_default_and_worker_are_inert():
    assert (
        _schedule.install(SimpleNamespace(getoption=lambda *args, **kwargs: False))
        is None
    )
    assert _schedule.install(SimpleNamespace(workerinput={})) is None


@pytest.mark.parametrize("version", ["6.2.5", "10.0.0"])
def test_unsupported_pytest_falls_back(monkeypatch, version):
    manager = pytest.PytestPluginManager()
    config = SimpleNamespace(
        pluginmanager=manager,
        getoption=lambda *args, **kwargs: True,
        add_cleanup=lambda callback: None,
    )
    monkeypatch.setattr(pytest, "__version__", version)
    state = _schedule.install(config)
    assert state.base is None
    assert "unsupported interpreter or pytest version" in state.reason


def test_cleanup_keeps_replacement_plugin():
    manager = pytest.PytestPluginManager()
    cleanups = []
    config = SimpleNamespace(
        pluginmanager=manager,
        getoption=lambda *args, **kwargs: True,
        add_cleanup=cleanups.append,
    )
    state = _schedule.install(config)
    assert "cache provider unavailable" in state.reason
    manager.unregister(state)
    replacement = object()
    manager.register(replacement, "boorst_schedule")
    cleanups[0]()
    assert manager.get_plugin("boorst_schedule") is replacement


def test_grouped_run_preserves_fixtures_and_outcomes(pytester):
    pytester.makeconftest("""
        import pytest
        @pytest.fixture(scope="session")
        def session_value():
            yield object()
        @pytest.fixture(scope="module")
        def module_value():
            yield object()
        @pytest.fixture(scope="class")
        def class_value():
            yield object()
    """)
    suite = """
        import pytest
        class TestGroup:
            seen = None
            @pytest.mark.parametrize("number", range(3))
            def test_value(self, session_value, module_value, class_value, number):
                current = (session_value, module_value, class_value)
                if type(self).seen is not None:
                    assert type(self).seen == current
                type(self).seen = current
            @pytest.mark.skip(reason="example")
            def test_skip(self):
                pass
            @pytest.mark.xfail(reason="example", strict=True)
            def test_expected(self):
                assert False
    """
    pytester.makepyfile(test_first=suite, test_second=suite, test_third=suite)
    args = ("-q", "-n", "2", "--dist=loadscope")
    stock = pytester.runpytest_subprocess(*args)
    cold = pytester.runpytest_subprocess(*args, "--boorst-schedule")
    warm = pytester.runpytest_subprocess(*args, "--boorst-schedule")
    for result in (stock, cold, warm):
        result.assert_outcomes(passed=9, skipped=3, xfailed=3)
    cold.stdout.fnmatch_lines(
        ["*boorst schedule: learning durations; stock loadscope order*"]
    )
    warm.stdout.fnmatch_lines(
        ["*boorst schedule: ordering loadscope groups by cached durations*"]
    )
    assert "boorst schedule:" not in stock.stdout.str()


@pytest.mark.parametrize(
    "args,reason",
    [
        (("-p", "no:cacheprovider"), "cache provider unavailable"),
        (("--no-loadscope-reorder",), "scope reordering disabled"),
        (("--dist=load",), "requires --dist=loadscope"),
    ],
)
def test_explicit_fallbacks_preserve_execution(pytester, args, reason):
    pytester.makepyfile("def test_example(): pass")
    result = pytester.runpytest_subprocess(
        "-q", "-n", "2", "--dist=loadscope", "--boorst-schedule", *args
    )
    result.assert_outcomes(passed=1)
    result.stdout.fnmatch_lines([f"*boorst schedule: {reason}*"])


def test_custom_scheduler_remains_in_control(pytester):
    pytester.makeconftest("""
        from xdist.scheduler.loadscope import LoadScopeScheduling
        def pytest_xdist_make_scheduler(config, log):
            return LoadScopeScheduling(config, log)
    """)
    pytester.makepyfile("def test_example(): pass")
    result = pytester.runpytest_subprocess(
        "-q", "-n", "2", "--dist=loadscope", "--boorst-schedule"
    )
    result.assert_outcomes(passed=1)
    result.stdout.fnmatch_lines(
        ["*boorst schedule: another plugin controls scheduling*"]
    )


@pytest.mark.parametrize(
    "workers,expected",
    [(0, "parallel workers required"), (2, "unverified xdist implementation")],
)
def test_unverified_version_and_serial_runs_fall_back(monkeypatch, workers, expected):
    manager = pytest.PytestPluginManager()
    options = {
        "boorst_schedule": True,
        "numprocesses": workers,
        "dist": "loadscope",
        "loadscopereorder": True,
    }
    config = SimpleNamespace(
        cache=SimpleNamespace(get=lambda *args: {}),
        pluginmanager=manager,
        getoption=lambda key, default=None: options.get(key, default),
        add_cleanup=lambda callback: None,
    )
    monkeypatch.setattr(_schedule, "version", lambda name: "99.0")
    state = _schedule.install(config)
    assert state.base is None
    assert expected in state.reason


def test_scheduler_mutation_during_collection_preserves_stock_order(pytester):
    pytester.makeconftest("""
        from xdist.scheduler.loadscope import LoadScopeScheduling
        original = LoadScopeScheduling._split_scope
        def pytest_xdist_node_collection_finished(node, ids):
            def changed(self, nodeid):
                return original(self, nodeid)
            LoadScopeScheduling._split_scope = changed
    """)
    pytester.makepyfile("def test_example(): pass")
    result = pytester.runpytest_subprocess(
        "-q", "-n", "2", "--dist=loadscope", "--boorst-schedule"
    )
    result.assert_outcomes(passed=1)
    result.stdout.fnmatch_lines(
        ["*boorst schedule: scope scheduler changed; using stock order*"]
    )


@pytest.mark.parametrize(
    "error",
    [OSError("cache write failed"), pytest.PytestCacheWarning("cache write failed")],
)
def test_duration_cache_write_failure_does_not_fail_completed_run(error):
    state, data = recorder()

    def fail_write(key, value):
        raise error

    state.config.cache.set = fail_write
    state.pytest_sessionfinish(None, 0)
    assert data == {"previous": 2}
    assert "could not save duration history" in state.reason


def test_worker_restart_preserves_outcomes_and_previous_duration_cache(pytester):
    pytester.makeconftest("""
        import json
        from pathlib import Path
        calls = []
        workers = []
        def pytest_testnodeready(node):
            workers.append(node.gateway.id)
        def pytest_runtest_logreport(report):
            if report.when == "call" and report.passed:
                calls.append(report.nodeid)
        def pytest_sessionfinish(session, exitstatus):
            if not hasattr(session.config, "workerinput"):
                Path("calls.json").write_text(json.dumps(sorted(calls)))
                Path("workers.json").write_text(json.dumps(workers))
    """)
    pytester.makepyfile(
        test_first="""
            import os
            from pathlib import Path
            def test_crash_once():
                marker = Path("crashed-once")
                if Path("enable-crash").exists() and not marker.exists():
                    marker.touch()
                    os._exit(17)
            def test_after_crash():
                pass
        """,
        test_second="def test_one(): pass\ndef test_two(): pass\n",
        test_third="def test_one(): pass\ndef test_two(): pass\n",
    )
    args = ("-q", "-n", "2", "--dist=loadscope", "--max-worker-restart=1")
    training = pytester.runpytest_subprocess(*args, "--boorst-schedule", timeout=30)
    training.assert_outcomes(passed=6)
    history = pytester.path / ".pytest_cache" / "v" / _schedule.CACHE_KEY
    previous = history.read_bytes()
    (pytester.path / "enable-crash").touch()
    results = []
    calls = []
    for enabled in (False, True):
        (pytester.path / "crashed-once").unlink(missing_ok=True)
        result = pytester.runpytest_subprocess(
            *args, *(("--boorst-schedule",) if enabled else ()), timeout=30
        )
        assert result.ret == 1
        workers = json.loads((pytester.path / "workers.json").read_text())
        assert len(workers) == len(set(workers)) == 3
        results.append(result.parseoutcomes())
        calls.append(json.loads((pytester.path / "calls.json").read_text()))
        assert history.read_bytes() == previous
    assert results[0] == results[1]
    assert results[0]["failed"] == 1
    assert calls[0] == calls[1]
    remaining = [nodeid for nodeid in calls[1] if "test_crash_once" not in nodeid]
    assert len(remaining) == len(set(remaining)) == 5
    result.stdout.fnmatch_lines(
        ["*boorst schedule: ordering loadscope groups by cached durations*"]
    )


def test_warm_order_preserves_collection_group_order_and_fixture_finalizers(pytester):
    pytester.makeconftest("""
        import json
        from pathlib import Path
        import pytest
        events = []
        collected = []
        @pytest.fixture(scope="session")
        def session_value():
            events.append(["setup", "session", "session"])
            yield object()
            events.append(["teardown", "session", "session"])
        @pytest.fixture(scope="module")
        def module_value(request, session_value):
            events.append(["setup", "module", request.node.nodeid])
            yield object()
            events.append(["teardown", "module", request.node.nodeid])
        @pytest.fixture(scope="class")
        def class_value(request, module_value):
            events.append(["setup", "class", request.node.nodeid])
            yield object()
            events.append(["teardown", "class", request.node.nodeid])
        def pytest_collection_finish(session):
            collected.extend(item.nodeid for item in session.items)
        def pytest_runtest_call(item):
            events.append(["call", item.nodeid])
        def pytest_sessionfinish(session, exitstatus):
            if hasattr(session.config, "workerinput"):
                Path("lifecycle.json").write_text(json.dumps({
                    "events": events, "collection": collected,
                }))
    """)
    suite = """
        class TestFirst:
            seen = None
            def test_one(self, session_value, module_value, class_value):
                type(self).seen = (session_value, module_value, class_value)
            def test_two(self, session_value, module_value, class_value):
                assert type(self).seen == (session_value, module_value, class_value)
        class TestSecond(TestFirst):
            pass
    """
    pytester.makepyfile(test_alpha=suite, test_beta=suite)
    args = ("-q", "-n", "1", "--dist=loadscope", "--boorst-schedule")
    cold = pytester.runpytest_subprocess(*args, timeout=30)
    cold.assert_outcomes(passed=8)
    baseline = json.loads((pytester.path / "lifecycle.json").read_text())
    scopes = [
        "test_alpha.py::TestSecond",
        "test_beta.py::TestFirst",
        "test_alpha.py::TestFirst",
        "test_beta.py::TestSecond",
    ]
    history = pytester.path / ".pytest_cache" / "v" / _schedule.CACHE_KEY
    history.write_text(
        json.dumps(
            {
                f"{scope}::{name}": 4 - index
                for index, scope in enumerate(scopes)
                for name in ("test_one", "test_two")
            }
        )
    )
    warm = pytester.runpytest_subprocess(*args, timeout=30)
    warm.assert_outcomes(passed=8)
    warm.stdout.fnmatch_lines(
        ["*boorst schedule: ordering loadscope groups by cached durations*"]
    )
    active = json.loads((pytester.path / "lifecycle.json").read_text())
    assert active["collection"] == baseline["collection"]
    assert [row[1] for row in baseline["events"] if row[0] == "call"] == baseline[
        "collection"
    ]
    assert [row[1] for row in active["events"] if row[0] == "call"] == [
        f"{scope}::{name}" for scope in scopes for name in ("test_one", "test_two")
    ]
    for snapshot in (baseline, active):
        stack = []
        for event in snapshot["events"]:
            if event[0] == "setup":
                assert event[1] == ("session", "module", "class")[len(stack)]
                stack.append(event[1:])
            elif event[0] == "teardown":
                assert stack.pop() == event[1:]
            else:
                assert stack[-1] == ["class", event[1].rsplit("::", 1)[0]]
        assert not stack
