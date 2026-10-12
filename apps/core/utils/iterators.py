"""
Iterators and generators.

A generator function (`yield`) produces values lazily, one at a time, so you can
process millions of rows with constant memory — e.g. streaming a CSV export.
"""

import csv
from collections.abc import Iterable, Iterator
from itertools import islice


def chunked[T](iterable: Iterable[T], size: int) -> Iterator[list[T]]:
    """Yield lists of `size` items: chunked(range(5), 2) -> [0,1] [2,3] [4]."""
    iterator = iter(iterable)
    while chunk := list(islice(iterator, size)):
        yield chunk


class Echo:
    """A file-like object whose write() returns the value instead of storing it.
    Lets csv.writer produce strings we can `yield` to a StreamingHttpResponse."""

    def write(self, value: str) -> str:
        return value


def csv_rows(header: list[str], rows: Iterable[Iterable[object]]) -> Iterator[str]:
    writer = csv.writer(Echo())
    yield writer.writerow(header)
    for row in rows:
        yield writer.writerow(row)


class Countdown:
    """The iterator protocol by hand (__iter__ + __next__), what a generator
    gives you for free. Kept small on purpose, as a reference."""

    def __init__(self, start: int) -> None:
        self.current = start

    def __iter__(self) -> "Countdown":
        return self

    def __next__(self) -> int:
        if self.current <= 0:
            raise StopIteration
        self.current -= 1
        return self.current + 1
