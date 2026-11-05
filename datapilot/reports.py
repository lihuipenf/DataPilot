"""可分享的 Markdown 报告和可导入表格软件的汇总 CSV。"""
from datetime import datetime
import csv
import io
import json
import re


def markdown_text(value):
    # 实体在Markdown语法识别之后解码，避免HTML、链接、图片和表格语法注入。
    text = str(value).replace('\r', ' ').replace('\n', ' ')
    return ''.join(c if c.isalnum() or c == ' ' else f'&#{ord(c)};' for c in text)


def literal_block(value, language='text'):
    # 用户/模型可能包含围栏；外层必须长于内容中任何连续反引号。
    text = str(value)
    fence = '`' * max(3, 1 + max((len(m) for m in re.findall(r'`+', text)), default=0))
    return f'{fence}{language}\n{text}\n{fence}'


def amount_text(value):
    # 固定两位后去掉多余的0；避免 :g 默认六位有效数字导致金额变化。
    return f"{float(value):.2f}".rstrip("0").rstrip(".")


def markdown_report(record):
    summary = record.agent.registry.get_dataset_summary()
    lines = ["# DataPilot 销售分析报告", "", f"生成时间：{datetime.now().isoformat(timespec='seconds')}",
             f"数据文件：{markdown_text(record.filename)}", f"运行模式：{markdown_text(record.agent.settings.provider + ' / ' + record.agent.settings.model) if record.mode == 'live' else '离线规则演示（未调用大模型）'}", "",
             "## 数据概况", "", f"- 记录数：{summary['row_count']}", f"- 商品数：{summary['product_count']}",
             f"- 总销售额：{summary['total_sales_amount']}（币种未指定）", f"- 日期范围：{summary['date_min']} ～ {summary['date_max']}",
             "", "## 商品销售额汇总", "", "| 商品 | 销售额 |", "| --- | ---: |"]
    for name, value in record.agent.registry.product_sales().items():
        safe_name = markdown_text(name)
        lines.append(f"| {safe_name} | {amount_text(value)} |")
    lines += ["", "## 问答与计算依据", ""]
    for index, (question, result) in enumerate(record.results, 1):
        lines += [f"### 问题 {index}", "", literal_block(question), "", literal_block(result.answer), "",
                  f"模型：{markdown_text(result.provider or '未记录')} / {markdown_text(result.model or '未记录')}" if result.mode == "live" else "模式：离线演示",
                  "", "工具执行结果：", ""]
        for trace in result.traces:
            lines += [f"- {markdown_text(trace['name'])}，耗时 {trace['duration_ms']} ms",
                      literal_block(json.dumps(trace["result"], ensure_ascii=False, indent=2), 'json'), ""]
        lines += [f"模型步骤：{result.request_count} 次（每步最多2次HTTP尝试）；耗时：{result.duration_ms} ms；Token：{json.dumps(result.usage)}", ""]
    lines += ["## 说明", "", "数值由本地 Python 工具计算；模型负责选择工具和组织回答。演示模式使用规则路由。",
              "金额汇总保留两位小数，不包含税率、退货或币种转换。启用状态数据库时，历史问答及数据保存在本地SQLite。", ""]
    return "\n".join(lines)


def summary_csv(registry):
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["product", "sales_amount"])
    for name, value in registry.product_sales().items():
        # 导出到表格软件时，将公式前缀作为文本，避免误执行数据中的公式。
        name = str(name)
        if name.lstrip().startswith(("=", "+", "-", "@")):
            name = "'" + name
        writer.writerow([name, amount_text(value)])
    return "\ufeff" + output.getvalue()
