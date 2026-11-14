import tempfile
import unittest
from pathlib import Path
from uuid import uuid4
from unittest.mock import patch
from malenia.store import TaskStore
from malenia.knowledge import KnowledgeBase, KnowledgeError

class KnowledgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = TaskStore(self.root / 'fixture.sqlite3')
        self.base = KnowledgeBase(self.store)
    def tearDown(self):
        self.temp.cleanup()
    def save(self,title='Правило проверки',content='Не выдумывать номер заказа',kind='memory'):
        return self.base.save(str(uuid4()),title,content,kind)
    def test_confirmed_memory_survives_reopen_and_can_be_deleted(self):
        record = self.save()
        reopened = KnowledgeBase(TaskStore(self.store.path))
        self.assertEqual(reopened.list()[0]['content'],record['content'])
        self.assertEqual(reopened.retrieve('Проверь заказ')[0]['id'],record['id'])
        self.assertTrue(reopened.delete(record['id']))
        self.assertEqual(reopened.retrieve('Проверь заказ'),[])
        self.assertEqual(self.store.list_tasks(),[])
        self.assertEqual(self.store.list_events(),[])
    def test_retries_do_not_duplicate_or_silently_change_memory(self):
        record = self.save()
        self.assertEqual(self.base.save(record['id'],record['title'],record['content']),record)
        with self.assertRaises(KnowledgeError):self.base.save(record['id'],'Изменено',record['content'])
        self.assertEqual(len(self.base.list()),1)
    def test_invalid_and_excessive_memory_is_rejected(self):
        for title,content,kind in [('', 'text','memory'),('title','x'*2001,'memory'),('title','text','command'),('title','text',[]),('title','text',{})]:
            with self.assertRaises(KnowledgeError):self.base.save(str(uuid4()),title,content,kind)
        for n in range(12):self.save(title=str(n))
        with self.assertRaises(KnowledgeError):self.save()
    def folder(self,name='vault'):
        folder=self.root/name;folder.mkdir();return folder
    def test_import_is_explicit_snapshot_and_preserves_manual_memory(self):
        folder=self.folder()
        (folder/'Japan.md').write_text('# Япония\nСтолица Японии — Токио.',encoding='utf-8')
        (folder/'not-a-note.txt').write_text('not imported')
        hidden=folder/'.obsidian';hidden.mkdir();(hidden/'secret.md').write_text('not imported')
        self.save()
        self.assertEqual(self.base.import_folder(str(folder))['imported'],1)
        sources=self.base.retrieve('Столица Японии')
        self.assertTrue(any('Токио' in r['excerpt'] and r['source']=='Japan.md' for r in sources))
        self.assertEqual(self.base.import_folder(str(folder))['imported'],1)
        self.assertEqual(len(self.base.list()),2)
        (folder/'Japan.md').unlink();(folder/'Order.md').write_text('# Заказы\nПроверять количество.',encoding='utf-8')
        self.base.import_folder(str(folder))
        self.assertEqual({r['title'] for r in self.base.list()},{'Заказы','Правило проверки'})
    def test_failed_import_is_atomic_and_does_not_remove_old_snapshot(self):
        folder=self.folder();note=folder/'note.md';note.write_text('original',encoding='utf-8')
        self.base.import_folder(str(folder))
        note.write_text('x'*6001,encoding='utf-8')
        with self.assertRaises(KnowledgeError):self.base.import_folder(str(folder))
        self.assertEqual(self.base.list()[0]['content'],'original')
    def test_no_link_traversal_or_relative_and_root_import(self):
        folder=self.folder();(folder/'note.md').write_text('fixture',encoding='utf-8')
        with patch.object(self.base,'_linked',return_value=True),self.assertRaises(KnowledgeError):
            self.base.import_folder(str(folder))
        for path in ['relative',str(Path(self.root.anchor)),str(Path.home())]:
            with self.assertRaises(KnowledgeError):self.base.import_folder(path)
    def test_retrieval_is_bounded_and_does_not_include_unrelated_notes(self):
        self.save('Кошки','Кошки спят','note')
        self.assertEqual(self.base.retrieve('Номер заказа'),[])
        for n in range(5):self.save('Заказ '+str(n),'Заказ '+('текст '*900),'note')
        records=self.base.retrieve('Заказ')
        self.assertLessEqual(len(records),4)
        self.assertTrue(all(len(r['excerpt'])<=600 for r in records))

    def test_exact_identifier_excludes_similar_and_unknown_order_numbers(self):
        wanted=self.save('Заказ AB-17','Адрес заказа AB-17: Токио.','note')
        self.save('Заказ AB-170','Адрес заказа AB-170: Магадан.','note')
        self.save('Заказ AB-18','Адрес заказа AB-18: Москва.','note')
        matches=self.base.retrieve('Какой адрес у ab-17?',matched_only=True)
        self.assertEqual([r['id'] for r in matches],[wanted['id']])
        self.assertEqual(self.base.retrieve('Адрес AB-19',matched_only=True),[])
        self.assertEqual(self.base.retrieve('Адрес AB-1700',matched_only=True),[])

    def test_passage_contains_specific_answer_far_from_generic_query_word(self):
        content='Доставка: общие условия. '+('Справочная информация. '*80)+'\nСтоимость доставки в Токио: 500 рублей.\n'+('Дополнение. '*40)
        note=self.save('Регламент доставки',content,'note')
        hit=self.base.retrieve('Стоимость доставки в Токио',matched_only=True)[0]
        self.assertEqual(hit['id'],note['id'])
        self.assertIn('500 рублей',hit['excerpt'])
        self.assertGreater(hit['start'],600)
        self.assertEqual(hit['excerpt'],content[hit['start']:hit['end']])
        self.assertLessEqual(len(hit['excerpt']),600)

    def test_general_preferences_remain_context_but_do_not_satisfy_strict_search(self):
        preference=self.save('Общение','Пиши кратко и вежливо')
        self.assertEqual(self.base.retrieve('Адрес AB-17')[0]['id'],preference['id'])
        self.assertEqual(self.base.retrieve('Адрес AB-17',matched_only=True),[])
        self.assertEqual(self.base.retrieve('Столица Японии',matched_only=True),[])

    def test_search_does_not_reread_source_files(self):
        folder=self.folder();note=folder/'note.md';note.write_text('Код заказа AB-17: Токио',encoding='utf-8')
        self.base.import_folder(str(folder));note.unlink()
        with patch.object(Path,'open',side_effect=AssertionError('Search must use snapshot')):
            self.assertIn('Токио',self.base.retrieve('AB-17',matched_only=True)[0]['excerpt'])

if __name__=='__main__':unittest.main()
