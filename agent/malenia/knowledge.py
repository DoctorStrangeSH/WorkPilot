"""Explicit local knowledge storage and bounded Markdown snapshot import."""
from __future__ import annotations
import os
import re
import uuid
from pathlib import Path
from .store import TaskStore, _now

class KnowledgeError(ValueError):
    pass


def words(text):
    stop = {"какая", "какой", "какие", "это", "для", "как", "что", "the", "and", "номер", "заказ"}
    return {w for w in re.findall(r"[^\W_]{2,}", text.casefold()) if w not in stop}


def identifiers(text):
    # Keep the complete code, including separators: AB-17 must never match AB-170.
    candidates = re.findall(r"(?<![\w./-])[\w]+(?:[-./][\w]+)+(?![\w./-])", text.casefold())
    return {code for code in candidates if any(c.isalpha() for c in code) and any(c.isdigit() for c in code)}


def passages(content):
    # Overlap keeps answers around paragraph/window boundaries. Offsets refer to
    # the stored snapshot, not to a live file which may have changed meanwhile.
    for start in range(0, max(1, len(content)), 400):
        yield start, content[start:start + 600]


def match_score(query, title, text):
    query_words = words(query)
    title_words, text_words = words(title), words(text)
    exact = len(query_words & text_words) + 3 * len(query_words & title_words)
    # Prefix matching is only a fallback for long words, never for numeric codes.
    prefixes = {word[:5] for word in query_words if len(word) >= 5 and word.isalpha()}
    fallback = len(prefixes & {word[:5] for word in title_words | text_words if len(word) >= 5 and word.isalpha()})
    phrase = query.casefold().strip()
    return exact * 4 + fallback + (8 if len(phrase) >= 4 and phrase in text.casefold() else 0)


