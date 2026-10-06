"""Тесты модуля вакансий: список (DOM-карточки), страница вакансии (JSON-LD),
параллельные фазы сбора и метки страниц (searchQuery/searchPage)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from ejob_parsing.models import Vacancy
from ejob_parsing.parsers.vacancies import (
    SEARCH_URL,
    _collect_links,
    _fetch_vacancy,
    _last_pages,
    _read_progress,
    _write_progress,
    build_search_queries,
    extract_initial_state,
    extract_vacancy_links,
    matches_vacancy,
    parse_jsonld,
    parse_salary,
    parse_search_cards,
    parse_vacancy_page,
)
from ejob_parsing.storage import append_jsonl
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


def test_matches_vacancy_work_formats() -> None:
    # формат работы: "удаленн" есть в тексте (с учётом ё/е) -> подходит
    vacancy = _vacancy_with_text("Удалённая работа. Разработка на Python")
    assert matches_vacancy(vacancy, work_formats=["удаленн"])
    assert not matches_vacancy(vacancy, work_formats=["офис"])
    # латиница ищется так же по подстроке
    remote = _vacancy_with_text("Remote-friendly, стек Python/Go")
    assert matches_vacancy(remote, work_formats=["remote"])
    # пустой список = фильтр выключен
    assert matches_vacancy(vacancy, work_formats=[])


def test_matches_vacancy_schedule_considered() -> None:
    # формат работы ищется и в поле schedule
    vacancy = Vacancy(
        vacancy_id="1",
        name="Developer",
        schedule="Полный день",
    )
    assert not matches_vacancy(vacancy, work_formats=["удаленн"])
    vacancy.schedule = "Удалённый график"
    assert matches_vacancy(vacancy, work_formats=["удаленн"])


def test_matches_vacancy_all_filters_combined() -> None:
    vacancy = _vacancy_with_text("Удалённая работа, Python, без ручного тестирования")
    assert matches_vacancy(
        vacancy,
        ["python"],
        exclude_keywords=["qa"],
        work_formats=["удаленн"],
    )
    assert not matches_vacancy(
        vacancy,
        ["python"],
        exclude_keywords=["тестирован"],
        work_formats=["удаленн"],
    )
    assert not matches_vacancy(
        vacancy,
        ["python"],
        exclude_keywords=["qa"],
        work_formats=["офис"],
    )


# ── Параллельные фазы (parse_workers) ───────────────────────────────────


class _FakeResponse:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeClient:
    """Подмена HttpClient: список -> SEARCH_HTML, вакансия -> VACANCY_HTML.

    Запоминает вызовы get (URL + params), чтобы тесты могли проверить,
    с какой страницы началась пагинация.
    """

    instances: list[_FakeClient] = []

    def __init__(self, settings: Any = None, *, impersonate: str = "chrome") -> None:
        self.settings = settings
        self.calls: list[tuple[str, dict[str, Any] | None]] = []
        _FakeClient.instances.append(self)

    def get(self, url: str, params: dict[str, Any] | None = None) -> _FakeResponse:
        self.calls.append((url, params))
        if url == SEARCH_URL:
            return _FakeResponse(SEARCH_HTML)
        return _FakeResponse(VACANCY_HTML)

    def close(self) -> None:
        return None


class _BrokenClient(_FakeClient):
    """Сетевой сбой: _fetch_vacancy должен вернуть ("error", msg)."""

    def get(self, url: str, params: dict[str, Any] | None = None) -> _FakeResponse:
        raise RuntimeError("network down")


def _vacancy_link() -> dict[str, Any]:
    return {
        "vacancyId": "138126305",
        "url": "https://hh.ru/vacancy/138126305",
        "name": "Инженер-программист",
        "searchQuery": "middle fullstack python",
        "searchPage": 2,
    }


def test_collect_links_parallel(monkeypatch: pytest.MonkeyPatch) -> None:
    """Два запроса обрабатываются воркерами; ссылки собираются в общий список."""
    _FakeClient.instances.clear()
    monkeypatch.setattr("ejob_parsing.parsers.vacancies.HttpClient", _FakeClient)
    queries = [
        {"text": "middle fullstack python", "experience": "between3And6"},
        {"text": "senior web go", "experience": "between3And6"},
    ]
    links, progress = _collect_links(make_settings(), queries, pages_limit=1, workers=2)
    assert len(links) == 4  # 2 запроса x 2 карточки со страницы
    assert all(link["vacancyId"].isdigit() for link in links)
    # каждая ссылка помечена запросом и номером страницы выдачи
    query_texts = {q["text"] for q in queries}
    assert all(link["searchQuery"] in query_texts for link in links)
    assert all(link["searchPage"] == 0 for link in links)
    # прогресс: по каждому запросу обработана страница 0
    assert progress == {q["text"]: 0 for q in queries}


def test_fetch_vacancy_add(monkeypatch: pytest.MonkeyPatch) -> None:
    """Вакансия прошла фильтры -> ("add", данные для сохранения)."""
    monkeypatch.setattr("ejob_parsing.parsers.vacancies.HttpClient", _FakeClient)
    status, payload = _fetch_vacancy(make_settings(), _vacancy_link(), ["python"])
    assert status == "add"
    assert isinstance(payload, dict)
    assert payload["vacancyId"] == "138126305"
    assert payload["employer"]["name"] == "ООО Ромашка"
    # метки страницы попадают в данные для сохранения
    assert payload["searchQuery"] == "middle fullstack python"
    assert payload["searchPage"] == 2


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


def test_last_pages_returns_max_per_query(tmp_path: Path) -> None:
    """Из записей .jsonl берётся максимальная страница по каждому запросу."""
    path = tmp_path / "vacancies.jsonl"
    append_jsonl(
        path,
        {"vacancyId": "1", "searchQuery": "middle fullstack python", "searchPage": 2},
    )
    append_jsonl(
        path,
        {"vacancyId": "2", "searchQuery": "middle fullstack python", "searchPage": 5},
    )
    append_jsonl(
        path,
        {"vacancyId": "3", "searchQuery": "senior web go", "searchPage": 1},
    )
    append_jsonl(path, {"vacancyId": "4"})  # старые записи без меток игнорируются
    assert _last_pages(path) == {
        "middle fullstack python": 5,
        "senior web go": 1,
    }


def test_collect_links_skips_pages_before_last(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Пагинация начинается с последней обработанной страницы, а не с нуля."""
    _FakeClient.instances.clear()
    monkeypatch.setattr("ejob_parsing.parsers.vacancies.HttpClient", _FakeClient)
    queries = [{"text": "middle fullstack python", "experience": "between3And6"}]
    links, progress = _collect_links(
        make_settings(),
        queries,
        pages_limit=4,
        workers=1,
        start_pages={"middle fullstack python": 2},
    )
    requested_pages = [
        params.get("page") or 0
        for client in _FakeClient.instances
        for _, params in client.calls
        if params is not None
    ]
    assert requested_pages == [2, 3]  # страницы 0 и 1 не перезапрашивались
    assert len(links) == 4  # 2 страницы x 2 карточки
    assert all(link["searchPage"] in (2, 3) for link in links)
    # прогресс фиксирует последнюю запрошенную страницу (даже если с неё
    # ничего бы не сохранилось — дубли/фильтр)
    assert progress == {"middle fullstack python": 3}


def test_progress_roundtrip(tmp_path: Path) -> None:
    """Прогресс пагинации сохраняется и читается обратно."""
    path = tmp_path / "vacancies.jsonl.progress.json"
    _write_progress(
        path,
        {
            "middle fullstack python": 4,
            "senior web go": 1,
        },
    )
    assert _read_progress(path) == {
        "middle fullstack python": 4,
        "senior web go": 1,
    }


def test_read_progress_missing_or_broken(tmp_path: Path) -> None:
    """Отсутствующий или повреждённый файл прогресса = пустой словарь."""
    missing = tmp_path / "none.json"
    assert _read_progress(missing) == {}
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    assert _read_progress(broken) == {}
    empty = tmp_path / "empty.json"
    _write_progress(empty, {})  # пустой прогресс не создаёт файл
    assert not empty.exists()
