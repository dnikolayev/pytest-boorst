import json
from types import SimpleNamespace
from xml.etree import ElementTree

import pytest
from pytest_boorst import _profile


def test_worker_totals_replace_repeated_snapshots_and_preserve_controller_reports():
    profiler = _profile.Profiler(SimpleNamespace())
    node = SimpleNamespace(
        gateway=SimpleNamespace(id="gw0"),
        workeroutput={
            "boorst_profile": {
                "modules": {"test_example.py": 2.0},
                "collection_wall": 3.0,
            }
        },
    )
    profiler.reports["call"] = 5.0
    profiler.pytest_testnodedown(node, None)
    profiler.pytest_testnodedown(node, None)
    data = profiler.snapshot()
    assert data["modules"] == {"test_example.py": 2.0}
    assert data["worker_collection_sum"] == 3.0
    assert data["reported_phase_sum"]["call"] == 5.0


def test_profile_preserves_outcomes_and_does_not_enable_acceleration(
    pytester, monkeypatch
):
    monkeypatch.delenv("PYTEST_BOORST", raising=False)
    pytester.makeconftest("""
        import json
        from pathlib import Path
        import pytest
        @pytest.fixture(scope="session")
        def service():
            yield 17
        @pytest.hookimpl(trylast=True)
        def pytest_sessionfinish(session, exitstatus):
            observer = session.config.pluginmanager.get_plugin("boorst_profile")
            boorst = session.config.pluginmanager.get_plugin("boorst")
            Path("profile.json").write_text(json.dumps({
                "data": observer.snapshot() if observer else None,
                "state": session.config.stash[boorst.STATE_KEY],
                "exitstatus": int(exitstatus),
            }))
    """)
    pytester.makepyfile("""
        import pytest
        class TestGroup:
            def test_ok(self, service):
                assert service == 17
        @pytest.mark.skip(reason="example")
        def test_skip():
            pass
        @pytest.mark.xfail(reason="example", strict=True)
        def test_expected_failure(service):
            assert service == 0
    """)
    stock = pytester.runpytest_subprocess("-q")
    active = pytester.runpytest_subprocess("-q", "--boorst-profile")
    stock.assert_outcomes(passed=1, skipped=1, xfailed=1)
    active.assert_outcomes(passed=1, skipped=1, xfailed=1)
    assert active.ret == stock.ret
    active.stdout.fnmatch_lines(["*boorst profile*", "*Startup imports precede*"])
    result = json.loads((pytester.path / "profile.json").read_text())
    assert result["state"]["status"] == "disabled"
    assert result["state"]["native_calls"] == 0
    data = result["data"]
    assert data["collection_wall"] > 0
    assert data["test_loop_wall"] > 0
    assert set(data["reported_phase_sum"]) == {"setup", "call", "teardown"}
    assert all(value > 0 for value in data["reported_phase_sum"].values())
    assert list(data["modules"]) == [
        "test_profile_preserves_outcomes_and_does_not_enable_acceleration.py"
    ]


def test_profile_xdist_reports_worker_collection_and_controller_wall(pytester):
    pytester.makepyfile("""
        import pytest
        @pytest.mark.parametrize("value", range(8))
        def test_example(value):
            assert value >= 0
    """)
    result = pytester.runpytest_subprocess("-q", "--boorst-profile", "-n", "2")
    result.assert_outcomes(passed=8)
    result.stdout.fnmatch_lines(
        ["*Worker collection seconds (sum)*", "*Top module collection seconds*"]
    )


def test_profile_collection_error_remains_an_error(pytester):
    pytester.makepyfile("raise RuntimeError('collection example')")
    result = pytester.runpytest_subprocess("-q", "--boorst-profile")
    assert result.ret == 2
    result.stdout.fnmatch_lines(
        ["*RuntimeError: collection example*", "*boorst profile*"]
    )


def test_profile_keeps_guarded_directory_reuse(pytester):
    import sys

    import pytest

    if pytest.__version__ != "9.1.1" or sys.platform == "win32":
        pytest.skip("directory reuse validation boundary")
    files = []
    for index in range(32):
        path = pytester.path / f"test_case_{index}.py"
        path.write_text("def test_example():\n    pass\n")
        files.append(str(path))
    result = pytester.runpytest_subprocess("-q", "--boorst", "--boorst-profile", *files)
    result.assert_outcomes(passed=32)
    result.stdout.fnmatch_lines(["*boorst profile*", "*31 directory reports reused*"])


def test_cleanup_unregisters_only_its_profiler():
    import pytest

    manager = pytest.PytestPluginManager()
    cleanup = []
    config = SimpleNamespace(pluginmanager=manager, add_cleanup=cleanup.append)
    _profile.install(config)
    observer = manager.get_plugin("boorst_profile")
    assert isinstance(observer, _profile.Profiler)
    cleanup.pop()()
    assert manager.get_plugin("boorst_profile") is None
    _profile.install(config)
    manager.unregister(manager.get_plugin("boorst_profile"))
    replacement = object()
    manager.register(replacement, "boorst_profile")
    cleanup.pop()()
    assert manager.get_plugin("boorst_profile") is replacement


