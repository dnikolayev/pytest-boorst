import itertools
import random
from types import SimpleNamespace

import pytest
from _pytest.python import IdMaker
from pytest_boorst._ids import unique_ids
from pytest_boorst.plugin import _ORIGINAL


def stock_ids(ids):
    maker = SimpleNamespace(
        _resolve_ids=lambda: iter(ids),
        _strict_parametrization_ids_enabled=lambda: False,
    )
    return _ORIGINAL(maker)


def test_native_and_python_match_stock():
    from pytest_boorst import _native

    rng = random.Random(814)
    alphabet = ["", "a", "a0", "a1", "a_0", "b", "0", "9", "a0_0", "\x00"]
    cases = list(itertools.product(alphabet[:5], repeat=4))
    cases += [rng.choices(alphabet, k=rng.randrange(100)) for _ in range(2500)]
    cases += [["a0", "a0", "a", "a"], ["x"] * 1000]
    for values in cases:
        values = list(values)
        before = values.copy()
        expected = stock_ids(values)
        assert unique_ids(values) == expected
        assert _native.unique_ids(values) == expected
        assert values == before


@pytest.mark.parametrize("values", [["é", "é"], ["x²", "x²"], ["\ud800", "\ud800"]])
def test_python_comparison_handles_python_strings(values):
    assert unique_ids(values) == stock_ids(values)


def test_stock_oracle_is_original():
    # The package stays disabled during its own tests unless explicitly requested.
    assert IdMaker.make_unique_parameterset_ids is _ORIGINAL
