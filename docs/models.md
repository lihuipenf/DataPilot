# 多模型配置与协议

适用当前版本 **v1.3.1**。[文档导航](README.md) · [版本说明](releases/v1.3.1.md)

只在本地 `.env` 填写凭据，保留旧文件，不要用示例文件覆盖已有密钥。服务读取配置后需要重启；网页只能选择模型，不能修改密钥或服务地址。

| 网页选项 / provider | 协议 | 凭据 / 模型 / 地址变量 |
|---|---|---|
| DeepSeek / `deepseek` | Chat Completions，仅此服务发送关闭思考参数 | `DEEPSEEK_API_KEY` / `DEEPSEEK_MODEL` / `DEEPSEEK_BASE_URL` |
| OpenAI / Codex / `openai` | Responses，保留推理项、工具调用和消息 phase，`store=false` | `OPENAI_API_KEY` / `OPENAI_MODEL` / `OPENAI_BASE_URL` |
| Claude / `anthropic` | 原生 Messages，`tool_use` 和 `tool_result` | `ANTHROPIC_API_KEY` / `ANTHROPIC_MODEL` / `ANTHROPIC_BASE_URL` |
| OpenAI 兼容服务 / `compatible` | Chat Completions，服务与模型都须支持 function calling | `COMPATIBLE_API_KEY` / `COMPATIBLE_MODEL` / `COMPATIBLE_BASE_URL` |

例如在现有 `.env` 末尾添加：

```dotenv
OPENAI_API_KEY=在本地填写
OPENAI_MODEL=gpt-5.3-codex
OPENAI_BASE_URL=https://api.openai.com/v1

ANTHROPIC_API_KEY=在本地填写
ANTHROPIC_MODEL=claude-sonnet-4-6
ANTHROPIC_BASE_URL=https://api.anthropic.com/v1
```

这是模型 ID 示例，不代表最新型号，也不保证你的账户有权限。模型可在网页编辑。OpenAI/Codex 接口按 [OpenAI 模型文档](https://developers.openai.com/api/docs/models/gpt-5.3-codex) 与 [函数调用文档](https://developers.openai.com/api/docs/guides/function-calling) 实现。Claude 遵循 [原生工具调用文档](https://platform.claude.com/docs/en/agents-and-tools/tool-use/handle-tool-calls)。不读取或复用桌面 Codex、Claude Code 的登录凭据。

重启 `app.py` 后，网页选择服务商和模型 ID，选择“大模型实时分析”。以后更换模型点击“应用模型”，会新建会话并复制数据，旧历史仍可恢复。每条新回答记录 provider/model。旧版没有记录过的回答显示“未记录”，不伪造其模型来源；旧版实时会话按DeepSeek恢复。

命令行（项目根目录）：

```powershell
.\.venv\Scripts\python.exe api_test.py --provider openai --model gpt-5.3-codex
.\.venv\Scripts\python.exe api_test.py --provider anthropic --model claude-sonnet-4-6
.\.venv\Scripts\python.exe -m evals.run_eval --mode live --provider openai --model gpt-5.3-codex
```

真实评测会产生API费用。每个服务商都应分别跑题集，不能把DeepSeek历史分数当作Claude或Codex的效果。

`DATAPILOT_PROVIDER` 控制默认服务（未设时deepseek），`DATAPILOT_TIMEOUT` 控制单次请求超时1～120秒，兼容旧 `DEEPSEEK_TIMEOUT`。每个模型步骤至多两次HTTP尝试，总工具步数有界。OpenAI/Claude最大输出4096 tokens，DeepSeek/兼容接口900。当前没有流式输出；网页支持协作式停止，默认整轮预算120秒。预算在步骤边界检查，不保证立即中断正在进行的同步网络请求或锁等待。

远程服务地址必须使用HTTPS；HTTP仅允许localhost、127.0.0.0/8和::1等回环IP。私有局域网地址也不能明文发送密钥。空的BASE_URL使用该服务默认值；无效数字配置会指出配置项。HTTP客户端默认 `DATAPILOT_TRUST_ENV=false`，不自动读取环境代理或CA设置；需要可信企业代理/自定义CA时显式设true并重启。

`INPUT_PRICE_PER_MILLION` / `OUTPUT_PRICE_PER_MILLION` 只属于默认配置的模型；改选其他服务或模型时不继承价格，避免错误估算。Token采用服务返回值；缓存计费、重试及账单并不完全等价。

本地无鉴权的兼容服务可将 `COMPATIBLE_API_KEY` 填为任意非空占位值，指定模型名与如 `http://localhost:11434/v1` 的地址。云服务填写真实密钥。只适配兼容工具调用的接口，不保证任意服务商、任意模型均可运行。Gemini原生、Bedrock、Azure专用鉴权和CLI订阅登录不是本次实现范围。

服务端配置的模型凭据不主动进入会话数据库、浏览器或报告；如果使用者把密钥填进问题或CSV，它仍可能作为输入数据被保存、导出或发送。会话保存原始业务数据、问题、工具证据及供应商协议续传信息，明文保存在本地 `outputs/`。实时请求会向所选端点发送必要历史与工具结果；只读SQL工具可能返回原始记录，请使用适合发送给该服务的数据。完整限制见 [能力边界](capabilities.md)。
