import tempfile
import unittest
from pathlib import Path
from uuid import uuid4
from unittest.mock import Mock

from malenia.ai import OllamaClient
from malenia.skills import SkillRegistry, SkillError
from malenia.store import TaskStore


class SkillRegistryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = TaskStore(Path(self.temp.name) / "skills.sqlite3")
        self.skills = SkillRegistry(self.store)

    def tearDown(self):
        self.temp.cleanup()

    def test_builtin_skills_are_multi_domain_and_not_executable(self):
        builtin = self.skills.list()
        self.assertGreaterEqual(len(builtin), 4)
        self.assertTrue(all(s["builtin"] and s["status"] == "approved" for s in builtin))
        self.assertEqual(self.skills.matching("Проанализируй таблицу Excel")[0]["id"], "data-analysis")
        self.assertEqual(self.skills.matching("Выполни неизвестное")[0:1], [])

    def test_new_skill_draft_requires_approval_and_can_be_deleted(self):
        identity = str(uuid4())
        record = self.skills.draft(identity, "График смен", "Планирование рабочего графика",
                                   "Учитывай длительность смен и перерывы", "график смена перерыв")
        self.assertEqual(record["status"], "draft")
        self.assertFalse(any(x["id"] == identity for x in self.skills.matching("график смена")))
        self.assertEqual(self.skills.draft(identity, record["title"],
                         record["description"], record["instructions"], record["terms"]), record)
        with self.assertRaises(SkillError):
            self.skills.draft(identity, "Изменено", record["description"],
                              record["instructions"], record["terms"])
        self.skills.approve(identity)
        self.assertTrue(any(x["id"] == identity for x in self.skills.matching("график смена")))
        reopened = SkillRegistry(TaskStore(self.store.path))
        self.assertEqual(reopened.get(identity)["status"], "approved")
        self.assertTrue(reopened.delete(identity))
        self.assertFalse(any(x["id"] == identity for x in reopened.matching("график смена")))

    def test_feedback_is_replay_safe_and_contains_no_chat_content(self):
        skill_id = "planning"
        feedback_id = str(uuid4())
        first = self.skills.record_feedback(feedback_id, skill_id, False)
        self.assertFalse(first["helpful"])
        self.assertEqual(self.skills.record_feedback(feedback_id, skill_id, False), first)
        with self.assertRaises(SkillError):
            self.skills.record_feedback(feedback_id, skill_id, True)
        with self.assertRaises(SkillError):
            self.skills.record_feedback(str(uuid4()), "unapproved", True)
        self.assertEqual(self.skills.feedback_counts()[skill_id], (0, 1))
        with self.store._session() as db:
            columns = set(dict(db.execute("SELECT * FROM assistant_skill_feedback").fetchone()))
        self.assertEqual(columns, {"request_id", "skill_id", "helpful", "created_at"})

    def test_sherlock_suggests_skill_but_never_saves_it(self):
        client = OllamaClient()
        suggestion = {"title": "Рабочие письма",
                      "description": "Подготовка профессиональных ответов",
                      "instructions": "Проверь получателя и предложи черновик, ничего не отправляй",
                      "terms": "письмо переписка ответ"}
        client._request = Mock(side_effect=[
            {"models": [{"name": "qwen3:8b"}]},
            {"done": True, "message": {"content": __import__("json").dumps(suggestion)}}])
        result = client.suggest_skill({
            "model": "qwen3:8b", "request": "Как ответить на письмо?",
            "response": "Проверьте адресата и составьте черновик."})
        self.assertEqual(result["suggestion"], suggestion)
        self.assertFalse(result["saved"])
        self.assertFalse(result["approved"])
        self.assertFalse(result["tools_enabled"])
        self.assertEqual(len(self.skills.list()), 4)
        self.assertNotIn("tools", client._request.call_args.args[1])

    def test_suggestion_rejects_invalid_provider_output_and_input(self):
        from malenia.ai import AIError
        client = OllamaClient()
        with self.assertRaises(AIError):
            client.suggest_skill({"model": [], "request": "x", "response": "y"})
        client._request = Mock(side_effect=[
            {"models": [{"name": "qwen3:8b"}]},
            {"done": True, "message": {"content": '{"title":"x"}'}}])
        with self.assertRaises(AIError):
            client.suggest_skill({"model": "qwen3:8b",
                                  "request": "Подскажи", "response": "Шаги"})
        self.assertEqual(len(self.skills.list()), 4)

    def test_ai_receives_only_relevant_approved_skill_not_executable_tool(self):
        client = OllamaClient()
        client.skills = self.skills
        client._request = Mock(side_effect=[
            {"models": [{"name": "qwen3:8b"}]},
            {"done": True, "message": {"role": "assistant", "content": "Проверю шаги."}}
        ])
        result = client.chat({"model": "qwen3:8b",
                              "messages": [{"role": "user", "content": "Составь план проекта"}]})
        self.assertIn("planning", result["skill_ids"])
        body = client._request.call_args.args[1]
        self.assertIn("Планирование работы", body["messages"][0]["content"])
        self.assertNotIn("tools", body)
        self.assertFalse(body["think"])
        self.assertFalse(result["tools_enabled"])


if __name__ == "__main__":
    unittest.main()
