"""
A tiny in-process event bus (DDD "domain events").

The publisher (a service) does not know who reacts to an event; handlers in
other apps subscribe at startup (AppConfig.ready). Handlers run synchronously,
in subscription order; one failing handler is logged and does not stop the others.
"""

import logging
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

logger = logging.getLogger(__name__)


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
        try:
            handler(event)
        except Exception:
            logger.exception("Event handler %s failed for %r", handler.__qualname__, event)
