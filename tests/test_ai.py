import io
import json
import unittest
from unittest.mock import Mock
from malenia.ai import AIError, NoRedirect, OllamaClient

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

    def test_oversized_provider_response_is_not_returned(self):
        self.client._opener=Mock()
        self.client._opener.open.return_value=io.BytesIO(b"x"*131073)
        with self.assertRaises(AIError):self.client._request("/api/chat",self.payload)

if __name__=="__main__":unittest.main()
