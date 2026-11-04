"""模型协议边界测试：只替换外部 HTTP，真实运行 SDK、Agent 与本地工具。"""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import httpx
from openai import OpenAI
from datapilot.config import Settings
from datapilot import models
from datapilot.agent import AgentSession
from .test_core import registry


class ConfigurationTests(unittest.TestCase):
    def test_switching_model_does_not_reuse_the_previous_models_price(self):
        settings=Settings(api_key="key",input_price=1,output_price=2)
        self.assertIsNone(settings.select(model="another-model").input_price)

    def test_provider_credentials_are_isolated_and_legacy_env_still_works(self):
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY":"legacy-secret", "OPENAI_API_KEY":"other-secret",
                                    "DATAPILOT_PROVIDER":"openai", "OPENAI_MODEL":"gpt-5.3-codex"}, clear=True), patch("datapilot.config.load_dotenv"):
            settings = Settings.from_env()
        self.assertEqual(settings.provider, "openai")
        self.assertEqual(settings.api_key, "other-secret")
        self.assertEqual(settings.select("deepseek").api_key, "legacy-secret")
        self.assertNotIn("secret", repr(settings))
        self.assertNotIn("secret", json.dumps(settings.public_providers()))
        self.assertIsNone(settings.select("deepseek").input_price)

    def test_invalid_provider_or_endpoint_is_rejected_without_request(self):
        for env in [{"DATAPILOT_PROVIDER":"unknown"},
                    {"DEEPSEEK_BASE_URL":"https://name:secret@example.com"},
                    {"DEEPSEEK_BASE_URL":"file:///tmp/model"}]:
            with self.subTest(env=env), patch.dict(os.environ,env,clear=True), patch("datapilot.config.load_dotenv"):
                with self.assertRaises(ValueError):
                    Settings.from_env()


class ProtocolTests(unittest.TestCase):
    def test_malformed_success_response_is_a_model_error_for_every_protocol(self):
        for provider,body in [("openai",{"status":"completed","output":None}),
                              ("anthropic",[]), ("compatible",{"choices":[{"message":None}]})]:
            with self.subTest(provider=provider):
                with self.assertRaises(models.ModelError) as caught:
                    self.run_agent(provider,[body])
                self.assertEqual(caught.exception.code,"invalid_response")

    def test_claude_parallel_results_stay_together_and_final_step_disables_tools(self):
        self.payloads=[]
        def handler(request):
            self.payloads.append(json.loads(request.content))
            if len(self.payloads)==1:
                return httpx.Response(200,json={"stop_reason":"tool_use","content":[
                    {"type":"tool_use","id":"a","name":"get_total_sales","input":{}},
                    {"type":"tool_use","id":"b","name":"get_top_product","input":{}}],"usage":{}})
            return httpx.Response(200,json={"stop_reason":"end_turn","content":[{"type":"text","text":"总额1350，Monitor为800。"}],"usage":{}})
        with httpx.Client(transport=httpx.MockTransport(handler)) as client, patch("httpx.post",side_effect=client.post):
            settings=Settings(provider="anthropic",api_key="key",model="test",base_url="https://example.test/v1",max_tool_rounds=1)
            result=AgentSession(registry(),models.create_gateway(settings),settings).ask("总额和冠军？")
        self.assertEqual(len(result.traces),2)
        self.assertEqual([b["tool_use_id"] for b in self.payloads[1]["messages"][-1]["content"]],["a","b"])
        self.assertEqual(self.payloads[1]["tool_choice"],{"type":"none"})
        self.assertTrue(self.payloads[1]["tools"])

    def test_claude_authentication_and_transient_failures_are_bounded_and_redacted(self):
        for status,code,attempts in [(401,"authentication",1),(429,"rate_limit",2),(503,"api_error",2)]:
            requests=[]
            def handler(request):
                requests.append(request)
                return httpx.Response(status,json={"error":{"message":"private-key-in-upstream-error"}})
            with self.subTest(status=status), httpx.Client(transport=httpx.MockTransport(handler)) as client, patch("httpx.post",side_effect=client.post), patch("datapilot.models.time.sleep"):
                gateway=models.create_gateway(Settings(provider="anthropic",api_key="private-key",model="test"))
                with self.assertRaises(models.ModelError) as caught:
                    gateway.complete([{"role":"user","content":"你好"}],[])
                self.assertEqual(caught.exception.code,code)
                self.assertEqual(len(requests),attempts)
                self.assertNotIn("private-key",str(caught.exception))

    def run_agent(self, provider, responses):
        self.payloads = []
        def handler(request):
            self.payloads.append(json.loads(request.content))
            return httpx.Response(200,json=responses.pop(0))
        client = httpx.Client(transport=httpx.MockTransport(handler))
        self.addCleanup(client.close)
        settings = Settings(api_key="test-secret", provider=provider, model="test-model",
                            base_url="https://example.test/v1")
        def openai_client(**kwargs):
            return OpenAI(**kwargs,http_client=client)
        with patch("openai.OpenAI", side_effect=openai_client), patch("httpx.post",side_effect=client.post):
            agent = AgentSession(registry(),models.create_gateway(settings),settings)
            result = agent.ask("总销售额是多少？")
        return result, agent

    def test_openai_responses_preserves_reasoning_and_returns_tool_output(self):
        result, agent = self.run_agent("openai", [
            {"id":"resp_1","object":"response","status":"completed","output":[
                {"id":"rs_1","type":"reasoning","summary":[],"encrypted_content":"opaque"},
                {"type":"function_call","id":"fc_1","call_id":"call_1","name":"get_total_sales","arguments":"{}"}],
             "usage":{"input_tokens":20,"output_tokens":5,"total_tokens":25}},
            {"id":"resp_2","object":"response","status":"completed","output":[
                {"id":"msg_1","type":"message","role":"assistant","phase":"final_answer","status":"completed",
                 "content":[{"type":"output_text","text":"总销售额为1350。","annotations":[]}]}],
             "usage":{"input_tokens":30,"output_tokens":6,"total_tokens":36}}])
        self.assertEqual(result.traces[0]["result"], {"total_sales_amount":1350})
        self.assertEqual(result.provider,"openai")
        self.assertEqual(result.usage,{"prompt_tokens":50,"completion_tokens":11})
        payload=self.payloads[1]
        self.assertFalse(payload["store"])
        self.assertEqual(payload["input"][-1],{"type":"function_call_output","call_id":"call_1","output":'{"total_sales_amount": 1350}'})
        self.assertIn("opaque",json.dumps(payload))
        self.assertEqual(agent.turns[-1][-1]["provider_data"]["items"][0]["phase"],"final_answer")
        self.assertNotIn("thinking",json.dumps(payload))

    def test_claude_native_tool_use_roundtrip(self):
        result, _ = self.run_agent("anthropic", [
            {"id":"msg_1","type":"message","role":"assistant","model":"test-model","stop_reason":"tool_use",
             "content":[{"type":"tool_use","id":"toolu_1","name":"get_total_sales","input":{}}],
             "usage":{"input_tokens":10,"output_tokens":4}},
            {"id":"msg_2","type":"message","role":"assistant","model":"test-model","stop_reason":"end_turn",
             "content":[{"type":"text","text":"总销售额为1350。"}],"usage":{"input_tokens":20,"output_tokens":5}}])
        self.assertIn("1350",result.answer)
        self.assertEqual(result.usage,{"prompt_tokens":30,"completion_tokens":9})
        payload=self.payloads[1]
        self.assertEqual(payload["messages"][-1]["role"],"user")
        self.assertEqual(payload["messages"][-1]["content"][0]["tool_use_id"],"toolu_1")
        self.assertEqual(payload["tools"][0]["name"],"get_total_sales")
        self.assertIn("input_schema",payload["tools"][0])
        self.assertIn("简体中文",payload["system"])

    def test_compatible_endpoint_does_not_receive_deepseek_parameters(self):
        result,_=self.run_agent("compatible",[{"id":"c1","object":"chat.completion","created":0,"model":"test-model",
           "choices":[{"index":0,"finish_reason":"stop","message":{"role":"assistant","content":"你好"}}]}])
        self.assertEqual(result.answer,"你好")
        self.assertNotIn("thinking", self.payloads[0])

    def test_claude_truncation_is_an_error_and_history_is_not_committed(self):
        with self.assertRaises(models.ModelError) as caught:
            self.run_agent("anthropic",[{"content":[{"type":"text","text":"不完整"}],"stop_reason":"max_tokens","usage":{}}])
        self.assertEqual(caught.exception.code,"truncated_response")


