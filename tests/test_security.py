"""安全与异常输入回归；仅使用临时数据，不读取真实业务数据或调用外部模型。"""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from datapilot.config import Settings
from datapilot.web import create_app
from datapilot.data import load_sales
from .test_core import registry


class BoundaryTests(unittest.TestCase):
    def setUp(self):
        self.client=TestClient(create_app(Settings(output_dir=Path(tempfile.mkdtemp()))), base_url="http://localhost")
        self.addCleanup(self.client.close)
        self.identifier=self.client.post('/api/sessions',json={'mode':'demo'}).json()['id']
        self.url=f'/api/sessions/{self.identifier}'

    def test_cross_site_simple_reset_is_denied_and_history_survives(self):
        self.client.post(self.url+'/chat',json={'question':'总销售额是多少？'})
        for headers in [{'origin':'https://untrusted.example'}, {'origin':'null'}, {'sec-fetch-site':'cross-site'}]:
            with self.subTest(headers=headers):
                response=self.client.post(self.url+'/reset',headers=headers)
                self.assertEqual(response.status_code,403)
                self.assertEqual(len(self.client.get(self.url).json()['turns']),1)

    def test_same_origin_and_non_browser_clients_remain_usable(self):
        self.assertEqual(self.client.post(self.url+'/reset',headers={'origin':'http://localhost'}).status_code,200)
        self.assertEqual(self.client.get('/api/sessions',headers={'origin':'https://other.example'}).status_code,403)
        self.assertEqual(self.client.get('/api/sessions').status_code,200)

    def test_json_body_is_bounded_with_and_without_content_length(self):
        body=json.dumps({'question':'x'*20000}).encode()
        for content in [body, iter([body[:10000],body[10000:]])]:
            with self.subTest(streamed=not isinstance(content,bytes)):
                response=self.client.post(self.url+'/chat',content=content,headers={'content-type':'application/json'})
                self.assertEqual(response.status_code,413)
        self.assertEqual(self.client.get(self.url).json()['turns'],[])

    def test_security_headers_and_invalid_host(self):
        self.assertEqual(self.client.get('/api/sessions',headers={'host':'attacker.example'}).status_code,400)
        page=self.client.get('/')
        self.assertEqual(page.headers.get('x-content-type-options'),'nosniff')
        self.assertIn("frame-ancestors 'none'",page.headers.get('content-security-policy',''))
        self.assertEqual(self.client.get(self.url).headers.get('cache-control'),'no-store')

    def test_only_machine_readable_api_schema_is_exposed_without_cdn_scripts(self):
        self.assertEqual(self.client.get('/docs').status_code,404)
        self.assertEqual(self.client.get('/redoc').status_code,404)
        self.assertIn('/api/sessions',self.client.get('/openapi.json').json()['paths'])

    def test_nonfinite_deep_or_invalid_unicode_json_is_rejected_without_500(self):
        for media in ['application/json','application/problem+json','Application/JSON']:
            for body in [b'{"mode":NaN}', b'{"mode":1e999}', b'{"model":"\\ud800"}', b'['*2000+b'0'+b']'*2000]:
                with self.subTest(media=media,body_length=len(body)):
                    response=self.client.post('/api/sessions',content=body,headers={'content-type':media})
                    self.assertEqual(response.status_code,400)

    def test_csv_identifiers_remain_strings_and_na_is_a_valid_name(self):
        frame=load_sales(b'date,product,quantity,unit_price\n2026-01-01,00123,1,10\n2026-01-01,123,1,20\n2026-01-01,NA,1,30\n2026-01-01,1e3,1,40\n')
        self.assertEqual(frame['product'].tolist(),['00123','123','NA','1e3'])
        numeric=load_sales(b'date,product,quantity,unit_price\n2026-01-01,00123,1,10\n2026-01-01,123,1,20\n')
        self.assertEqual(numeric['product'].tolist(),['00123','123'])

    def test_oversized_sql_integer_returns_structured_error_then_next_query_works(self):
        tools=registry()
        result=tools.execute('run_readonly_sql',json.dumps({'sql':'SELECT ? AS value','parameters':[2**80]}))
        self.assertIn('error',result)
        self.assertEqual(tools.execute('get_total_sales','{}'),{'total_sales_amount':1350})

    def test_nonfinite_model_arguments_remain_serializable_tool_errors(self):
        from dataclasses import asdict
        from datapilot.agent import AgentSession
        from datapilot.models import ModelReply, ToolCall
        class Gateway:
            mode='test'
            replies=[ModelReply(tool_calls=[ToolCall('a','get_product_ranking','{"limit":NaN}')]),
                     ModelReply(content='参数无效，请使用整数排名数量。')]
            def complete(self,*args,**kwargs):
                return self.replies.pop(0)
        result=AgentSession(registry(),Gateway(),Settings()).ask('列出排名')
        self.assertFalse(result.traces[0]['success'])
        json.dumps(asdict(result),allow_nan=False)
        tools=registry()
        self.assertIn('error',tools.execute('get_total_sales','{"extra":'+('['*2000)+'0'+(']'*2000)+'}'))


class PackagingTests(unittest.TestCase):
    def test_scanner_does_not_forget_file_key_when_environment_overrides_it(self):
        from scripts import check_secrets
        import os
        import subprocess
        root=Path(tempfile.mkdtemp())
        subprocess.run(['git','init','-q',str(root)],check=True)
        (root/'.env').write_text('ANTHROPIC_API_KEY=file-private-key\n',encoding='utf-8')
        (root/'notes.md').write_text('file-private-key',encoding='utf-8')
        subprocess.run(['git','-C',str(root),'add','notes.md'],check=True)
        with patch.object(check_secrets,'ROOT',root), patch.dict(os.environ,{'ANTHROPIC_API_KEY':'process-private-key'}):
            with self.assertRaises(RuntimeError):
                check_secrets.check()

    def test_source_archive_rejects_all_provider_credentials(self):
        from scripts import package_source
        for key in ['OPENAI_API_KEY','ANTHROPIC_API_KEY','COMPATIBLE_API_KEY']:
            with self.subTest(key=key):
                root=Path(tempfile.mkdtemp())
                (root/'docs').mkdir()
                (root/'.env').write_text(f'{key}=synthetic-sensitive-value\n',encoding='utf-8')
                (root/'docs'/'leaked.json').write_text('{"value":"synthetic-sensitive-value"}',encoding='utf-8')
                with patch.object(package_source,'ROOT',root):
                    with self.assertRaises(RuntimeError):
                        package_source.package()
                self.assertFalse((root/'dist').exists())
