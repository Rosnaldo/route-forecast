"""
Context managers: setup/teardown around a `with` block, guaranteed to run the
teardown even if the block raises. Two ways to write them: a class with
__enter__/__exit__, or a generator decorated with @contextmanager.
"""

import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from types import TracebackType

from django.db import connection
from django.test.utils import CaptureQueriesContext


@dataclass
class Timer:
    """Class-based context manager.

    with Timer() as t:
        do_work()
    print(t.elapsed_ms)
    """

    elapsed_ms: float = 0.0
    _start: float = field(default=0.0, repr=False)

    def __enter__(self) -> "Timer":
        self._start = time.perf_counter()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool:
        self.elapsed_ms = (time.perf_counter() - self._start) * 1000
        return False  # do not swallow exceptions


@contextmanager
def count_queries() -> Iterator[CaptureQueriesContext]:
    """Generator-based context manager that records SQL executed in the block.
    Works even with DEBUG=False; handy for spotting N+1 queries.

    with count_queries() as ctx:
        list(User.objects.all())
    len(ctx.captured_queries)
    """
    with CaptureQueriesContext(connection) as ctx:
        yield ctx
