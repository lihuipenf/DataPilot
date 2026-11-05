"""业务与 Agent 回归测试：外部模型由脚本化响应代替，数据计算使用真实代码。"""
import copy
import importlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

CSV = b"date,product,quantity,unit_price\n2026-11-01,Keyboard,2,100\n2026-11-01,Mouse,3,50\n2026-11-02,Keyboard,1,100\n2026-11-02,Monitor,1,800\n2026-11-02,Mouse,2,50\n"


def module(name):
    try:
        return importlib.import_module("datapilot." + name)
    except ModuleNotFoundError as error:
        raise AssertionError(f"待实现的模块：datapilot.{name}") from error


def registry():
    data, tools = module("data"), module("tools")
    folder = Path(tempfile.mkdtemp(prefix="datapilot-test-"))
    return tools.ToolRegistry(data.load_sales(CSV), folder)


class DataTests(unittest.TestCase):
    def test_loads_csv_and_computes_amount(self):
        frame = module("data").load_sales(CSV)
        self.assertEqual(frame["sales_amount"].tolist(), [200, 150, 100, 800, 100])

    def test_rejects_invalid_inputs_with_readable_errors(self):
        data = module("data")
        bad = [b"", b"date,product,quantity,unit_price\n", b"product,quantity\nA,1\n",
               b"date,product,quantity,unit_price\n2026-11-01,,1,2\n",
               b"date,product,quantity,unit_price\nwrong,A,1,2\n",
               b"date,product,quantity,unit_price\n2026-11-01,A,-1,2\n",
               b"date,product,quantity,unit_price\n2026-11-01,A,1.5,2\n",
               b"date,product,quantity,unit_price\n2026-11-01,A,1,NaN\n",
               b"date,product,quantity,unit_price\n2026-11-01,A,1,inf\n",
               b"date,product,quantity,unit_price\n2026-11-01,A,1,abc\n",
               b"date,product,quantity,unit_price\n2026-11-01,A,1,-2\n",
               b"date,product,quantity,quantity,unit_price\n2026-11-01,A,1,1,2\n"]
        for content in bad:
            with self.subTest(content=content), self.assertRaises(data.DataError):
                data.load_sales(content)

    def test_accepts_chinese_gb18030_and_removes_bom(self):
        data = module("data")
        text = "date,product,quantity,unit_price\n2026-11-01,键盘,1,100\n"
        self.assertEqual(data.load_sales(text.encode("gb18030"))["product"].iloc[0], "键盘")
        self.assertEqual(len(data.load_sales(b"\xef\xbb\xbf" + CSV)), 5)

    def test_ignores_forged_amount_column(self):
        content = b"date,product,quantity,unit_price,sales_amount\n2026-11-01,A,2,3,999\n"
        self.assertEqual(module("data").load_sales(content)["sales_amount"].iloc[0], 6)

    def test_rejects_extra_fields_in_data_rows(self):
        data = module("data")
        content = b"date,product,quantity,unit_price\nignored,2026-11-01,A,1,2\n"
        with self.assertRaises(data.DataError):
            data.load_sales(content)

    def test_accepts_zero_and_decimal_values(self):
        content = b"date,product,quantity,unit_price\n2026-11-01,A,1,0.1\n2026-11-01,A,1,0.2\n2026-11-01,B,0,100\n"
        tools = module("tools").ToolRegistry(module("data").load_sales(content), Path(tempfile.mkdtemp()))
        self.assertEqual(tools.execute("get_total_sales", "{}"), {"total_sales_amount": 0.3})


