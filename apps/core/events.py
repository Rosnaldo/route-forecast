"""
A tiny in-process event bus (DDD "domain events").

The publisher (a service) does not know who reacts to an event; handlers in
other apps subscribe at startup (AppConfig.ready). Handlers run only after the
DB transaction commits, so they never act on data that is later rolled back.
"""

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import partial, update_wrapper

from django.db import transaction


@dataclass(frozen=True, kw_only=True)
class DomainEvent:
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))


type Handler = Callable[[DomainEvent], None]

_handlers: dict[type[DomainEvent], list[Handler]] = defaultdict(list)


def subscribe(event_type: type[DomainEvent]) -> Callable[[Handler], Handler]:
    """Decorator: @subscribe(SomethingHappened) def handler(event): ..."""

    def decorator(func: Handler) -> Handler:
        if func not in _handlers[event_type]:
            _handlers[event_type].append(func)
        return func

    return decorator


def publish(event: DomainEvent) -> None:
    for handler in _handlers[type(event)]:
        # robust=True: a failing handler is logged and does not stop the others.
        # update_wrapper gives the partial the handler's __qualname__, which
        # Django's robust error logging needs.
        callback = update_wrapper(partial(handler, event), handler)
        transaction.on_commit(callback, robust=True)
