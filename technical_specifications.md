# Техническое задание: Парсер вакансий и резюме hh.ru

## 1. Цель проекта

Разработать автоматизированный парсер для сбора и анализа данных с hh.ru по заданным настройкам поиска. Парсер работает в трёх режимах:

1. Сбор вакансий — сохранение всех вакансий, соответствующих фильтрам.
2. Извлечение ключевых слов — частотный анализ терминов из собранных вакансий.
3. Сбор топовых резюме — сохранение резюме, которые hh.ru показывает первыми по тем же ключевым словам.

Входные настройки поиска:
- Уровень: middle, senior
- Опыт: 3–6 лет
- Направления: fullstack, web
- Технологии: python, go, js, ai

---

## 2. Технический стек

### 2.1. Общий стек

| Компонент | Технология | Обоснование |
|---|---|---|
| Язык | Python 3.11+ | Лучшая экосистема для парсинга и анализа текста |
| Менеджер зависимостей | uv или poetry | Быстрее pip, фиксирует версии |
| HTTP-клиент | curl_cffi | Имитирует TLS-отпечаток Chrome |
| Парсинг HTML | selectolax | Быстрее BeautifulSoup/lxml в 5–10 раз |
| Работа с JSON | orjson | Быстрее стандартного json |
| Хранение | JSON Lines (.jsonl) | Удобно дописывать, не грузить всё в память |
| Логирование | loguru | Проще logging, ротация из коробки |
| Конфиги | pydantic-settings + .env | Валидация и типизация настроек |
| CLI | typer | Удобный интерфейс запуска модулей |
| Ретраи | tenacity | Повторные попытки при ошибках сети |

### 2.2. Стек модуля вакансий

| Задача | Технология |
|---|---|
| HTTP-запросы | curl_cffi (impersonate="chrome") |
| Извлечение JSON | selectolax + re |
| Ротация User-Agent | fake-useragent |
| Задержки | time.sleep + tenacity |
| Прокси (опционально) | встроенные возможности curl_cffi |

### 2.3. Стек модуля ключевых слов

| Задача | Технология |
|---|---|
| Токенизация RU | razdel |
| Лемматизация RU | pymorphy3 |
| Лемматизация EN | spacy или nltk |
| Стоп-слова | готовые списки + stop-words |
| N-граммы | scikit-learn CountVectorizer |
| Частотный анализ | collections.Counter |

### 2.4. Стек модуля резюме

| Задача | Технология |
|---|---|
| Автоматизация браузера | Playwright |
| Стелс-режим | patchright или Camoufox |
| Управление сессией | storage_state (cookies + localStorage) |
| Эмуляция человека | кастомные движения мыши, скроллы |
| Прокси | резидентские, через playwright proxy= |
| Парсинг результата | selectolax |

### 2.5. Инфраструктура

| Задача | Технология |
|---|---|
| Планировщик | APScheduler или cron |
| Тесты | pytest + respx |
| Линтеры | ruff + mypy |
| Pre-commit | pre-commit |
| Анализ (опционально) | pandas / polars / duckdb |

### 2.6. Минимальный MVP-стек

- curl_cffi
- selectolax
- orjson
- razdel + pymorphy3
- loguru
- typer

---

## 3. Функциональные требования

### 3.1. Модуль сбора вакансий (папка vacancies/)

