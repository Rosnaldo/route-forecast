# Architecture conventions

This base has no business domain yet. These are the conventions for adding one.
They are applied with judgement: full layering where the rules are rich, a plain
view where it is just glue. There is no database: state lives in Redis (cache)
and S3 (files).

```
     HTTP / Celery / management commands                 <- driving adapters
                          │
          views.py · tasks.py                             (thin: parse, call, serialize)
                          │  serializers validate input and build commands
                          ▼
          services.py   application layer: one function/method per use case
                          │
                          ▼
          domain.py     pure Python: dataclasses, rules, domain exceptions,
                        events, and PORTS (typing.Protocol) for what it needs
                          ▲
                          │ implements ports
          adapters      clients for external APIs (weather, maps), Redis/S3 storage
```

## Building blocks already in `apps/core`

| Piece | File | Use it for |
|---|---|---|
| Domain exceptions | [core/exceptions.py](../apps/core/exceptions.py) | Raise `DomainError` / `NotFoundError` / `ConflictError` / `PermissionDeniedError` from domain or service code. No DRF import. |
| HTTP mapping | [core/exception_handler.py](../apps/core/exception_handler.py) | Converts domain exceptions into `{"code", "detail", ...}` responses with the right status. |
| Domain events | [core/events.py](../apps/core/events.py) | `publish(Event(...))` in a service; `@subscribe(Event)` handlers in other apps run immediately, isolated from each other's failures. |
| Pagination | [core/pagination.py](../apps/core/pagination.py) | Page-number by default; cursor pagination for feeds. |
| Utilities | [core/utils/](../apps/core/utils/) | `retry` decorator, `Timer`, `log_duration`, `chunked`, CSV streaming. |
| Request context | [core/middleware.py](../apps/core/middleware.py), [core/logging.py](../apps/core/logging.py) | Request ID on every log line and response. |

## Rules of thumb

- **Domain code is pure.** `domain.py` imports no Django, DRF or HTTP
  clients, so its rules are unit-testable without Redis or network.
- **External services sit behind ports.** Define a `Protocol` in the domain and
  implement it in an adapter module. Tests pass fakes, production passes the
  real client.
- **Tasks take plain, serializable arguments** (coordinates, run times) and are
  idempotent, so a retried task does no harm.
- **Don't over-layer.** An adapter that only wraps `cache.get()` is
  ceremony; layer where real rules live.
