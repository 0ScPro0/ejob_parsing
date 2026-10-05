"""Pydantic-модели данных.

Форматы соответствуют разделу 7 ТЗ:

- Vacancy  -> vacancies/*.jsonl  (7.1, ключи camelCase, кроме published_at)
- Resume   -> most_cv/*.jsonl    (7.3, ключи snake_case)

Модели умеют принимать сырой JSON из template HH-Lux-InitialState
(validation_alias), а сериализуются `model_dump(by_alias=True)` в формат ТЗ.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any

from pydantic import AliasChoices, BaseModel, BeforeValidator, ConfigDict, Field


def _parse_datetime(value: Any) -> datetime | None:
    """Accept ISO-8601 strings and unix timestamps (seconds or milliseconds).

    hh.ru в template HH-Lux-InitialState отдаёт время строкой ISO,
    в API-ответах бывают epoch-миллисекунды.
    """
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        ts = value / 1000 if value > 10_000_000_000 else value
        return datetime.fromtimestamp(ts, tz=UTC)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


FlexibleDatetime = Annotated[datetime | None, BeforeValidator(_parse_datetime)]


class Employer(BaseModel):
    """Работодатель вакансии (в .jsonl хранится только name, см. 7.1)."""

    model_config = ConfigDict(populate_by_name=True)

    name: str = ""


class Area(BaseModel):
    """Город/регион вакансии (хранится только name)."""

    model_config = ConfigDict(populate_by_name=True)

    name: str = ""


class Salary(BaseModel):
    """Зарплатная вилка. Поле `from` — зарезервированное слово Python,
    поэтому в коде оно называется from_, а в JSON сериализуется как "from"."""

    model_config = ConfigDict(populate_by_name=True)

    from_: int | None = Field(
        default=None,
        validation_alias=AliasChoices("from", "from_"),
        serialization_alias="from",
    )
    to: int | None = None
    currency: str | None = None
    gross: bool | None = None


class Vacancy(BaseModel):
    """Вакансия для сохранения в vacancies/*.jsonl (формат 7.1 ТЗ)."""

    model_config = ConfigDict(populate_by_name=True)

    vacancy_id: str = Field(
        validation_alias=AliasChoices("vacancyId", "vacancy_id"),
        serialization_alias="vacancyId",
    )
    name: str
    description: str | None = None  # нужно модулю ключевых слов (F-2.2)
    employer: Employer = Field(default_factory=Employer)
    salary: Salary | None = None
    area: Area | None = None
    experience: str | None = None
    employment: str | None = None
    schedule: str | None = None
    key_skills: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("keySkills", "key_skills"),
        serialization_alias="keySkills",
    )
    professional_role_ids: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("professionalRoleIds", "professional_role_ids"),
        serialization_alias="professionalRoleIds",
    )
    published_at: FlexibleDatetime = Field(
        default=None,
        validation_alias=AliasChoices("publishedAt", "published_at"),
        # по ТЗ остаётся snake_case: "published_at"
    )
    creation_time: FlexibleDatetime = Field(
        default=None,
        validation_alias=AliasChoices("creationTime", "creation_time"),
        serialization_alias="creationTime",
    )
    responses_count: int | None = Field(
        default=None,
        validation_alias=AliasChoices("responsesCount", "responses_count"),
        serialization_alias="responsesCount",
    )
    url: str = ""


class Resume(BaseModel):
    """Резюме для сохранения в most_cv/*.jsonl (формат 7.3 ТЗ, snake_case)."""

    model_config = ConfigDict(populate_by_name=True)

    resume_id: str
    link: str
    title: str
    salary: int | None = None
    age: int | None = None
    city: str | None = None
    key_skills: list[str] = Field(default_factory=list)
    last_job: str | None = None
