"""明确标注的离线规则演示。它不调用大模型，不用于声称模型准确率。"""
import json
import re
from uuid import uuid4
from .models import ModelReply, ToolCall


class DemoGateway:
    mode = "demo"

    def __init__(self, products):
        self.products = list(products)

    def complete(self, messages, tools, allow_tools=True):
        question = next(m["content"] for m in reversed(messages) if m["role"] == "user")
        if messages[-1]["role"] == "tool":
            results = []
            for message in reversed(messages):
                if message["role"] != "tool":
                    break
                results.insert(0, json.loads(message["content"]))
            return ModelReply(content="\n\n".join(self._answer(result) for result in results))
        calls = []
        def call(name, args=None):
            calls.append(ToolCall(uuid4().hex, name, json.dumps(args or {}, ensure_ascii=False)))
        if any(word in question for word in ["画", "绘", "图表", "柱状图", "折线图"]):
            call("create_sales_chart", {"kind": "daily" if any(w in question for w in ["每日", "趋势", "日期", "折线"]) else "product"})
        elif any(word in question for word in ["概况", "多少条", "多少种", "数据范围", "总销量"]):
            call("get_dataset_summary")
        elif any(word in question for word in ["排名", "排行", "前两", "前二", "前三", "前2", "前3"]):
            limit_match = re.search(r"前\s*(\d+)", question)
            limit = int(limit_match.group(1)) if limit_match else 2 if any(w in question for w in ["前两", "前二"]) else 3 if "前三" in question else 5
            call("get_product_ranking", {"limit": limit, "metric": "quantity" if "销量" in question else "sales_amount"})
        elif any(word in question for word in ["每日", "每天", "趋势", "日期"]) or re.search(r"\d{4}-\d{2}-\d{2}", question):
            dates = re.findall(r"\d{4}-\d{2}-\d{2}", question)
            args = {"start_date": dates[0], "end_date": dates[-1]} if dates else {}
            call("get_sales_by_date", args)
        else:
            if any(word in question for word in ["总销售额", "总额", "销售总额", "销售额总和", "一共卖"]):
                call("get_total_sales")
            if any(word in question for word in ["最高", "卖得最好", "最多销售额"]):
                call("get_top_product")
            if not calls:
                names = [p for p in self.products if p.casefold() in question.casefold()]
                unknown = re.findall(r"[A-Za-z][A-Za-z0-9_-]*", question)
                name = names[0] if names else unknown[0] if unknown else None
                if name:
                    call("get_sales_for_product", {"product_name": name})
        if calls and allow_tools:
            return ModelReply(tool_calls=calls)
        return ModelReply(content="这是离线演示模式。我可以查询总销售额、最高商品、指定商品、每日趋势、商品排名和生成图表。启用 DeepSeek 后可使用更灵活的自然语言分析。")

    @staticmethod
    def _answer(result):
        if "error" in result:
            return "查询未完成：" + result["error"]
        if "artifact" in result:
            return "销售图表已生成，可在下方查看或下载 PNG。图中最多显示前20名商品或最近366个有记录日期。"
        if "row_count" in result:
            return f"当前数据共有 {result['row_count']} 条记录、{result['product_count']} 种商品，总销量 {result['total_quantity']}，总销售额 {result['total_sales_amount']}。日期范围为 {result['date_min']} 至 {result['date_max']}。"
        if "ranking" in result:
            label = "销量" if result["metric"] == "quantity" else "销售额"
            return label + "排名：\n" + "\n".join(f"{i}. {row['product']}：{row[result['metric']]}" for i, row in enumerate(result["ranking"], 1))
        if "daily_sales" in result:
            return ("\n".join(f"{row['date']}：{row['sales_amount']}" for row in result["daily_sales"]) or "所选日期范围没有销售记录。") + f"\n范围内总销售额：{result['total_sales_amount']}。"
        if "product" in result:
            names = "、".join(result.get("tied_products", [result["product"]]))
            if result.get("tied_products_truncated"):
                names += f"（共{result['tied_count']}个并列商品，仅展示前20个）"
            return f"{names} 的销售额为 {result['sales_amount']}。"
        return f"所有商品的总销售额为 {result['total_sales_amount']}。币种未在数据中指定。"
