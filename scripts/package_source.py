"""生成可分享源码包：只收录白名单文件，并检查本地密钥未混入。"""
from datetime import datetime
from hashlib import sha256
from pathlib import Path
import zipfile
try:
    from .check_secrets import configured_secrets, check_content, FORBIDDEN
except ImportError:  # 同时支持 python scripts/package_source.py 和模块入口。
    from check_secrets import configured_secrets, check_content, FORBIDDEN

ROOT = Path(__file__).resolve().parent.parent
ROOT_FILES = {"app.py", "api_test.py", "main.py", "sales_tools.py", "check_tools.py", "sales.csv",
              "README.md", "README_EN.md", "LICENSE", "SECURITY.md", "SUPPORT.md", "CONTRIBUTING.md", "CHANGELOG.md", "Dockerfile", "compose.yaml",
              ".dockerignore", ".gitattributes", ".env.example", ".gitignore", "requirements.txt", "requirements-lock.txt", "start_datapilot.ps1"}
FOLDERS = {"datapilot", "static", "tests", "evals", "docs", "scripts", "semantic", ".github", "examples"}
EXTENSIONS = {".py", ".html", ".js", ".css", ".md", ".json", ".csv", ".txt", ".png", ".webm", ".yml", ".yaml"}


def package():
    files = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(ROOT)
        if any(part in FORBIDDEN for part in relative.parts) or (path.name.startswith('.env') and path.name != '.env.example'):
            continue
        if relative.parts[0] in ROOT_FILES or (relative.parts[0] in FOLDERS and (path.suffix in EXTENSIONS or relative.as_posix()=='.github/CODEOWNERS') and "__pycache__" not in relative.parts):
            if path.is_symlink() or not path.resolve().is_relative_to(ROOT.resolve()):
                raise RuntimeError("源码包不接受指向外部文件的链接。")
            files.append(path)
    # 仅读入本地密钥做包含性检查，不打印、不写入任何归档或报告。
    secrets = configured_secrets(ROOT)
    for path in files:
        check_content(path.read_bytes(),path.relative_to(ROOT),secrets)
    output = ROOT / "dist"
    output.mkdir(exist_ok=True)
    archive = output / ("DataPilot-source-" + datetime.now().strftime("%Y%m%d-%H%M%S") + ".zip")
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as target:
        for path in sorted(files):
            target.write(path, Path("DataPilot") / path.relative_to(ROOT))
    with zipfile.ZipFile(archive) as check:
        if check.testzip() is not None or any(Path(name).name == ".env" for name in check.namelist()):
            raise RuntimeError("源码包验证未通过。")
    digest = sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix(".zip.sha256").write_text(digest + "  " + archive.name + "\n", encoding="utf-8")
    print("ARCHIVE=" + str(archive))
    print(f"FILES={len(files)}; BYTES={archive.stat().st_size}; SECRET_CHECK=PASS; SHA256={digest}")
    return archive


if __name__ == "__main__":
    package()
