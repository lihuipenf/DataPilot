"""集中管理配置；密钥不会进入日志、前端或报告。"""
from dataclasses import dataclass, field, replace
import os
import math
from pathlib import Path
from dotenv import load_dotenv
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
CACHE = Path("D:/CodexData/caches") if os.name == "nt" else ROOT / ".cache"
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
            number = float(value)
            if not math.isfinite(number) or number < 0:
                raise ValueError(f"{key} 必须是非负数。")
            return number
        timeout = float(os.getenv("DATAPILOT_TIMEOUT", os.getenv("DEEPSEEK_TIMEOUT", "45")))
        if not 1 <= timeout <= 120:
            raise ValueError("模型请求超时应在 1～120 秒之间。")
        provider = os.getenv("DATAPILOT_PROVIDER", "deepseek").strip().lower()
        if provider not in PROVIDERS:
            raise ValueError("DATAPILOT_PROVIDER 不受支持。")
        profiles = {key: ModelProfile(os.getenv(f"{prefix}_API_KEY", "").strip(),
                                    os.getenv(f"{prefix}_MODEL", model).strip(),
                                    validate_endpoint(os.getenv(f"{prefix}_BASE_URL", url)))
                    for key, (_, prefix, model, url) in PROVIDERS.items()}
        profile = profiles[provider]
        output_dir = Path(os.getenv("DATAPILOT_OUTPUT_DIR", str(ROOT / "outputs"))).resolve()
        return cls(api_key=profile.api_key, model=profile.model, base_url=profile.base_url,
                   provider=provider, profiles=profiles,
                   timeout=timeout,
                   output_dir=output_dir,
                   state_path=Path(os.getenv("DATAPILOT_STATE_PATH", str(output_dir / "state.sqlite3"))).resolve(),
                   input_price=price("INPUT_PRICE_PER_MILLION"),
                   output_price=price("OUTPUT_PRICE_PER_MILLION"))
