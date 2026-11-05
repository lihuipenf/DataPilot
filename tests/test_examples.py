"""公开案例契约：真实CSV、离线Agent、Web上传、图表及导出端到端复核。"""
import csv
from decimal import Decimal
import json
from pathlib import Path
import tempfile
import unittest
from fastapi.testclient import TestClient
from datapilot.config import ROOT, Settings
from datapilot.web import create_app


def contains(actual, expected):
    if isinstance(expected,dict):
        return isinstance(actual,dict) and all(k in actual and contains(actual[k],v) for k,v in expected.items())
    if isinstance(expected,list):
        return isinstance(actual,list) and len(actual)==len(expected) and all(contains(a,b) for a,b in zip(actual,expected))
    return actual==expected


class ExampleTests(unittest.TestCase):
    def manifest(self):
        path=ROOT/'examples'/'cases.json'
        self.assertTrue(path.exists(),'缺少三个案例的数据与问题清单')
        return json.loads(path.read_text(encoding='utf-8'))

    def test_three_synthetic_csvs_reconcile_with_decimal(self):
        cases=self.manifest()['cases']
        self.assertEqual([c['id'] for c in cases],['retail_weekly','promotion_review','data_boundaries'])
        for case in cases:
            with self.subTest(case=case['id']):
                with (ROOT/'examples'/case['data_file']).open(encoding='utf-8-sig',newline='') as source:
                    reader=csv.DictReader(source)
                    self.assertEqual(reader.fieldnames,['date','product','quantity','unit_price'])
                    rows=list(reader)
                self.assertEqual(len(rows),case['summary']['row_count'])
                self.assertEqual(sum(int(r['quantity']) for r in rows),case['summary']['total_quantity'])
                self.assertEqual(sum(Decimal(r['quantity'])*Decimal(r['unit_price']) for r in rows),Decimal(str(case['summary']['total_sales_amount'])))
                self.assertEqual(len({r['product'] for r in rows}),case['summary']['product_count'])

    def test_all_documented_demo_questions_through_web(self):
        cases=self.manifest()['cases']
        folder=Path(tempfile.mkdtemp(prefix='datapilot-examples-'))
        with TestClient(create_app(Settings(api_key='',output_dir=folder)), base_url="http://localhost") as client:
            for case in cases:
                with self.subTest(case=case['id']):
                    identifier=client.post('/api/sessions',json={'mode':'demo'}).json()['id']
                    root=f'/api/sessions/{identifier}'
                    uploaded=client.post(root+'/dataset',content=(ROOT/'examples'/case['data_file']).read_bytes(),headers={'x-filename':case['data_file']})
                    self.assertEqual(uploaded.status_code,200,uploaded.text)
                    self.assertTrue(contains(uploaded.json()['summary'],case['summary']))
                    for item in case['questions']:
                        response=client.post(root+'/chat',json={'question':item['question']})
                        self.assertEqual(response.status_code,200,response.text)
                        result=response.json()
                        matches=[t for t in result['traces'] if t['name']==item['tool']]
                        expected=item['expected']
                        if item.get('unordered_rows'):
                            # SQL只按金额排序，并列时不约定内部顺序；按标识匹配结果集合。
                            expected={**expected,'rows':sorted(expected['rows'],key=lambda r:r['product'])}
                            matches=[{**t,'result':{**t['result'],'rows':sorted(t['result']['rows'],key=lambda r:r['product'])}} for t in matches]
                        self.assertTrue(any(contains(t['result'],expected) for t in matches),(case['id'],item['question'],result))
                        for text in item.get('answer_contains',[]):
                            self.assertIn(text,result['answer'])
                        if item['tool']=='create_sales_chart':
                            self.assertEqual(len(result['artifacts']),1)
                        for artifact in result['artifacts']:
                            self.assertTrue(client.get(artifact['url']).content.startswith(b'\x89PNG'))
                    report=client.get(root+'/export.md')
                    self.assertEqual(report.status_code,200)
                    self.assertIn(str(case['summary']['total_sales_amount']),report.text)
                    self.assertEqual(client.get(root+'/export.csv').status_code,200)
