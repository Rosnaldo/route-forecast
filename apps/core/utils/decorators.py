"""
Decorators: functions that take a function and return a new one.
`functools.wraps` keeps the original __name__/__doc__ (important for logging,
Celery task names, DRF introspection...). ParamSpec keeps the type signature.
"""

import functools
import logging
import time
from collections.abc import Callable

logger = logging.getLogger(__name__)


def timed[**P, R](func: Callable[P, R]) -> Callable[P, R]:
    """Simple decorator (no arguments): logs how long the call took."""

    @functools.wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        start = time.perf_counter()
        try:
            return func(*args, **kwargs)
        finally:
            logger.debug("%s took %.2fms", func.__qualname__, (time.perf_counter() - start) * 1000)

    return wrapper


def retry[**P, R](
    *,
    exceptions: tuple[type[BaseException], ...] = (Exception,),
    attempts: int = 3,
    backoff: float = 0.1,
    sleep: Callable[[float], None] = time.sleep,
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Decorator factory (takes arguments): retries with exponential backoff.

    @retry(exceptions=(ConnectionError,), attempts=5)
    def call_payment_gateway(): ...
    """

    def decorator(func: Callable[P, R]) -> Callable[P, R]:
        @functools.wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            for attempt in range(1, attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as exc:
                    if attempt == attempts:
                        raise
                    delay = backoff * 2 ** (attempt - 1)
                    logger.warning(
                        "%s failed (%s), retry %d in %.2fs", func.__name__, exc, attempt, delay
                    )
                    sleep(delay)
            raise AssertionError("unreachable")

        return wrapper

    return decorator
