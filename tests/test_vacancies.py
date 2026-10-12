"""Тесты модуля вакансий: список (DOM-карточки), страница вакансии (JSON-LD)
и параллельные фазы сбора (_collect_links, _fetch_vacancy)."""

from __future__ import annotations

from typing import Any

import pytest

from ejob_parsing.models import Vacancy
from ejob_parsing.parsers.vacancies import (
    SEARCH_URL,
    _collect_links,
    _fetch_vacancy,
    build_search_queries,
    extract_initial_state,
    extract_vacancy_links,
    matches_vacancy,
    parse_jsonld,
    parse_salary,
    parse_search_cards,
    parse_vacancy_page,
)
from tests._settings import make_settings

SEARCH_HTML = """
<html><body>
<article data-qa="vacancy-serp__vacancy vacancy-serp-item_clickme">
  <div class="actions-container-narrow--ERhWyxHyP98YkBk2"></div>
  <div id="138126305" class="vacancy-card--n77Dj8TY8VIUF0yM font-inter">
    <a data-qa="serp-item__title" href="https://adsrv.hh.ru/click?b=1">Инженер-программист</a>
  </div>
</article>
<article data-qa="vacancy-serp__vacancy">
  <div id="138126306" class="vacancy-card--n77Dj8TY8VIUF0yM font-inter">
    <a data-qa="serp-item__title" href="https://hh.ru/vacancy/138126306">Backend dev</a>
  </div>
</article>
<!--noindex--><template style="display:none" id="HH-Lux-InitialState">
{"redirectConfig":{"strictMode":true}}
</template><!--/noindex-->
</body></html>
"""


def test_build_search_queries_splits_by_technology() -> None:
    """Каждая технология уходит отдельным запросом — выборка шире (R-2)."""
    settings = make_settings(
        search_levels=["middle", "senior"],
        search_directions=["fullstack", "web"],
        search_technologies=["python", "go"],
    )
    queries = build_search_queries(settings)
    assert len(queries) == 2 * 2 * 2  # уровни x направления x технологии
    texts = [q["text"] for q in queries]
    assert "middle fullstack python" in texts
    assert "senior web go" in texts
    assert all(q["experience"] == "between3And6" for q in queries)


def test_build_search_queries_multiple_experiences() -> None:
    """SEARCH_EXPERIENCE=between1And3,between3And6 -> запрос на каждый опыт."""
    settings = make_settings(
        search_levels=["middle"],
        search_directions=["fullstack"],
        search_technologies=["python"],
        search_experience=["between1And3", "between3And6"],
    )
    queries = build_search_queries(settings)
    # 1 уровень x 1 направление x 1 технология x 2 опыта
    assert len(queries) == 2
    experiences = {q["experience"] for q in queries}
    assert experiences == {"between1And3", "between3And6"}


def test_build_search_queries_work_formats() -> None:
    """SEARCH_WORK_FORMATS добавляет work_format в запрос (регистр -> upper)."""
    settings = make_settings(
        search_levels=["middle"],
        search_directions=["fullstack"],
        search_technologies=["python"],
        search_work_formats=["remote", "hybrid"],
    )
    queries = build_search_queries(settings)
    # по одному запросу на формат, значение нормализовано в верхний регистр
    assert len(queries) == 2
    assert {q["work_format"] for q in queries} == {"REMOTE", "HYBRID"}
    # без настроенных форматов параметр work_format в запросах отсутствует
    plain = build_search_queries(make_settings())
    assert all("work_format" not in q for q in plain)


