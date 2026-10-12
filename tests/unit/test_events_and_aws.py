import os
from dataclasses import dataclass
from unittest import mock

from apps.core import aws
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


def test_load_secrets_does_not_override_existing_env(monkeypatch):
    monkeypatch.setenv("AWS_SECRETS_ID", "shop/prod")
    monkeypatch.setenv("SECRET_KEY", "from-env")
    monkeypatch.delenv("REDIS_URL_TEST_ONLY", raising=False)
    secret = {"SECRET_KEY": "from-secret", "REDIS_URL_TEST_ONLY": "redis://x"}

    with mock.patch.object(aws, "get_secret", return_value=secret):
        aws.load_secrets_into_environ()

    assert os.environ["SECRET_KEY"] == "from-env"
    assert os.environ["REDIS_URL_TEST_ONLY"] == "redis://x"
    monkeypatch.delenv("REDIS_URL_TEST_ONLY")


def test_load_secrets_is_noop_without_secret_id(monkeypatch):
    monkeypatch.delenv("AWS_SECRETS_ID", raising=False)
    with mock.patch.object(aws, "get_secret") as get_secret:
        aws.load_secrets_into_environ()
    get_secret.assert_not_called()