def test_native_batch_keeps_float_addition_order_and_does_not_mutate_input():
    from pytest_boorst import _native

    initial = (1e16, 0.0, 0.0)
    reports = [(0, 1.0), (1, 0.1), (0, -1e16), (2, 0.2)]
    expected = list(initial)
    for phase, duration in reports:
        expected[phase] += duration
    actual = _native.sum_report_batch(initial, reports[:2])
    actual = _native.sum_report_batch(actual, reports[2:])
    assert actual == tuple(expected) == (0.0, 0.1, 0.2)
    assert initial == (1e16, 0.0, 0.0)
    assert reports == [(0, 1.0), (1, 0.1), (0, -1e16), (2, 0.2)]
    with pytest.raises(ValueError, match="unknown report phase"):
        _native.sum_report_batch(initial, [(0, 1.0), (3, 1.0)])


def test_batch_buffer_is_bounded_and_snapshots_do_not_repeat_reports():
    profiler = _profile.Profiler(SimpleNamespace(), batch_reporting=True)
    assert profiler.batch_state["status"] == "native"
    expected = dict.fromkeys(_profile.PHASES, 0.0)
    for index in range(_profile.BATCH_SIZE * 2 + 7):
        phase = _profile.PHASES[index % 3]
        duration = 0.1 if index % 2 else 0.2
        profiler.pytest_runtest_logreport(
            SimpleNamespace(when=phase, duration=duration)
        )
        expected[phase] += duration
        assert len(profiler.pending_reports) < _profile.BATCH_SIZE
    assert profiler.batch_state["native_batches"] == 2
    first = profiler.snapshot()
    assert first["reported_phase_sum"] == expected
    assert first["batch_reporting"]["native_batches"] == 3
    assert first["batch_reporting"]["native_reports"] == _profile.BATCH_SIZE * 2 + 7
    assert profiler.snapshot()["reported_phase_sum"] == expected
    profiler.pytest_sessionfinish(None, 1)
    assert profiler.snapshot()["batch_reporting"] == first["batch_reporting"]


@pytest.mark.parametrize("failure", ["raise", "wrong_length", "wrong_type"])
def test_native_batch_failure_falls_back_once_without_losing_reports(failure):
    profiler = _profile.Profiler(SimpleNamespace(), batch_reporting=True)
    calls = []

    def broken(initial, reports):
        calls.append((initial, reports))
        if failure == "raise":
            raise RuntimeError("batch unavailable")
        if failure == "wrong_length":
            return (1.0,)
        return (1.0, 1.0, "invalid")

    profiler.batch_function = broken
    profiler.pytest_runtest_logreport(SimpleNamespace(when="setup", duration=0.1))
    profiler.pytest_runtest_logreport(SimpleNamespace(when="call", duration=0.2))
    assert profiler.snapshot()["reported_phase_sum"] == {
        "setup": 0.1,
        "call": 0.2,
        "teardown": 0.0,
    }
    profiler.pytest_runtest_logreport(SimpleNamespace(when="call", duration=0.3))
    assert profiler.snapshot()["reported_phase_sum"]["call"] == 0.5
    assert profiler.batch_state["status"] == "fallback"
    assert profiler.batch_state["native_reports"] == 0
    assert len(calls) == 1
    assert calls[0] == ((0.0, 0.0, 0.0), ((0, 0.1), (1, 0.2)))


def test_custom_durations_use_python_without_coercion():
    class Duration:
        def __float__(self):
            raise AssertionError("custom durations must not be coerced")

        def __radd__(self, value):
            return value + 4.0

    profiler = _profile.Profiler(SimpleNamespace(), batch_reporting=True)
    profiler.pytest_runtest_logreport(SimpleNamespace(when="call", duration=1.0))
    profiler.pytest_runtest_logreport(SimpleNamespace(when="call", duration=Duration()))
    assert profiler.snapshot()["reported_phase_sum"]["call"] == 5.0
    assert profiler.batch_state["status"] == "fallback"
    assert profiler.batch_state["reason"] == "custom report values"
    assert profiler.batch_state["native_reports"] == 1


@pytest.mark.parametrize("error", [KeyboardInterrupt(), SystemExit(2)])
def test_interrupted_flush_accounts_for_reports_before_propagating(error):
    profiler = _profile.Profiler(SimpleNamespace(), batch_reporting=True)

    def interrupted(initial, reports):
        raise error

    profiler.batch_function = interrupted
    for _ in range(_profile.BATCH_SIZE - 1):
        profiler.pytest_runtest_logreport(SimpleNamespace(when="call", duration=1.0))
    with pytest.raises(type(error)):
        profiler.pytest_runtest_logreport(SimpleNamespace(when="call", duration=1.0))
    assert profiler.pending_reports == []
    assert profiler.snapshot()["reported_phase_sum"]["call"] == _profile.BATCH_SIZE
    profiler.pytest_runtest_logreport(SimpleNamespace(when="call", duration=0.5))
    assert (
        profiler.snapshot()["reported_phase_sum"]["call"] == _profile.BATCH_SIZE + 0.5
    )
    assert profiler.batch_state["status"] == "fallback"
    assert profiler.batch_state["native_reports"] == 0