class ToolTests(unittest.TestCase):
    def test_total(self):
        self.assertEqual(registry().execute("get_total_sales", "{}"), {"total_sales_amount": 1350})

    def test_top(self):
        self.assertEqual(registry().execute("get_top_product", "{}"), {"product": "Monitor", "sales_amount": 800})

    def test_product_case_and_missing(self):
        tools = registry()
        self.assertEqual(tools.execute("get_sales_for_product", '{"product_name":" keyboard "}'), {"product": "Keyboard", "sales_amount": 300})
        self.assertIn("error", tools.execute("get_sales_for_product", '{"product_name":"Phone"}'))

    def test_daily_range(self):
        result = registry().execute("get_sales_by_date", '{"start_date":"2026-11-02","end_date":"2026-11-02"}')
        self.assertEqual(result["total_sales_amount"], 1000)
        self.assertEqual(result["daily_sales"], [{"date": "2026-11-02", "sales_amount": 1000}])

    def test_daily_all_and_empty_range(self):
        tools = registry()
        self.assertEqual([d["sales_amount"] for d in tools.execute("get_sales_by_date", "{}")["daily_sales"]], [350, 1000])
        self.assertEqual(tools.execute("get_sales_by_date", '{"start_date":"2027-01-01"}')["total_sales_amount"], 0)

    def test_ranking_by_sales_and_quantity(self):
        tools = registry()
        result = tools.execute("get_product_ranking", '{"limit":2,"metric":"sales_amount"}')
        self.assertEqual([r["product"] for r in result["ranking"]], ["Monitor", "Keyboard"])
        result = tools.execute("get_product_ranking", '{"metric":"quantity"}')
        self.assertEqual(result["ranking"][0], {"product": "Mouse", "quantity": 5})

    def test_summary(self):
        result = registry().execute("get_dataset_summary", "{}")
        self.assertEqual((result["row_count"], result["product_count"], result["total_quantity"]), (5, 3, 9))

    def test_all_parameter_failures_are_structured(self):
        tools = registry()
        cases = [("unknown", "{}"), ("get_total_sales", "not-json"),
                 ("get_total_sales", "[]"), ("get_total_sales", '{"extra":1}'),
                 ("get_sales_for_product", "{}"), ("get_sales_for_product", '{"product_name":1}'),
                 ("get_product_ranking", '{"limit":0}'), ("get_product_ranking", '{"limit":true}'),
                 ("get_product_ranking", '{"limit":51}'), ("get_product_ranking", '{"metric":"oops"}'),
                 ("get_sales_by_date", '{"start_date":"bad"}'),
                 ("get_sales_by_date", '{"start_date":"2027-01-01","end_date":"2026-01-01"}'),
                 ("create_sales_chart", '{"kind":"pie"}')]
        for name, args in cases:
            with self.subTest(name=name, args=args):
                self.assertIn("error", tools.execute(name, args))

    def test_chart_artifact_is_real_png(self):
        tools = registry()
        for kind in ["product", "daily"]:
            result = tools.execute("create_sales_chart", json.dumps({"kind": kind}))
            self.assertTrue((tools.output_dir / result["artifact"]["id"]).read_bytes().startswith(b"\x89PNG"))

    def test_large_tie_result_is_explicitly_bounded(self):
        import pandas as pd
        frame = pd.DataFrame({"date": ["2026-01-01"] * 5000,
                              "product": [f"P{i:04d}_" + "x" * 72 for i in range(5000)],
                              "quantity": [1] * 5000, "unit_price": [1] * 5000})
        tools = module("tools").ToolRegistry(module("data").load_sales(frame), Path(tempfile.mkdtemp()))
        result = tools.execute("get_top_product", "{}")
        self.assertIn("tied_count", result)
        self.assertEqual(result["tied_count"], 5000)
        self.assertLessEqual(len(result["tied_products"]), 20)
        self.assertTrue(result["tied_products_truncated"])


