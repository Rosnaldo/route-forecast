# Architecture conventions

This base has no business domain yet. These are the conventions for adding one.
They are applied with judgement: full layering where the rules are rich, plain
ModelViewSets where it is just CRUD.

```
     HTTP / Celery / management commands                 <- driving adapters
                          │
          views.py · tasks.py                             (thin: parse, call, serialize)
                          │  serializers validate input and build commands
                          ▼
          services.py   application layer: one function/method per use case,
                        owns the transaction boundary
          queries.py    read side (CQRS): optimised queries returning plain data
                          │
                          ▼
          domain.py     pure Python: dataclasses, rules, domain exceptions,
                        events, and PORTS (typing.Protocol) for what it needs
                          ▲
                          │ implements ports
          adapters      repositories.py (ORM), clients for external APIs
```

## Building blocks already in `apps/core`

| Piece | File | Use it for |
|---|---|---|
| Domain exceptions | [core/exceptions.py](../apps/core/exceptions.py) | Raise `DomainError` / `NotFoundError` / `ConflictError` / `PermissionDeniedError` from domain or service code. No DRF import. |
| HTTP mapping | [core/exception_handler.py](../apps/core/exception_handler.py) | Converts domain exceptions into `{"code", "detail", ...}` responses with the right status. |
| Domain events | [core/events.py](../apps/core/events.py) | `publish(Event(...))` in a service; `@subscribe(Event)` handlers in other apps run **after commit**, isolated from each other's failures. |
| Base model | [core/models.py](../apps/core/models.py) | `TimeStampedModel` (`created_at`, `updated_at`). |
| Pagination | [core/pagination.py](../apps/core/pagination.py) | Page-number by default; cursor pagination for feeds. |
| Utilities | [core/utils/](../apps/core/utils/) | `retry` decorator, `Timer`, `count_queries`, `chunked`, CSV streaming. |
| Request context | [core/middleware.py](../apps/core/middleware.py), [core/logging.py](../apps/core/logging.py) | Request ID on every log line and response. |

## Rules of thumb

- **Domain code is pure.** `domain.py` imports no Django ORM, DRF or HTTP
  clients, so its rules are unit-testable without a database or network.
- **External services sit behind ports.** Define a `Protocol` in the domain and
  implement it in an adapter module. Tests pass fakes, production passes the
  real client.
- **Services own transactions** (`transaction.atomic()`); views never do.
- **Tasks take IDs, not objects,** are idempotent, and are enqueued with
  `transaction.on_commit`.
- **Don't over-layer.** A repository that only wraps `Model.objects.get()` is
  ceremony; layer where real rules live.
