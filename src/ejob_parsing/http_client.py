"""Обёртка над curl_cffi: TLS-имитация Chrome, ретраи, задержки, логирование.

Покрывает F-1.2 (TLS-отпечаток), F-1.8 (ошибки сети и 403/429),
задержки между запросами и опциональную ротацию User-Agent.
"""

from __future__ import annotations

import random
import time
from typing import Any

from curl_cffi import requests as cffi_requests
from curl_cffi.requests import Response, Session
from curl_cffi.requests.errors import RequestsError
from loguru import logger
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from ejob_parsing.config import Settings, get_settings

DEFAULT_HEADERS = {
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.5",
}

RETRYABLE_STATUS = {403, 429, 500, 502, 503, 504}


class RetryableHttpError(RuntimeError):
    """Ошибка, после которой стоит повторить запрос (403/429/5xx/сеть)."""


class NonRetryableHttpError(RuntimeError):
    """HTTP-ошибка, которую повторять не нужно (400/404/410 и т.п.)."""


class HttpClient:
    """Сессия curl_cffi с ретраями и человекоподобными паузами."""

    def __init__(
        self, settings: Settings | None = None, *, impersonate: str = "chrome"
    ) -> None:
        self.settings = settings or get_settings()
        self.impersonate = impersonate
        self.session: Session = cffi_requests.Session(
            impersonate=impersonate,
            timeout=self.settings.request_timeout,
        )
        if self.settings.proxy_url:
            self.session.proxies = {
                "http": self.settings.proxy_url,
                "https": self.settings.proxy_url,
            }
        # Декорируем _get ретраями с настройками из .env (tenacity).
        # Ретраим 403/429/5xx (RetryableHttpError) и сетевые сбои curl_cffi
        # (например, curl: (16) HTTP/2 stream error — сервер рвёт соединение).
        self.get = retry(
            stop=stop_after_attempt(self.settings.retry_attempts),
            wait=wait_exponential(
                multiplier=self.settings.retry_wait_seconds, min=1, max=60
            ),
            retry=retry_if_exception_type((RetryableHttpError, RequestsError)),
            before_sleep=lambda state: logger.warning(
                "Повторяю запрос (попытка {} из {})...",
                state.attempt_number + 1,
                self.settings.retry_attempts,
            ),
            reraise=True,
        )(self._get)

    def _get(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Response:
        """Один GET-запрос: пауза перед запросом, проверка статуса, ретрай при 403/429."""
        time.sleep(
            random.uniform(
                self.settings.request_delay_min, self.settings.request_delay_max
            )
        )
        request_headers = {**DEFAULT_HEADERS, **(headers or {})}
        if self.settings.rotate_user_agent:
            request_headers["User-Agent"] = self._random_user_agent()
        resp = self.session.get(url, params=params, headers=request_headers)
        logger.debug("GET {} -> {}", url, resp.status_code)
        if resp.status_code in RETRYABLE_STATUS:
            raise RetryableHttpError(f"HTTP {resp.status_code} for {url}")
        if resp.status_code >= 400:
            # Не ретраим: 400/404/410 и т.п. вернут одно и то же
            raise NonRetryableHttpError(f"HTTP {resp.status_code} for {url}")
        return resp

    @staticmethod
    def _random_user_agent() -> str:
        """Ротация User-Agent через fake-useragent (ленивый импорт)."""
        from fake_useragent import UserAgent

        return UserAgent().random

    def close(self) -> None:
        self.session.close()

    def __enter__(self) -> HttpClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