class ProviderWebTests(unittest.TestCase):
    def test_session_model_survives_restart_and_does_not_follow_new_default(self):
        from fastapi.testclient import TestClient
        from datapilot.web import create_app
        path=Path(tempfile.mkdtemp()) / "state.sqlite3"
        with patch.dict(os.environ,{"OPENAI_API_KEY":"test-secret","OPENAI_MODEL":"gpt-5.3-codex"},clear=True), patch("datapilot.config.load_dotenv"):
            from dataclasses import replace
            settings=replace(Settings.from_env(),state_path=path)
        with TestClient(create_app(settings)) as client:
            result=client.post("/api/sessions",json={"mode":"live","provider":"openai","model":"gpt-5.3-codex"})
            self.assertEqual(result.status_code,200,result.text)
            identifier=result.json()["id"]
            self.assertEqual(result.json()["provider"],"openai")
            saved=client.get("/api/sessions").json()["sessions"][0]
            self.assertEqual(saved["provider"],"openai")
            self.assertEqual(saved["model"],"gpt-5.3-codex")
            self.assertNotIn("test-secret",client.get("/api/providers").text)
            self.assertEqual(client.post("/api/sessions",json={"mode":"live","provider":"anthropic"}).status_code,400)
        with TestClient(create_app(Settings(state_path=path))) as client:
            restored=client.get(f"/api/sessions/{identifier}")
            self.assertEqual(restored.json()["provider"],"openai")
            self.assertEqual(restored.json()["model"],"gpt-5.3-codex")
            failed=client.post(f"/api/sessions/{identifier}/chat",json={"question":"总额？"})
            self.assertEqual(failed.json()["code"],"missing_key")
            self.assertIn("openai",failed.json()["detail"].lower())

    def test_invalid_provider_returns_readable_client_error(self):
        from fastapi.testclient import TestClient
        from datapilot.web import create_app
        with TestClient(create_app(Settings())) as client:
            response=client.post("/api/sessions",json={"mode":"live","provider":"unknown"})
            self.assertEqual(response.status_code,400)


if __name__ == "__main__":
    unittest.main()
