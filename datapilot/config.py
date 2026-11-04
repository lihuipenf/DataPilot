"""集中管理配置；密钥不会进入日志、前端或报告。"""
from dataclasses import dataclass, field
import os
import math
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
CACHE = Path("D:/CodexData/caches") if os.name == "nt" else ROOT / ".cache"
os.environ.setdefault("MPLCONFIGDIR", str(CACHE / "matplotlib"))


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
        timeout = float(os.getenv("DEEPSEEK_TIMEOUT", "45"))
        if not 1 <= timeout <= 120:
            raise ValueError("DEEPSEEK_TIMEOUT 应在 1～120 秒之间。")
        output_dir = Path(os.getenv("DATAPILOT_OUTPUT_DIR", str(ROOT / "outputs"))).resolve()
        return cls(api_key=os.getenv("DEEPSEEK_API_KEY", ""),
                   model=os.getenv("DEEPSEEK_MODEL", "deepseek-flash"),
                   base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
                   timeout=timeout,
                   output_dir=output_dir,
                   state_path=Path(os.getenv("DATAPILOT_STATE_PATH", str(output_dir / "state.sqlite3"))).resolve(),
                   input_price=price("INPUT_PRICE_PER_MILLION"),
                   output_price=price("OUTPUT_PRICE_PER_MILLION"))
