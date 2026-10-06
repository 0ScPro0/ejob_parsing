"""Модуль 2: частотный анализ ключевых слов (F-2.1 .. F-2.9).

Поток: читаем vacancies/*.jsonl -> извлекаем текст (name, description,
keySkills) -> нормализуем -> токенизируем razdel -> лемматизируем
pymorphy3 -> считаем n-граммы -> пишем keywords.txt ("термин: частота").

razdel и pymorphy3 импортируются лениво внутри функций, чтобы модуль
загружался быстро и без этих зависимостей.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

from loguru import logger

from ejob_parsing.config import Settings, get_settings
from ejob_parsing.exceptions import AIGenerationError
from ejob_parsing.storage import iter_jsonl

PUNCT_RE = re.compile(r"[^\w\s-]+", re.UNICODE)
WHITESPACE_RE = re.compile(r"\s+")

# Стоп-слова: служебные части речи + общие слова вакансий, не несущие смысла.
# Можно расширять (F-2.4): RU + EN.
STOPWORDS: set[str] = {
    # русские служебные
    "и",
    "в",
    "во",
    "не",
    "что",
    "он",
    "на",
    "я",
    "с",
    "со",
    "как",
    "а",
    "то",
    "все",
    "она",
    "так",
    "его",
    "но",
    "да",
    "ты",
    "к",
    "у",
    "же",
    "вы",
    "за",
    "бы",
    "по",
    "только",
    "ее",
    "мне",
    "было",
    "вот",
    "от",
    "меня",
    "еще",
    "нет",
    "о",
    "из",
    "ему",
    "теперь",
    "когда",
    "даже",
    "ну",
    "вдруг",
    "ли",
    "если",
    "уже",
    "или",
    "ни",
    "быть",
    "был",
    "него",
    "до",
    "вас",
    "нибудь",
    "опять",
    "уж",
    "вам",
    "ведь",
    "там",
    "потом",
    "себя",
    "ничего",
    "ей",
    "может",
    "они",
    "тут",
    "где",
    "есть",
    "надо",
    "ней",
    "для",
    "мы",
    "тебя",
    "их",
    "чем",
    "была",
    "сам",
    "чтоб",
    "без",
    "будто",
    "чего",
    "раз",
    "тоже",
    "себе",
    "под",
    "будет",
    "ж",
    "тогда",
    "кто",
    "этот",
    "того",
    "потому",
    "этого",
    "какой",
    "совсем",
    "ним",
    "здесь",
    "этом",
    "один",
    "почти",
    "мой",
    "тем",
    "чтобы",
    "нее",
    "кажется",
    "сейчас",
    "были",
    "куда",
    "зачем",
    "сказать",
    "всех",
    "никогда",
    "сегодня",
    "можно",
    "при",
    "наконец",
    "два",
    "об",
    "другой",
    # общие слова вакансий
    "работа",
    "работы",
    "работе",
    "работу",
    "работать",
    "вакансия",
    "вакансии",
    "компания",
    "компании",
    "требования",
    "требование",
    "обязанности",
    "обязанность",
    "условия",
    "условие",
    "знание",
    "знания",
    "умение",
    "умения",
    "навыки",
    "навык",
    "опыт",
    "года",
    "год",
    "году",
    "лет",
    "также",
    "хорошо",
    "отличный",
    "уметь",
    "знать",
    "должен",
    "должна",
    "готовность",
    "возможность",
    "участие",
    "участвовать",
    "помощь",
    "наша",
    "наш",
    "наши",
    "своя",
    "свой",
    "свои",
    "большой",
    "большая",
    "который",
    "которая",
    "которые",
    "приветствуется",
    "является",
    "рассмотрим",
    "рассматриваем",
    # английские служебные
    "the",
    "and",
    "for",
    "with",
    "are",
    "you",
    "your",
    "our",
    "will",
    "have",
    "has",
    "was",
    "were",
    "that",
    "this",
    "from",
    "they",
    "their",
    "what",
    "can",
    "all",
    "not",
    "but",
    "its",
    "also",
    "into",
    "than",
    "them",
    "these",
    "those",
    "who",
    "which",
    "when",
    "where",
    "why",
    "how",
    "then",
    "there",
    "here",
    "about",
    "between",
    "during",
    "through",
    "because",
    "work",
    "working",
    "company",
    "team",
    "experience",
    "years",
    "year",
    "good",
    "strong",
    "skills",
}

# Слова короче 3 символов после лемматизации не интересны
MIN_LEMMA_LEN = 3


# ── Текстовая обработка ─────────────────────────────────────────────────


def normalize(text: str) -> str:
    """Нижний регистр + удаление пунктуации (F-2.3)."""
    lowered = text.lower()
    cleaned = PUNCT_RE.sub(" ", lowered)
    return WHITESPACE_RE.sub(" ", cleaned).strip()


def tokenize_ru(text: str) -> list[str]:
    """Токенизация русского текста через razdel (F-2.5)."""
    from razdel import tokenize

    return [token.text for token in tokenize(text)]


def lemmatize_ru(tokens: Iterable[str]) -> Iterator[str]:
    """Лемматизация через pymorphy3 (F-2.6), короткие слова отбрасываем."""
    import pymorphy3

    morph = pymorphy3.MorphAnalyzer()
    for token in tokens:
        lemma = morph.parse(token)[0].normal_form
        if len(lemma) >= MIN_LEMMA_LEN:
            yield lemma


def filter_stopwords(tokens: Iterable[str]) -> Iterator[str]:
    """Удаляет стоп-слова RU + EN (F-2.4)."""
    return (token for token in tokens if token not in STOPWORDS)


def count_ngrams(tokens: list[str], max_n: int = 3) -> Counter[tuple[str, ...]]:
    """Частотность униграмм/биграмм/триграмм (F-2.7).

    N-грамма с любым стоп-словом внутри не учитывается.
    """
    counter: Counter[tuple[str, ...]] = Counter()
    for n in range(1, max_n + 1):
        for i in range(len(tokens) - n + 1):
            gram = tuple(tokens[i : i + n])
            if all(word not in STOPWORDS for word in gram):
                counter[gram] += 1
    return counter


# ── Чтение вакансий и формат вывода ────────────────────────────────────


def load_vacancy_texts(path: Path) -> Iterator[str]:
    """Извлекает текст из полей name, description, keySkills (F-2.2)."""
    for item in iter_jsonl(path):
        yield " ".join(filter(None, [item.get("name"), item.get("description")]))
        yield " ".join(item.get("keySkills") or [])


def format_keywords(
    counter: Counter[tuple[str, ...]], *, top: int | None = None
) -> Iterator[str]:
    """Формат keywords.txt (7.2 ТЗ): "термин: частота"."""
    for gram, count in counter.most_common(top):
        yield f"{' '.join(gram)}: {count}"


def _write_terms(path: Path, terms: list[tuple[str, int]]) -> None:
    """Пишет список (термин, частота) в keywords.txt в формате 7.2 ТЗ."""
    lines = [f"{term}: {count}" for term, count in terms]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


# ── Запуск модуля ───────────────────────────────────────────────────────


def run(
    min_frequency: int | None = None,
    *,
    top: int | None = None,
    use_ai: bool | None = None,
) -> Path:
    """Читает уже собранные вакансии (без сети!) и пишет keywords.txt
    (частотный анализ, F-2.1..F-2.9). Если включена ИИ-аналитика (и задан
    OPENAI_API_KEY) — дополнительно генерируется сводка по вакансиям со
    ссылками и примерами сопроводительных писем в ai_analytics.txt.
    """
    settings = get_settings()
    vacancies = list(iter_jsonl(settings.vacancies_output))
    texts = list(load_vacancy_texts(settings.vacancies_output))
    logger.info("Загружено вакансий: {}", len(vacancies))
    if not vacancies:
        logger.warning(
            "Вакансий нет — сначала соберите данные: ejob-parsing parse vacancies"
        )

    counter: Counter[tuple[str, ...]] = Counter()
    for text in texts:
        tokens = tokenize_ru(normalize(text))
        lemmas = list(lemmatize_ru(filter_stopwords(tokens)))
        counter.update(count_ngrams(lemmas, max_n=settings.keyword_ngram_max))

    threshold = min_frequency or settings.min_keyword_freq
    filtered = Counter(
        {gram: count for gram, count in counter.items() if count >= threshold}
    )
    out = settings.keywords_output
    _write_terms(out, list(format_terms(filtered, top=top or settings.top_keywords)))
    logger.success(
        "Сохранено {} терминов (порог >= {}) в {}", len(filtered), threshold, out
    )

    if use_ai if use_ai is not None else settings.ai_analytics_enabled:
        if settings.openai_api_key:
            _run_ai_analytics(settings, vacancies)
        else:
            logger.warning(
                "OPENAI_API_KEY не задан — пропускаю ИИ-аналитику "
                "(ai_analytics.txt не создаётся)"
            )
    return out


def _run_ai_analytics(
    settings: Settings, vacancies: list[dict[str, Any]]
) -> Path | None:
    """Генерирует сводку по вакансиям и сохраняет в ai_analytics.txt.

    Ошибки -> None: keywords.txt уже записан, пайплайн не ломается.
    """
    try:
        from ejob_parsing.ai import OpenAIClient, analyze_vacancies

        client = OpenAIClient(settings)
        logger.info(
            "Запускаю ИИ-аналитику (модель {}) по {} вакансиям...",
            client.model,
            len(vacancies),
        )
        text = analyze_vacancies(client, vacancies)
        out = settings.ai_analytics_output
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            text + ("\n" if text and not text.endswith("\n") else ""),
            encoding="utf-8",
        )
        logger.success("ИИ-аналитика сохранена в {}", out)
        return out

    except AIGenerationError as e:
        logger.warning(
            f"Ошибка при генерации ответа ({type(e)}: {e}). Использую обычный анализ."
        )
    except Exception as e:
        logger.warning(
            f"ИИ-аналитика недоступна ({type(e)}: {e}). Использую обычный анализ."
        )
    return None


def format_terms(
    counter: Counter[tuple[str, ...]], *, top: int | None = None
) -> list[tuple[str, int]]:
    """Пары (термин, частота) из счётчика n-грамм, отсортированные по убыванию."""
    return [(" ".join(gram), count) for gram, count in counter.most_common(top)]
