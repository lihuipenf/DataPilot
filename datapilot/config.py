"""集中管理配置；密钥不会进入日志、前端或报告。"""
from dataclasses import dataclass, field, replace
import os
import math
import ipaddress
from pathlib import Path
from dotenv import load_dotenv
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / ".cache"
os.environ.setdefault("MPLCONFIGDIR", str(CACHE / "matplotlib"))

# 协议由服务商决定，模型 ID 可在网页或环境变量中指定。
PROVIDERS = {
    "deepseek": ("DeepSeek", "DEEPSEEK", "deepseek-flash", "https://api.deepseek.com"),
    "openai": ("OpenAI / Codex", "OPENAI", "gpt-5.3-codex", "https://api.openai.com/v1"),
    "anthropic": ("Claude", "ANTHROPIC", "claude-sonnet-4-6", "https://api.anthropic.com/v1"),
    "compatible": ("OpenAI 兼容服务", "COMPATIBLE", "", "http://localhost:11434/v1"),
}


def validate_endpoint(value):
    parsed = urlsplit(value)
    if (parsed.scheme not in ("https", "http") or not parsed.hostname or parsed.username
            or parsed.password or parsed.query or parsed.fragment):
        raise ValueError("模型地址必须是 HTTP(S) URL，且不能包含凭据、查询参数或片段。")
    if parsed.scheme == 'http':
        try:
            local = ipaddress.ip_address(parsed.hostname).is_loopback
        except ValueError:
            local = parsed.hostname.lower() == 'localhost'
        if not local:
            raise ValueError('远程模型地址必须使用 HTTPS；HTTP 仅允许 localhost 或回环 IP。')
    try:
        parsed.port
    except ValueError as error:
        raise ValueError('模型地址端口无效。') from error
    return value.rstrip("/")


@dataclass(frozen=True)
class ModelProfile:
    api_key: str = field(default="", repr=False)
    model: str = ""
    base_url: str = ""


@dataclass(frozen=True)
class Settings:
    api_key: str = field(default="", repr=False)
    model: str = "deepseek-flash"
    base_url: str = "https://api.deepseek.com"
    timeout: float = 45.0
    max_tool_rounds: int = 4
    max_tool_calls: int = 8
    max_history_turns: int = 6
    max_context_chars: int = 24000
    max_tool_result_chars: int = 8000
    turn_timeout: float = 120.0
    trust_env: bool = False
    max_saved_sessions: int = 200
    max_session_charts: int = 100
    max_chart_bytes: int = 256 * 1024 * 1024
    output_dir: Path = ROOT / "outputs"
    state_path: Path | None = None
    input_price: float | None = None
    output_price: float | None = None
    provider: str = "deepseek"
    profiles: dict = field(default_factory=dict, repr=False)

    def select(self, provider=None, model=None):
        provider = provider or self.provider
        if provider not in PROVIDERS:
            raise ValueError("未知模型服务商，请选择 deepseek、openai、anthropic 或 compatible。")
        if provider == self.provider:
            selected = self
        else:
            _, _, default_model, default_url = PROVIDERS[provider]
            profile = self.profiles.get(provider, ModelProfile(model=default_model, base_url=default_url))
            selected = replace(self, provider=provider, api_key=profile.api_key, model=profile.model,
                               base_url=profile.base_url, input_price=None, output_price=None)
        name = selected.model if model is None else model.strip()
        if len(name) > 160 or any(ord(c) < 32 for c in name):
            raise ValueError("模型 ID 最多160个字符，不能包含控制字符。")
        if name != selected.model:
            selected = replace(selected, input_price=None, output_price=None)
        return replace(selected, model=name, base_url=validate_endpoint(selected.base_url))

    def public_providers(self):
        return [{"id": key, "label": values[0], "model": self.select(key).model,
                 "available": bool(self.select(key).api_key)} for key, values in PROVIDERS.items()]

    @classmethod
    def from_env(cls):
        load_dotenv(ROOT / ".env")
        def price(key):
            value = os.getenv(key, "").strip()
            if not value:
                return None
            try:
                number = float(value)
            except ValueError as error:
                raise ValueError(f'{key} 必须是数字。') from error
            if not math.isfinite(number) or number < 0:
                raise ValueError(f"{key} 必须是非负数。")
            return number
        def numeric(key, default, low, high, integer=False):
            raw = os.getenv(key) or str(default)
            try:
                value = int(raw) if integer else float(raw)
            except ValueError as error:
                raise ValueError(f'{key} 必须是数字。') from error
            if not math.isfinite(value) or not low <= value <= high:
                raise ValueError(f'{key} 应在 {low}～{high} 之间。')
            return value
        timeout = numeric('DATAPILOT_TIMEOUT',os.getenv('DEEPSEEK_TIMEOUT') or 45,1,120)
        if not 1 <= timeout <= 120:
            raise ValueError("模型请求超时应在 1～120 秒之间。")
        provider = os.getenv("DATAPILOT_PROVIDER", "deepseek").strip().lower()
        if provider not in PROVIDERS:
            raise ValueError("DATAPILOT_PROVIDER 不受支持。")
        profiles = {key: ModelProfile(os.getenv(f"{prefix}_API_KEY", "").strip(),
                                    os.getenv(f"{prefix}_MODEL", model).strip(),
                                    validate_endpoint(os.getenv(f"{prefix}_BASE_URL") or url))
                    for key, (_, prefix, model, url) in PROVIDERS.items()}
        profile = profiles[provider]
        output_dir = Path(os.getenv("DATAPILOT_OUTPUT_DIR") or str(ROOT / "outputs")).resolve()
        state = os.getenv('DATAPILOT_STATE_PATH') or str(output_dir/'state.sqlite3')
        if state == ':memory:':
            raise ValueError('DATAPILOT_STATE_PATH 不支持 :memory:；使用持久文件路径。')
        trust = os.getenv('DATAPILOT_TRUST_ENV','false').lower().strip()
        if trust not in ('true','false'):
            raise ValueError('DATAPILOT_TRUST_ENV 必须是 true 或 false。')
        return cls(api_key=profile.api_key, model=profile.model, base_url=profile.base_url,
                   provider=provider, profiles=profiles,
                   timeout=timeout,
                   output_dir=output_dir,
                   state_path=Path(state).resolve(),
                   max_context_chars=numeric('DATAPILOT_MAX_CONTEXT_CHARS',24000,12000,200000,True),
                   max_tool_result_chars=numeric('DATAPILOT_MAX_TOOL_RESULT_CHARS',8000,1000,60000,True),
                   turn_timeout=numeric('DATAPILOT_TURN_TIMEOUT',120,1,600), trust_env=trust=='true',
                   max_saved_sessions=numeric('DATAPILOT_MAX_SAVED_SESSIONS',200,1,10000,True),
                   max_session_charts=numeric('DATAPILOT_MAX_SESSION_CHARTS',100,1,10000,True),
                   max_chart_bytes=numeric('DATAPILOT_MAX_CHART_BYTES',256*1024*1024,1024,10*1024**3,True),
                   input_price=price("INPUT_PRICE_PER_MILLION"),
                   output_price=price("OUTPUT_PRICE_PER_MILLION"))