VACANCY_HTML = """
<html><body>
<h1 data-qa="vacancy-title">Инженер-программист</h1>
<span data-qa="vacancy-salary-compensation-type-net">
  от <data value="200000">200 000</data> до <data value="300000">300 000</data>
  <data value="RUB">₽</data> за месяц
</span>
<a data-qa="vacancy-view-raw-address">Москва</a>
<p data-qa="vacancy-experience">3–6 лет</p>
<li class="vacancy-skill-list-item--PumrWcVEn0Syd8vd" data-qa="skills-element">
  <div class="magritte-tag__label___YHV-o_5-3-25_xhh">Python</div>
</li>
<li class="vacancy-skill-list-item--PumrWcVEn0Syd8vd" data-qa="skills-element">
  <div class="magritte-tag__label___YHV-o_5-3-25_xhh">Django</div>
</li>
<span data-qa="vacancy-view-response-counter">12 откликов</span>
<script type="application/ld+json">
{
  "@context": "https://schema.org/",
  "@type": "JobPosting",
  "description": "<p>Разработка сервисов на <b>Python</b> и Go</p>",
  "datePosted": "2026-10-05T13:35:00.934+03:00",
  "title": "Инженер-программист",
  "hiringOrganization": {"@type": "Organization", "name": "ООО Ромашка"},
  "identifier": {"@type": "PropertyValue", "value": 138126305}
}
</script>
</body></html>
"""


def test_extract_initial_state_flexible_attributes() -> None:
    """template с атрибутами перед id (реальная вёрстка hh.ru) разбирается."""
    state = extract_initial_state(SEARCH_HTML)
    assert state["redirectConfig"]["strictMode"] is True


def test_parse_search_cards_from_dom() -> None:
    cards = parse_search_cards(SEARCH_HTML, make_settings())
    assert len(cards) == 2
    assert cards[0]["vacancyId"] == "138126305"
    assert cards[0]["url"] == "https://hh.ru/vacancy/138126305"
    assert cards[0]["name"] == "Инженер-программист"


def test_extract_vacancy_links_falls_back_to_dom() -> None:
    """InitialState без vacancySearchResult -> ссылки берём из DOM-карточек."""
    links = extract_vacancy_links(SEARCH_HTML, make_settings())
    assert len(links) == 2
    assert links[1]["vacancyId"] == "138126306"


def test_parse_jsonld() -> None:
    meta = parse_jsonld(VACANCY_HTML)
    assert meta["title"] == "Инженер-программист"
    assert meta["hiringOrganization"]["name"] == "ООО Ромашка"
    assert meta["datePosted"].startswith("2026")


def test_parse_salary() -> None:
    salary = parse_salary("от 200 000 до 300 000 ₽")
    assert salary is not None
    assert salary.from_ == 200000
    assert salary.to == 300000
    assert salary.currency == "RUR"
    assert parse_salary(None) is None


def test_parse_salary_handles_nbsp() -> None:
    # неразрывные пробелы между разрядами не должны ломать парсинг
    salary = parse_salary("от\u00a025\u00a0000\u00a0до\u00a040\u00a0000\u00a0₽")
    assert salary is not None
    assert salary.from_ == 25000
    assert salary.to == 40000


def test_parse_vacancy_page() -> None:
    vacancy = parse_vacancy_page(VACANCY_HTML, "138126305", make_settings())
    assert isinstance(vacancy, Vacancy)
    assert vacancy.vacancy_id == "138126305"
    assert vacancy.name == "Инженер-программист"
    assert vacancy.employer.name == "ООО Ромашка"
    assert vacancy.salary is not None and vacancy.salary.from_ == 200000
    assert vacancy.area is not None and vacancy.area.name == "Москва"
    assert vacancy.experience == "3–6 лет"
    assert vacancy.key_skills == ["Python", "Django"]
    assert vacancy.responses_count == 12
    # описание из JSON-LD очищено от HTML для модуля ключевых слов (F-2.2)
    assert vacancy.description == "Разработка сервисов на Python и Go"
    assert vacancy.published_at is not None and vacancy.published_at.year == 2026


def test_matches_vacancy() -> None:
    vacancy = parse_vacancy_page(VACANCY_HTML, "1", make_settings())
    assert matches_vacancy(vacancy, ["python"])
    assert matches_vacancy(vacancy, ["Go"])  # регистр не важен
    assert not matches_vacancy(vacancy, ["rust"])
    assert matches_vacancy(vacancy, [])  # пустой список = подходят все


def _vacancy_with_text(text: str) -> Vacancy:
    return Vacancy(vacancy_id="1", name="Middle Developer", description=text)


