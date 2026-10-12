"""ИИ-аналитика вакансий (OpenAI) для модуля ключевых слов.

Пакет openai входит в базовый uv sync, нужен только OPENAI_API_KEY в .env.
Задача: на основе уже собранных вакансий (без сети!) составить общую сводку
по рынку, указав ссылку на каждую вакансию и приложив пример сопроводительного
письма. Результат сохраняется в ai_analytics.txt.

Системный промпт можно переопределить через OPENAI_SYSTEM_PROMPT в .env
(многострочный текст — с \\n). Дефолтный промпт — ниже.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from typing import Any

from loguru import logger

from ejob_parsing.config import Settings, get_settings
from ejob_parsing.exceptions import AIGenerationError

JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)

DEFAULT_SYSTEM_PROMPT = """\
Ты — карьерный аналитик. Перед тобой список вакансий с hh.ru: название, \
работодатель, зарплата, город, требуемый опыт, краткое описание и ссылка.

Составь структурированный отчёт (Markdown, по-русски):
1. Общая сводка по рынку: какие роли встречаются, диапазоны зарплат, \
основные технологии и требования, что выделяется.
2. По каждой вакансии: краткая справка (суть роли, почему она может быть \
интересна соискателю) и готовый пример сопроводительного письма из 3-6 \
предложений, которое соискатель может отправить при отклике.
3. Для каждой вакансии обязательно указывай ссылку на неё (URL).

Не выдумывай данные: опирайся только на предоставленную информацию. Выражайся кратко
"""


def _system_prompt(settings: Settings) -> str:
    """Системный промпт: из .env (OPENAI_SYSTEM_PROMPT) или дефолтный."""
    if settings.openai_system_prompt and settings.openai_system_prompt.strip():
        return settings.openai_system_prompt.replace("\\n", "\n")
    return DEFAULT_SYSTEM_PROMPT


def _format_vacancy(item: dict[str, Any], char_limit: int) -> str:
    """Одна вакансия в тексте для модели: заголовок + ключевые поля + URL."""
    employer = (item.get("employer") or {}).get("name") or "—"
    salary = item.get("salary") or {}
    if salary.get("from") or salary.get("to"):
        salary_text = f"{salary.get('from') or '?'} - {salary.get('to') or '?'}"
    else:
        salary_text = "не указана"
    area = (item.get("area") or {}).get("name") or "—"
    description = (item.get("description") or "").replace("\n", " ")[:char_limit]
    return (
        f"### {item.get('name') or 'Без названия'}\n"
        f"- Работодатель: {employer}\n"
        f"- Зарплата: {salary_text}\n"
        f"- Город: {area}\n"
        f"- Опыт: {item.get('experience') or 'не указан'}\n"
        f"- Ссылка: {item.get('url') or '—'}\n"
        f"- Описание: {description}\n"
    )


def build_user_prompt(vacancies: Iterable[dict[str, Any]], settings: Settings) -> str:
    """Формирует user-сообщение: вакансии в пределах лимита."""
    blocks = [
        _format_vacancy(item, settings.ai_text_char_limit)
        for item in list(vacancies)[: settings.ai_vacancies_limit]
    ]
    if not blocks:
        return "Вакансий нет."
    return "Список вакансий:\n\n" + "\n\n".join(blocks)


def extract_json(text: Any) -> dict[str, Any]:
    """Достаёт JSON-объект из ответа модели (в т.ч. внутри ```json блоков).

    Принимает и готовый dict (уже распарсенный SDK), и строку, и список
    контент-частей (openai SDK 3.x) — никогда не бросает исключений.
    """
    if isinstance(text, dict):
        return text
    if not isinstance(text, str):
        return {}
    raw = text.strip()
    if not raw:
        return {}
    match = JSON_BLOCK_RE.search(raw)
    if match is not None:
        raw = match.group(1)
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        start, end = raw.find("{"), raw.rfind("}")
        if start != -1 and end > start:
            try:
                data = json.loads(raw[start : end + 1])
                return data if isinstance(data, dict) else {}
            except json.JSONDecodeError:
                pass
        logger.warning("Не удалось распарсить JSON из ответа модели: {}", raw[:200])
        return {}


def _normalize_content(content: Any) -> str:
    """openai SDK 3.x может вернуть message.content как список частей."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict):
                text = part.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts)
    return str(content)


class OpenAIClient:
    """Тонкая обёртка над openai SDK с настройками из .env."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        if not self.settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY не задан — добавьте его в .env")
        from openai import OpenAI  # lazy import (пакет входит в базовый uv sync)

        self.model = self.settings.openai_model
        self.client = OpenAI(
            api_key=self.settings.openai_api_key.get_secret_value(),
            base_url=self.settings.openai_base_url,
            timeout=self.settings.openai_timeout,
        )

    def chat_text(self, system: str, user: str) -> str:
        """Один вызов chat.completions, возвращает текст ответа модели."""
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            # temperature=0.5,
        )
        return _normalize_content(response.choices[0].message.content)


def analyze_vacancies(client: OpenAIClient, vacancies: list[dict[str, Any]]) -> str:
    """Сводка по вакансиям: общий анализ, ссылки, примеры сопроводительных писем."""
    system = _system_prompt(client.settings)
    user = build_user_prompt(vacancies, client.settings)
    try:
        return client.chat_text(system, user).strip()
    except Exception as exc:
        raise AIGenerationError(exc) from exc
