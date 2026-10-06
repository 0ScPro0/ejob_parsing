"""CLI-интерфейс (typer). Команды соответствуют разделу 6 ТЗ:

ejob-parsing auth              # первичная авторизация (storage_state)
ejob-parsing parse vacancies   # модуль 1: сбор вакансий
ejob-parsing parse keywords    # модуль 2: ключевые слова
ejob-parsing parse resumes     # модуль 3: топовые резюме
ejob-parsing parse all         # все три модуля последовательно
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from ejob_parsing.config import get_settings

app = typer.Typer(
    name="ejob-parsing",
    help="Парсер вакансий и резюме hh.ru",
    no_args_is_help=True,
    add_completion=False,
)
parse = typer.Typer(help="Модули парсинга", no_args_is_help=True)
app.add_typer(parse, name="parse")


@app.command()
def auth(
    storage_state: Annotated[
        Path | None,
        typer.Option(
            "--storage-state",
            help="Куда сохранить storage_state (по умолчанию из .env)",
        ),
    ] = None,
    headless: Annotated[
        bool, typer.Option("--headless", help="Открыть браузер невидимым")
    ] = False,
) -> None:
    """Первичная авторизация на hh.ru и сохранение сессии (F-3.1)."""
    from ejob_parsing.parsers.resumes import authorize

    authorize(storage_state, headless=headless)


@parse.command("vacancies")
def parse_vacancies(
    max_pages: Annotated[
        int | None,
        typer.Option(
            "--max-pages", help="Лимит страниц (по умолчанию MAX_PAGES из .env)"
        ),
    ] = None,
    workers: Annotated[
        int | None,
        typer.Option(
            "--workers",
            help=(
                "Сколько HTTP-клиентов работают параллельно "
                "(по умолчанию PARSE_WORKERS из .env)"
            ),
        ),
    ] = None,
) -> None:
    """Собрать вакансии hh.ru по настройкам из .env (модуль 1)."""
    from ejob_parsing.parsers.vacancies import run as run_vacancies

    run_vacancies(max_pages=max_pages, workers=workers)


@parse.command("keywords")
def parse_keywords(
    min_frequency: Annotated[
        int | None,
        typer.Option(
            "--min-frequency",
            help="Минимальная частота термина (по умолчанию MIN_KEYWORD_FREQ из .env)",
        ),
    ] = None,
    top: Annotated[
        int | None,
        typer.Option("--top", help="Сколько терминов записать в keywords.txt"),
    ] = None,
    ai: Annotated[
        bool | None,
        typer.Option(
            "--ai/--no-ai",
            help=(
                "ИИ-аналитика (сводка по вакансиям в ai_analytics.txt; "
                "по умолчанию AI_ANALYTICS_ENABLED из .env)"
            ),
        ),
    ] = None,
) -> None:
    """Извлечь ключевые слова (keywords.txt) и, если включено, ИИ-сводку
    по вакансиям со ссылками и сопроводительными письмами (ai_analytics.txt)."""
    from ejob_parsing.parsers.keywords import run as run_keywords

    run_keywords(min_frequency, top=top, use_ai=ai)


@parse.command("resumes")
def parse_resumes(
    keywords_file: Annotated[
        Path,
        typer.Option(
            "--keywords-file",
            help="Файл со списком ключевых слов (формат keywords.txt)",
        ),
    ] = Path("keywords.txt"),
    top: Annotated[
        int | None,
        typer.Option(
            "--top",
            help="Сколько первых ключевых слов использовать (по умолчанию RESUME_TOP из .env)",
        ),
    ] = None,
) -> None:
    """Собрать топовые резюме по ключевым словам (модуль 3)."""
    from ejob_parsing.parsers.resumes import collect

    keywords = read_keywords(keywords_file)
    collect(keywords, top=top or get_settings().resume_top)


@parse.command("all")
def parse_all() -> None:
    """Последовательно: вакансии -> ключевые слова -> резюме."""
    parse_vacancies(max_pages=None, workers=None)
    parse_keywords(min_frequency=None, top=None, ai=None)
    parse_resumes(keywords_file=Path("keywords.txt"), top=None)


def read_keywords(path: Path) -> list[str]:
    """Читает keywords.txt: из строки 'термин: частота' берёт термин."""
    if not path.exists():
        raise typer.BadParameter(
            f"Файл {path} не найден. Сначала выполните:\n"
            "  ejob-parsing parse vacancies\n"
            "  ejob-parsing parse keywords"
        )
    terms: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        term = line.split(":", 1)[0].strip()
        if term:
            terms.append(term)
    return terms


def main() -> None:
    app()
