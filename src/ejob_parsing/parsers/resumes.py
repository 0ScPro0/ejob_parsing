"""Модуль 3: сбор топовых резюме hh.ru (F-3.1 .. F-3.8).

Использует Playwright/patchright в стелс-режиме. Зависимости входят в
базовый uv sync, но импортируются лениво внутри функций — браузер
устанавливается командой `patchright install chromium`.

Этапы: авторизация (auth) -> сохранение storage_state -> сбор первой
страницы выдачи по ключевым словам из keywords.txt.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast
from urllib.parse import urlencode

from loguru import logger

from ejob_parsing.config import Settings, get_settings
from ejob_parsing.models import Resume
from ejob_parsing.storage import JsonlDedupStore

SEARCH_URL = "https://hh.ru/search/resume"
LOGIN_URL = "https://hh.ru/account/login"


# ── Авторизация (F-3.1) ─────────────────────────────────────────────────


def authorize(storage_state: Path | None = None, *, headless: bool = False) -> Path:
    """Первичная авторизация на hh.ru.

    Открывает браузер, пользователь входит вручную, после входа нажимает
    Enter в терминале — cookies и localStorage сохраняются в storage_state.
    """
    from patchright.sync_api import sync_playwright  # lazy import (в базовом uv sync)

    settings = get_settings()
    target = storage_state or settings.hh_storage_state
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context()
        page = context.new_page()
        page.goto(LOGIN_URL, wait_until="domcontentloaded")
        logger.info(
            "Войдите в аккаунт в открывшемся браузере, затем нажмите Enter здесь..."
        )
        input("Нажмите Enter после входа на hh.ru...")
        context.storage_state(path=str(target))
        browser.close()
    logger.success("storage_state сохранён: {}", target)
    return target


# ── Сбор резюме (F-3.3 .. F-3.6) ────────────────────────────────────────


def collect(
    keywords: list[str],
    *,
    top: int | None = None,
    storage_state: Path | None = None,
    proxy: str | None = None,
) -> int:
    """Собирает первую страницу выдачи по каждому ключевому слову (F-3.4).

    TODO(F-3.2): подключить Camoufox/стелс-режим и эмуляцию человека
    (движение мыши, скроллы) — F-3.8.
    TODO(F-3.7): ротация резидентских прокси через `proxy`.
    """
    from patchright.sync_api import sync_playwright  # lazy import (в базовом uv sync)

    settings = get_settings()
    store = JsonlDedupStore(settings.most_cv_output, key_field="resume_id")
    selected_top = top or settings.resume_top
    collected = 0

    # Прокси для контекста браузера (F-3.7): сервер берём из аргумента или .env
    proxy_server = proxy or settings.proxy_url or ""
    # patchright переопределяет ProxySettings (playwright) — приводим через Any
    proxy_settings = cast("Any", {"server": proxy_server}) if proxy_server else None

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=settings.resume_headless)
        context = browser.new_context(
            storage_state=str(storage_state or settings.hh_storage_state),
            proxy=proxy_settings,
        )
        page = context.new_page()
        try:
            for keyword in keywords[:selected_top]:
                logger.info("Резюме по ключу: {}", keyword)
                # Playwright не принимает params в goto — добавляем query в URL
                page.goto(
                    f"{SEARCH_URL}?{urlencode({'text': keyword})}",
                    wait_until="domcontentloaded",
                )
                page.wait_for_selector(settings.selector_resume_card, timeout=30_000)

                cards = page.query_selector_all(settings.selector_resume_card)
                logger.info("Найдено карточек: {}", len(cards))
                for card in cards:
                    resume = parse_resume_card(card, settings)
                    if resume is None:
                        continue
                    if store.add(resume.model_dump(exclude_none=True)):
                        collected += 1
        finally:
            browser.close()

    logger.success(
        "Готово: добавлено {} резюме, всего в файле {}", collected, store.size
    )
    return collected


# ── Разбор карточки резюме ──────────────────────────────────────────────


def parse_resume_card(card: Any, settings: Settings | None = None) -> Resume | None:
    """Достаёт поля резюме из карточки выдачи (F-3.5).

    `card` — Locator карточки из Playwright/patchright. Селекторы вынесены
    в конфиг (R-7) — при изменении вёрстки правим только их. Значения по
    умолчанию могут отличаться от реальных — уточнить при отладке.
    """
    s = settings or get_settings()

    def text(selector: str) -> str | None:
        element = card.query_selector(selector)
        if element is None:
            return None
        value = element.inner_text().strip()
        return value or None

    link_element = card.query_selector(s.selector_resume_link)
    href = link_element.get_attribute("href") if link_element else None
    resume_id = href.rstrip("/").rsplit("/", 1)[-1] if href else ""
    if not resume_id:
        return None

    title = text(s.selector_resume_title) or ""
    salary_raw = text(s.selector_resume_salary)
    age_raw = text(s.selector_resume_age)

    skills_element = card.query_selector(s.selector_resume_skills)
    skills = skills_element.inner_text().split(", ") if skills_element else []

    return Resume(
        resume_id=resume_id,
        link=href,
        title=title,
        salary=(
            int(salary_raw.replace(" ", ""))
            if salary_raw and salary_raw.replace(" ", "").isdigit()
            else None
        ),
        age=int(age_raw) if age_raw and age_raw.isdigit() else None,
        city=text(s.selector_resume_city),
        key_skills=skills,
        last_job=text(s.selector_resume_last_job),
    )
