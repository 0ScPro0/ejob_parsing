"""Тесты HTTP-клиента: ретраи на сетевые ошибки и 5xx, отсутствие ретрая на 4xx."""

from __future__ import annotations

from typing import Any

import pytest
from curl_cffi.requests.errors import RequestsError

from ejob_parsing.http_client import (
    HttpClient,
    NonRetryableHttpError,
    RetryableHttpError,
)
from tests._settings import make_settings


class FakeResponse:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code

    @property
    def text(self) -> str:
        return ""


class FakeSession:
    """Подменяет curl_cffi Session: заданное поведение и счётчик вызовов."""

    def __init__(self, behavior: Any) -> None:
        self.behavior = behavior
        self.calls = 0

    def get(self, *args: Any, **kwargs: Any) -> Any:
        self.calls += 1
        if isinstance(self.behavior, Exception):
            raise self.behavior
        return self.behavior


def _make_client(
    monkeypatch: pytest.MonkeyPatch, behavior: Any
) -> tuple[HttpClient, FakeSession]:
    fake_session = FakeSession(behavior)
    monkeypatch.setattr(
        "ejob_parsing.http_client.cffi_requests.Session", lambda **kw: fake_session
    )
    client = HttpClient(
        make_settings(
            retry_attempts=2,
            retry_wait_seconds=0.01,
            request_delay_min=0.0,
            request_delay_max=0.0,
        )
    )
    return client, fake_session


def test_retries_on_network_error(monkeypatch: pytest.MonkeyPatch) -> None:
    # curl: (16) HTTP/2 stream error и подобные сетевые сбои должны ретраиться
    error = RequestsError("Failed to perform, curl: (16)")
    client, session = _make_client(monkeypatch, error)
    with pytest.raises(RequestsError):
        client.get("https://hh.ru/vacancy/1")
    assert session.calls == 2  # первая попытка + один ретрай


def test_retries_on_503(monkeypatch: pytest.MonkeyPatch) -> None:
    client, session = _make_client(monkeypatch, FakeResponse(503))
    with pytest.raises(RetryableHttpError):
        client.get("https://hh.ru/search/vacancy")
    assert session.calls == 2


def test_no_retry_on_404(monkeypatch: pytest.MonkeyPatch) -> None:
    client, session = _make_client(monkeypatch, FakeResponse(404))
    with pytest.raises(NonRetryableHttpError):
        client.get("https://hh.ru/vacancy/999")
    assert session.calls == 1  # 404 не повторяется


def test_success_on_first_try(monkeypatch: pytest.MonkeyPatch) -> None:
    client, session = _make_client(monkeypatch, FakeResponse(200))
    response = client.get("https://hh.ru/search/vacancy")
    assert response.status_code == 200
    assert session.calls == 1
