"""Тесты моделей: сериализация в форматы ТЗ (раздел 7)."""

from __future__ import annotations

from datetime import datetime

from ejob_parsing.models import Resume, Salary, Vacancy


def _sample_vacancy() -> Vacancy:
    return Vacancy(
        vacancy_id="12345678",
        name="Fullstack разработчик (Python/JS)",
        description="<p>Разработка сервисов</p>",
        employer={"name": "ООО Ромашка"},
        salary=Salary(from_=200000, to=300000, currency="RUR", gross=False),
        area={"name": "Москва"},
        experience="between3And6",
        employment="full",
        schedule="remote",
        key_skills=["Python", "Django", "React"],
        professional_role_ids=["96"],
        published_at="2026-10-05T10:00:00+03:00",
        creation_time=1_752_400_000_000,  # epoch-ms -> datetime
        responses_count=12,
        url="https://hh.ru/vacancy/12345678",
    )


def test_vacancy_dump_matches_spec_format() -> None:
    data = _sample_vacancy().model_dump(by_alias=True, exclude_none=True)
    # ключи по ТЗ 7.1: camelCase, кроме published_at
    assert data["vacancyId"] == "12345678"
    assert data["employer"] == {"name": "ООО Ромашка"}
    assert data["salary"]["from"] == 200000
    assert data["salary"]["to"] == 300000
    assert data["salary"]["currency"] == "RUR"
    assert data["keySkills"] == ["Python", "Django", "React"]
    assert data["professionalRoleIds"] == ["96"]
    assert data["responsesCount"] == 12
    assert "published_at" in data
    assert data["creationTime"] is not None


def test_vacancy_flexible_datetime() -> None:
    vacancy = _sample_vacancy()
    assert isinstance(vacancy.published_at, datetime)
    assert vacancy.published_at is not None and vacancy.published_at.year == 2026
    assert isinstance(vacancy.creation_time, datetime)
    # epoch-millis 1752400000000 -> корректная дата
    assert vacancy.creation_time is not None and vacancy.creation_time.year == 2025


def test_vacancy_accepts_camel_case_raw_dict() -> None:
    raw = {
        "vacancyId": "42",
        "name": "Python dev",
        "keySkills": ["Python"],
        "professionalRoleIds": ["96"],
        "publishedAt": "2026-01-01T00:00:00+03:00",
    }
    vacancy = Vacancy.model_validate(raw)
    assert vacancy.vacancy_id == "42"
    assert vacancy.key_skills == ["Python"]


def test_resume_dump_matches_spec_format() -> None:
    resume = Resume(
        resume_id="abcdef123456",
        link="https://hh.ru/resume/abcdef123456",
        title="Fullstack-разработчик",
        salary=250000,
        age=28,
        city="Москва",
        key_skills=["Python", "FastAPI"],
        last_job="Senior Developer в TechCorp",
    )
    data = resume.model_dump(exclude_none=True)
    assert data["resume_id"] == "abcdef123456"
    assert data["key_skills"] == ["Python", "FastAPI"]
    assert data["last_job"] == "Senior Developer в TechCorp"
