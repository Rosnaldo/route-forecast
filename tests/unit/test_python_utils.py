"""Phase 1: decorators, context managers, iterators/generators."""

import logging

import pytest

from apps.core.utils.context_managers import Timer
from apps.core.utils.decorators import retry, timed
from apps.core.utils.iterators import Countdown, chunked, csv_rows


def test_timed_preserves_metadata_and_result(caplog):
    @timed
    def add(a: int, b: int) -> int:
        """Adds."""
        return a + b

    with caplog.at_level(logging.DEBUG):
        assert add(2, 3) == 5
    assert add.__name__ == "add" and add.__doc__ == "Adds."  # functools.wraps
    assert "took" in caplog.text


def test_retry_retries_with_exponential_backoff():
    sleeps: list[float] = []
    calls = {"n": 0}

    @retry(exceptions=(ConnectionError,), attempts=3, backoff=0.5, sleep=sleeps.append)
    def flaky() -> str:
        calls["n"] += 1
        if calls["n"] < 3:
            raise ConnectionError("down")
        return "ok"

    assert flaky() == "ok"
    assert sleeps == [0.5, 1.0]


def test_retry_gives_up_and_reraises():
    @retry(exceptions=(ValueError,), attempts=2, sleep=lambda _: None)
    def always_fails():
        raise ValueError("nope")

    with pytest.raises(ValueError):
        always_fails()


def test_retry_does_not_catch_other_exceptions():
    @retry(exceptions=(ValueError,), sleep=lambda _: None)
    def boom():
        raise KeyError("x")

    with pytest.raises(KeyError):
        boom()


def test_timer_context_manager_measures_and_propagates():
    with Timer() as t:
        sum(range(1000))
    assert t.elapsed_ms > 0

    with pytest.raises(ZeroDivisionError), Timer() as t2:
        1 / 0  # noqa: B018
    assert t2.elapsed_ms > 0  # __exit__ ran anyway


def test_chunked_generator_is_lazy():
    def numbers():
        yield from range(5)

    gen = chunked(numbers(), 2)
    assert next(gen) == [0, 1]
    assert list(gen) == [[2, 3], [4]]


def test_csv_rows_streams_lines():
    lines = list(csv_rows(["a", "b"], ([i, i * 2] for i in range(2))))
    assert lines == ["a,b\r\n", "0,0\r\n", "1,2\r\n"]


def test_iterator_protocol():
    assert list(Countdown(3)) == [3, 2, 1]
    assert [x * 2 for x in Countdown(2)] == [4, 2]  # works with comprehensions
    assert {x: x**2 for x in Countdown(2)} == {2: 4, 1: 1}