def test_matches_vacancy_excludes_keywords() -> None:
    # негативные параметры: слово в тексте вакансии -> скип
    vacancy = _vacancy_with_text("QA инженер, автоматизация тестирования")
    assert not matches_vacancy(vacancy, exclude_keywords=["qa"])
    assert not matches_vacancy(vacancy, exclude_keywords=["тестирован"])
    assert matches_vacancy(vacancy, exclude_keywords=["manager"])
    # регистр не важен
    assert not matches_vacancy(vacancy, exclude_keywords=["QA"])


def test_matches_vacancy_all_filters_combined() -> None:
    # формат работы теперь задаётся критерием поиска (SEARCH_WORK_FORMATS),
    # а здесь остаются только позитивные и негативные ключевые слова
    vacancy = _vacancy_with_text("Удалённая работа, Python, без ручного тестирования")
    assert matches_vacancy(vacancy, ["python"], exclude_keywords=["qa"])
    assert not matches_vacancy(vacancy, ["python"], exclude_keywords=["тестирован"])


# ── Параллельные фазы (parse_workers) ───────────────────────────────────


class _FakeResponse:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeClient:
    """Подмена HttpClient: список -> SEARCH_HTML, вакансия -> VACANCY_HTML."""

    def __init__(self, settings: Any = None, *, impersonate: str = "chrome") -> None:
        self.settings = settings

    def get(self, url: str, params: dict[str, Any] | None = None) -> _FakeResponse:
        if url == SEARCH_URL:
            return _FakeResponse(SEARCH_HTML)
        return _FakeResponse(VACANCY_HTML)

    def close(self) -> None:
        return None


class _BrokenClient(_FakeClient):
    """Сетевой сбой: _fetch_vacancy должен вернуть ("error", msg)."""

    def get(self, url: str, params: dict[str, Any] | None = None) -> _FakeResponse:
        raise RuntimeError("network down")


def _vacancy_link() -> dict[str, str]:
    return {
        "vacancyId": "138126305",
        "url": "https://hh.ru/vacancy/138126305",
        "name": "Инженер-программист",
    }


def test_collect_links_parallel(monkeypatch: pytest.MonkeyPatch) -> None:
    """Два запроса обрабатываются воркерами; ссылки собираются в общий список."""
    monkeypatch.setattr("ejob_parsing.parsers.vacancies.HttpClient", _FakeClient)
    queries = [
        {"text": "middle fullstack python", "experience": "between3And6"},
        {"text": "senior web go", "experience": "between3And6"},
    ]
    links = _collect_links(make_settings(), queries, pages_limit=1, workers=2)
    assert len(links) == 4  # 2 запроса x 2 карточки со страницы
    assert all(link["vacancyId"].isdigit() for link in links)


def test_fetch_vacancy_add(monkeypatch: pytest.MonkeyPatch) -> None:
    """Вакансия прошла фильтры -> ("add", данные для сохранения)."""
    monkeypatch.setattr("ejob_parsing.parsers.vacancies.HttpClient", _FakeClient)
    status, payload = _fetch_vacancy(make_settings(), _vacancy_link(), ["python"])
    assert status == "add"
    assert isinstance(payload, dict)
    assert payload["vacancyId"] == "138126305"
    assert payload["employer"]["name"] == "ООО Ромашка"


def test_fetch_vacancy_skip(monkeypatch: pytest.MonkeyPatch) -> None:
    """Не совпали ключевые слова -> ("skip", "")."""
    monkeypatch.setattr("ejob_parsing.parsers.vacancies.HttpClient", _FakeClient)
    status, payload = _fetch_vacancy(make_settings(), _vacancy_link(), ["rust"])
    assert status == "skip"
    assert payload == ""


def test_fetch_vacancy_network_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Сетевой сбой не роняет пул: воркер возвращает ("error", msg)."""
    monkeypatch.setattr("ejob_parsing.parsers.vacancies.HttpClient", _BrokenClient)
    status, payload = _fetch_vacancy(make_settings(), _vacancy_link(), ["python"])
    assert status == "error"
    assert "network down" in str(payload)
