from dataclasses import dataclass

from apps.core.events import DomainEvent, publish, subscribe


@dataclass(frozen=True, kw_only=True)
class SomethingHappened(DomainEvent):
    value: int


def test_failing_handler_does_not_stop_the_others(caplog):
    received = []

    @subscribe(SomethingHappened)
    def broken(event):
        raise RuntimeError("boom")

    @subscribe(SomethingHappened)
    def recorder(event):
        received.append(event.value)

    publish(SomethingHappened(value=1))

    assert received == [1]  # `broken` raised, yet `recorder` still ran
    assert "broken failed" in caplog.text
