# DataPilot · 销售数据分析 Agent

用自然语言查询销售数据，查看计算依据，生成图表并导出报告。项目从 CSV / Pandas 练习发展为一个带工具调用、短期对话记忆和质量校验的本地应用。

![工作台](docs/screenshots/workspace.png)

## 快速运行

已有本项目虚拟环境时，在 PyCharm 打开项目，选择 `.venv/Scripts/python.exe`，右键运行 **`app.py`**，浏览器打开 **http://127.0.0.1:8765**。

页面默认是**离线演示模式**：使用规则选择工具，仍由真实 Python 代码计算数据，不消耗模型调用额度。右上角切换到 **DeepSeek 实时分析** 后才会调用模型。切换模式保留当前CSV，并开始新对话。

全新安装（Windows PowerShell，Python 3.12）：

```powershell
Set-Location "D:\agent ai\DataPilot"
New-Item -ItemType Directory -Path "D:\CodexData\temp" -Force | Out-Null
$env:TEMP = "D:\CodexData\temp"
$env:TMP = "D:\CodexData\temp"
$env:PIP_CACHE_DIR = "D:\CodexData\caches\pip"
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
.\.venv\Scripts\python.exe app.py
```

也可使用 `start_datapilot.ps1`，它为本次运行设置D盘缓存。启动服务后保持该终端运行。端口被占用时，先关闭自己之前启动的实例。

## DeepSeek 配置

保留现有 `.env` 即可；全新安装时把 `.env.example` 复制为 `.env`，填写：

```dotenv
DEEPSEEK_API_KEY=你的密钥
DEEPSEEK_MODEL=deepseek-flash
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_TIMEOUT=45
```

配置改变后重启服务。密钥只由Python读取，不发送到浏览器；源码包与Git忽略文件均排除 `.env`。模型名和接口遵循 [DeepSeek 官方文档](https://api-docs.deepseek.com/)。实时模式会把问题、必要对话历史和工具结果发给DeepSeek；原始CSV默认不整表发送。

## 可以做什么

| 工具 | 能力 | 示例问题 |
|---|---|---|
| `get_total_sales` | 所有记录的总销售额 | 所有商品的总销售额是多少？ |
| `get_top_product` | 最高商品及并列情况 | 哪个商品销售额最高？ |
| `get_sales_for_product` | 指定商品查询，名称忽略大小写 | Keyboard 的销售额是多少？ |
| `get_sales_by_date` | 每日汇总与含边界日期筛选 | 2026-11-01 到 2026-11-02 的销售额是多少？ |
| `get_product_ranking` | 销售额 / 销量排名，最多50名 | 按销量列出前3名商品 |
| `get_dataset_summary` | 数据量、日期范围和总量 | 数据一共有多少条记录？ |
| `create_sales_chart` | 商品柱状图 / 每日趋势图，下载PNG | 画每日销售趋势图 |

支持上下文追问，例如先问“Keyboard 的销售额是多少？”，再问“那 Mouse 呢？”。复杂问题可在一轮中调用多个工具或分步查询。工具参数通过Pydantic校验，仅执行白名单函数。

界面支持上传CSV、数据预览、工具执行记录、图表下载、商品汇总CSV导出和含问答依据的Markdown报告。切换数据会校验新文件，成功后开始新对话；文件不合格时原数据保留。

## CSV 数据约定

```csv
date,product,quantity,unit_price
2026-11-01,Keyboard,2,100
2026-11-01,Mouse,3,50
```

- 必须包含 `date`、`product`、`quantity`、`unit_price`，可以有其他命名列。
- 日期必须为有效的 `YYYY-MM-DD`；商品名非空，最多120字符。
- 数量是非负整数，单价是有限非负数；必要字段不允许空值。
- UTF-8 / UTF-8 BOM / GB18030；最多5 MB、50,000行；重复表头和行宽错误会被拒绝。
- `sales_amount` 始终根据数量与单价重算；汇总显示保留两位小数。币种未指定，不推断税费、退货或汇率。
- 日期统计最多返回366个有记录日期；图表显示前20名商品或最近366个有记录日期。大规模并列仅返回前20个名称及总数，不假装是完整清单。

## 代码结构

```text
app.py                  网页入口，PyCharm直接运行
api_test.py             兼容入口，启动命令行Agent
main.py                 纯Python分析与绘图示例，不调用模型
sales_tools.py          保留早期练习函数的兼容接口
datapilot/
  config.py             配置、密钥与项目路径
  data.py               CSV读取和质量校验
  tools.py              7个工具、参数契约和分发
  models.py             DeepSeek客户端、超时与有界重试
  demo.py               明确标注的离线规则演示
  agent.py              工具循环、历史与完整上下文预算
  reports.py            Markdown和CSV导出
  web.py                会话、上传、聊天与文件下载API
  cli.py                连续命令行问答
static/                 HTML/CSS/JavaScript本地界面，无前端构建步骤
tests/                  自动化回归测试
evals/                  26题固定功能评测与同模型基线对照
docs/                   架构、学习路线、评测与演示说明
outputs/                运行产物（Git忽略，保留在本地）
```

从其他工作目录启动也能找到项目默认CSV和 `.env`，所有路径以项目目录为基准。命令行：

```powershell
.\.venv\Scripts\python.exe api_test.py --demo
.\.venv\Scripts\python.exe api_test.py
.\.venv\Scripts\python.exe api_test.py --csv "D:\你的数据\sales.csv"
```

## 测试和评测

```powershell
# 不调用模型，覆盖真实数据计算、异常、工具流程与HTTP API
.\.venv\Scripts\python.exe -m unittest discover -v

# 26题规则演示回归，不消耗模型额度
.\.venv\Scripts\python.exe -m evals.run_eval --mode demo

# 26题真实DeepSeek评测，并运行24题单次生成基线（会调用API）
.\.venv\Scripts\python.exe -m evals.run_eval --mode live --baseline
```

逐题结果、Token、耗时和报告写入 `outputs/evaluations/`。实际运行数据见 [评测报告](docs/evaluation.md)，评测边界与基线条件也在报告中说明。演示模式的通过率不代表模型准确率；这组固定小数据回归也不代表真实业务泛化。

## 运行边界

这是单用户本地作品，默认仅监听 `127.0.0.1`，不作为公网多租户服务。数据与对话保存在服务进程内，最多32个会话；更换数据或模式重开当前对话。模型保留最近6个完整轮次，并把每次完整请求限制在24,000字符，超限时先移除旧轮次，再给出可解释的范围提示。

每轮最多4轮工具选择、8次工具执行，最后一轮仅生成回答；每个模型步骤最多2次HTTP尝试，默认单次超时45秒。失败不提交不完整历史。Token来自服务返回值；可在 `.env` 填写每百万Token单价估算费用，实际账单以服务商为准。

## 展示与面试

- [架构与请求流程](docs/architecture.md)
- [按模块理解代码](docs/learning-guide.md)
- [评测结果与指标边界](docs/evaluation.md)
- [演示脚本与简历描述](docs/demo-and-resume.md)

原练习文件的修改前备份保留在 `D:\CodexData\temp\DataPilot-original-20261104-151046`，现有 `.env` 未被覆盖。项目未自动创建远程GitHub仓库或推送代码。
