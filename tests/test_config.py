"""Тесты конфигурации: парсинг списков, пути, дефолты из ТЗ."""

from __future__ import annotations

from ejob_parsing.config import _parse_list
from tests._settings import make_settings


def test_parse_list_comma_separated() -> None:
    assert _parse_list("middle, senior,  junior") == ["middle", "senior", "junior"]


def test_parse_list_json_array() -> None:
    assert _parse_list('["python", "go"]') == ["python", "go"]


def test_parse_list_empty() -> None:
    assert _parse_list("") == []
    assert _parse_list(None) == []


def test_settings_defaults_from_spec() -> None:
    settings = make_settings()
    # раздел 1 ТЗ: уровень, опыт, направления, технологии
    assert settings.search_levels == ["middle", "senior"]
    assert settings.search_experience == ["between3And6"]
    assert settings.search_directions == ["fullstack", "web"]
    assert settings.search_technologies == ["python", "go", "js", "ai"]
    assert settings.search_work_formats == []  # пусто = все форматы
    # раздел 11 ТЗ
    assert settings.max_pages == 40
    assert settings.min_keyword_freq == 5
    assert settings.request_delay_min == 4
    assert settings.request_delay_max == 8


def test_settings_env_overrides(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("SEARCH_LEVELS", "lead")
    monkeypatch.setenv("MAX_PAGES", "10")
    settings = make_settings()
    assert settings.search_levels == ["lead"]
    assert settings.max_pages == 10
    monkeypatch.delenv("SEARCH_LEVELS")
    monkeypatch.delenv("MAX_PAGES")


def test_settings_relative_path_resolved(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("VACANCIES_OUTPUT", "./out/vac.jsonl")
    settings = make_settings()
    assert settings.vacancies_output.is_absolute()
    assert settings.vacancies_output.name == "vac.jsonl"
    monkeypatch.delenv("VACANCIES_OUTPUT")
