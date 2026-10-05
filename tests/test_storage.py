"""Тесты JSON Lines хранилища: запись, чтение, дедупликация."""

from __future__ import annotations

from pathlib import Path

from ejob_parsing.storage import JsonlDedupStore, iter_jsonl


def test_store_appends_and_reads_back(tmp_path: Path) -> None:
    path = tmp_path / "out" / "vacancies.jsonl"
    store = JsonlDedupStore(path, key_field="vacancyId")

    assert store.add({"vacancyId": "1", "name": "A"})
    assert store.add({"vacancyId": "2", "name": "B"})
    assert store.size == 2

    items = list(iter_jsonl(path))
    assert len(items) == 2
    assert items[0]["name"] == "A"


def test_store_deduplicates_by_key(tmp_path: Path) -> None:
    path = tmp_path / "vacancies.jsonl"
    store = JsonlDedupStore(path, key_field="vacancyId")

    assert store.add({"vacancyId": "1", "name": "A"})
    assert not store.add({"vacancyId": "1", "name": "A-copy"})  # дубликат
    assert store.size == 1

    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1  # дубликат не дописан в файл


def test_store_sees_existing_keys_on_restart(tmp_path: Path) -> None:
    path = tmp_path / "vacancies.jsonl"
    first = JsonlDedupStore(path, key_field="vacancyId")
    first.add({"vacancyId": "1", "name": "A"})

    second = JsonlDedupStore(path, key_field="vacancyId")
    assert not second.add({"vacancyId": "1", "name": "A"})  # ключ известен из файла
    assert second.add({"vacancyId": "2", "name": "B"})
    assert second.size == 2
