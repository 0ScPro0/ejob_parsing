"""Общие фикстуры для тестов."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests._settings import make_settings


@pytest.fixture
def settings(tmp_path: Path) -> object:
    """Настройки с путями во временной директории и без чтения .env."""
    return make_settings(
        vacancies_output=tmp_path / "vacancies.jsonl",
        most_cv_output=tmp_path / "most_cv.jsonl",
        keywords_output=tmp_path / "keywords.txt",
        hh_storage_state=tmp_path / "storage_state.json",
    )
