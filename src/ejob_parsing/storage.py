"""JSON Lines хранилища: запись, чтение, дедупликация.

Формат хранения — .jsonl (раздел 2.1 ТЗ): строка = один JSON-объект,
удобно дописывать без загрузки всего файла в память.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import orjson
from loguru import logger

__all__ = ["JsonlDedupStore", "append_jsonl", "ensure_dir", "iter_jsonl"]


def ensure_dir(path: Path) -> Path:
    """Создаёт родительский каталог файла, если его нет."""
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def append_jsonl(path: Path, item: dict[str, Any]) -> None:
    """Дописывает один объект в конец .jsonl-файла."""
    ensure_dir(path)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(orjson.dumps(item).decode() + "\n")


def iter_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    """Читает .jsonl-файл, допуская многострочные записи и битые фрагменты.

    Записи могут быть как однострочными (стандартный JSON Lines), так и
    pretty-printed (по несколько строк). Незакрытые/повреждённые фрагменты
    пропускаются с предупреждением — файл не должен валить весь пайплайн.
    """
    if not path.exists():
        return
    buffer: list[str] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            stripped = line.strip()
            if not stripped:
                continue
            buffer.append(stripped)
            candidate = "".join(buffer)
            try:
                item = orjson.loads(candidate)
            except orjson.JSONDecodeError:
                # Пришло начало новой записи, а буфер так и не собрался — старый фрагмент битый
                if stripped.startswith("{") and len(buffer) > 1:
                    logger.warning("Пропускаю повреждённый фрагмент в {}", path)
                    buffer = [stripped]
                continue
            buffer = []
            yield item
    if buffer:
        logger.warning(
            "Пропускаю незакрытый хвост файла {} ({} строк)", path, len(buffer)
        )


class JsonlDedupStore:
    """Дописывает записи в .jsonl и отбрасывает дубликаты по ключевому полю.

    Используется для вакансий (F-1.5, ключ `vacancyId`) и резюме (F-3.6,
    ключ `resume_id`). При старте читает уже собранные ключи из файла,
    поэтому повторный запуск не создаёт дубликатов.
    """

    def __init__(self, path: Path, key_field: str) -> None:
        self.path = ensure_dir(path)
        self.key_field = key_field
        self._seen: set[str] = {
            str(item[key_field]) for item in iter_jsonl(path) if key_field in item
        }

    def add(self, item: dict[str, Any]) -> bool:
        """Сохраняет запись. Возвращает False, если ключ уже встречался."""
        key = str(item.get(self.key_field))
        if key in self._seen:
            return False
        append_jsonl(self.path, item)
        self._seen.add(key)
        return True

    def __contains__(self, key: object) -> bool:
        """Позволяет проверять `key in store` без записи."""
        return str(key) in self._seen

    @property
    def size(self) -> int:
        """Количество уникальных записей в хранилище."""
        return len(self._seen)
