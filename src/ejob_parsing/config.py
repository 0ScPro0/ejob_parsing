"""Application settings loaded from environment variables and the .env file.

Every attribute maps to an environment variable automatically
(case-insensitive), e.g.:

    search_levels     -> SEARCH_LEVELS
    request_delay_min -> REQUEST_DELAY_MIN
    hh_login          -> HH_LOGIN

List fields accept several formats in .env (see `_parse_list`):

    SEARCH_LEVELS=middle, senior
    SEARCH_LEVELS=["middle", "senior"]
    SEARCH_TECHNOLOGIES=python,go,js,ai

Everything the parsers need is typed here — parsers should never read
os.environ directly (NF-9, NF-10).
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any

from pydantic import BeforeValidator, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# Project root = <repo>/ (three levels up from this file: config.py -> ejob_parsing -> src -> repo)
PROJECT_ROOT = Path(__file__).resolve().parents[2]


# ── Helpers for env values ──────────────────────────────────────────────


def _parse_list(value: Any) -> list[str]:
    """Parse a comma-separated string or a JSON array into a list of strings."""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    if not text:
        return []
    if text.startswith("["):  # JSON array form
        try:
            loaded = json.loads(text)
        except json.JSONDecodeError:
            loaded = None
        if isinstance(loaded, list):
            return [str(item).strip() for item in loaded if str(item).strip()]
    return [part.strip() for part in text.split(",") if part.strip()]


# NoDecode запрещает pydantic-settings парсить значение как JSON —
# строку из .env обрабатывает наш валидатор (иначе "middle,senior"
# интерпретируется как невалидный JSON).
ListOfStr = Annotated[list[str], NoDecode, BeforeValidator(_parse_list)]


def _absolute_path(value: Any) -> Path:
    """Resolve relative paths against the project root (not the CWD)."""
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


# ── Main settings ───────────────────────────────────────────────────────


class Settings(BaseSettings):
    """Все настройки проекта. Значения по умолчанию — это заглушки,
    переопределяются через переменные окружения или файл .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Общие (раздел 11 ТЗ) ---
    log_level: str = "INFO"
    request_timeout: float = 30.0
    retry_attempts: int = 3
    retry_wait_seconds: float = 5.0
    request_delay_min: float = 4.0
    request_delay_max: float = 8.0
    rotate_user_agent: bool = False

    # --- Поиск вакансий, модуль 1 (раздел 1 ТЗ) ---
    search_levels: ListOfStr = Field(default_factory=lambda: ["middle", "senior"])
    # Опыт — тоже список: SEARCH_EXPERIENCE=between1And3,between3And6.
    # hh.ru принимает только одно значение experience за раз, поэтому парсер
    # уходит отдельным запросом на каждое (R-2).
    search_experience: ListOfStr = Field(default_factory=lambda: ["between3And6"])
    search_directions: ListOfStr = Field(default_factory=lambda: ["fullstack", "web"])
    search_technologies: ListOfStr = Field(
        default_factory=lambda: ["python", "go", "js", "ai"]
    )
    max_pages: int = 40  # лимит пагинации hh.ru (F-1.4, R-2)
    items_per_page: int = 50  # карточек на страницу поиска (больше = больше выборка)
    # Параллельность парсинга: столько HTTP-клиентов работают одновременно.
    # Ускорение ~N раз, но растёт нагрузка на hh.ru (риск бана, R-4).
    parse_workers: int = 3

    # --- Ключевые слова, модуль 2 (F-2.7..F-2.9) ---
    min_keyword_freq: int = 5  # порог частоты (N=5 по ТЗ)
    top_keywords: int = 200  # сколько терминов писать в keywords.txt
    keyword_ngram_max: int = 3  # униграммы/биграммы/триграммы

    # --- ИИ-аналитика вакансий (модуль 2, опционально) ---
    # Сводка по собранным вакансиям со ссылками и примерами сопроводительных
    # писем -> ai_analytics.txt. Требует OPENAI_API_KEY; без него пропускается.
    ai_analytics_enabled: bool = True
    ai_vacancies_limit: int = 50  # сколько вакансий передать модели
    ai_text_char_limit: int = 1000  # длина описания каждой вакансии для модели

    # --- OpenAI ---
    openai_api_key: SecretStr | None = None
    openai_model: str = "gpt-4o-mini"
    openai_base_url: str | None = None  # для прокси/совместимых API
    openai_timeout: float = 960.0
    # Переопределение системного промпта (дефолтный — в ai.py).
    # В .env многострочный текст можно записать с \n.
    openai_system_prompt: str | None = None

    # --- Резюме, модуль 3 (F-3.4) ---
    resume_top: int = 1  # сколько первых ключевых слов использовать
    resume_headless: bool = True

    # --- Авторизация hh.ru (F-3.1) ---
    hh_login: str | None = None
    hh_password: SecretStr | None = None
    hh_storage_state: Path = PROJECT_ROOT / "storage_state.json"

    # --- Прокси, опционально (F-3.7, R-4) ---
    proxy_url: str | None = None

    # --- Пути вывода данных ---
    vacancies_output: Path = PROJECT_ROOT / "vacancies" / "vacancies.jsonl"
    most_cv_output: Path = PROJECT_ROOT / "most_cv" / "most_cv.jsonl"
    keywords_output: Path = PROJECT_ROOT / "keywords.txt"
    ai_analytics_output: Path = PROJECT_ROOT / "out" / "ai_analytics.txt"

    # --- Фильтр подходящих вакансий (модуль 1) ---
    # Вакансия сохраняется, если в name/description/keySkills встречается хотя бы
    # одно из слов. Пустой список = используются search_technologies.
    vacancy_match_keywords: ListOfStr = Field(default_factory=list)
    # Негативные параметры: вакансия скипается, если в её тексте встречается
    # любое из слов (например: qa, тестировщик). Регистр не важен.
    vacancy_exclude_keywords: ListOfStr = Field(default_factory=list)
    # Формат работы — критерий ПОИСКА (query-параметр work_format), а не
    # пост-фильтр текста: hh.ru сразу отдаёт только такие вакансии, парсер
    # не открывает страницы лишних. Значения (регистр не важен):
    # FULL_DAY | SHIFT | FLEXIBLE | REMOTE | HYBRID. Каждый формат уходит
    # отдельным запросом. Пусто = все форматы.
    search_work_formats: ListOfStr = Field(default_factory=list)

    # --- Селекторы hh.ru (R-7: вёрстка может меняться — правим только здесь) ---
    # Список вакансий (search/vacancy)
    # data-qa карточки может содержать несколько токенов, поэтому `*=`
    selector_vacancy_card: str = "article[data-qa*='vacancy-serp__vacancy']"
    # id вакансии берём из блока vacancy-card (ссылка может быть рекламным трекером)
    selector_vacancy_card_id: str = "div[class*='vacancy-card']"
    selector_vacancy_title_link: str = "a[data-qa='serp-item__title']"
    # Страница вакансии (/vacancy/{id})
    selector_vacancy_title: str = "[data-qa='vacancy-title']"
    selector_vacancy_employer: str = "[data-qa='vacancy-view-raw-company']"
    selector_vacancy_salary: str = "[data-qa='vacancy-salary-compensation-type-net']"
    selector_vacancy_experience: str = "[data-qa='vacancy-experience']"
    selector_vacancy_employment: str = "[data-qa='vacancy-view-employment-mode']"
    selector_vacancy_schedule: str = "[data-qa='vacancy-view-employment-schedule']"
    selector_vacancy_skills: str = "[data-qa='skills-element']"
    selector_vacancy_address: str = "a[data-qa='vacancy-view-raw-address']"
    selector_vacancy_description: str = "[data-qa='vacancy-description']"
    selector_vacancy_responses: str = "[data-qa='vacancy-view-response-counter']"
    # Резюме (search/resume)
    selector_resume_card: str = "[data-qa='resume-serp__resume']"
    selector_resume_link: str = "a[data-qa='resume-serp__resume-title']"
    selector_resume_title: str = "[data-qa='resume-serp__resume-title']"
    selector_resume_salary: str = "[data-qa='resume-serp__resume-compensation']"
    selector_resume_age: str = "[data-qa='resume-serp__resume-age']"
    selector_resume_city: str = "[data-qa='resume-serp__resume-location']"
    selector_resume_skills: str = "[data-qa='resume-serp__resume-skills']"
    selector_resume_last_job: str = "[data-qa='resume-serp__resume-last-job']"

    @field_validator(
        "hh_storage_state",
        "vacancies_output",
        "most_cv_output",
        "keywords_output",
        "ai_analytics_output",
        mode="before",
    )
    @classmethod
    def _normalize_paths(cls, value: Any) -> Path:
        return _absolute_path(value)


@lru_cache
def get_settings() -> Settings:
    """Доступ к настройкам из любого места (одна копия на процесс)."""
    return Settings()
