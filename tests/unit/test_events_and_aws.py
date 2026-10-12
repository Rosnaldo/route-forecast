import os
from dataclasses import dataclass
from unittest import mock

import pytest

from apps.core import aws
from apps.core.events import DomainEvent, publish, subscribe


@dataclass(frozen=True, kw_only=True)
class SomethingHappened(DomainEvent):
    value: int


@pytest.mark.django_db
def test_handlers_run_only_on_commit_and_failures_are_isolated(django_capture_on_commit_callbacks):
    received = []

    @subscribe(SomethingHappened)
    def broken(event):
        raise RuntimeError("boom")

    @subscribe(SomethingHappened)
    def recorder(event):
        received.append(event.value)

    # execute=True runs the hooks the way a real commit does (honouring robust=True).
    with django_capture_on_commit_callbacks(execute=True):
        publish(SomethingHappened(value=1))
        assert received == []  # nothing before commit

    assert received == [1]  # `broken` raised, yet `recorder` still ran


def test_load_secrets_does_not_override_existing_env(monkeypatch):
    monkeypatch.setenv("AWS_SECRETS_ID", "shop/prod")
    monkeypatch.setenv("SECRET_KEY", "from-env")
    monkeypatch.delenv("DATABASE_URL_TEST_ONLY", raising=False)
    secret = {"SECRET_KEY": "from-secret", "DATABASE_URL_TEST_ONLY": "postgres://x"}

    with mock.patch.object(aws, "get_secret", return_value=secret):
        aws.load_secrets_into_environ()

    assert os.environ["SECRET_KEY"] == "from-env"
    assert os.environ["DATABASE_URL_TEST_ONLY"] == "postgres://x"
    monkeypatch.delenv("DATABASE_URL_TEST_ONLY")


def test_load_secrets_is_noop_without_secret_id(monkeypatch):
    monkeypatch.delenv("AWS_SECRETS_ID", raising=False)
    with mock.patch.object(aws, "get_secret") as get_secret:
        aws.load_secrets_into_environ()
    get_secret.assert_not_called()