class KnowledgeBase:
    def __init__(self, store: TaskStore):
        self.store = store
        with store._session() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS knowledge (
                id TEXT PRIMARY KEY, title TEXT NOT NULL, content TEXT NOT NULL,
                kind TEXT NOT NULL, source TEXT NOT NULL, origin TEXT NOT NULL,
                updated_at TEXT NOT NULL)""")

    def list(self):
        with self.store._session() as db:
            return [dict(row) for row in db.execute("SELECT * FROM knowledge ORDER BY updated_at DESC, id")]

    @staticmethod
    def validate(title, content, kind):
        if not isinstance(title, str) or not title.strip() or len(title) > 120:
            raise KnowledgeError("Название: от 1 до 120 символов")
        limit = 2000 if kind == "memory" else 6000
        if not isinstance(kind, str) or kind not in {"memory", "note"} or not isinstance(content, str) or not content.strip() or len(content) > limit:
            raise KnowledgeError(f"Текст: от 1 до {limit} символов")

    def save(self, request_id, title, content, kind="memory"):
        try:
            if str(uuid.UUID(request_id)) != request_id:
                raise ValueError()
        except (ValueError, TypeError, AttributeError):
            raise KnowledgeError("Некорректный идентификатор записи") from None
        self.validate(title, content, kind)
        with self.store._session() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT * FROM knowledge WHERE id = ?", (request_id,)).fetchone()
            if old:
                if old["title"] != title.strip() or old["content"] != content.strip() or old["kind"] != kind:
                    raise KnowledgeError("Эта запись уже сохранена с другим текстом")
                return dict(old)
            count = db.execute("SELECT count(*) FROM knowledge").fetchone()[0]
            memories = db.execute("SELECT count(*) FROM knowledge WHERE kind='memory'").fetchone()[0]
            if count >= 200 or (kind == "memory" and memories >= 12):
                raise KnowledgeError("Лимит: 12 записей памяти и 200 заметок всего. Удалите ненужные записи")
            record = dict(id=request_id, title=title.strip(), content=content.strip(), kind=kind,
                          source="Подтверждено пользователем", origin="", updated_at=_now())
            db.execute("INSERT INTO knowledge VALUES (:id,:title,:content,:kind,:source,:origin,:updated_at)", record)
        return record

    def delete(self, record_id):
        with self.store._session() as db:
            return db.execute("DELETE FROM knowledge WHERE id = ?", (record_id,)).rowcount > 0

    @staticmethod
    def _linked(path):
        return path.is_symlink() or bool(getattr(path.lstat(), "st_file_attributes", 0) & 0x400)

    def import_folder(self, folder):
        if not isinstance(folder, str) or not folder:
            raise KnowledgeError("Укажите абсолютный путь к отдельной папке заметок")
        requested = Path(folder)
        if not requested.is_absolute():
            raise KnowledgeError("Нужен абсолютный путь к папке")
        try:
            if any(self._linked(p) for p in [requested, *requested.parents]):
                raise KnowledgeError("Папки-ссылки не импортируются")
            root = requested.resolve(strict=True)
            if not root.is_dir() or root == Path(root.anchor) or root == Path.home():
                raise KnowledgeError("Выберите отдельную папку заметок")
            records, stack, visited = [], [(root, 0)], 0
            while stack:
                directory, depth = stack.pop()
                for path in sorted(directory.iterdir()):
                    visited += 1
                    if visited > 1000:
                        raise KnowledgeError("В папке слишком много файлов. Выберите папку поменьше")
                    if path.name.startswith('.') or self._linked(path) or bool(getattr(path.lstat(), "st_file_attributes", 0) & 2):
                        continue
                    if path.is_dir():
                        if depth >= 6:
                            raise KnowledgeError("Вложенность папки превышает 6 уровней")
                        stack.append((path, depth + 1))
                    elif path.suffix.lower() == '.md' and path.is_file():
                        if len(records) >= 100 or path.stat().st_size > 24 * 1024:
                            raise KnowledgeError("Лимит импорта: 100 заметок, до 24 КБ каждая")
                        with path.open('rb') as stream:
                            raw = stream.read(24 * 1024 + 1)
                        if len(raw) > 24 * 1024:
                            raise KnowledgeError("Заметка слишком большая")
                        content = raw.decode('utf-8-sig')
                        relative = path.relative_to(root).as_posix()
                        title = next((line.lstrip('#').strip() for line in content.splitlines()
                                      if line.startswith('# ')), path.stem)[:120]
                        self.validate(title, content, "note")
                        records.append(dict(id=str(uuid.uuid5(uuid.NAMESPACE_URL, str(root) + '/' + relative)),
                            title=title, content=content, kind="note", source=relative, origin=str(root), updated_at=_now()))
            if not records:
                raise KnowledgeError("В папке нет непустых заметок .md в UTF-8")
            with self.store._session() as db:
                db.execute("BEGIN IMMEDIATE")
                other = db.execute("SELECT count(*) FROM knowledge WHERE origin != ?", (str(root),)).fetchone()[0]
                if other + len(records) > 200:
                    raise KnowledgeError("Лимит базы — 200 записей")
                db.execute("DELETE FROM knowledge WHERE origin = ?", (str(root),))
                db.executemany("INSERT INTO knowledge VALUES (:id,:title,:content,:kind,:source,:origin,:updated_at)", records)
            return {"imported": len(records), "snapshot": True}
        except (OSError, UnicodeError):
            raise KnowledgeError("Не удалось прочитать выбранные заметки. Нужны обычные файлы .md в UTF-8") from None

    def retrieve(self, query, matched_only=False):
        if not isinstance(query, str) or not query.strip() or len(query) > 2000:
            raise KnowledgeError("Поисковый запрос: от 1 до 2000 символов")
        query_codes = identifiers(query)
        ranked = []
        for record in self.list():
            title_codes = identifiers(record['title'])
            # A differently numbered record is not a source for the requested ID.
            if query_codes and title_codes and not query_codes & title_codes:
                continue
            preference = record['kind'] == 'memory' and not matched_only and not identifiers(record['title'] + ' ' + record['content'])
            candidates = []
            for start, excerpt in passages(record['content']):
                codes = identifiers(excerpt) | title_codes
                if query_codes and not query_codes & codes and not preference:
                    continue
                score = match_score(query, record['title'], excerpt)
                if query_codes:
                    score += 40 * len(query_codes & codes)
                candidates.append((score, -start, excerpt))
            if not candidates:
                continue
            score, negative_start, excerpt = max(candidates)
            # Preferences may be supplied as context in ordinary chat. In strict
            # mode and preview, only text matching the question qualifies.
            if score <= 0 and (matched_only or record['kind'] != 'memory'):
                continue
            start = -negative_start
            ranked.append((score, {"id": record['id'], "title": record['title'], "source": record['source'],
                "kind": record['kind'], "excerpt": excerpt, "start": start, "end": start + len(excerpt)}))
        memories = sorted((r for r in ranked if r[1]['kind'] == 'memory'), key=lambda r: r[0], reverse=True)[:2]
        notes = sorted((r for r in ranked if r[1]['kind'] == 'note'), key=lambda r: r[0], reverse=True)[:2]
        return [record for _, record in memories + notes]