class AgentTests(unittest.TestCase):
    def make_agent(self, replies, **settings):
        agent_module, models, config = module("agent"), module("models"), module("config")
        class Scripted:
            mode = "test"
            def __init__(self):
                self.requests = []
            def complete(self, messages, tools, allow_tools=True):
                self.requests.append(copy.deepcopy(messages))
                item = replies.pop(0)
                if isinstance(item, Exception):
                    raise item
                return item
        gateway = Scripted()
        return agent_module.AgentSession(registry(), gateway, config.Settings(**settings)), gateway, models

    def test_multistep_tool_loop_and_chinese_answer(self):
        models = module("models")
        replies = [models.ModelReply(tool_calls=[models.ToolCall("a", "get_total_sales", "{}")]),
                   models.ModelReply(tool_calls=[models.ToolCall("b", "get_top_product", "{}")]),
                   models.ModelReply(content="总销售额为1350，最高为Monitor，800。")]
        agent, gateway, _ = self.make_agent(replies)
        result = agent.ask("总销售额和最高商品？")
        self.assertEqual(len(result.traces), 2)
        self.assertEqual(result.request_count, 3)
        self.assertEqual(result.traces[0]["result"], {"total_sales_amount": 1350})
        self.assertEqual([m["role"] for m in gateway.requests[-1]], ["system", "user", "assistant", "tool", "assistant", "tool"])

    def test_followup_receives_previous_complete_turn(self):
        models = module("models")
        agent, gateway, _ = self.make_agent([models.ModelReply(content="Keyboard为300。"), models.ModelReply(content="Mouse为250。")])
        agent.ask("Keyboard是多少？")
        agent.ask("那Mouse呢？")
        self.assertEqual([m["role"] for m in gateway.requests[-1]], ["system", "user", "assistant", "user"])

    def test_failed_request_does_not_corrupt_history(self):
        models = module("models")
        agent, _, _ = self.make_agent([models.ModelError("timeout", "请求超时")])
        with self.assertRaises(models.ModelError):
            agent.ask("总额？")
        self.assertEqual(agent.turns, [])

    def test_tool_loop_is_bounded(self):
        models = module("models")
        calls = [models.ModelReply(tool_calls=[models.ToolCall(str(i), "get_total_sales", "{}")]) for i in range(3)]
        agent, gateway, _ = self.make_agent(calls, max_tool_rounds=1)
        with self.assertRaises(models.ModelError):
            agent.ask("总额？")
        self.assertLessEqual(len(gateway.requests), 2)

    def test_trim_keeps_whole_turns(self):
        models = module("models")
        agent, gateway, _ = self.make_agent([models.ModelReply(content="好") for _ in range(4)], max_history_turns=1)
        for question in ["一", "二", "三"]:
            agent.ask(question)
        contents = [m["content"] for m in gateway.requests[-1] if m["role"] == "user"]
        self.assertEqual(contents, ["二", "三"])

    def test_malformed_tool_arguments_reach_model_as_error(self):
        models = module("models")
        agent, gateway, _ = self.make_agent([models.ModelReply(tool_calls=[models.ToolCall("a", "get_sales_for_product", "bad")]), models.ModelReply(content="参数有误。")])
        result = agent.ask("查商品")
        self.assertIn("error", result.traces[0]["result"])
        self.assertEqual(gateway.requests[-1][-1]["role"], "tool")

    def test_blank_question_is_rejected_without_model_call(self):
        agent, gateway, _ = self.make_agent([])
        with self.assertRaises(ValueError):
            agent.ask("  ")
        self.assertEqual(gateway.requests, [])

    def test_current_tool_result_cannot_exceed_context_budget(self):
        import pandas as pd
        models = module("models")
        agent, gateway, _ = self.make_agent([
            models.ModelReply(tool_calls=[models.ToolCall("a", "get_sales_by_date", "{}")]),
            models.ModelReply(content="不应发出这次请求")], max_context_chars=1000)
        frame = pd.DataFrame({"date": pd.date_range("2025-01-01", periods=365).strftime("%Y-%m-%d"),
                              "product": ["A"] * 365, "quantity": [1] * 365, "unit_price": [1] * 365})
        agent.registry = module("tools").ToolRegistry(module("data").load_sales(frame), Path(tempfile.mkdtemp()))
        with self.assertRaises(models.ModelError):
            agent.ask("每天销售额？")
        self.assertLessEqual(len(gateway.requests), 1)
        self.assertEqual(agent.turns, [])


