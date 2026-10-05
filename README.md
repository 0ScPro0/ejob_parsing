# ejob-parsing

Парсер вакансий и резюме [hh.ru](https://hh.ru) по заданным настройкам поиска.
Реализация по [technical_specifications.md](technical_specifications.md).

## Три модуля

| Модуль | Команда | Результат |
|---|---|---|
| 1. Сбор вакансий | `ejob-parsing parse vacancies` | `vacancies/vacancies.jsonl` |
| 2. Ключевые слова | `ejob-parsing parse keywords` | `keywords.txt` |
| 3. Топовые резюме | `ejob-parsing parse resumes` | `most_cv/most_cv.jsonl` |

## Быстрый старт

```bash
# 1. Установка зависимостей (Python 3.13, uv)
uv sync

# 2. Конфигурация из шаблона
copy .env.example .env      # Windows
# cp .env.example .env      # Linux/macOS
# --- заполните .env: HH_LOGIN, HH_PASSWORD, прокси и т.д.

# 3. Авторизация hh.ru (нужна для модуля резюме)
uv run ejob-parsing auth    # войдите в браузере и нажмите Enter

# 4. Прогон
uv run ejob-parsing parse all

# или по отдельности
uv run ejob-parsing parse vacancies
uv run ejob-parsing parse keywords --min-frequency 5
uv run ejob-parsing parse resumes --top 1
```

Модуль резюме требует стелс-браузер (этап 4 ТЗ), зависимости подключаются отдельно:

```bash
uv sync --extra resumes
playwright install chromium
```

## Структура проекта

```
ejob_parsing/
├── src/ejob_parsing/
│   ├── config.py            # pydantic-settings: ВСЕ настройки из .env
│   ├── models.py            # pydantic-модели данных (вакансия, резюме)
│   ├── http_client.py       # обёртка над curl_cffi: TLS Chrome, ретраи, задержки
│   ├── storage.py           # .jsonl: запись, чтение, дедупликация
│   ├── parsers/
│   │   ├── vacancies.py     # модуль 1: сбор вакансий
│   │   ├── keywords.py      # модуль 2: частотный анализ (razdel + pymorphy3)
│   │   └── resumes.py       # модуль 3: топовые резюме (Playwright/patchright)
│   ├── cli.py               # typer CLI
│   └── __main__.py          # python -m ejob_parsing
├── tests/                   # pytest
├── vacancies/               # создаётся при первом запуске (вакансии .jsonl)
├── most_cv/                 # создаётся при первом запуске (резюме .jsonl)
├── keywords.txt             # создаётся модулем 2
├── storage_state.json       # сессия hh.ru (создаётся командой auth)
├── .env.example             # шаблон переменных окружения
├── pyproject.toml           # зависимости и инструменты (ruff/mypy/pytest)
└── .pre-commit-config.yaml  # хуки качества
```

## Куда что пихать

### Конфигурация — [`src/ejob_parsing/config.py`](src/ejob_parsing/config.py)

Все настройки типизированы в классе `Settings`. Поле класса = переменная
окружения (без учёта регистра): `search_levels` → `SEARCH_LEVELS`,
`request_delay_min` → `REQUEST_DELAY_MIN`, `hh_login` → `HH_LOGIN`.
Списки можно задавать через запятую или JSON-массивом:

```dotenv
SEARCH_LEVELS=middle,senior
SEARCH_TECHNOLOGIES=["python","go"]
```

Парсеры **не должны** читать `os.environ` напрямую — только
`get_settings()`.

### Данные — [`src/ejob_parsing/models.py`](src/ejob_parsing/models.py)

- `Vacancy` — формат `vacancies/*.jsonl` (раздел 7.1 ТЗ). Ключи
  сериализуются в camelCase (`vacancyId`, `keySkills`, `professionalRoleIds`,
  `creationTime`, `responsesCount`), кроме `published_at` — как в ТЗ.
  Принимает и сырой dict из шаблона HH (валидационные алиасы camelCase).
- `Resume` — формат `most_cv/*.jsonl` (раздел 7.3 ТЗ), snake_case.
- `Salary.from_` — в JSON пишется `"from"` (сериализационный алиас).

### HTTP — [`src/ejob_parsing/http_client.py`](src/ejob_parsing/http_client.py)

`HttpClient(settings)` — одна сессия curl_cffi с `impersonate="chrome"`
(F-1.2). Ретраи 403/429/5xx через tenacity (F-1.8), случайные паузы
`REQUEST_DELAY_MIN..MAX`, опциональные прокси и ротация User-Agent.

### Хранилище — [`src/ejob_parsing/storage.py`](src/ejob_parsing/storage.py)

`JsonlDedupStore(path, key_field)` дописывает записи в `.jsonl` и
отбрасывает дубликаты по ключу (F-1.5/F-3.6). Ключи уже записанных
объектов читаются при старте — повторные запуски безопасны.

### Модуль 1 — [`src/ejob_parsing/parsers/vacancies.py`](src/ejob_parsing/parsers/vacancies.py)

`build_search_queries()` генерирует запросы «уровень × направление» с
технологиями. `extract_initial_state()` вытаскивает JSON из
`<template id="HH-Lux-InitialState">` (F-1.3), `map_vacancy()` преобразует
сырую вакансию в модель — здесь правим структуру, если hh.ru что-то
поменяет. Пагинация до `MAX_PAGES` страниц, остановка по пустой странице.

### Модуль 2 — [`src/ejob_parsing/parsers/keywords.py`](src/ejob_parsing/parsers/keywords.py)

Поток F-2.1..F-2.9: чтение `.jsonl` → текст из `name`, `description`,
`keySkills` → нормализация → токенизация razdel → лемматизация pymorphy3 →
стоп-слова RU/EN → n-граммы (1..3) → порог `MIN_KEYWORD_FREQ` →
`keywords.txt` в формате `термин: частота`.

### Модуль 3 — [`src/ejob_parsing/parsers/resumes.py`](src/ejob_parsing/parsers/resumes.py)

`authorize()` — первичный вход и сохранение `storage_state.json`.
`collect()` — сбор первой страницы выдачи по ключам из `keywords.txt`.
Селекторы карточек вынесены в конфиг (`selector_resume_*`, риск R-7) —
при изменении вёрстки правим только их. TODO по стелс-режиму (F-3.2,
F-3.8) и ротации прокси (F-3.7) помечены в коде.

## Разработка

```bash
uv sync --extra dev          # инструменты: pytest, ruff, mypy, respx, pre-commit
uv run pre-commit install    # хуки (NF-6)
uv run ruff check .          # линтер (NF-4)
uv run ruff format .         # форматтер (NF-5)
uv run mypy src tests        # типизация (NF-3)
uv run pytest                # тесты (NF-7)
```

## Ключевые риски (из ТЗ)

| Риск | Митигация в проекте |
|---|---|
| 403 из-за TLS | curl_cffi `impersonate="chrome"` (R-1) |
| Лимит пагинации 40 стр. | дробить запросы в `build_search_queries` (R-2) |
| Детект Playwright | extra `resumes`, TODO в `resumes.py` (R-3) |
| Бан аккаунта | прокси + задержки + лимит `RESUME_TOP` (R-4) |
| Изменение вёрстки | селекторы в конфиге (R-7) |