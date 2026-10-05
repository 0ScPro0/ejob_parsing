"""Изолированные настройки для тестов: без чтения .env.

pydantic-settings принимает `_env_file=None` только как init-аргумент,
который статические анализаторы не видят в сигнатуре __init__, поэтому
передаём его через **kwargs.
"""

from __future__ import annotations

from typing import Any

from ejob_parsing.config import Settings


def make_settings(**overrides: Any) -> Settings:
    """Settings без загрузки .env-файла и с переопределёнными полями.

    Пример:
        settings = make_settings(
            vacancies_output=tmp_path / "vacancies.jsonl",
            max_pages=5,
        )
    """
    return Settings(**{"_env_file": None, **overrides})
