"""检查Git索引的发布边界；不打印密钥内容。"""
from pathlib import Path
import os
import re
import subprocess
from dotenv import dotenv_values

ROOT=Path(__file__).resolve().parent.parent
FORBIDDEN={".venv","outputs","dist",".idea",".cache","__pycache__"}
PATTERN=re.compile(rb"(?:sk-|ghp_|gho_)[A-Za-z0-9_-]{24,}")


def configured_secrets(root):
    # 两个来源都保留；即使环境覆盖.env，文件里的旧凭据仍不能发布。
    return {value.strip().encode() for source in (dotenv_values(root/".env"),os.environ)
            for key,value in source.items() if key.endswith("_API_KEY") and value and value.strip()}


def check_content(content, path, secrets):
    if any(secret in content for secret in secrets):
        raise RuntimeError("检测到本地密钥，停止发布。文件："+str(path))
    if path.suffix not in {".png",".webm"} and PATTERN.search(content):
        raise RuntimeError("检测到疑似凭据，停止发布。文件："+str(path))


def check():
    names=subprocess.check_output(["git","ls-files","-z"],cwd=ROOT).decode().split("\x00")
    # 包含 .env 和进程环境中的所有服务商凭据；不打印值。
    secrets = configured_secrets(ROOT)
    checked=0
    for name in filter(None,names):
        path=Path(name)
        if (path.name.startswith(".env") and path.name!=".env.example") or any(part in FORBIDDEN for part in path.parts) or path.suffix in {".db",".sqlite",".sqlite3"}:
            raise RuntimeError("不应提交的文件："+name)
        content=subprocess.check_output(["git","show",":"+name],cwd=ROOT)
        check_content(content,path,secrets)
        checked+=1
    print(f"Git发布检查通过：{checked}个文件；未包含运行数据、配置密钥或虚拟环境。")


if __name__=="__main__":
    check()
