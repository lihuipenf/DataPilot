"""v1.1：SQL约束、指标口径和重启恢复的行为回归。"""
import importlib
import json
from pathlib import Path
import tempfile
import unittest
from .test_core import CSV, module


def temp_dir():
    return Path(tempfile.mkdtemp(prefix="datapilot-v11-"))


class SqlTests(unittest.TestCase):
    def engine(self, **kwargs):
        return module("sql").ReadOnlySql(module("data").load_sales(CSV), **kwargs)

    def test_grouping_and_bound_parameters(self):
        result = self.engine().query("SELECT product, SUM(sales_amount) AS total FROM sales WHERE product = ? GROUP BY product", ["Keyboard"])
        self.assertEqual(result["rows"], [{"product": "Keyboard", "total": 300}])
        self.assertFalse(result["truncated"])

    def test_cte_and_result_truncation(self):
        result = self.engine().query("WITH s AS (SELECT product FROM sales) SELECT * FROM s", limit=2)
        self.assertEqual(result["row_count"], 2)
        self.assertTrue(result["truncated"])

    def test_writes_external_access_and_multiple_statements_are_rejected(self):
        engine = self.engine()
        for sql in ["DELETE FROM sales", "DROP TABLE sales", "UPDATE sales SET quantity=99", "CREATE TABLE x(a)",
                    "ATTACH DATABASE ':memory:' AS other", "PRAGMA database_list", "SELECT load_extension('x')",
                    "SELECT * FROM sqlite_master", "SELECT 1; SELECT 2", "VACUUM", "SELECT randomblob(999999999)"]:
            with self.subTest(sql=sql):
                self.assertIn("error", engine.query(sql))
        self.assertEqual(engine.query("SELECT SUM(sales_amount) AS total FROM sales")["rows"][0]["total"], 1350)

    def test_query_deadline_is_enforced(self):
        result = self.engine(timeout_seconds=0).query("SELECT COUNT(*) FROM sales a, sales b, sales c, sales d, sales e, sales f")
        self.assertEqual(result.get("code"), "sql_timeout")

    def test_sql_errors_and_non_finite_values_are_structured(self):
        for sql in ["SELECT unknown FROM sales", "SELECT 1e999 AS huge", "SELECT product,product FROM sales"]:
            with self.subTest(sql=sql):
                self.assertIn("error", self.engine().query(sql))

    def test_blob_results_are_rejected_before_json_serialization(self):
        engine=self.engine()
        for sql in ["SELECT CAST(product AS BLOB) AS bytes FROM sales", "SELECT x'4142' AS bytes"]:
            with self.subTest(sql=sql):
                self.assertIn("error",engine.query(sql))

    def test_blob_error_roundtrip_through_agent(self):
        models,agent_module,config=module("models"),module("agent"),module("config")
        class Gateway:
            mode="test"
            replies=[models.ModelReply(tool_calls=[models.ToolCall("blob","run_readonly_sql",'{"sql":"SELECT x\'4142\' AS bytes"}')]),
                     models.ModelReply(content="该查询返回不支持的二进制结果，请改用文本。")]
            def complete(self,*args,**kwargs):
                return self.replies.pop(0)
        tools=module("tools").ToolRegistry(module("data").load_sales(CSV),temp_dir())
        result=agent_module.AgentSession(tools,Gateway(),config.Settings()).ask("执行BLOB查询")
        self.assertIn("error",result.traces[0]["result"])
        self.assertIn("不支持",result.answer)

    def test_generated_datasets_match_independent_decimal_totals(self):
        from decimal import Decimal
        import pandas as pd
        for size in [1, 30, 1000, 5000]:
            with self.subTest(size=size):
                rows = [{"date":f"2026-01-{i % 28 + 1:02}","product":f"P{i % 7}",
                         "quantity":i % 5 + 1,"unit_price":(i % 13 + 1)/10} for i in range(size)]
                expected = sum(Decimal(str(row["unit_price"])) * row["quantity"] for row in rows)
                frame = module("data").load_sales(pd.DataFrame(rows))
                engine = module("sql").ReadOnlySql(frame)
                result = engine.query("SELECT ROUND(SUM(quantity * unit_price), 2) AS total FROM sales")
                self.assertEqual(Decimal(str(result["rows"][0]["total"])),expected)
                engine.close()


class SemanticTests(unittest.TestCase):
    def registry(self):
        return module("tools").ToolRegistry(module("data").load_sales(CSV), temp_dir())

    def test_definitions_and_weighted_average(self):
        tools = self.registry()
        metrics = tools.execute("get_business_metrics", "{}")
        self.assertIn("weighted_unit_price", [m["name"] for m in metrics["metrics"]])
        result = tools.execute("query_metric", '{"metric":"weighted_unit_price"}')
        self.assertEqual(result["rows"], [{"value": 150}])

    def test_metric_grouping_and_date_range(self):
        tools = self.registry()
        result = tools.execute("query_metric", '{"metric":"sales_amount","group_by":"product","start_date":"2026-11-02","end_date":"2026-11-02"}')
        self.assertEqual(result["rows"], [{"product":"Keyboard","value":100},{"product":"Monitor","value":800},{"product":"Mouse","value":100}])

    def test_unknown_metric_and_dimension_are_rejected(self):
        tools = self.registry()
        self.assertIn("error", tools.execute("query_metric", '{"metric":"not_a_metric"}'))
        self.assertIn("error", tools.execute("query_metric", '{"metric":"sales_amount","group_by":"product;DROP TABLE sales"}'))

    def test_schema_sql_tool_and_metric_contract(self):
        tools = self.registry()
        self.assertEqual(tools.execute("get_data_schema", "{}")["table"], "sales")
        result = tools.execute("run_readonly_sql", '{"sql":"SELECT COUNT(*) AS count FROM sales"}')
        self.assertEqual(result["rows"], [{"count":5}])
        self.assertIn("error", tools.execute("run_readonly_sql", '{"sql":"SELECT * FROM sales","limit":201}'))


