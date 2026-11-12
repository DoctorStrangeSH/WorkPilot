import io
import json
import unittest
from unittest.mock import Mock
from malenia.web import PublicSearch, NoRedirect, WebError, public_link
from malenia.ai import OllamaClient, AIError

RSS = b'<rss><channel><item><title>Japan</title><link>https://example.org/japan</link><description>Tokyo is the capital of Japan.</description></item></channel></rss>'

class WebTests(unittest.TestCase):
    def test_fixed_endpoint_bounded_snippets_and_no_page_fetch(self):
        search = PublicSearch(); search._opener = Mock()
        search._opener.open.return_value = io.BytesIO(RSS)
        sources = search.search('Japan capital')
        self.assertEqual(sources[0]['url'], 'https://example.org/japan')
        self.assertEqual(search._opener.open.call_count, 1)
        request = search._opener.open.call_args.args[0]
        self.assertEqual(request.full_url, 'https://www.bing.com/search?format=rss&q=Japan+capital')
        self.assertFalse(request.has_header('Cookie'))

    def test_unsafe_links_and_redirects_are_rejected(self):
        for value in ['file:///secret', 'http://localhost/test', 'http://127.0.0.1', 'https://169.254.169.254/x',
                      'https://[::1]/', 'https://user:pass@example.org', 'https://example.org:8765/', 'https://foo.local/x',
                      'https://example.org\\@127.0.0.1/x', 'javascript:alert(1)', 'http://2130706433/x']:
            self.assertFalse(public_link(value), value)
        with self.assertRaises(WebError):
            NoRedirect().redirect_request(None,None,302,None,None,'http://localhost')

    def test_oversized_malformed_xml_and_entities_fail_closed(self):
        for raw in [b'x' * (256*1024+1), b'<html>captcha</html>', b'<!DOCTYPE rss><rss/>', b'invalid']:
            search=PublicSearch(); search._opener=Mock(); search._opener.open.return_value=io.BytesIO(raw)
            with self.assertRaises(WebError): search.search('fixture')

    def client(self):
        client=OllamaClient(Mock()); client.web=Mock()
        client.web.search.return_value=[{'id':'web-1','title':'Japan','source':'https://example.org/japan',
            'url':'https://example.org/japan','kind':'web','excerpt':'Tokyo is the capital.'}]
        client._request=Mock(side_effect=[{'models':[{'name':'qwen3:8b'}]}, {'done':True,'message':{'content':json.dumps({'answer':'Tokyo','sufficient':True,'source_ids':['web-1']})}}])
        return client

    def payload(self, **extra):
        return {'model':'qwen3:8b','messages':[{'role':'user','content':'private past question'},
            {'role':'assistant','content':'private past answer'},{'role':'user','content':'Japan capital'}], **extra}

    def test_web_is_opt_in_and_never_receives_history_or_knowledge(self):
        client=self.client(); result=client.chat(self.payload(use_web=True))
        client.web.search.assert_called_once_with('Japan capital')
        client.knowledge.retrieve.assert_not_called()
        body=client._request.call_args.args[1]
        self.assertEqual(body['messages'][1:],[{'role':'user','content':'Japan capital'}])
        self.assertNotIn('private past', str(body))
        self.assertEqual(result['answer_mode'],'web'); self.assertFalse(result['local_only'])
        self.assertEqual(result['cited_source_ids'],['web-1'])
        client=self.client(); client.knowledge=None
        client._request=Mock(side_effect=[{'models':[{'name':'qwen3:8b'}]}, {'done':True,'message':{'content':'Tokyo'}}])
        client.chat(self.payload()); client.web.search.assert_not_called()

    def test_no_results_skips_generation_and_network_failure_is_visible(self):
        client=self.client(); client.web.search.return_value=[]
        result=client.chat(self.payload(use_web=True)); self.assertFalse(result['generated'])
        client._request.assert_not_called()
        client.web.search.side_effect=WebError('web_search_unavailable')
        with self.assertRaises(AIError) as error: client.chat(self.payload(use_web=True))
        self.assertEqual(error.exception.code,'web_search_unavailable')

    def test_conflicting_modes_non_boolean_and_fabricated_citations_rejected(self):
        for extra in [{'use_web':'yes'},{'use_web':True,'knowledge_only':True}]:
            client=self.client()
            with self.assertRaises(AIError): client.chat(self.payload(**extra))
            client.web.search.assert_not_called()
        client=self.client()
        client._request.side_effect=[{'models':[{'name':'qwen3:8b'}]},{'done':True,'message':{'content':json.dumps({'answer':'wrong','sufficient':True,'source_ids':['invented']})}}]
        with self.assertRaises(AIError): client.chat(self.payload(use_web=True))