class WebTests(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        self.client = TestClient(module("web").create_app(module("config").Settings(api_key="")), base_url="http://localhost")
        self.session = self.client.post("/api/sessions", json={"mode": "demo"}).json()["id"]

    def test_demo_chat_and_exports(self):
        result = self.client.post(f"/api/sessions/{self.session}/chat", json={"question": "所有商品的总销售额是多少？"})
        self.assertEqual(result.status_code, 200)
        self.assertIn("1350", result.json()["answer"])
        self.assertIn("1350", self.client.get(f"/api/sessions/{self.session}/export.md").text)
        self.assertIn("Monitor", self.client.get(f"/api/sessions/{self.session}/export.csv").text)

    def test_invalid_upload_is_atomic_and_valid_upload_resets_history(self):
        url = f"/api/sessions/{self.session}/dataset"
        self.assertEqual(self.client.post(url, content=b"wrong").status_code, 400)
        self.assertEqual(self.client.get(f"/api/sessions/{self.session}").json()["summary"]["total_sales_amount"], 1350)
        content = b"date,product,quantity,unit_price\n2026-11-01,New,1,10\n"
        self.assertEqual(self.client.post(url, content=content).status_code, 200)
        self.assertEqual(self.client.get(f"/api/sessions/{self.session}").json()["summary"]["total_sales_amount"], 10)

    def test_live_without_key_and_invalid_question(self):
        self.assertEqual(self.client.post("/api/sessions", json={"mode": "live"}).status_code, 400)
        self.assertEqual(self.client.post(f"/api/sessions/{self.session}/chat", json={"question": " "}).status_code, 400)

    def test_chart_download_and_artifact_path_validation(self):
        result = self.client.post(f"/api/sessions/{self.session}/chat", json={"question": "画商品销售额柱状图"}).json()
        artifact = result["artifacts"][0]
        response = self.client.get(artifact["url"])
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content.startswith(b"\x89PNG"))
        self.assertEqual(self.client.get(f"/api/sessions/{self.session}/artifacts/unknown.png").status_code, 404)

    def test_switching_mode_preserves_uploaded_dataset(self):
        url = f"/api/sessions/{self.session}"
        content = b"date,product,quantity,unit_price\n2026-11-01,Custom,2,7\n"
        self.client.post(url + "/dataset", content=content)
        result = self.client.post(url + "/mode", json={"mode": "demo"})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["summary"]["total_sales_amount"], 14)

    def test_exports_preserve_large_amount_precision(self):
        url = f"/api/sessions/{self.session}"
        content = b"date,product,quantity,unit_price\n2026-11-01,Large,1,1234567.89\n"
        self.client.post(url + "/dataset", content=content)
        self.assertIn("1234567.89", self.client.get(url + "/export.csv").text)
        self.assertIn("1234567.89", self.client.get(url + "/export.md").text)


class GatewayTests(unittest.TestCase):
    def check_failure(self, error, expected_code, expected_attempts):
        models, config = module("models"), module("config")
        create = Mock(side_effect=error)
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        with patch("openai.OpenAI", return_value=client), patch("datapilot.models.time.sleep"):
            gateway = models.DeepSeekGateway(config.Settings(api_key="offline-test-key"))
            with self.assertRaises(models.ModelError) as caught:
                gateway.complete([{"role": "user", "content": "查询总额"}], [])
        self.assertEqual(caught.exception.code, expected_code)
        self.assertEqual(create.call_count, expected_attempts)
        self.assertNotIn("offline-test-key", str(caught.exception))

    def test_timeout_retries_once(self):
        import httpx
        from openai import APITimeoutError
        self.check_failure(APITimeoutError(request=httpx.Request("POST", "https://example.test")), "timeout", 2)

    def test_authentication_is_not_retried(self):
        import httpx
        from openai import AuthenticationError
        response = httpx.Response(401, request=httpx.Request("POST", "https://example.test"))
        self.check_failure(AuthenticationError("invalid", response=response, body=None), "authentication", 1)

    def test_rate_limit_retries_once(self):
        import httpx
        from openai import RateLimitError
        response = httpx.Response(429, request=httpx.Request("POST", "https://example.test"))
        self.check_failure(RateLimitError("busy", response=response, body=None), "rate_limit", 2)


if __name__ == "__main__":
    unittest.main()
