"""Модуль 1: сбор вакансий hh.ru (F-1.1 .. F-1.8).

Поток: запрос /search/vacancy -> вытащить template HH-Lux-InitialState ->
распарсить вакансии -> дедупликация -> дописать в vacancies/*.jsonl.
"""

from __future__ import annotations

import re
from itertools import product
from pathlib import Path
from typing import Any, cast

import orjson
from loguru import logger
from selectolax.lexbor import LexborHTMLParser

from ejob_parsing.config import Settings, get_settings
from ejob_parsing.http_client import HttpClient
from ejob_parsing.models import Area, Employer, Salary, Vacancy
from ejob_parsing.storage import JsonlDedupStore

SEARCH_URL = "https://hh.ru/search/vacancy"

# Встроенный JSON со списком вакансий лежит в этом template (F-1.3)
INITIAL_STATE_RE = re.compile(
    r'<template\s+id="HH-Lux-InitialState"[^>]*>(.*?)</template>', re.DOTALL
)


# ── Построение запросов (F-1.1) ─────────────────────────────────────────


def build_search_queries(settings: Settings | None = None) -> list[dict[str, str]]:
    """Генерирует поисковые запросы: уровень x направление + все технологии.

    Пример: {"text": "middle fullstack python go js ai", "experience": "between3And6"}
    Если нужно дробить по регионам/технологиям (R-2), расширяем здесь.
    """
    s = settings or get_settings()
    queries: list[dict[str, str]] = []
    for level, direction in product(s.search_levels, s.search_directions):
        text = " ".join(filter(None, [level, direction, *s.search_technologies]))
        queries.append({"text": text, "experience": s.search_experience.value})
    return queries


# ── Извлечение и маппинг данных ─────────────────────────────────────────


def extract_initial_state(html: str) -> dict[str, Any]:
    """Достаёт JSON из <template id="HH-Lux-InitialState"> (F-1.3)."""
    match = INITIAL_STATE_RE.search(html)
    if match is None:
        raise ValueError("Блок HH-Lux-InitialState не найден на странице")
    return cast("dict[str, Any]", orjson.loads(match.group(1)))


def get_vacancies(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Список сырых вакансий из состояния страницы."""
    return (state.get("vacancySearchResult") or {}).get("vacancies") or []


def get_pages_total(state: dict[str, Any]) -> int | None:
    """Общее число страниц выдачи из блока paging (для пагинации, F-1.4)."""
    paging = (state.get("vacancySearchResult") or {}).get("paging") or {}
    return paging.get("pages")


def _nested_id(raw: dict[str, Any] | None, default: str | None = None) -> str | None:
    """experience/employment/schedule в шаблоне — словари вида {"id": ..., "name": ...}."""
    if not raw:
        return default
    return raw.get("id") or default


def _strip_html(text: str | None) -> str | None:
    """Чистит описание вакансии от HTML-тегов (нужно модулю ключевых слов)."""
    if not text:
        return None
    return LexborHTMLParser(text).text().strip() or None


def map_vacancy(raw: dict[str, Any]) -> Vacancy:
    """Преобразует одну сырую вакансию из InitialState в модель Vacancy.

    Сырая структура (может отличаться от версии к версии, правим здесь):
    {
      "vacancyId": "...", "name": "...", "description": "<p>...</p>",
      "employer": {"name": "..."}, "compensation": {"from":..,"to":..,
                    "currencyCode":"RUR","gross":false},
      "area": {"name": "..."}, "experience": {"id":..}, "employment": {"id":..},
      "schedule": {"id":..}, "keySkills": [...], "professionalRoleIds": [...],
      "publishedAt": "...", "creationTime": "...", "responsesCount": 12,
      "links": {"desktop": "https://hh.ru/vacancy/..."}
    }
    """
    vacancy_id = str(raw.get("vacancyId", ""))
    employer = raw.get("employer") or {}
    area = raw.get("area") or {}
    compensation = raw.get("compensation") or {}
    links = raw.get("links") or {}

    salary = None
    if any(compensation.get(key) is not None for key in ("from", "to", "currencyCode")):
        salary = Salary(
            from_=compensation.get("from"),
            to=compensation.get("to"),
            currency=compensation.get("currencyCode"),
            gross=compensation.get("gross"),
        )

    return Vacancy(
        vacancy_id=vacancy_id,
        name=raw.get("name") or "",
        description=_strip_html(raw.get("description")),
        employer=Employer(name=employer.get("name") or ""),
        salary=salary,
        area=Area(name=area.get("name")) if area.get("name") else None,
        experience=_nested_id(raw.get("experience")),
        employment=_nested_id(raw.get("employment")),
        schedule=_nested_id(raw.get("schedule")),
        key_skills=raw.get("keySkills") or [],
        professional_role_ids=[str(i) for i in (raw.get("professionalRoleIds") or [])],
        published_at=raw.get("publishedAt"),
        creation_time=raw.get("creationTime"),
        responses_count=raw.get("responsesCount"),
        url=links.get("desktop") or f"https://hh.ru/vacancy/{vacancy_id}",
    )


# ── Основной цикл (F-1.2..F-1.8) ────────────────────────────────────────


def run(max_pages: int | None = None, *, output: Path | None = None) -> int:
    """Запускает сбор вакансий. Возвращает число добавленных вакансий."""
    settings = get_settings()
    client = HttpClient(settings)
    store = JsonlDedupStore(output or settings.vacancies_output, key_field="vacancyId")
    collected = 0
    pages_limit = max_pages or settings.max_pages

    try:
        for query in build_search_queries(settings):
            logger.info("Запрос: {}", query)
            for page in range(pages_limit):
                params: dict[str, Any] = {
                    "text": query["text"],
                    "experience": query["experience"],
                    "page": page,
                    "items_on_page": 20,
                }
                try:
                    response = client.get(SEARCH_URL, params=params)
                except Exception as exc:
                    logger.warning("Пропускаю страницу {}: {}", page, exc)
                    continue

                try:
                    state = extract_initial_state(response.text)
                except ValueError as exc:
                    logger.error("{}", exc)
                    break

                vacancies = get_vacancies(state)
                if not vacancies:
                    logger.info("Страница {} пуста, завершаю пагинацию", page)
                    break

                for raw in vacancies:
                    try:
                        vacancy = map_vacancy(raw)
                    except Exception as exc:
                        logger.warning("Не удалось разобрать вакансию: {}", exc)
                        continue
                    if store.add(vacancy.model_dump(by_alias=True, exclude_none=True)):
                        collected += 1

                pages_total = get_pages_total(state)
                if pages_total is not None and page + 1 >= pages_total:
                    break
    finally:
        client.close()

    logger.success(
        "Готово: добавлено {} вакансий, всего в файле {}", collected, store.size
    )
    return collected
