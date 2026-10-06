"""Модуль 1: сбор вакансий hh.ru (F-1.1 .. F-1.8).

Текущая вёрстка hh.ru (2026): список отдаёт карточки прямо в HTML
(<article data-qa="vacancy-serp__vacancy">), а детали вакансии лежат на её
странице, в том числе в <script type="application/ld+json"> (Schema.org
JobPosting). Поэтому поток такой:

1. GET /search/vacancy -> собираем ссылки на вакансии (DOM-карточки;
   если в HH-Lux-InitialState вдруг снова появятся вакансии — берём их).
2. На каждую вакансию GET /vacancy/{id} -> парсим JSON-LD + DOM.
3. Проверяем «подходит ли» по ключевым словам (match_keywords).
4. Дедупликация по vacancyId и дописывание в vacancies/*.jsonl.

Параллельность (parse_workers, PARSE_WORKERS): фаза 1 — поисковые запросы
выполняются одновременно (по HttpClient на запрос), фаза 2 — страницы
вакансий разбираются пулом воркеров. Сохранение — только из главного потока
(JsonlDedupStore не потокобезопасен). Больше воркеров = больше запросов в
минуту, растёт риск бана (R-4).
"""

from __future__ import annotations

import re
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
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
BASE_URL = "https://hh.ru"

# Встроенный JSON в template HH-Lux-InitialState. Перед id могут стоять
# любые атрибуты (например style="display:none") — это ломалось раньше.
INITIAL_STATE_RE = re.compile(
    r'<template\b[^>]*\bid="HH-Lux-InitialState"[^>]*>(.*?)</template>',
    re.DOTALL,
)
# Schema.org данные вакансии (описание, дата публикации, работодатель)
JSONLD_RE = re.compile(
    r'<script\b[^>]*type="application/ld\+json"[^>]*>(.*?)</script>',
    re.DOTALL,
)
NUMBER_RE = re.compile(r"\d[\d ]*")


# ── Построение запросов (F-1.1) ─────────────────────────────────────────


def build_search_queries(settings: Settings | None = None) -> list[dict[str, str]]:
    """Генерирует поисковые запросы: уровень x направление x технология.

    Каждая технология уходит отдельным запросом (вместо одного запроса со
    всеми сразу) — так выборка вакансий существенно шире (R-2). Пример:
    {"text": "middle fullstack python", "experience": "between3And6"}.
    """
    s = settings or get_settings()
    queries: list[dict[str, str]] = []
    for level, direction in product(s.search_levels, s.search_directions):
        base = [level, direction]
        if s.search_technologies:
            for tech in s.search_technologies:
                text = " ".join(filter(None, [*base, tech]))
                queries.append({"text": text, "experience": s.search_experience.value})
        else:
            queries.append(
                {"text": " ".join(base), "experience": s.search_experience.value}
            )
    return queries


# ── Список вакансий (страница поиска) ───────────────────────────────────


def extract_initial_state(html: str) -> dict[str, Any]:
    """Достаёт JSON из <template id="HH-Lux-InitialState">, если он есть."""
    match = INITIAL_STATE_RE.search(html)
    if match is None:
        raise ValueError("Блок HH-Lux-InitialState не найден на странице")
    return cast("dict[str, Any]", orjson.loads(match.group(1)))


