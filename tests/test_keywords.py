"""Тесты модуля ключевых слов: нормализация, стоп-слова, n-граммы."""

from __future__ import annotations

from collections import Counter

from ejob_parsing.parsers.keywords import (
    STOPWORDS,
    count_ngrams,
    filter_stopwords,
    format_keywords,
    normalize,
)


def test_normalize_lowercase_and_punctuation() -> None:
    assert normalize("Python, FastAPI!  Разработка...") == "python fastapi разработка"


def test_filter_stopwords_removes_ru_and_en() -> None:
    tokens = ["и", "the", "python", "работа", "docker"]
    result = list(filter_stopwords(tokens))
    assert result == ["python", "docker"]
    assert "и" in STOPWORDS
    assert "the" in STOPWORDS


def test_count_ngrams_unigrams_bigrams() -> None:
    tokens = ["python", "разработчик", "python"]
    counter = count_ngrams(tokens, max_n=2)
    assert counter[("python",)] == 2
    assert counter[("python", "разработчик")] == 1


def test_count_ngrams_skips_stopword_inside() -> None:
    tokens = ["python", "и", "docker"]
    counter = count_ngrams(tokens, max_n=2)
    # биграмма, содержащая стоп-слово, не учитывается
    assert ("python", "docker") not in counter


def test_format_keywords_spec_format() -> None:
    counter: Counter[tuple[str, ...]] = Counter({("python",): 342, ("docker",): 287})
    lines = list(format_keywords(counter))
    assert lines == ["python: 342", "docker: 287"]