class PersistenceTests(unittest.TestCase):
    def clients(self):
        from fastapi.testclient import TestClient
        config, web = module("config"), module("web")
        settings = config.Settings(api_key="", state_path=temp_dir()/"state.sqlite3", output_dir=temp_dir())
        return settings, TestClient(web.create_app(settings))

    def test_dataset_history_and_evidence_survive_restart(self):
        from fastapi.testclient import TestClient
        settings, first = self.clients()
        identifier = first.post("/api/sessions", json={"mode":"demo"}).json()["id"]
        url = f"/api/sessions/{identifier}"
        first.post(url+"/dataset", content=b"date,product,quantity,unit_price\n2026-11-01,Custom,2,7\n", headers={"x-filename":"custom.csv"})
        first.post(url+"/chat", json={"question":"所有商品的总销售额是多少？"})
        restored = TestClient(module("web").create_app(settings))
        result = restored.get(url).json()
        self.assertEqual(result["filename"], "custom.csv")
        self.assertEqual(result["summary"]["total_sales_amount"], 14)
        self.assertEqual(result["turns"][0]["traces"][0]["result"], {"total_sales_amount":14})
        self.assertIn(identifier, [item["id"] for item in restored.get("/api/sessions").json()["sessions"]])

    def test_reset_and_failed_upload_remain_correct_after_restart(self):
        from fastapi.testclient import TestClient
        settings, first = self.clients()
        identifier = first.post("/api/sessions", json={"mode":"demo"}).json()["id"]
        url = f"/api/sessions/{identifier}"
        first.post(url+"/chat", json={"question":"Keyboard 的销售额是多少？"})
        self.assertEqual(first.post(url+"/dataset", content=b"wrong").status_code,400)
        first.post(url+"/reset")
        restored = TestClient(module("web").create_app(settings))
        self.assertEqual(restored.get(url).json()["turns"], [])
        self.assertEqual(restored.get(url).json()["summary"]["total_sales_amount"],1350)

    def test_new_session_clones_current_data_and_keeps_original_history(self):
        settings, client = self.clients()
        identifier = client.post("/api/sessions",json={"mode":"demo"}).json()["id"]
        url=f"/api/sessions/{identifier}"
        client.post(url+"/dataset",content=b"date,product,quantity,unit_price\n2026-11-01,Custom,2,7\n")
        client.post(url+"/chat",json={"question":"所有商品的总销售额是多少？"})
        clone=client.post("/api/sessions",json={"mode":"demo","source_session_id":identifier}).json()
        self.assertNotEqual(clone["id"],identifier)
        self.assertEqual(clone["summary"]["total_sales_amount"],14)
        self.assertEqual(clone["turns"],[])
        self.assertEqual(len(client.get(url).json()["turns"]),1)

    def test_inflight_session_is_not_evicted_or_split_into_two_writers(self):
        from concurrent.futures import ThreadPoolExecutor
        import threading
        from fastapi.testclient import TestClient
        settings,client=self.clients()
        app=client.app
        identifier=client.post("/api/sessions",json={"mode":"demo"}).json()["id"]
        record=app.state.records[identifier]
        ready,resume=threading.Event(),threading.Event()
        class GateLock:
            def __init__(self):
                self.real=threading.Lock()
                self.first=True
            def acquire(self,blocking=True):
                if self.first:
                    self.first=False
                    ready.set()
                    if not resume.wait(10):
                        raise TimeoutError("test gate timeout")
                return self.real.acquire(blocking=blocking)
            def release(self): self.real.release()
            def locked(self): return self.real.locked()
            def __enter__(self): self.acquire();return self
            def __exit__(self,*args): self.release()
        record.lock=GateLock()
        url=f"/api/sessions/{identifier}"
        with ThreadPoolExecutor(max_workers=1) as pool:
            first=pool.submit(client.post,url+"/chat",json={"question":"所有商品的总销售额是多少？"})
            try:
                self.assertTrue(ready.wait(5))
                for _ in range(33):
                    self.assertEqual(client.post("/api/sessions",json={"mode":"demo"}).status_code,200)
                second=client.post(url+"/chat",json={"question":"Mouse 的销售额是多少？"})
                self.assertEqual(second.status_code,200)
            finally:
                resume.set()
            self.assertEqual(first.result(timeout=10).status_code,200)
        restored=TestClient(module("web").create_app(settings))
        questions={turn["question"] for turn in restored.get(url).json()["turns"]}
        self.assertEqual(questions,{"所有商品的总销售额是多少？","Mouse 的销售额是多少？"})


if __name__ == "__main__":
    unittest.main()
