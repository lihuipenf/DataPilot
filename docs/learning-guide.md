# 从原练习代码理解新版

建议每次只读一个模块，边打断点边运行，不需要一次读完整个项目。

## 1. 从熟悉的数据计算开始

读 `datapilot/data.py` 的 `load_sales()` 和 `validate_sales()`，再读 `datapilot/tools.py` 的三个原有工具。

原来的 `df['quantity'] * df['unit_price']` 仍然存在。变化是它被放在统一的数据入口中；无论网页上传还是命令行读文件，都先执行同样的检查。`sales_tools.py` 保留了最初的函数签名，`check_tools.py` 仍可运行。

练习：把单价改成文字、把日期改成不存在的日期，观察程序在哪一层拒绝数据。恢复原数据后再继续。

## 2. 理解参数契约

读 `ProductArgs`、`DateArgs`、`RankArgs` 和 `ToolRegistry.execute()`。

Pydantic同时负责生成给模型的JSON Schema和检查模型返回的参数。它会拒绝遗漏商品名、无效日期、字符串排名数量、超过范围的排名和额外参数。JSON解析错误变成工具结果，模型可据此改正。

练习：在Python控制台调用 `registry.execute('get_product_ranking', '{"limit":0}')`，查看结构化错误。

## 3. 跟踪一次工具调用

在 `AgentSession.ask()` 的 `gateway.complete()` 前后打断点。观察 `current` 如何依次出现 user、assistant工具请求、tool结果、assistant最终回答。

原来的两次请求扩展成了有限循环，因而能够先查总额，再查排名或日期。注意：循环受上限约束，不会无限运行。

## 4. 理解历史与失败恢复

阅读 `_request_messages()` 和 `self.turns.append(current)`。完整轮次成功后才进入历史。观察网络失败前后 `turns` 的长度；旧轮次按整体移除，工具请求和结果不会被拆开。

练习：先问Keyboard，再问“那Mouse呢？”，查看第二次请求中的历史。然后点击“新对话”，再观察历史长度。

## 5. 分清模型网关与演示模式

读 `models.py` 和 `demo.py`。离线模式只是可控的规则示例，用来在无密钥环境体验交互；真实模式由所选模型决定工具。两者都调用同一套计算工具。

v1.2继续读 `create_gateway()`、`ResponsesGateway` 和 `ClaudeGateway`：比较相同的内部工具消息如何转换为不同API协议。`provider_data` 为什么必须留在服务端历史中？为什么不能把DeepSeek的thinking参数发给所有服务商？配置操作见 [多模型指南](models.md)。

## 6. 理解网页入口

读 `web.py` 的 `/chat`、`/dataset`、`/providers` 和创建会话路由，再看 `static/app.js` 中的 `startSession()`、`sendQuestion()` 和 `renderResult()`。浏览器发送问题、CSV或模型选择，服务器返回答案、工具记录和图表地址。`/mode` 从v1.3起复制数据并返回新会话ID，旧历史保留；`/cancel` 请求协作式停止当前分析。时间预算实现在 `budget.py`，不会强制终止正在进行的同步调用。

## 7. 读测试和评测

`tests/test_core.py` 用脚本化模型响应检查控制流程，实际Pandas计算和PNG生成不替换。`evals/run_eval.py --mode live` 才会真实调用模型。二者验证不同层面，不能互相冒充。

面试时应能回答：为什么要有工具ID、为什么不能直接执行模型给出的函数字符串、为什么要按完整轮次裁剪历史、为什么单次回答正确不代表系统可靠。

## 8. 学习成熟数据产品的两个核心抽象

先读 `semantic/metrics.json`：为什么“销售额”“销量”“加权成交均价”需要明确定义？再读 `semantic.py`，观察它如何把已批准的表达式和维度变成参数化SQL。

再读 `sql.py` 的 `_authorize()` 与 `query()`。验证 `SELECT` 如何通过，`DELETE`、`ATTACH`、`load_extension`如何被拒绝。不要把字符串检查当作完整SQL安全边界；真正的授权发生在SQLite编译执行层。

## 9. 跟踪会话如何跨重启恢复

读 `store.py` 的 `save()`、`load()`，再看Web层的 `persist()` 和 `get_record()`。数据库里保存的是业务数据与消息，不是模型客户端或密钥。试着重启服务，恢复历史会话，检查SQL依据和上传文件名称是否一致。

## 10. 理解发布流水线

阅读 `.github/workflows/ci.yml`，区分单元测试、离线评测、容器冒烟测试和真实模型评测。CI不需要模型密钥，也不会把离线演示成绩当成LLM效果。
