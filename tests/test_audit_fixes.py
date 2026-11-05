"""2026-11-05 审计回归：真实 SQL、CSV 和 HTTP 边界。"""
import csv
import io
import tempfile
import tracemalloc
import unittest
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient
from datapilot.config import Settings
from datapilot.data import DataError, load_sales
from datapilot.reports import markdown_report
from datapilot.sql import ReadOnlySql
from datapilot.web import create_app


class ResourceTests(unittest.TestCase):
    def test_oversized_sql_fields_are_rejected_without_batch_allocation(self):
        engine = ReadOnlySql(load_sales())
        self.addCleanup(engine.close)
        expr = "'aaaaaaaaa'"
        for _ in range(5):
            expr = f"replace({expr},'a','aaaaaaaaaa')"
        tracemalloc.start()
        try:
            result = engine.query(f'SELECT {expr} AS value FROM sales a, sales b LIMIT 20', limit=20)
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        self.assertIn('error', result)
        self.assertLess(peak, 5_000_000, '应在首个超长字段处停止，不分配整批18MB结果')
        self.assertEqual(engine.query('SELECT 1 AS ok')['rows'], [{'ok': 1}])

    def test_sql_total_result_budget_includes_many_small_fields(self):
        engine = ReadOnlySql(load_sales())
        self.addCleanup(engine.close)
        # 使用绑定参数，使 SQL 文本本身保持在长度上限内。
        result = engine.query('SELECT ? AS a, ? AS b FROM sales x, sales y, sales z LIMIT 100',
                              ['中' * 1900, '文' * 1900], limit=100)
        self.assertTrue('error' in result, '超出总字节预算必须拒绝')
        self.assertEqual(engine.query('SELECT product FROM sales', limit=2)['row_count'], 2)

    def test_wide_csv_is_rejected_but_regular_extra_columns_work(self):
        raw = ('date,product,quantity,unit_price,' + ','.join(f'x{i}' for i in range(10000))
               + '\n2026-01-01,Sample,1,10,' + ','.join('1' for _ in range(10000)) + '\n').encode()
        with self.assertRaises(DataError):
            load_sales(raw)
        frame = load_sales(b'date,product,quantity,unit_price,note\n2026-01-01,00123,1,10,ignored\n')
        self.assertEqual(frame['product'].tolist(), ['00123'])
        self.assertEqual(frame['sales_amount'].tolist(), [10])
        with self.assertRaises(DataError):
            load_sales(b'date,product,quantity,unit_price,note\n2026-01-01,A,1,10\n')

    def test_sql_budget_counts_repeated_column_names(self):
        engine = ReadOnlySql(load_sales())
        self.addCleanup(engine.close)
        result = engine.query('SELECT 1 AS "' + 'x' * 3000 + '" FROM sales a, sales b, sales c LIMIT 100', limit=100)
        self.assertTrue('error' in result, '列名在每行对象中重复，必须计入结果预算')


class HttpAndReportTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.app = create_app(Settings(output_dir=Path(self.directory.name)))
        self.client = TestClient(self.app, raise_server_exceptions=False, base_url="http://localhost")
        self.addCleanup(self.client.close)
        self.sid = self.client.post('/api/sessions', json={'mode': 'demo'}).json()['id']
        self.url = '/api/sessions/' + self.sid

    def test_non_json_bodies_are_rejected_without_affecting_valid_requests(self):
        for media in ['text/plain', 'application/octet-stream', 'application/x-www-form-urlencoded', '']:
            with self.subTest(media=media):
                headers = {'content-type': media} if media else {}
                response = self.client.post(self.url + '/chat', content=b'\xff', headers=headers)
                self.assertEqual(response.status_code, 415)
                self.assertIn('detail', response.json())
        for media in ['application/json', 'application/problem+json', 'Application/JSON']:
            response = self.client.post(self.url + '/chat', content='{"question":"总销售额是多少？"}'.encode(),
                                        headers={'content-type': media})
            self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.post(self.url + '/reset').status_code, 200)
        self.assertEqual(self.client.post(self.url + '/dataset/default').status_code, 200)

    def test_export_product_html_and_markdown_are_inert_text(self):
        name = '<img src="https://audit.invalid/pixel"> ![x](https://audit.invalid/p)'
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(['date', 'product', 'quantity', 'unit_price'])
        writer.writerow(['2026-01-01', name, 1, 10])
        self.assertEqual(self.client.post(self.url + '/dataset', content=buf.getvalue().encode(),
                                         headers={'x-filename': 'probe.csv'}).status_code, 200)
        report = self.client.get(self.url + '/export.md').text
        self.assertNotIn('<img', report)
        self.assertNotIn('![x](', report)
        self.assertIn('10', report)

    def test_untrusted_answer_and_trace_cannot_escape_report_code_blocks(self):
        record = self.app.state.records[self.sid]
        attack = '```\n<img src="https://audit.invalid/pixel">\n![x](https://audit.invalid/p)\n````'
        result = SimpleNamespace(answer=attack, mode='demo', provider='', model='',
                                 traces=[{'name':'`<img>', 'duration_ms':1, 'result':{'value':attack}}],
                                 request_count=1, duration_ms=1, usage={})
        record.results = [(attack, result)]
        report = markdown_report(record)
        # 用围栏状态识别报告中的活动内容，拒绝正文中逸出的 HTML/图片。
        import re
        fence = None
        for line in report.splitlines():
            match = re.match(r'^(`{3,})(.*)$', line)
            if fence:
                if match and len(match[1]) >= fence and not match[2].strip():
                    fence = None
            elif match:
                fence = len(match[1])
            else:
                self.assertNotIn('<img', line)
                self.assertNotIn('![x](', line)
        self.assertIsNone(fence)
        self.assertIn('## 说明', report)