| ID | Требование |
|---|---|
| F-1.1 | Формировать поисковые запросы на основе конфига (уровень, опыт, стек) |
| F-1.2 | Выполнять HTTP-запросы к https://hh.ru/search/vacancy с корректным TLS-отпечатком |
| F-1.3 | Извлекать встроенный JSON из тега <template id="HH-Lux-InitialState"> |
| F-1.4 | Поддерживать пагинацию (до 40 страниц) |
| F-1.5 | Дедуплицировать вакансии по vacancyId |
| F-1.6 | Сохранять результат в vacancies/*.jsonl |
| F-1.7 | Логировать каждый этап (запрос, парсинг, сохранение) |
| F-1.8 | Обрабатывать ошибки сети и 403/429 с ретраями |

Поля вакансии для сохранения:
- vacancyId, name, employer.name
- salary (from, to, currency, gross)
- area.name, experience, employment, schedule
- keySkills, professionalRoleIds
- published_at, creationTime, responsesCount
- url

### 3.2. Модуль ключевых слов (файл keywords.txt)

| ID | Требование |
|---|---|
| F-2.1 | Читать все вакансии из vacancies/*.jsonl |
| F-2.2 | Извлекать текст из полей name, description, keySkills |
| F-2.3 | Приводить текст к нижнему регистру, удалять пунктуацию |
| F-2.4 | Удалять стоп-слова (RU + EN) |
| F-2.5 | Токенизировать русский текст через razdel |
| F-2.6 | Лемматизировать русские слова через pymorphy3 |
| F-2.7 | Считать частотность униграмм, биграмм, триграмм |
| F-2.8 | Фильтровать термины с частотой ниже порога (N=5) |
| F-2.9 | Сохранять результат в keywords.txt в формате "термин: частота" |

### 3.3. Модуль сбора резюме (папка most_cv/)

| ID | Требование |
|---|---|
| F-3.1 | Авторизоваться на hh.ru через Playwright с сохранением storage_state |
| F-3.2 | Использовать стелс-режим (patchright / Camoufox) |
| F-3.3 | Формировать запросы на https://hh.ru/search/resume по ключевым словам |
| F-3.4 | Собирать только первую страницу выдачи (топ-резюме) |
| F-3.5 | Извлекать поля: resume_id, link, title, salary, age, city, key_skills, last_job |
| F-3.6 | Сохранять результат в most_cv/*.jsonl |
| F-3.7 | Поддерживать ротацию резидентских прокси |
| F-3.8 | Эмулировать человекоподобное поведение (задержки, скроллы) |

---

## 4. Нефункциональные требования

| ID | Требование |
|---|---|
| NF-1 | Язык реализации: Python 3.11+ |
| NF-2 | Менеджер зависимостей: uv или poetry |
| NF-3 | Типизация: mypy без ошибок |
| NF-4 | Линтинг: ruff без предупреждений |
| NF-5 | Форматирование: ruff format |
| NF-6 | Pre-commit хуки настроены |
| NF-7 | Тесты: pytest + respx для моков HTTP |
| NF-8 | Логирование через loguru с ротацией |
| NF-9 | Конфиги через pydantic-settings + .env |
| NF-10 | Секреты не хранятся в коде |

---

## 5. Структура проекта

```
project/
├── vacancies/                  # Собранные вакансии (.jsonl)
├── most_cv/                    # Собранные резюме (.jsonl)
├── keywords.txt                # Частотный словарь терминов
├── src/
│   ├── config.py               # pydantic-settings, чтение .env
│   ├── http_client.py          # обёртка над curl_cffi
│   ├── parsers/
│   │   ├── vacancies.py        # логика модуля 1
│   │   ├── keywords.py         # логика модуля 2
│   │   └── resumes.py          # логика модуля 3
│   ├── storage.py              # запись/чтение .jsonl
│   ├── models.py               # pydantic-модели
│   └── cli.py                  # typer CLI
├── tests/
├── .env.example
├── pyproject.toml
├── README.md
└── .pre-commit-config.yaml
```

---

## 6. CLI-интерфейс

| Команда | Описание |
|---|---|
| parse vacancies | Запустить сбор вакансий |
| parse keywords | Извлечь ключевые слова из собранных вакансий |
| parse resumes | Запустить сбор топовых резюме |
| parse all | Запустить все три модуля последовательно |

Пример:
```bash
python -m src.cli parse vacancies --query "fullstack python" --experience between3And6
python -m src.cli parse keywords --min-frequency 5
python -m src.cli parse resumes --keywords-file keywords.txt --top 1
```

---

## 7. Форматы данных

### 7.1. Вакансия (vacancies/*.jsonl)

```json
{
  "vacancyId": "12345678",
  "name": "Fullstack разработчик (Python/JS)",
  "employer": {"name": "ООО Ромашка"},
  "salary": {"from": 200000, "to": 300000, "currency": "RUR", "gross": false},
  "area": {"name": "Москва"},
  "experience": "between3And6",
  "employment": "full",
  "schedule": "remote",
  "keySkills": ["Python", "Django", "React", "PostgreSQL"],
  "professionalRoleIds": ["96"],
  "published_at": "2026-10-05T10:00:00+03:00",
  "creationTime": "2026-10-04T15:00:00+03:00",
  "responsesCount": 12,
  "url": "https://hh.ru/vacancy/12345678"
}
```

### 7.2. Ключевые слова (keywords.txt)

```
python: 342
docker: 287
kubernetes: 198
postgresql: 176
react: 154
```

### 7.3. Резюме (most_cv/*.jsonl)

```json
{
  "resume_id": "abcdef123456",
  "link": "https://hh.ru/resume/abcdef123456",
  "title": "Fullstack-разработчик",
  "salary": 250000,
  "age": 28,
  "city": "Москва",
  "key_skills": ["Python", "FastAPI", "React", "Docker"],
  "last_job": "Senior Developer в TechCorp"
}
```

---

## 8. Ограничения и риски

| ID | Риск | Митигация |
|---|---|---|
| R-1 | 403 из-за TLS-отпечатка | Использовать curl_cffi с impersonate |
| R-2 | Лимит 40 страниц пагинации | Дробить запросы по регионам/ключам |
| R-3 | Детект Playwright | patchright / Camoufox + прокси |
| R-4 | Бан аккаунта при сборе резюме | Резидентские прокси, лимиты, задержки |
| R-5 | Юридические риски (перс. данные) | Только для личной аналитики, без публикации |
| R-6 | Дубликаты между запросами | Дедупликация по id |
| R-7 | Изменение вёрстки hh.ru | Регулярные тесты, вынос селекторов в конфиг |

---

## 9. Критерии готовности (Definition of Done)

- Модуль вакансий собирает данные по всем заданным фильтрам
- Дедупликация работает корректно
- keywords.txt содержит осмысленные термины с частотами
- Модуль резюме успешно авторизуется и собирает топ-1 страницу
- Все данные сохраняются в указанной структуре папок
- Покрытие тестами ключевых функций ≥ 60%
- mypy и ruff проходят без ошибок
- README с инструкцией по запуску
- .env.example содержит все необходимые переменные

---

## 10. Этапы разработки

| Этап | Задачи | Результат |
|---|---|---|
| 1 | Настройка проекта, конфиги, модели | Скелет проекта |
| 2 | Модуль вакансий | vacancies/*.jsonl |
| 3 | Модуль ключевых слов | keywords.txt |
| 4 | Модуль резюме (авторизация + стелс) | most_cv/*.jsonl |
| 5 | CLI, тесты, документация | Готовый проект |
| 6 | Прогон на реальных данных, отладка | Рабочий парсер |

---

## 11. Переменные окружения (.env)

```
HH_LOGIN=your_email@example.com
HH_PASSWORD=your_password
HH_STORAGE_STATE=./storage_state.json
PROXY_URL=http://user:pass@proxy:port
LOG_LEVEL=INFO
REQUEST_DELAY_MIN=4
REQUEST_DELAY_MAX=8
MAX_PAGES=40
MIN_KEYWORD_FREQ=5
```

---

## 12. Команды для запуска

```bash
# Установка
uv sync

# Установка браузера для Playwright
playwright install chromium

# Первичная авторизация (сохранит storage_state.json)
python -m src.cli auth

# Полный прогон
python -m src.cli parse all

# Только вакансии
python -m src.cli parse vacancies

# Только ключевые слова
python -m src.cli parse keywords

# Только резюме
python -m src.cli parse resumes
```