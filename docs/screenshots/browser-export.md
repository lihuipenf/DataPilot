# DataPilot 销售分析报告

生成时间：2026-11-04T15:39:05
数据文件：sales.csv
运行模式：离线规则演示（未调用大模型）

## 数据概况

- 记录数：5
- 商品数：3
- 总销售额：1350（币种未指定）
- 日期范围：2026-11-01 ～ 2026-11-02

## 商品销售额汇总

| 商品 | 销售额 |
| --- | ---: |
| Keyboard | 300 |
| Monitor | 800 |
| Mouse | 250 |

## 问答与计算依据

### 问题 1

Keyboard 的销售额是多少？

Keyboard 的销售额为 300。

工具执行结果：

- `get_sales_for_product`，耗时 1 ms
```json
{
  "product": "Keyboard",
  "sales_amount": 300
}
```

模型步骤：2 次（每步最多2次HTTP尝试）；耗时：5 ms；Token：{"prompt_tokens": 0, "completion_tokens": 0}

### 问题 2

那 Mouse 呢？

Mouse 的销售额为 250。

工具执行结果：

- `get_sales_for_product`，耗时 1 ms
```json
{
  "product": "Mouse",
  "sales_amount": 250
}
```

模型步骤：2 次（每步最多2次HTTP尝试）；耗时：6 ms；Token：{"prompt_tokens": 0, "completion_tokens": 0}

### 问题 3

Phone 的销售额是多少？

查询未完成：没有找到商品：Phone

工具执行结果：

- `get_sales_for_product`，耗时 1 ms
```json
{
  "error": "没有找到商品：Phone",
  "code": "product_not_found"
}
```

模型步骤：2 次（每步最多2次HTTP尝试）；耗时：9 ms；Token：{"prompt_tokens": 0, "completion_tokens": 0}

### 问题 4

画每日销售趋势图

销售图表已生成，可在下方查看或下载 PNG。图中最多显示前20名商品或最近366个有记录日期。

工具执行结果：

- `create_sales_chart`，耗时 177 ms
```json
{
  "chart_kind": "daily",
  "artifact": {
    "id": "5fe5635f4a5348d482ea38dc719c98e0.png",
    "kind": "chart",
    "mime_type": "image/png",
    "url": "/api/sessions/f262dd495a864eaa9d74e73b75b1f560/artifacts/5fe5635f4a5348d482ea38dc719c98e0.png"
  },
  "displayed_points": 2
}
```

模型步骤：2 次（每步最多2次HTTP尝试）；耗时：182 ms；Token：{"prompt_tokens": 0, "completion_tokens": 0}

## 说明

数值由本地 Python 工具计算；模型负责选择工具和组织回答。演示模式使用规则路由。
金额汇总保留两位小数，不包含税率、退货或币种转换。历史问答仅保存在当前服务进程内。