def test_custom_initial_totals_are_not_coerced_by_native_helper():
    class Total:
        def __float__(self):
            raise AssertionError("custom totals must not be coerced")

        def __add__(self, value):
            return 4.0 + value

    profiler = _profile.Profiler(SimpleNamespace(), batch_reporting=True)
    profiler.reports["call"] = Total()
    profiler.pytest_runtest_logreport(SimpleNamespace(when="call", duration=1.0))
    assert profiler.snapshot()["reported_phase_sum"]["call"] == 5.0
    assert profiler.batch_state["status"] == "fallback"
    assert profiler.batch_state["native_reports"] == 0


@pytest.mark.parametrize("kind", ["missing", "older", "uncallable"])
def test_batch_helper_unavailable_keeps_python_profile(monkeypatch, kind):
    def unavailable(name):
        assert name == "pytest_boorst._native"
        if kind == "missing":
            raise ImportError("native helper unavailable")
        if kind == "uncallable":
            return SimpleNamespace(sum_report_batch=None)
        return SimpleNamespace()

    monkeypatch.setattr(_profile.importlib, "import_module", unavailable)
    profiler = _profile.Profiler(SimpleNamespace(), batch_reporting=True)
    profiler.pytest_runtest_logreport(SimpleNamespace(when="call", duration=0.5))
    data = profiler.snapshot()
    assert data["reported_phase_sum"]["call"] == 0.5
    assert data["batch_reporting"]["status"] == "fallback"
    assert data["batch_reporting"]["reason"] == "native batch helper unavailable"


def test_unsupported_batch_runtime_does_not_import_native(monkeypatch):
    def unexpected(name):
        raise AssertionError("unsupported runtime must not load native code")

    monkeypatch.setattr(_profile.pytest, "__version__", "10.0.0")
    monkeypatch.setattr(_profile.importlib, "import_module", unexpected)
    profiler = _profile.Profiler(SimpleNamespace(), batch_reporting=True)
    assert profiler.batch_state["reason"] == "unsupported runtime"


@pytest.mark.parametrize("workers", [(), ("-n", "2")])
def test_batch_profile_preserves_reports_outcomes_and_junit(
    pytester, monkeypatch, workers
):
    monkeypatch.delenv("PYTEST_BOORST", raising=False)
    pytester.makeconftest("""
        import json
        from pathlib import Path
        import pytest
        reports = []
        totals = dict.fromkeys(("setup", "call", "teardown"), 0.0)
        def pytest_runtest_logreport(report):
            reports.append((report.nodeid, report.when, report.outcome,
                            getattr(report, "wasxfail", None)))
            totals[report.when] += report.duration
        @pytest.hookimpl(trylast=True)
        def pytest_sessionfinish(session, exitstatus):
            if hasattr(session.config, "workerinput"):
                return
            profiler = session.config.pluginmanager.get_plugin("boorst_profile")
            boorst = session.config.pluginmanager.get_plugin("boorst")
            Path("receipt.json").write_text(json.dumps({
                "profile": profiler.snapshot(), "reports": sorted(reports),
                "totals": totals, "exitstatus": int(exitstatus),
                "state": session.config.stash[boorst.STATE_KEY],
            }))
    """)
    pytester.makepyfile(
        test_outcomes="""
        import pytest
        def test_pass():
            assert True
        def test_fail():
            assert False
        @pytest.mark.skip(reason="example skip")
        def test_skip():
            pass
        @pytest.mark.xfail(reason="example xfail", strict=True)
        def test_xfail():
            assert False
    """
    )

    def run(flag, xml):
        result = pytester.runpytest_subprocess(
            "-q", flag, f"--junitxml={xml}", *workers
        )
        result.assert_outcomes(passed=1, failed=1, skipped=1, xfailed=1)
        receipt = json.loads((pytester.path / "receipt.json").read_text())
        assert result.ret == receipt["exitstatus"] == 1
        assert receipt["totals"] == receipt["profile"]["reported_phase_sum"]
        assert receipt["state"]["status"] == "disabled"
        cases = sorted(
            (
                case.get("classname"),
                case.get("name"),
                tuple(
                    (child.tag, child.get("type"), child.get("message"))
                    for child in case
                ),
            )
            for case in ElementTree.parse(pytester.path / xml).iter("testcase")
        )
        return result, receipt, cases

    _, stock, stock_xml = run("--boorst-profile", "stock.xml")
    active, candidate, candidate_xml = run("--boorst-batch-reporting", "batch.xml")
    assert stock["reports"] == candidate["reports"]
    assert stock_xml == candidate_xml
    assert "batch_reporting" not in stock["profile"]
    state = candidate["profile"]["batch_reporting"]
    assert state["status"] == "native"
    assert state["native_reports"] == len(candidate["reports"])
    active.stdout.fnmatch_lines(
        ["*boorst profile*", "*Batch phase aggregation: native*"]
    )
    if workers:
        active.stdout.fnmatch_lines(
            ["*Worker batch aggregation: 2 native, 0 fallback*"]
        )
