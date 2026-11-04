"""模型边界：真实 DeepSeek 请求与离线演示均返回同一种结构。"""
from dataclasses import dataclass, field
import time


class ModelError(RuntimeError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


class MissingKeyGateway:
    """允许查看恢复的实时会话，但不伪装成已配置模型。"""
    mode = "live"

    def complete(self, messages, tools, allow_tools=True):
        raise ModelError("missing_key", "当前未配置DeepSeek密钥，可先切换离线演示模式。")


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

    def as_message(self):
        message = {"role": "assistant", "content": self.content}
        if self.tool_calls:
            message["tool_calls"] = [{"id": call.id, "type": "function", "function": {
                "name": call.name, "arguments": call.arguments}} for call in self.tool_calls]
        return message


class DeepSeekGateway:
    mode = "live"

    def __init__(self, settings):
        if not settings.api_key:
            raise ModelError("missing_key", "请在项目 .env 文件中配置 DEEPSEEK_API_KEY，或使用离线演示模式。")
        from openai import OpenAI
        self.settings = settings
        # SDK 不额外重试；下面统一限制为最多重试一次。
        self.client = OpenAI(api_key=settings.api_key, base_url=settings.base_url,
                             timeout=settings.timeout, max_retries=0)

    def complete(self, messages, tools, allow_tools=True):
        from openai import (APITimeoutError, APIConnectionError, AuthenticationError,
                            RateLimitError, APIStatusError)
        for attempt in range(2):
            try:
                params = dict(model=self.settings.model, messages=messages, max_tokens=900,
                              extra_body={"thinking": {"type": "disabled"}})
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
                raise ModelError("authentication", "DeepSeek 密钥无效，请检查本地 .env 配置。") from error
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
                text = "模型账户余额不足，请检查 DeepSeek 控制台。" if error.status_code == 402 else "模型服务拒绝了请求，请检查模型配置或稍后重试。"
                raise ModelError("api_error", text) from error
