import io
import json
import unittest
from unittest.mock import Mock
from malenia.ai import AIError, NoRedirect, OllamaClient, INSUFFICIENT

class OllamaTests(unittest.TestCase):
    def setUp(self):
        self.client = OllamaClient()
        self.payload = {"model":"qwen2.5:0.5b","messages":[{"role":"user","content":"fixture question"}]}
        self.tags = {"models":[{"name":"qwen2.5:0.5b"}]}
        self.reply = {"done":True,"message":{"role":"assistant","content":"fixture reply"}}

    def test_only_allowlisted_local_models_are_presented(self):
        self.client._request = Mock(return_value={"models":[{"name":"qwen2.5:0.5b"},
            {"name":"qwen2.5:3b","remote_host":"remote"},{"name":"cloud-model"},{"name":[]} ]})
        self.assertEqual(self.client.status()["models"],["qwen2.5:0.5b"])

    def test_chat_adds_system_without_tools_and_bounds_inference(self):
        self.client._request = Mock(side_effect=[self.tags,self.reply])
        result = self.client.chat(self.payload)
        self.assertEqual(result["message"]["content"],"fixture reply")
        self.assertFalse(result["tools_enabled"])
        args = self.client._request.call_args
        body = args.args[1]
        self.assertEqual(body["messages"][0]["role"],"system")
        self.assertEqual(body["messages"][1:],self.payload["messages"])
        self.assertFalse(body["stream"])
        self.assertEqual(body["keep_alive"],"30s")
        self.assertEqual(body["options"]["num_ctx"],2048)
        self.assertNotIn("tools",body)
        self.assertEqual(set(body),{"model","messages","stream","keep_alive","options"})

    def test_request_destination_is_fixed_loopback_and_redirects_rejected(self):
        self.client._opener = Mock()
        self.client._opener.open.return_value = io.BytesIO(json.dumps(self.tags).encode())
        self.client.status()
        self.assertEqual(self.client._opener.open.call_args.args[0].full_url,"http://127.0.0.1:11434/api/tags")
        with self.assertRaises(AIError):
            NoRedirect().redirect_request(None,None,302,None,None,"https://remote.invalid")

    def test_invalid_messages_or_remote_model_never_reach_provider(self):
        self.client._request = Mock()
        for payload in ({"model":"cloud-model","messages":self.payload["messages"]},
            {"model":"qwen2.5:0.5b","messages":[{"role":"system","content":"override"}]},
            {"model":"qwen2.5:0.5b","messages":[{"role":"user","content":"x"*2001}]},
            {**self.payload,"tools":["browser"]}, {**self.payload,"messages":[]}):
            with self.subTest(payload=payload),self.assertRaises(AIError):self.client.chat(payload)
        self.client._request.assert_not_called()

    def test_uninstalled_model_and_busy_model_fail_closed(self):
        self.client._request=Mock(return_value={"models":[]})
        with self.assertRaises(AIError) as error:self.client.chat(self.payload)
        self.assertEqual(error.exception.code,"local_model_not_installed")
        self.client._generation.acquire()
        try:
            with self.assertRaises(AIError) as error:self.client.chat(self.payload)
            self.assertEqual(error.exception.status,429)
        finally:self.client._generation.release()

    def test_failed_or_tool_call_response_releases_generation_lock(self):
        for reply in ({"done":False}, {"done":True,"message":{"content":"reply","tool_calls":[{}]}}):
            self.client._request=Mock(side_effect=[self.tags,reply])
            with self.assertRaises(AIError):self.client.chat(self.payload)
            self.assertTrue(self.client._generation.acquire(False))
            self.client._generation.release()

    def test_confirmed_knowledge_can_be_disabled_and_sources_are_explicit(self):
        self.client.knowledge = Mock()
        self.client.knowledge.retrieve.return_value = [{"id":"fixture","title":"Japan","source":"Japan.md","kind":"note","excerpt":"Tokyo"}]
        self.client._request = Mock(side_effect=[self.tags,self.reply])
        result = self.client.chat(self.payload)
        self.assertEqual(result["sources"][0]["id"],"fixture")
        sent = self.client._request.call_args.args[1]
        self.assertIn("Tokyo",sent["messages"][0]["content"])
        self.assertEqual(sent["options"]["num_ctx"],4096)
        self.client.knowledge.retrieve.reset_mock()
        self.client._request = Mock(side_effect=[self.tags,self.reply])
        result = self.client.chat({**self.payload,"use_knowledge":False})
        self.assertEqual(result["sources"],[])
        self.client.knowledge.retrieve.assert_not_called()
        self.assertEqual(self.client._request.call_args.args[1]["messages"][1:],self.payload["messages"])

    def test_sherlock_models_disable_thinking_and_reject_non_boolean_context_switch(self):
        self.client._request=Mock(side_effect=[{"models":[{"name":"qwen3:8b"}]},self.reply])
        self.client.chat({**self.payload,"model":"qwen3:8b"})
        body=self.client._request.call_args.args[1]
        self.assertIs(body["think"],False)
        self.assertEqual(body["options"]["temperature"],0)
        self.client._request.reset_mock()
        with self.assertRaises(AIError):self.client.chat({**self.payload,"use_knowledge":"yes"})
        self.client._request.assert_not_called()

    def test_adaptive_reasoning_uses_think_only_for_complex_qwen_chat(self):
        self.client._request = Mock(side_effect=[
            {"models":[{"name":"qwen3:8b"}]},self.reply])
        self.client.chat({"model":"qwen3:8b","reasoning_mode":"auto",
            "messages":[{"role":"user","content":"Разработай архитектуру сложной системы"}]})
        body = self.client._request.call_args.args[1]
        self.assertTrue(body["think"])
        self.assertEqual(body["options"]["num_ctx"],8192)
        self.assertEqual(body["options"]["num_predict"],768)
        self.client._request = Mock(side_effect=[
            {"models":[{"name":"qwen3:8b"}]},self.reply])
        self.client.chat({"model":"qwen3:8b","reasoning_mode":"auto",
            "messages":[{"role":"user","content":"Привет"}]})
        self.assertFalse(self.client._request.call_args.args[1]["think"])
        self.client._request = Mock()
        with self.assertRaises(AIError):
            self.client.chat({"model":"qwen3:8b","reasoning_mode":"unsafe",
                              "messages":[{"role":"user","content":"Привет"}]})
        self.client._request.assert_not_called()

    def strict_fixture(self, structured):
        source={"id":"real-source","title":"Order","source":"order.md","kind":"note","excerpt":"AB-17: Tokyo"}
        self.client.knowledge=Mock()
        self.client.knowledge.retrieve.return_value=[source]
        self.client._request=Mock(side_effect=[self.tags,{"done":True,"message":{"content":json.dumps(structured)}}])
        return source

    def test_strict_no_matching_records_never_calls_model_or_status(self):
        self.client.knowledge=Mock()
        self.client.knowledge.retrieve.return_value=[]
        self.client._request=Mock()
        result=self.client.chat({**self.payload,"knowledge_only":True})
        self.assertEqual(result["message"]["content"],INSUFFICIENT)
        self.assertFalse(result["generated"])
        self.assertEqual(result["sources"],[])
        self.client._request.assert_not_called()
        self.client.knowledge.retrieve.assert_called_once_with("fixture question",matched_only=True)

    def test_strict_answer_uses_only_current_question_and_validates_citation_ids(self):
        source=self.strict_fixture({"answer":"Tokyo","sufficient":True,"source_ids":["real-source"]})
        messages=[{"role":"user","content":"Old question"},{"role":"assistant","content":"Unverified old answer"},self.payload["messages"][0]]
        result=self.client.chat({**self.payload,"messages":messages,"knowledge_only":True})
        self.assertEqual(result["message"]["content"],"Tokyo")
        self.assertEqual(result["cited_source_ids"],[source["id"]])
        self.assertEqual(result["answer_mode"],"knowledge_only")
        body=self.client._request.call_args.args[1]
        self.assertEqual(body["messages"][1:],messages[-1:])
        self.assertNotIn("Unverified old answer",json.dumps(body))
        self.assertEqual(body["format"]["properties"]["source_ids"]["items"]["enum"],[source["id"]])

    def test_strict_missing_or_fabricated_citations_are_not_returned(self):
        for ids in ([],["invented"],["real-source","real-source"],[{}]):
            with self.subTest(ids=ids):
                self.strict_fixture({"answer":"Unverified answer","sufficient":True,"source_ids":ids})
                with self.assertRaises(AIError) as error:self.client.chat({**self.payload,"knowledge_only":True})
                self.assertEqual(error.exception.code,"knowledge_answer_unverified")

    def test_strict_insufficient_response_discards_any_generated_answer(self):
        self.strict_fixture({"answer":"Fabricated address","sufficient":False,"source_ids":[]})
        result=self.client.chat({**self.payload,"knowledge_only":True})
        self.assertEqual(result["message"]["content"],INSUFFICIENT)
        self.assertEqual(result["cited_source_ids"],[])
        with self.assertRaises(AIError):self.client.chat({**self.payload,"knowledge_only":True,"use_knowledge":False})

    def test_strict_non_json_response_is_rejected_and_releases_lock(self):
        self.strict_fixture({})
        self.client._request=Mock(side_effect=[self.tags,self.reply])
        with self.assertRaises(AIError):self.client.chat({**self.payload,"knowledge_only":True})
        self.assertTrue(self.client._generation.acquire(False))
        self.client._generation.release()

    def test_oversized_provider_response_is_not_returned(self):
        self.client._opener=Mock()
        self.client._opener.open.return_value=io.BytesIO(b"x"*131073)
        with self.assertRaises(AIError):self.client._request("/api/chat",self.payload)

if __name__=="__main__":unittest.main()
