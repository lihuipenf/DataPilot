"""检查Git索引的发布边界；不打印密钥内容。"""
from pathlib import Path
import re
import subprocess
from dotenv import dotenv_values

ROOT=Path(__file__).resolve().parent.parent
FORBIDDEN={".venv","outputs","dist",".idea",".cache","__pycache__"}
PATTERN=re.compile(rb"(?:sk-|ghp_|gho_)[A-Za-z0-9_-]{24,}")


def check():
    names=subprocess.check_output(["git","ls-files","-z"],cwd=ROOT).decode().split("\x00")
    secret=(dotenv_values(ROOT/".env").get("DEEPSEEK_API_KEY") or "").strip().encode()
    checked=0
    for name in filter(None,names):
        path=Path(name)
        if (path.name.startswith(".env") and path.name!=".env.example") or any(part in FORBIDDEN for part in path.parts) or path.suffix in {".db",".sqlite",".sqlite3"}:
            raise RuntimeError("不应提交的文件："+name)
        content=subprocess.check_output(["git","show",":"+name],cwd=ROOT)
        if secret and secret in content:
            raise RuntimeError("检测到本地密钥，停止发布。文件："+name)
        if path.suffix not in {".png",".webm"} and PATTERN.search(content):
            raise RuntimeError("检测到疑似凭据，停止发布。文件："+name)
        checked+=1
    print(f"Git发布检查通过：{checked}个文件；未包含运行数据、配置密钥或虚拟环境。")


if __name__=="__main__":
    check()
