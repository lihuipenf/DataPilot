# 从零启动 DataPilot

[项目首页](../README.md) · [English quick start](../README_EN.md) · [模型配置](models.md)

本教程从获取源码开始。先运行不需要密钥的规则演示，再按需接入模型。命令以项目根目录为工作目录，不依赖作者的盘符、用户名或PyCharm配置。

## 选择启动方式

| 方式 | 需要准备 | 适用情况 |
|---|---|---|
| Windows原生 | Git、Python 3.12.x、PowerShell | 在本机运行或用PyCharm学习代码 |
| macOS/Linux原生 | Git、Python 3.12.x及venv模块 | 使用终端开发；不需要桌面绘图窗口 |
| Docker Compose | Git、已启动的Docker、Compose插件 | 在容器中运行，不在宿主机安装Python依赖 |

下载入口：[Python](https://www.python.org/downloads/)、[Git](https://git-scm.com/downloads)、[Docker](https://docs.docker.com/get-started/get-docker/)。首次下载源码、依赖或构建镜像需要联网；原生规则演示在依赖安装后不请求模型服务。实时模式需要对应服务商的API Key、模型访问权限和网络。

不需要Node.js、npm或单独安装前端依赖。项目以Python 3.12为验证版本；其他Python版本不作为本教程的支持承诺。

验证范围：Windows全新虚拟环境的安装、启动、问答和图表已实测；GitHub CI验证Linux依赖、测试与容器构建/启动。macOS原生命令和Compose完整流程仍需在对应环境试跑。

## 获取源码

先进入你想存放项目的父目录，再运行：

```bash
git clone https://github.com/lihuipenf/DataPilot.git
cd DataPilot
```

仓库目前私有，需要已获授权的GitHub账号完成Git认证。出现 `Repository not found` 或认证失败时，先确认账号有仓库访问权限。如果无法使用Git，可在有权限的仓库页面通过 **Code → Download ZIP** 下载并解压，再进入包含 `app.py`、`requirements-lock.txt` 和 `sales.csv` 的目录，继续安装。

已有项目源码时跳过克隆。目录中有空格时，终端切换目录的路径要加引号。不要在 `.venv` 子目录中创建或运行项目文件。

## Windows PowerShell 启动

在项目根目录检查解释器：

```powershell
python --version
```

确认输出 `Python 3.12.x`。若默认 `python` 是其他版本，已安装Windows Python Launcher时可用 `py -3.12 --version`，并将下面创建环境的命令改为 `py -3.12 -m venv .venv`。

首次创建环境并安装：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
.\.venv\Scripts\python.exe -m pip check
```

`pip check` 应显示 `No broken requirements found.`。随后启动：

```powershell
$env:MPLCONFIGDIR = Join-Path (Get-Location).Path ".cache\matplotlib"
.\.venv\Scripts\python.exe app.py
```

字体缓存放在项目 `.cache` 下，适用于没有D盘的电脑。这个环境变量只影响当前终端，后续新开终端运行时可再次设置。项目保留的 `start_datapilot.ps1` 使用作者的D盘缓存布局；通用安装使用本节命令。

无需执行 `Activate.ps1`，也无需更改PowerShell执行策略。不要把 `import pandas` 等Python代码直接输入到 `PS>` 提示符中；代码写入 `.py` 文件，用Python运行。

## macOS / Linux 启动

在项目根目录运行：

```bash
python3.12 --version
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-lock.txt
.venv/bin/python -m pip check
.venv/bin/python app.py
```

若系统只有 `python3` 命令，先检查 `python3 --version`；确认为3.12.x后，创建环境时可使用 `python3 -m venv .venv`。部分Linux发行版需要先安装与解释器匹配的venv组件；按发行版文档安装后重新创建环境。不要用 `sudo pip install` 安装项目依赖。

无需激活环境。字体缓存默认在项目 `.cache/matplotlib`。无桌面Linux也能通过服务器绘图后端生成PNG。如果中文图表出现方框，安装Noto Sans CJK SC等受支持字体后重启；Docker镜像已安装CJK字体。

## 首次运行验收

1. 保持启动终端运行，浏览器访问 **http://127.0.0.1:8765**。
2. 页面应显示离线演示、默认 `sales.csv`、5条记录、3种商品，总销售额1350。
3. 提问“所有商品的总销售额是多少？”，预期1350，展开分析过程应看到 `get_total_sales`。
4. 提问“哪个商品的销售额最高？”，预期Monitor、800。
5. 提问“画商品销售额柱状图”，应显示图表并可下载PNG。

规则演示使用本地数据和固定规则选择工具，明确不代表大模型推理效果。原生启动不需要创建 `.env`，也不需要API Key。

可在另一个终端检查服务状态：

```powershell
# Windows PowerShell
Invoke-RestMethod http://127.0.0.1:8765/api/health
```

```bash
# macOS / Linux
curl http://127.0.0.1:8765/api/health
```

应包含 `"status": "ok"`；`live_available` 表示默认模型是否配置了密钥，离线启动时为false是正常情况。API契约位于 `/openapi.json`；`/docs`、`/redoc` 已关闭。

## PyCharm 运行

完成对应系统的环境创建和依赖安装后：

1. 用PyCharm打开包含 `app.py` 的项目根目录。
2. 在项目Python解释器设置中选择已有环境：Windows为 `.venv/Scripts/python.exe`，macOS/Linux为 `.venv/bin/python`。
3. Windows若没有D盘，在运行配置的环境变量中将 `MPLCONFIGDIR` 设置为项目根目录下 `.cache/matplotlib` 的绝对路径。
4. 右键运行 `app.py`，打开终端输出的本地地址。

如果提示找不到pandas或fastapi，先确认选中的解释器与安装依赖时使用的解释器一致。不要在另一个系统Python里重复安装依赖来掩盖解释器选择问题。

## 接入真实模型

仅在 `.env` 不存在时创建配置文件，避免覆盖已有密钥：

```powershell
# Windows PowerShell，在项目根目录执行
if (-not (Test-Path -LiteralPath .env)) { Copy-Item .env.example .env }
```

```bash
# macOS / Linux，在项目根目录执行
if [ ! -f .env ]; then cp .env.example .env; fi
```

用文本编辑器打开 `.env`，按所选服务填写API Key及模型ID。例如使用DeepSeek时填写 `DEEPSEEK_API_KEY`；其他服务使用 `OPENAI_API_KEY`、`ANTHROPIC_API_KEY` 或 `COMPATIBLE_API_KEY`。可通过 `DATAPILOT_PROVIDER` 选择默认服务。详细变量与协议说明见 [多模型指南](models.md)。

停止原生服务并重新启动后，在网页选择服务商、模型ID与“大模型实时分析”。应用模型会复制当前数据并创建新会话，旧会话仍可恢复。实时模式会发送问题、必要历史和工具结果至所选服务，可能产生API费用。

`.env` 只保存在本地。已在终端设置的同名环境变量优先于 `.env`；如果配置修改未生效，检查运行环境中的对应变量。不要把密钥、完整 `.env`、会话数据库或真实业务数据粘贴到Issue中。

## Docker 启动

此方式不需要宿主机Python虚拟环境。先安装并启动Docker，确认以下命令正常：

```bash
docker version
docker compose version
```

在项目根目录按上一节命令创建 `.env`（不覆盖已存在文件）。Compose将其作为 `env_file` 读取，因此即使只使用离线演示，也需要该文件；密钥可留空。

```bash
docker compose up --build -d
docker compose ps
docker compose logs -f datapilot
```

首次构建需下载镜像、Python依赖及字体，可能需要等待。日志无启动错误后访问 **http://127.0.0.1:8765**，按“首次运行验收”检查。查看日志时按 `Ctrl+C` 只退出日志跟随，容器继续运行。

停止容器并保留业务数据：

```bash
docker compose down
```

会话和图表位于Compose管理的 `datapilot-data` 命名卷，原生启动的数据位于项目 `outputs`；两者不会自动互相同步。普通 `down` 保留命名卷，勿添加会删除卷的 `-v` 参数。迁移项目目录或改变Compose项目名可能使用另一个命名卷，原数据并不会自动迁移。

修改 `.env` 后重新创建容器使配置生效，命名卷保留：

```bash
docker compose up -d --force-recreate
```

容器内程序需监听容器网卡，宿主机端口仍仅绑定 `127.0.0.1`。本教程不配置公网部署或多人身份认证。

## 停止、再次运行与升级

原生服务在启动终端按 `Ctrl+C` 停止。下次进入同一项目目录，直接运行虚拟环境中的Python和 `app.py`，无需再次创建环境或安装依赖；Windows可再次设置上文字体缓存变量。

网页数据、对话和图表保存在项目 `outputs` 中，数据库为 `outputs/state.sqlite3`；停止服务不会主动删除它们。备份时先停止服务，再保留完整 `outputs` 目录与本地 `.env`。命令行聊天历史只保存在当前进程内存中。

更新前先保留配置和运行数据，并保存自己的源码修改。工作区干净时可更新：

```bash
git pull --ff-only
```

随后重新执行对应平台的依赖安装命令，再启动程序；Docker用户重新运行 `docker compose up --build -d`。不要复制新 `.env.example` 覆盖已有 `.env`，不要覆盖迁移备份。

## 常见问题

| 现象 | 处理方法 |
|---|---|
| `Repository not found` / Git认证失败 | 当前仓库私有；确认GitHub账号有权限。公开前无法匿名克隆 |
| `python` / `python3.12` 未找到 | 安装Python 3.12并重新打开终端；Windows可尝试 `py -3.12`，Unix仅在确认版本后使用 `python3` |
| 无匹配依赖版本或尝试从源码编译失败 | 核对Python 3.12及平台；优先安装64位Python或改用Docker。检查PyPI访问与实际报错，不要随意删除锁定版本 |
| `ModuleNotFoundError` | 用当前项目虚拟环境的Python执行 `-m pip install -r requirements-lock.txt`，并核对PyCharm解释器 |
| `Activate.ps1` 被禁止运行 | 本教程无需激活；直接调用 `.venv/Scripts/python.exe` |
| `[WinError 10048]` / `Address already in use` | 停止自己此前启动的原生或Docker实例，或用下文命令更换原生端口 |
| 浏览器无法连接 | 确认启动终端或容器仍运行、地址端口正确；检查 `/api/health` 与启动日志 |
| 模型显示未配置或请求失败 | 检查所选服务的API Key、模型权限、余额与网络；原生重启、Docker重新创建后生效，可先使用离线演示 |
| Docker提示缺少 `.env` | 按上文保护性复制命令创建文件；仅离线演示时保留空密钥即可 |
| 图表中文显示方框 | 安装受支持的CJK字体并重启，或使用已带字体的Docker镜像 |
| 新环境里没有历史会话 | 核对 `outputs` 目录/自定义状态路径；Docker核对是否使用原Compose项目及命名卷 |

原生更换端口示例（从项目根目录运行，取代 `app.py` 命令）：

```powershell
# Windows
.\.venv\Scripts\python.exe -m uvicorn app:app --host 127.0.0.1 --port 8766
```

```bash
# macOS / Linux
.venv/bin/python -m uvicorn app:app --host 127.0.0.1 --port 8766
```

随后访问 `http://127.0.0.1:8766`。Windows同样可先设置字体缓存变量。通过常规浏览器直接打开本地地址；API同源保护会拒绝来自其他网页来源的请求。

原生回归检查可在另一个终端运行 `虚拟环境中的Python -m unittest discover -v`，离线题集命令为 `虚拟环境中的Python -m evals.run_eval --mode demo`；都不调用真实模型。完整命令见项目首页。

命令依据：[Python venv](https://docs.python.org/3.12/library/venv.html)、[Compose env_file](https://docs.docker.com/compose/how-tos/environment-variables/set-environment-variables/)、[Compose down](https://docs.docker.com/reference/cli/docker/compose/down/)。
