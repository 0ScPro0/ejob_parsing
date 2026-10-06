"""Тесты ИИ-аналитики: парсинг ответа, промпт, анализ вакансий."""

from __future__ import annotations

from typing import Any, cast

import pytest

from ejob_parsing.ai import (
    DEFAULT_SYSTEM_PROMPT,
    OpenAIClient,
    _normalize_content,
    _system_prompt,
    analyze_vacancies,
    build_user_prompt,
    extract_json,
)
from tests._settings import make_settings


def test_extract_json_plain() -> None:
    data = extract_json('{"terms": [{"term": "Python", "count": 10}]}')
    assert data["terms"][0]["term"] == "Python"


def test_extract_json_from_markdown_block() -> None:
    text = 'Конечно! Вот результат:\n```json\n{"terms": [{"term": "Docker", "count": 5}]}\n```'
    data = extract_json(text)
    assert data["terms"][0]["count"] == 5


def test_extract_json_ignores_prose() -> None:
    assert extract_json("Мне сложно ответить на этот вопрос.") == {}


def test_extract_json_accepts_dict() -> None:
    data = extract_json({"terms": [{"term": "Python", "count": 1}]})
    assert data["terms"][0]["term"] == "Python"


def test_normalize_content_list_of_parts() -> None:
    # openai SDK 3.x может вернуть content списком частей
    content = _normalize_content([{"type": "text", "text": "Сводка"}])
    assert content == "Сводка"


def test_system_prompt_default() -> None:
    prompt = _system_prompt(make_settings())
    assert prompt == DEFAULT_SYSTEM_PROMPT
    assert "сопроводительного письма" in prompt


def test_system_prompt_overridden_from_env() -> None:
    custom = "Ты — помощник. Отвечай кратко."
    prompt = _system_prompt(make_settings(openai_system_prompt=custom))
    assert prompt == custom


def test_system_prompt_unwraps_newlines() -> None:
    prompt = _system_prompt(make_settings(openai_system_prompt="Строка1\\nСтрока2"))
    assert prompt == "Строка1\nСтрока2"


def test_build_user_prompt_includes_url_and_fields() -> None:
    settings = make_settings()
    vacancies = [
        {
            "name": "Backend Developer",
            "employer": {"name": "ООО Ромашка"},
            "salary": {"from": 200000, "to": 300000},
            "area": {"name": "Москва"},
            "experience": "3–6 лет",
            "description": "Разработка на Python",
            "url": "https://hh.ru/vacancy/123",
        }
    ]
    prompt = build_user_prompt(vacancies, settings)
    assert "### Backend Developer" in prompt
    assert "ООО Ромашка" in prompt
    assert "https://hh.ru/vacancy/123" in prompt


def test_analyze_vacancies_with_fake_client() -> None:
    class FakeClient:
        model = "fake"

        def __init__(self, settings: Any) -> None:
            self.settings = settings
            self.calls: list[tuple[str, str]] = []

        def chat_text(self, system: str, user: str) -> str:
            self.calls.append((system, user))
            return "Сводка по вакансиям.\nСсылка: https://hh.ru/vacancy/1"

    settings = make_settings()
    client = cast(Any, FakeClient(settings))
    result = analyze_vacancies(
        client, [{"name": "Dev", "url": "https://hh.ru/vacancy/1"}]
    )
    assert "Сводка по вакансиям" in result
    assert len(client.calls) == 1
    assert client.calls[0][0] == DEFAULT_SYSTEM_PROMPT


def test_openai_client_requires_api_key() -> None:
    settings = make_settings(openai_api_key=None)
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        OpenAIClient(settings)
