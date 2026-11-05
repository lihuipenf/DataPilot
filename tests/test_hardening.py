"""外部审计回归：预算、持久化、配置和资源生命周期。"""
import json
import os
import sqlite3
import tempfile
import threading
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
import time

import pandas as pd
from fastapi.testclient import TestClient
from datapilot.agent import AgentSession
from datapilot.config import Settings, validate_endpoint
from datapilot.data import DataError, MAX_BYTES, load_sales
from datapilot.models import ModelError, ModelReply, ToolCall
from datapilot.store import SessionStore, StorageError
from datapilot.tools import ToolRegistry
from datapilot.web import create_app


class HardeningTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def client(self, **kwargs):
        settings = Settings(output_dir=self.root/'out', state_path=self.root/'state.sqlite3', **kwargs)
        client = TestClient(create_app(settings), base_url='http://localhost')
        client.__enter__()
        self.addCleanup(client.__exit__, None, None, None)
        return client

    def test_long_sql_result_is_explicitly_truncated_and_schemas_fit_context(self):
        frame = load_sales(pd.DataFrame([dict(date='2026-01-01',product='P'*117+f'{i:03d}',quantity=1,unit_price=1) for i in range(200)]))
        settings = Settings()
        class Gateway:
            mode='test'
            requests=[]
            def complete(inner, messages, tools, **kwargs):
                inner.requests.append(messages)
                size=len(json.dumps({'messages':messages,'tools':tools},ensure_ascii=False))
                self.assertLessEqual(size,settings.max_context_chars)
                if len(inner.requests)==1:
                    return ModelReply(tool_calls=[ToolCall('a','run_readonly_sql','{"sql":"SELECT product FROM sales","limit":200}')])
                payload=json.loads(messages[-1]['content'])
                self.assertTrue(payload['truncated'])
                self.assertEqual(payload['row_count'],len(payload['rows']))
                self.assertGreater(len(payload['rows']),0)
                self.assertLess(len(payload['rows']),200)
                return ModelReply(content='结果过多，仅展示部分商品。')
        agent=AgentSession(ToolRegistry(frame,self.root),Gateway(),settings)
        result=agent.ask('查询所有商品')
        self.assertTrue(result.traces[0]['result']['truncated'])

    def test_remote_plain_http_rejected_local_http_allowed(self):
        for url in ['http://example.com/v1','http://192.168.1.2/v1','http://127.0.0.1.evil.example/v1']:
            with self.subTest(url=url), self.assertRaises(ValueError):validate_endpoint(url)
        for url in ['http://localhost:11434/v1','http://127.0.0.1:11434/v1','http://[::1]:11434/v1','https://example.com/v1']:
            self.assertEqual(validate_endpoint(url),url)

    def test_empty_unused_url_defaults_and_invalid_numeric_errors_name_setting(self):
        with patch.dict(os.environ,{'OPENAI_BASE_URL':'','DATAPILOT_TIMEOUT':'abc'},clear=True), patch('datapilot.config.load_dotenv'):
            with self.assertRaisesRegex(ValueError,'DATAPILOT_TIMEOUT'):Settings.from_env()
        with patch.dict(os.environ,{'OPENAI_BASE_URL':''},clear=True), patch('datapilot.config.load_dotenv'):
            self.assertEqual(Settings.from_env().select('openai').base_url,'https://api.openai.com/v1')

    def test_trailing_slash_upload_and_control_character_filename(self):
        c=self.client();sid=c.post('/api/sessions',json={'mode':'demo'}).json()['id']
        raw=b'date,product,quantity,unit_price\n'+b'2026-01-01,A,1,10\n'*1300
        r=c.post(f'/api/sessions/{sid}/dataset/',content=raw,headers={'content-type':'text/csv','x-filename':'a%00%0d%0ab.csv'})
        self.assertEqual(r.status_code,200)
        self.assertEqual(r.json()['filename'],'ab.csv')
        self.assertEqual(r.json()['summary']['row_count'],1300)

    def test_mode_endpoint_clones_and_original_history_survives_restart(self):
        c=self.client();sid=c.post('/api/sessions',json={'mode':'demo'}).json()['id']
        c.post(f'/api/sessions/{sid}/chat',json={'question':'总销售额是多少？'})
        clone=c.post(f'/api/sessions/{sid}/mode',json={'mode':'demo'}).json()
        self.assertNotEqual(clone['id'],sid)
        self.assertEqual(clone['turns'],[])
        self.assertEqual(len(c.get(f'/api/sessions/{sid}').json()['turns']),1)
        restored=self.client()
        self.assertEqual(len(restored.get(f'/api/sessions/{sid}').json()['turns']),1)

    def test_memory_store_rejected_with_actionable_error(self):
        with self.assertRaisesRegex(StorageError,':memory:'):SessionStore(':memory:')

    def test_path_read_is_bounded_before_allocating_entire_file(self):
        path=self.root/'large.csv'
        with path.open('wb') as f:f.truncate(MAX_BYTES+100)
        # Path.read_bytes整包读取会触发此断言；有界open/read不受影响。
        with patch.object(Path,'read_bytes',side_effect=AssertionError('unbounded read')):
            with self.assertRaises(DataError):load_sales(path)

    def test_sql_connection_closed_on_dataset_replace_and_shutdown(self):
        c=self.client();sid=c.post('/api/sessions',json={'mode':'demo'}).json()['id']
        engine=c.app.state.records[sid].agent.registry.sql_engine
        r=c.post(f'/api/sessions/{sid}/dataset/default')
        self.assertEqual(r.status_code,200)
        with self.assertRaises(sqlite3.ProgrammingError):engine.connection.execute('SELECT 1')
        engine2=c.app.state.records[sid].agent.registry.sql_engine
        c.__exit__(None,None,None)
        # 避免重复退出TestClient；退出后允许再次close。
        self._cleanups.pop()
        with self.assertRaises(sqlite3.ProgrammingError):engine2.connection.execute('SELECT 1')

    def test_production_host_rejects_testserver(self):
        c=self.client()
        self.assertEqual(c.get('/api/health',headers={'host':'testserver'}).status_code,400)

    def test_store_session_limit_rejects_new_but_allows_update(self):
        c=self.client(max_saved_sessions=2)
        ids=[c.post('/api/sessions',json={'mode':'demo'}).json()['id'] for _ in range(2)]
        self.assertEqual(c.post('/api/sessions',json={'mode':'demo'}).status_code,503)
        self.assertEqual(c.post(f'/api/sessions/{ids[0]}/chat',json={'question':'总销售额是多少？'}).status_code,200)

    def test_cancelled_turn_never_commits_history(self):
        event=threading.Event();event.set()
        class Gateway:
            mode='test'
            def complete(self,*a,**k):raise AssertionError('cancelled call must not reach model')
        agent=AgentSession(ToolRegistry(load_sales(),self.root),Gateway(),Settings())
        with self.assertRaises(ModelError) as ctx:agent.ask('总销售额？',cancelled=event)
        self.assertEqual(ctx.exception.code,'cancelled')
        self.assertEqual(agent.turns,[])

    def test_artifact_limit_preserves_existing_files(self):
        c=self.client(max_session_charts=1)
        sid=c.post('/api/sessions',json={'mode':'demo'}).json()['id']
        tools=c.app.state.records[sid].agent.registry
        first=tools.execute('create_sales_chart','{}')
        second=tools.execute('create_sales_chart','{}')
        self.assertIn('artifact',first)
        self.assertIn('error',second)
        self.assertTrue((tools.output_dir/first['artifact']['id']).is_file())

    def test_slow_restore_does_not_block_another_resident_session(self):
        c=self.client();old=c.post('/api/sessions',json={'mode':'demo'}).json()['id']
        engine=c.app.state.records[old].agent.registry.sql_engine
        for _ in range(33):resident=c.post('/api/sessions',json={'mode':'demo'}).json()['id']
        with self.assertRaises(sqlite3.ProgrammingError):engine.connection.execute('SELECT 1')
        entered,release=threading.Event(),threading.Event()
        load=SessionStore.load
        def slow(store,identifier):
            if identifier==old:
                entered.set()
                if not release.wait(5):raise RuntimeError('test synchronization timeout')
            return load(store,identifier)
        with patch.object(SessionStore,'load',slow), ThreadPoolExecutor(max_workers=2) as pool:
            first=pool.submit(c.get,f'/api/sessions/{old}')
            try:
                self.assertTrue(entered.wait(2))
                second=pool.submit(c.get,f'/api/sessions/{resident}')
                self.assertEqual(second.result(timeout=2).status_code,200)
                self.assertEqual(c.get(f'/api/sessions/{old}').status_code,409)
            finally:release.set()
            self.assertEqual(first.result(timeout=3).status_code,200)

    def test_slow_upload_persistence_does_not_block_health(self):
        c=self.client();sid=c.post('/api/sessions',json={'mode':'demo'}).json()['id']
        entered,release=threading.Event(),threading.Event()
        save=SessionStore.save
        def slow(store,payload):
            if payload['filename']=='probe.csv':
                entered.set()
                if not release.wait(5):raise RuntimeError('test synchronization timeout')
            return save(store,payload)
        with patch.object(SessionStore,'save',slow), ThreadPoolExecutor(max_workers=2) as pool:
            first=pool.submit(c.post,f'/api/sessions/{sid}/dataset',content=b'date,product,quantity,unit_price\n2026-01-01,A,1,10\n',headers={'x-filename':'probe.csv'})
            try:
                self.assertTrue(entered.wait(2))
                self.assertEqual(pool.submit(c.get,'/api/health').result(timeout=2).status_code,200)
            finally:release.set()
            self.assertEqual(first.result(timeout=3).status_code,200)

    def test_deadline_and_inflight_cancel_prevent_commit(self):
        class Slow:
            mode='test'
            def complete(self,*args,**kwargs):
                time.sleep(0.01)
                return ModelReply(content='too late')
        agent=AgentSession(ToolRegistry(load_sales(),self.root),Slow(),replace(Settings(),turn_timeout=0.001))
        with self.assertRaises(ModelError) as caught:agent.ask('总销售额？')
        self.assertEqual(caught.exception.code,'turn_timeout')
        self.assertEqual(agent.turns,[])

        c=self.client();sid=c.post('/api/sessions',json={'mode':'demo'}).json()['id']
        entered,release=threading.Event(),threading.Event()
        class Gate:
            mode='test'
            def complete(self,*args,**kwargs):
                entered.set()
                if not release.wait(5):raise RuntimeError('test synchronization timeout')
                return ModelReply(content='cancelled response')
        c.app.state.records[sid].agent.gateway=Gate()
        with ThreadPoolExecutor(max_workers=1) as pool:
            first=pool.submit(c.post,f'/api/sessions/{sid}/chat',json={'question':'总销售额？'})
            try:
                self.assertTrue(entered.wait(2))
                self.assertEqual(c.post(f'/api/sessions/{sid}/cancel').status_code,200)
            finally:release.set()
            self.assertEqual(first.result(timeout=3).status_code,409)
        self.assertEqual(c.get(f'/api/sessions/{sid}').json()['turns'],[])

    def test_cancel_idle_session_does_not_cancel_next_turn(self):
        c=self.client();sid=c.post('/api/sessions',json={'mode':'demo'}).json()['id']
        self.assertEqual(c.post(f'/api/sessions/{sid}/cancel').status_code,409)
        self.assertEqual(c.post(f'/api/sessions/{sid}/chat',json={'question':'总销售额？'}).status_code,200)
