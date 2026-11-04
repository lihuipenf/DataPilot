"""模型边界：原生协议适配为统一的工具调用、Token 和错误结构。"""
from dataclasses import dataclass, field
from functools import wraps
import json
import time
import httpx


class ModelError(RuntimeError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


class MissingKeyGateway:
    """允许查看恢复的实时会话，但不伪装成已配置模型。"""
    mode = "live"

    def __init__(self, provider="deepseek"):
        self.provider = provider

    def complete(self, messages, tools, allow_tools=True):
        raise ModelError("missing_key", f"当前未配置 {self.provider} API 密钥，可先切换离线演示模式。")


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str


@dataclass
class ModelReply:
    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: dict = field(default_factory=dict)
    provider_data: dict = field(default_factory=dict)

    def as_message(self):
        message = {"role": "assistant", "content": self.content}
        if self.provider_data:
            # 只存在服务端历史中；保留 Responses 推理项/phase 及 Claude 原生内容块。
            message["provider_data"] = self.provider_data
        if self.tool_calls:
            message["tool_calls"] = [{"id": call.id, "type": "function", "function": {
                "name": call.name, "arguments": call.arguments}} for call in self.tool_calls]
        return message


def validated_reply(method):
    """第三方返回 HTTP 200 也可能格式错误；统一为可恢复且不回显原始响应的错误。"""
    @wraps(method)
    def complete(*args, **kwargs):
        try:
            reply = method(*args, **kwargs)
            if reply.content is not None and not isinstance(reply.content, str):
                raise ValueError("invalid content")
            if any(not isinstance(value, int) or value < 0 for value in reply.usage.values()):
                raise ValueError("invalid usage")
            if any(not isinstance(value, str) for call in reply.tool_calls for value in (call.id,call.name,call.arguments)):
                raise ValueError("invalid tool call")
            return reply
        except (ValueError, TypeError, KeyError, AttributeError) as error:
            raise ModelError("invalid_response", "模型服务返回了无效响应，请检查服务端点或稍后重试。") from error
    return complete


class OpenAICompatibleGateway:
    mode = "live"

    def __init__(self, settings):
        if not settings.api_key:
            raise ModelError("missing_key", f"请在本地 .env 中配置 {settings.provider} API 密钥。")
        from openai import OpenAI
        self.settings = settings
        # SDK 不额外重试；下面统一限制为最多重试一次。
        self.client = OpenAI(api_key=settings.api_key, base_url=settings.base_url,
                             timeout=settings.timeout, max_retries=0)

    @validated_reply
    def complete(self, messages, tools, allow_tools=True):
        from openai import (APITimeoutError, APIConnectionError, AuthenticationError,
                            RateLimitError, APIStatusError)
        for attempt in range(2):
            try:
                params = dict(model=self.settings.model,
                              messages=[{k:v for k,v in m.items() if k != "provider_data"} for m in messages],
                              max_tokens=900)
                if self.settings.provider == "deepseek":
                    params["extra_body"] = {"thinking": {"type": "disabled"}}
                if tools:
                    params.update(tools=tools, tool_choice="auto" if allow_tools else "none")
                response = self.client.chat.completions.create(**params)
                if not response.choices:
                    raise ModelError("empty_response", "模型没有返回有效内容，请重试。")
                if response.choices[0].finish_reason == "length":
                    raise ModelError("truncated_response", "模型回复达到长度上限，请缩小问题范围后重试。")
                message = response.choices[0].message
                usage = response.usage
                return ModelReply(content=message.content,
                    tool_calls=[ToolCall(c.id, c.function.name, c.function.arguments) for c in message.tool_calls or []],
                    usage={"prompt_tokens": getattr(usage, "prompt_tokens", 0) or 0,
                           "completion_tokens": getattr(usage, "completion_tokens", 0) or 0})
            except AuthenticationError as error:
                raise ModelError("authentication", "模型服务密钥无效，请检查本地 .env 配置。") from error
            except (APITimeoutError, APIConnectionError, RateLimitError) as error:
                if attempt == 0:
                    time.sleep(0.3)
                    continue
                code = "timeout" if isinstance(error, APITimeoutError) else "rate_limit" if isinstance(error, RateLimitError) else "connection"
                raise ModelError(code, {"timeout": "模型请求超时，请稍后重试。", "rate_limit": "模型服务请求过于频繁，请稍后重试。",
                                       "connection": "无法连接模型服务，请检查网络后重试。"}[code]) from error
            except APIStatusError as error:
                if error.status_code >= 500 and attempt == 0:
                    time.sleep(0.3)
                    continue
                text = "模型账户余额不足，请检查服务商控制台。" if error.status_code == 402 else "模型服务拒绝了请求，请检查模型配置或稍后重试。"
                raise ModelError("api_error", text) from error


class DeepSeekGateway(OpenAICompatibleGateway):
    """旧脚本兼容入口；应用入口使用 create_gateway。"""


class ResponsesGateway(OpenAICompatibleGateway):
    @validated_reply
    def complete(self, messages, tools, allow_tools=True):
        items, instructions = [], []
        for message in messages:
            role = message["role"]
            if role == "system":
                instructions.append(message["content"])
            elif role == "tool":
                items.append({"type":"function_call_output", "call_id":message["tool_call_id"], "output":message["content"]})
            elif role == "assistant" and message.get("provider_data", {}).get("protocol") == "responses":
                items.extend(message["provider_data"]["items"])
            else:
                items.append({"role":role,"content":message.get("content") or ""})
        params = dict(model=self.settings.model, input=items, instructions="\n".join(instructions),
                      max_output_tokens=4096, store=False, include=["reasoning.encrypted_content"])
        if tools:
            params.update(tools=[{"type":"function", **t["function"], "strict":False} for t in tools],
                          tool_choice="auto" if allow_tools else "none")
        # 共用同一有界重试/脱敏错误策略，避免 SDK 隐式额外重试。
        response = self._request(lambda: self.client.responses.create(**params))
        if response.status != "completed":
            raise ModelError("truncated_response", "模型未完成回答，请缩小问题或检查模型输出额度。")
        output = [item.model_dump(exclude_none=True) for item in response.output]
        calls = [ToolCall(item["call_id"], item["name"], item["arguments"]) for item in output if item["type"] == "function_call"]
        return ModelReply(response.output_text, calls,
                          {"prompt_tokens":getattr(response.usage,"input_tokens",0) or 0,
                           "completion_tokens":getattr(response.usage,"output_tokens",0) or 0},
                          {"protocol":"responses","items":output})

    def _request(self, request):
        from openai import APIConnectionError, APIStatusError, APITimeoutError
        for attempt in range(2):
            try:
                return request()
            except (APIConnectionError, APIStatusError) as error:
                status = getattr(error, "status_code", None)
                code = "timeout" if isinstance(error, APITimeoutError) else "connection" if status is None else "authentication" if status in (401,403) else "rate_limit" if status == 429 else "api_error"
                if attempt == 0 and (status is None or status == 429 or status >= 500):
                    time.sleep(0.3)
                    continue
                raise ModelError(code, "模型请求失败，请检查密钥、模型权限、额度或网络后重试。") from error


class ClaudeGateway:
    mode = "live"

    def __init__(self, settings):
        self.settings = settings

    @validated_reply
    def complete(self, messages, tools, allow_tools=True):
        outgoing, system = [], []
        for message in messages:
            role = message["role"]
            if role == "system":
                system.append(message["content"])
                continue
            if role == "tool":
                role = "user"
                result = message["content"]
                content = [{"type":"tool_result","tool_use_id":message["tool_call_id"],"content":result,
                            "is_error":"error" in json.loads(result)}]
            elif role == "assistant" and message.get("provider_data",{}).get("protocol") == "anthropic":
                content = message["provider_data"]["content"]
            else:
                content = [{"type":"text","text":message.get("content") or ""}]
            # 并行工具结果必须合并到一个紧随 assistant 的 user 消息。
            if outgoing and outgoing[-1]["role"] == role:
                outgoing[-1]["content"].extend(content)
            else:
                outgoing.append({"role":role,"content":list(content)})
        params = dict(model=self.settings.model, system="\n".join(system), messages=outgoing, max_tokens=4096)
        if tools:
            params["tools"] = [{"name":t["function"]["name"],"description":t["function"].get("description",""),
                                "input_schema":t["function"]["parameters"]} for t in tools]
            params["tool_choice"] = {"type":"auto" if allow_tools else "none"}
        for attempt in range(2):
            try:
                response = httpx.post(self.settings.base_url.rstrip("/") + "/messages", json=params,
                                      headers={"x-api-key":self.settings.api_key,"anthropic-version":"2023-06-01"},
                                      timeout=self.settings.timeout)
                response.raise_for_status()
                body = response.json()
                if body.get("stop_reason") not in ("end_turn", "tool_use", "stop_sequence"):
                    raise ModelError("truncated_response", "Claude 未完成回答，请缩小问题或检查输出额度。")
                content = body["content"]
                return ModelReply("".join(b["text"] for b in content if b["type"] == "text"),
                                  [ToolCall(b["id"],b["name"],json.dumps(b["input"],ensure_ascii=False)) for b in content if b["type"] == "tool_use"],
                                  {"prompt_tokens":body.get("usage",{}).get("input_tokens",0),
                                   "completion_tokens":body.get("usage",{}).get("output_tokens",0)},
                                  {"protocol":"anthropic","content":content})
            except (httpx.TimeoutException, httpx.RequestError, httpx.HTTPStatusError) as error:
                status = error.response.status_code if isinstance(error,httpx.HTTPStatusError) else None
                if attempt == 0 and (status is None or status == 429 or status >= 500):
                    time.sleep(0.3)
                    continue
                code = "timeout" if isinstance(error,httpx.TimeoutException) else "connection" if status is None else "authentication" if status in (401,403) else "rate_limit" if status == 429 else "api_error"
                raise ModelError(code, "Claude 请求失败，请检查密钥、模型权限、额度或网络后重试。") from error
            except (ValueError, KeyError, TypeError) as error:
                raise ModelError("invalid_response", "Claude 返回了无效的响应结构，请检查服务端点。") from error


def create_gateway(settings, restored=False):
    settings = settings.select()
    if not settings.api_key:
        if restored:
            return MissingKeyGateway(settings.provider)
        raise ModelError("missing_key", f"请在本地 .env 中配置 {settings.provider} API 密钥。")
    if not settings.model:
        raise ModelError("invalid_config", "请先设置服务商提供的模型 ID。")
    if settings.provider == "openai":
        return ResponsesGateway(settings)
    if settings.provider == "anthropic":
        return ClaudeGateway(settings)
    return OpenAICompatibleGateway(settings)