def get_vacancies_from_state(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Сырые вакансии из InitialState (актуально для старых версий hh.ru)."""
    return (state.get("vacancySearchResult") or {}).get("vacancies") or []


def parse_search_cards(
    html: str, settings: Settings | None = None
) -> list[dict[str, str]]:
    """Собирает вакансии из DOM-карточек страницы поиска.

    Возвращает список вида: {"vacancyId": "123", "url": "...", "name": "..."}.

    id вакансии берём из <div id="..." class="vacancy-card--...">: ссылка
    заголовка может быть рекламным трекером (adsrv.hh.ru/click?...), а не
    прямой ссылкой на вакансию. Href используется как fallback.
    """
    s = settings or get_settings()
    root = LexborHTMLParser(html)
    cards: list[dict[str, str]] = []
    for article in root.css(s.selector_vacancy_card):
        link = article.css_first(s.selector_vacancy_title_link)
        if link is None:
            continue
        card_div = article.css_first(s.selector_vacancy_card_id)
        vacancy_id = (
            card_div.attributes.get("id") if card_div else ""
        ) or _id_from_href(link.attributes.get("href") or "")
        if not vacancy_id.isdigit():
            continue
        cards.append(
            {
                "vacancyId": vacancy_id,
                "url": f"{BASE_URL}/vacancy/{vacancy_id}",
                "name": link.text().strip(),
            }
        )
    return cards


def _id_from_href(href: str) -> str:
    """Числовой id вакансии из href (.../vacancy/123) или пустая строка."""
    last = href.rstrip("/").rsplit("/", 1)[-1]
    return last if last.isdigit() else ""


def extract_vacancy_links(
    html: str, settings: Settings | None = None
) -> list[dict[str, str]]:
    """Ссылки на вакансии: предпочитаем InitialState, иначе DOM-карточки."""
    s = settings or get_settings()
    try:
        state = extract_initial_state(html)
        raw_vacancies = get_vacancies_from_state(state)
    except ValueError:
        raw_vacancies = []

    if raw_vacancies:
        links: list[dict[str, str]] = []
        for raw in raw_vacancies:
            vacancy_id = str(raw.get("vacancyId", ""))
            page_urls = raw.get("links") or {}
            url = page_urls.get("desktop") or f"{BASE_URL}/vacancy/{vacancy_id}"
            links.append(
                {"vacancyId": vacancy_id, "url": url, "name": raw.get("name") or ""}
            )
        return links
    return parse_search_cards(html, s)


# ── Страница вакансии ───────────────────────────────────────────────────


def parse_jsonld(html: str) -> dict[str, Any]:
    """Данные вакансии из <script type="application/ld+json"> (Schema.org)."""
    match = JSONLD_RE.search(html)
    if match is None:
        return {}
    try:
        return cast("dict[str, Any]", orjson.loads(match.group(1)))
    except orjson.JSONDecodeError:
        return {}


HTML_TAG_RE = re.compile(r"<[^>]+>")
WHITESPACE_RE = re.compile(r"\s+")


def _strip_html(text: str | None) -> str | None:
    """Чистит описание вакансии от HTML-тегов (нужно модулю ключевых слов).

    Каждый тег заменяется пробелом: Lexbor text() иначе склеивает слова
    вокруг инлайн-тегов («на<b>Python</b>и» -> «наPythonи»).
    """
    if not text:
        return None
    cleaned = HTML_TAG_RE.sub(" ", text)
    return WHITESPACE_RE.sub(" ", cleaned).strip() or None


def _node_text(root: LexborHTMLParser, selector: str) -> str | None:
    node = root.css_first(selector)
    if node is None:
        return None
    return node.text(strip=True) or None


def parse_salary(text: str | None) -> Salary | None:
    """Зарплата из текста вида 'от 200 000 ₽' или '200 000 – 300 000 ₽'.

    Fallback, если на странице нет <data value="...">. from_ = первое число,
    to = последнее (если их больше одного). Неразрывные пробелы (\\u00a0)
    нормализуются — иначе «25 000» разбивается на «25» и «0».
    """
    if not text:
        return None
    normalized = text.replace("\u00a0", " ")
    numbers = [
        int(n.replace(" ", "")) for n in NUMBER_RE.findall(normalized) if n.strip()
    ]
    if not numbers:
        return None
    currency = "USD" if "$" in normalized else "EUR" if "€" in normalized else "RUR"
    return Salary(
        from_=numbers[0],
        to=numbers[-1] if len(numbers) > 1 else None,
        currency=currency,
        gross=False,
    )


def parse_salary_node(node: Any) -> Salary | None:
    """Зарплата из <data value="..."> внутри salary-блока (новая вёрстка hh.ru).

    Пример: от <data value="25000">25 000</data> до <data value="40000">
    40 000</data> <data value="RUB">₽</data> за месяц.
    """
    if node is None:
        return None
    values = [item.attributes.get("value") or "" for item in node.css("data[value]")]
    numbers = [int(value) for value in values if value.isdigit()]
    if not numbers:
        return None
    currency_token = next((value for value in values if not value.isdigit()), None)
    currency = {"RUB": "RUR", "USD": "USD", "EUR": "EUR", "KZT": "KZT"}.get(
        currency_token or "", "RUR"
    )
    return Salary(
        from_=numbers[0],
        to=numbers[-1] if len(numbers) > 1 else None,
        currency=currency,
        gross=False,
    )


def parse_vacancy_page(
    html: str, vacancy_id: str, settings: Settings | None = None
) -> Vacancy:
    """Разбирает страницу вакансии: JSON-LD (описание/дата) + DOM (остальное)."""
    s = settings or get_settings()
    root = LexborHTMLParser(html)
    meta = parse_jsonld(html)

    organization = meta.get("hiringOrganization") or {}
    address = (meta.get("jobLocation") or {}).get("address") or {}

    employer_name = (
        _node_text(root, s.selector_vacancy_employer) or organization.get("name") or ""
    )
    area_name = (
        _node_text(root, s.selector_vacancy_address)
        or address.get("addressLocality")
        or None
    )
    salary_node = root.css_first(s.selector_vacancy_salary)
    salary = parse_salary_node(salary_node) or parse_salary(
        salary_node.text() if salary_node else None
    )
    skills = [
        node.text(strip=True)
        for node in root.css(s.selector_vacancy_skills)
        if node.text(strip=True)
    ]
    description_html = meta.get("description") or _node_text(
        root, s.selector_vacancy_description
    )

    return Vacancy(
        vacancy_id=vacancy_id,
        name=(meta.get("title") or _node_text(root, s.selector_vacancy_title) or ""),
        description=(
            _strip_html(str(description_html))
            if isinstance(description_html, str)
            else None
        ),
        employer=Employer(name=employer_name),
        salary=salary,
        area=Area(name=area_name) if area_name else None,
        experience=_node_text(root, s.selector_vacancy_experience),
        employment=_node_text(root, s.selector_vacancy_employment),
        schedule=_node_text(root, s.selector_vacancy_schedule),
        key_skills=skills,
        professional_role_ids=[],
        published_at=meta.get("datePosted"),
        creation_time=None,
        responses_count=_parse_int(_node_text(root, s.selector_vacancy_responses)),
        url=f"{BASE_URL}/vacancy/{vacancy_id}",
    )


def _parse_int(text: str | None) -> int | None:
    if not text:
        return None
    digits = "".join(ch for ch in text if ch.isdigit())
    return int(digits) if digits else None


# ── Фильтр «подходит ли» ────────────────────────────────────────────────


def _normalize_text(text: str) -> str:
    """Нижний регистр + ё -> е: «Удалённая» ищется по «удаленн»."""
    return text.lower().replace("ё", "е")


def matches_vacancy(
    vacancy: Vacancy,
    keywords: list[str] | None = None,
    *,
    exclude_keywords: list[str] | None = None,
    work_formats: list[str] | None = None,
) -> bool:
    """Проверяет, подходит ли вакансия под все фильтры:

    - `keywords` — хотя бы одно слово в name/description/keySkills (пусто = ок);
    - `exclude_keywords` — НИ одного слова в тексте (негативные параметры);
    - `work_formats` — хотя бы одно значение в schedule/name/description
      (например, ["удаленн"] для «только удалёнки»).

    Сравнение по подстроке, без учёта регистра, ё == е.
    """
    haystack = _normalize_text(
        " ".join(
            filter(
                None,
                [
                    vacancy.name,
                    vacancy.description,
                    vacancy.schedule,
                    *vacancy.key_skills,
                ],
            )
        )
    )

    if exclude_keywords and any(
        _normalize_text(keyword) in haystack for keyword in exclude_keywords
    ):
        return False

    if keywords and not any(
        _normalize_text(keyword) in haystack for keyword in keywords
    ):
        return False

    if work_formats:
        return any(_normalize_text(fmt) in haystack for fmt in work_formats)
    return True


# ── Основной цикл (F-1.2..F-1.8) ────────────────────────────────────────


def _collect_links(
    settings: Settings,
    queries: list[dict[str, str]],
    pages_limit: int,
    workers: int,
) -> list[dict[str, str]]:
    """Собирает ссылки на вакансии параллельно: по одному HttpClient на запрос.

    Каждый запрос обходит свои страницы последовательно и останавливается на
    первой пустой странице. Результаты воркеров читаются в главном потоке
    через as_completed, поэтому общий список не требует блокировок.
    """
    links: list[dict[str, str]] = []

    def crawl(query: dict[str, str]) -> list[dict[str, str]]:
        local: list[dict[str, str]] = []
        client = HttpClient(settings)
        try:
            logger.info("Запрос: {}", query)
            for page in range(pages_limit):
                params: dict[str, Any] = {
                    "text": query["text"],
                    "experience": query["experience"],
                    "page": page,
                    "items_on_page": settings.items_per_page,
                }
                try:
                    response = client.get(SEARCH_URL, params=params)
                except Exception as exc:
                    logger.warning("Пропускаю страницу {}: {}", page, exc)
                    continue
                page_links = extract_vacancy_links(response.text, settings)
                if not page_links:
                    logger.info("Страница {} пуста, завершаю пагинацию", page)
                    break
                local.extend(page_links)
        finally:
            client.close()
        return local

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="links") as pool:
        futures = [pool.submit(crawl, query) for query in queries]
        for future in as_completed(futures):
            try:
                links.extend(future.result())
            except Exception as exc:
                logger.warning("Поисковый запрос не выполнен: {}", exc)
    return links


def _fetch_vacancy(
    settings: Settings,
    link: dict[str, str],
    keywords: list[str],
) -> tuple[str, dict[str, Any] | str]:
    """Загружает и разбирает одну вакансию; выполняется в воркере (фаза 2).

    Возвращает ("add", data) — вакансия прошла фильтры, можно сохранять;
    ("skip", "") — не прошла фильтры; ("error", msg) — сеть или парсинг.
    """
    vacancy_id = link["vacancyId"]
    client = HttpClient(settings)
    try:
        page_html = client.get(link["url"]).text
    except Exception as exc:
        logger.warning("Не удалось открыть вакансию {}: {}", vacancy_id, exc)
        return "error", str(exc)
    finally:
        client.close()
    try:
        vacancy = parse_vacancy_page(page_html, vacancy_id, settings)
    except Exception as exc:
        logger.warning("Не удалось разобрать вакансию {}: {}", vacancy_id, exc)
        return "error", str(exc)
    if not matches_vacancy(
        vacancy,
        keywords,
        exclude_keywords=settings.vacancy_exclude_keywords,
        work_formats=settings.vacancy_work_formats,
    ):
        return "skip", ""
    return "add", vacancy.model_dump(by_alias=True, exclude_none=True)


def run(
    max_pages: int | None = None,
    *,
    output: Path | None = None,
    match_keywords: list[str] | None = None,
    workers: int | None = None,
) -> int:
    """Запускает сбор вакансий. Возвращает число добавленных вакансий.

    Фаза 1: ссылки со страниц поиска (воркер на поисковый запрос).
    Фаза 2: детали вакансий пулом воркеров; сохранение — в главном потоке
    (JsonlDedupStore не потокобезопасен), дубли исключаются до submit.
    """
    settings = get_settings()
    keywords = (
        match_keywords
        or settings.vacancy_match_keywords
        or settings.search_technologies
    )
    store = JsonlDedupStore(output or settings.vacancies_output, key_field="vacancyId")
    collected = skipped = 0
    pages_limit = max_pages or settings.max_pages
    worker_count = workers or settings.parse_workers

    queries = build_search_queries(settings)
    links = _collect_links(settings, queries, pages_limit, worker_count)
    logger.info("Собрано ссылок на вакансии: {}", len(links))

    pending: list[Future[tuple[str, dict[str, Any] | str]]] = []
    with ThreadPoolExecutor(
        max_workers=worker_count, thread_name_prefix="vacancy"
    ) as pool:
        for link in links:
            vacancy_id = link["vacancyId"]
            if vacancy_id in store:
                logger.debug("Пропускаю дубликат вакансии {}", vacancy_id)
                continue
            pending.append(pool.submit(_fetch_vacancy, settings, link, keywords))

        for future in as_completed(pending):
            try:
                status, payload = future.result()
            except Exception as exc:
                logger.warning("Ошибка в воркере: {}", exc)
                continue
            if status == "skip":
                skipped += 1
                continue
            if status != "add" or not isinstance(payload, dict):
                continue
            if store.add(payload):
                collected += 1
                logger.info(
                    "Добавлена вакансия: {} ({})",
                    payload.get("name"),
                    payload.get("vacancyId"),
                )

    logger.success(
        "Готово: добавлено {} вакансий (пропущено по фильтру: {}), всего в файле {}",
        collected,
        skipped,
        store.size,
    )
    return collected
