"""
Context managers: setup/teardown around a `with` block, guaranteed to run the
teardown even if the block raises. Two ways to write them: a class with
__enter__/__exit__, or a generator decorated with @contextmanager.
"""

import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from types import TracebackType

logger = logging.getLogger(__name__)


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
def log_duration(label: str) -> Iterator[None]:
    """Generator-based context manager: logs how long the block took, even if it raises.

    with log_duration("fetch forecast"):
        fetch_forecast()
    """
    start = time.perf_counter()
    try:
        yield
    finally:
        logger.info("%s took %.1f ms", label, (time.perf_counter() - start) * 1000)
