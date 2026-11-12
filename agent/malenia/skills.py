"""Local, reviewable skill recipes for Malenia's general-purpose assistant.

Recipes are instructional context only, never executable code or capabilities.
All edits come from explicit local user approval, not model output or web pages.
"""
from __future__ import annotations

import re
import sqlite3
import uuid
from typing import Any

from .store import TaskStore, _now
from .knowledge import match_score, identifiers


class SkillError(ValueError):
    pass


BUILTINS = (
    {"id": "order-review", "title": "Проверка заказов",
     "description": "Анализ грузомест, сканов и статусов логистики",
     "instructions": "Уточни исходный номер и дату. Отличай предложенный статус от изменения в системе. Проверяй SC, результат и время скана. Не заявляй, что проверил сайты, если источник не был подключён.",
     "terms": "заказ грузоместо инвента datalens asgard скан статус"},
    {"id": "research", "title": "Поиск и исследование",
     "description": "Сравнение источников, проверка утверждений и неопределённости",
     "instructions": "Разделяй факты, предположения и недостающие сведения. Не выдумывай ссылки. Для актуальных фактов требуй разрешённый источник или обозначай, что нужна проверка.",
     "terms": "исследование анализ сравнение источники факты информация"},
    {"id": "planning", "title": "Планирование работы",
     "description": "Декомпозиция задач, зависимости и критерии готовности",
     "instructions": "Предложи короткий конкретный план с проверяемым результатом. Отмечай зависимости, требуемые права и шаги, которые нельзя исполнять без подключения.",
     "terms": "план задача проект этапы сроки сделать автоматизация"},
    {"id": "data-analysis", "title": "Разбор данных",
     "description": "Таблицы, показатели, сверки и качество данных",
     "instructions": "Проверяй полноту исходных данных, пропуски и дубликаты. Не приписывай данным точность или обновлённость, если этого нельзя подтвердить.",
     "terms": "таблица отчёт excel данные дашборд метрики показатели"},
)
MAX_CUSTOM = 100
VALID_CATEGORY = re.compile(r"^[a-z][a-z0-9_-]{2,39}$")


class SkillRegistry:
    def __init__(self, store: TaskStore):
        self.store = store
        with store._session() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS assistant_skills (
                id TEXT PRIMARY KEY, title TEXT NOT NULL, description TEXT NOT NULL,
                instructions TEXT NOT NULL, terms TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('draft','approved')),
                updated_at TEXT NOT NULL
            )""")

    @staticmethod
    def _validate(title: Any, description: Any, instructions: Any, terms: Any) -> None:
        if not isinstance(title, str) or not 1 <= len(title.strip()) <= 80:
            raise SkillError("invalid_skill_title")
        if not isinstance(description, str) or not 1 <= len(description.strip()) <= 200:
            raise SkillError("invalid_skill_description")
        if not isinstance(instructions, str) or not 1 <= len(instructions.strip()) <= 1600:
            raise SkillError("invalid_skill_instructions")
        if not isinstance(terms, str) or not 1 <= len(terms.strip()) <= 240:
            raise SkillError("invalid_skill_terms")

    def list(self) -> list[dict[str, Any]]:
        builtins = [{**s, "status": "approved", "builtin": True} for s in BUILTINS]
        with self.store._session() as db:
            rows = db.execute(
                "SELECT * FROM assistant_skills ORDER BY updated_at DESC,id"
            ).fetchall()
        return builtins + [{**dict(row), "builtin": False} for row in rows]

    def draft(self, request_id: str, title: str, description: str,
              instructions: str, terms: str) -> dict[str, Any]:
        try:
            if str(uuid.UUID(request_id)) != request_id:
                raise ValueError()
        except (ValueError, TypeError, AttributeError):
            raise SkillError("invalid_skill_id") from None
        self._validate(title, description, instructions, terms)
        values = (title.strip(), description.strip(), instructions.strip(), terms.strip())
        with self.store._session() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute("SELECT * FROM assistant_skills WHERE id=?",
                                  (request_id,)).fetchone()
            if existing:
                record = dict(existing)
                if tuple(record[k] for k in ("title", "description", "instructions", "terms")) != values:
                    raise SkillError("skill_request_conflict")
                return {**record, "builtin": False}
            count = db.execute("SELECT COUNT(*) FROM assistant_skills").fetchone()[0]
            if count >= MAX_CUSTOM:
                raise SkillError("skill_limit_reached")
            db.execute(
                """INSERT INTO assistant_skills
                   (id,title,description,instructions,terms,status,updated_at)
                   VALUES (?,?,?,?,?,'draft',?)""",
                (request_id, *values, _now()),
            )
        return self.get(request_id)

    def get(self, skill_id: str) -> dict[str, Any] | None:
        with self.store._session() as db:
            record = db.execute("SELECT * FROM assistant_skills WHERE id=?",
                                (skill_id,)).fetchone()
        return {**dict(record), "builtin": False} if record else None

    def approve(self, skill_id: str) -> dict[str, Any]:
        if not isinstance(skill_id, str):
            raise SkillError("invalid_skill_id")
        with self.store._session() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT status FROM assistant_skills WHERE id=?",
                             (skill_id,)).fetchone()
            if row is None:
                raise SkillError("skill_not_found")
            if row["status"] == "draft":
                db.execute("UPDATE assistant_skills SET status='approved',updated_at=? WHERE id=?",
                           (_now(), skill_id))
        return self.get(skill_id)

    def delete(self, skill_id: str) -> bool:
        if not isinstance(skill_id, str):
            raise SkillError("invalid_skill_id")
        with self.store._session() as db:
            return db.execute("DELETE FROM assistant_skills WHERE id=?",
                              (skill_id,)).rowcount > 0

    def matching(self, query: str, limit: int = 2) -> list[dict[str, Any]]:
        if not isinstance(query, str) or not 1 <= len(query.strip()) <= 2000:
            return []
        query_codes = identifiers(query)
        results = []
        for skill in self.list():
            if skill["status"] != "approved":
                continue
            text = skill["description"] + " " + skill["terms"]
            if identifiers(text) and query_codes and not identifiers(text) & query_codes:
                continue
            score = match_score(query, skill["title"], text)
            if score > 0:
                results.append((score, skill))
        results.sort(key=lambda item: (-item[0], item[1]["id"]))
        return [{k: item[k] for k in ("id", "title", "description", "instructions")}
                for _, item in results[:max(0, min(limit, 3))]]
