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
from enum import StrEnum
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


# ── Enums ───────────────────────────────────────────────────────────────


class ExperienceLevel(StrEnum):
    """Идентификаторы опыта, которые hh.ru принимает в query-параметре `experience`."""

    NO_EXPERIENCE = "noExperience"
    BETWEEN_1_AND_3 = "between1And3"
    BETWEEN_3_AND_6 = "between3And6"
    MORE_THAN_6 = "moreThan6"


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
    search_experience: ExperienceLevel = ExperienceLevel.BETWEEN_3_AND_6
    search_directions: ListOfStr = Field(default_factory=lambda: ["fullstack", "web"])
    search_technologies: ListOfStr = Field(
        default_factory=lambda: ["python", "go", "js", "ai"]
    )
    max_pages: int = 40  # лимит пагинации hh.ru (F-1.4, R-2)

    # --- Ключевые слова, модуль 2 (F-2.7..F-2.9) ---
    min_keyword_freq: int = 5  # порог частоты (N=5 по ТЗ)
    top_keywords: int = 200  # сколько терминов писать в keywords.txt
    keyword_ngram_max: int = 3  # униграммы/биграммы/триграммы

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

    # --- Селекторы hh.ru (R-7: вёрстка может меняться — правим только здесь) ---
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
        mode="before",
    )
    @classmethod
    def _normalize_paths(cls, value: Any) -> Path:
        return _absolute_path(value)


@lru_cache
def get_settings() -> Settings:
    """Доступ к настройкам из любого места (одна копия на процесс)."""
    return Settings()
