# 三个可复现案例

所有CSV均为人工构造的合成数据，没有客户信息或真实交易。金额币种未指定；一行是销售记录，不代表独立订单。文件遵循现有四列契约，直接上传即可使用。

| 案例 | 展示重点 | 数据 | 操作与预期结果 |
|---|---|---|---|
| 电商周报 | 销售额与销量排名、每日汇总、柱状图 | [retail_weekly.csv](retail_weekly.csv)：21条，3种商品 | [完整案例](../docs/cases/retail_weekly.md) |
| 促销复盘 | 同长度区间对比、加权成交均价、趋势图 | [promotion_review.csv](promotion_review.csv)：7条，1种商品 | [完整案例](../docs/cases/promotion_review.md) |
| 数据边界 | 前导零编号、并列冠军、缺失日期、未知商品、SQL依据 | [data_boundaries.csv](data_boundaries.csv)：6条，3种商品 | [完整案例](../docs/cases/data_boundaries.md) |

## 怎样演示

1. 按 [启动教程](../docs/getting-started.md) 运行程序，打开本地页面，保持“离线演示”。
2. 每个案例先点击“＋新建会话”，再上传对应CSV，保留之前案例的历史。
3. 按案例文档逐条复制问题；展开“分析过程”核对工具、参数与结果，SQL题另有结果表格。
4. 需要时下载PNG，或导出Markdown报告和商品汇总CSV。

在GitHub查看CSV时，可通过文件页面下载原始文件。第三个案例建议直接上传原始CSV，不要先用Excel打开后另存；表格软件可能把 `00123` 自动转换成数字。DataPilot上传后应保留为字符串。

## 验证与使用边界

每个案例包含6个问题，共18条。问题和预期工具字段保存在 [cases.json](cases.json)，原始CSV、问题、图片和文档一起进入版本控制；运行会话与报告仍保存在Git忽略的 `outputs` 中。

Windows复核：

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_examples -v
```

macOS/Linux复核：

```bash
.venv/bin/python -m unittest tests.test_examples -v
```

两项测试分别用标准库CSV/Decimal独立核对数据控制总量，并通过真实Web接口上传三个数据集、执行全部问题、验证结构化结果与图表/报告下载。它们验证离线规则路由及本地计算，不调用外部模型，也不表示任一模型在新数据上的准确率。

接入实时模型后可以尝试相同问题。不同模型可能选用其他等价工具或SQL，复核时应比较业务结果；真实模型行为需单独记录，不能沿用本案例的离线验证结论。离线SQL题只执行内置固定示例，不能任意指定复杂SQL。
