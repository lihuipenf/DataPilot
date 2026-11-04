"""工具业务逻辑、参数契约和受控分发；不执行模型生成的任意代码。"""
from datetime import date
import json
from pathlib import Path
import threading
from typing import Literal
from uuid import uuid4
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from .data import DataError, number
from .jsonutil import validate_json

CHART_LOCK = threading.Lock()


def parse_arguments(arguments):
    raw = json.loads(arguments) if isinstance(arguments,str) else arguments
    if not isinstance(raw,dict):
        raise ValueError("工具参数必须是 JSON 对象。")
    return validate_json(raw)


class NoArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProductArgs(NoArgs):
    product_name: str = Field(min_length=1, max_length=120)


class DateArgs(NoArgs):
    start_date: date | None = None
    end_date: date | None = None


class RankArgs(NoArgs):
    limit: int = Field(default=5, strict=True, ge=1, le=50)
    metric: Literal["sales_amount", "quantity"] = "sales_amount"


class ChartArgs(NoArgs):
    kind: Literal["product", "daily"] = "product"


class SqlArgs(NoArgs):
    sql: str = Field(min_length=1, max_length=6000)
    parameters: list[str | int | float | None] = Field(default_factory=list, max_length=20)
    limit: int = Field(default=100, strict=True, ge=1, le=200)


class MetricArgs(DateArgs):
    metric: str = Field(min_length=1, max_length=60)
    group_by: Literal["product", "date"] | None = None


SPECS = {
    "get_total_sales": (NoArgs, "计算当前数据中所有商品、所有日期的销售额总和。"),
    "get_top_product": (NoArgs, "查询累计销售额最高的商品；并列时返回数量及最多20个商品名称，并标明是否截断。"),
    "get_sales_for_product": (ProductArgs, "查询用户指定商品的累计销售额，商品名称使用原名，如 Keyboard。"),
    "get_sales_by_date": (DateArgs, "按天统计销售额。可限定起止日期，包含边界；最多返回366个有记录的日期。"),
    "get_product_ranking": (RankArgs, "商品排名，可按销售额 sales_amount 或销量 quantity，limit指定前几名。"),
    "get_dataset_summary": (NoArgs, "查询数据概况：记录数、商品数、总销量、总销售额、日期范围。"),
    "create_sales_chart": (ChartArgs, "绘制销售额图表并生成可下载PNG。product为商品柱状图，daily为每日趋势图。"),
    "get_data_schema": (NoArgs, "查询当前sales表字段、类型与业务含义。在编写SQL前使用。"),
    "get_business_metrics": (NoArgs, "查询销售额、销量、加权均价等指标的统一定义与假设，避免混淆指标。"),
    "query_metric": (MetricArgs, "按已批准的业务指标定义查询，可按商品或日期分组、限定日期。先查看指标定义。"),
    "run_readonly_sql": (SqlArgs, "对当前sales表执行单条只读SQLite SELECT或WITH查询。禁止写入、外部文件和未授权函数；最多200行，1秒超时。"),
}


class ToolRegistry:
    def __init__(self, frame, output_dir, artifact_prefix="/api/artifacts"):
        self.frame = frame
        self.output_dir = Path(output_dir)
        self.artifact_prefix = artifact_prefix
        self._sql = None

    @property
    def sql_engine(self):
        if self._sql is None:
            from .sql import ReadOnlySql
            self._sql = ReadOnlySql(self.frame)
        return self._sql

    def get_data_schema(self):
        return {"table": "sales", "dialect": "SQLite", "columns": [
            {"name":"date", "type":"TEXT", "meaning":"销售日期，YYYY-MM-DD"},
            {"name":"product", "type":"TEXT", "meaning":"商品原始名称"},
            {"name":"quantity", "type":"INTEGER", "meaning":"本条记录的销售数量"},
            {"name":"unit_price", "type":"REAL", "meaning":"单价，币种未指定"},
            {"name":"sales_amount", "type":"REAL", "meaning":"quantity乘unit_price，程序重算"}],
            "row_count": len(self.frame)}

    def get_business_metrics(self):
        from .semantic import MetricCatalog
        return MetricCatalog().describe()

    def query_metric(self, metric, group_by=None, start_date=None, end_date=None):
        from .semantic import MetricCatalog
        return MetricCatalog().query(self.sql_engine, metric, group_by, start_date, end_date)

    def run_readonly_sql(self, sql, parameters=None, limit=100):
        return self.sql_engine.query(sql, parameters, limit)

    def schemas(self):
        return [{"type": "function", "function": {"name": name, "description": description,
                "parameters": args.model_json_schema()}} for name, (args, description) in SPECS.items()]

    def execute(self, name, arguments):
        if name not in SPECS:
            return {"error": f"不支持的工具：{name}", "code": "unknown_tool"}
        try:
            raw = parse_arguments(arguments)
            args = SPECS[name][0].model_validate(raw)
            return getattr(self, name)(**args.model_dump())
        except (ValidationError, ValueError, TypeError, RecursionError) as error:
            if isinstance(error, ValidationError):
                # 只公开字段和校验原因，不回显潜在敏感输入。
                detail = "；".join(".".join(map(str, e["loc"])) + ": " + e["msg"] for e in error.errors())
            else:
                detail = "参数嵌套过深。" if isinstance(error,RecursionError) else str(error) if not isinstance(error, json.JSONDecodeError) else "参数不是有效的 JSON。"
            return {"error": detail, "code": "invalid_arguments"}

    def product_sales(self):
        return self.frame.groupby("product", sort=True)["sales_amount"].sum().round(2)

    def get_total_sales(self):
        return {"total_sales_amount": number(self.frame["sales_amount"].sum())}

    def get_top_product(self):
        sales = self.product_sales()
        amount = sales.max()
        tied = sales[sales == amount].index.tolist()
        result = {"product": tied[0], "sales_amount": number(amount)}
        if len(tied) > 1:
            result["tied_products"] = tied[:20]
            result["tied_count"] = len(tied)
            result["tied_products_truncated"] = len(tied) > 20
        return result

    def get_sales_for_product(self, product_name):
        sales = self.product_sales()
        # 忽略大小写和首尾空格；多个同形名称时要求用户确认。
        matches = [name for name in sales.index if name.casefold() == product_name.strip().casefold()]
        if not matches:
            return {"error": f"没有找到商品：{product_name}", "code": "product_not_found"}
        if len(matches) > 1:
            exact = product_name.strip()
            if exact not in matches:
                return {"error": "存在多个相似商品名称，请使用准确名称。", "code": "ambiguous_product"}
            matches = [exact]
        name = matches[0]
        return {"product": name, "sales_amount": number(sales[name])}

    def get_sales_by_date(self, start_date=None, end_date=None):
        if start_date and end_date and start_date > end_date:
            raise ValueError("开始日期不能晚于结束日期。")
        frame = self.frame
        if start_date:
            frame = frame[frame["date"] >= start_date.isoformat()]
        if end_date:
            frame = frame[frame["date"] <= end_date.isoformat()]
        sales = frame.groupby("date")["sales_amount"].sum()
        if len(sales) > 366:
            raise ValueError("日期过多，请将查询范围缩小到最多366个有记录的日期。")
        return {"daily_sales": [{"date": day, "sales_amount": number(value)} for day, value in sales.items()],
                "total_sales_amount": number(sales.sum())}

    def get_product_ranking(self, limit=5, metric="sales_amount"):
        sales = self.frame.groupby("product")[metric].sum().round(2)
        ordered = sorted(sales.items(), key=lambda row: (-row[1], row[0]))[:limit]
        return {"metric": metric, "ranking": [{"product": key, metric: number(value)} for key, value in ordered]}

    def get_dataset_summary(self):
        return {"row_count": len(self.frame), "product_count": int(self.frame["product"].nunique()),
                "total_quantity": int(self.frame["quantity"].sum()), **self.get_total_sales(),
                "date_min": self.frame["date"].min(), "date_max": self.frame["date"].max(),
                "top_product": self.get_top_product()["product"], "currency": "未指定"}

    def create_sales_chart(self, kind="product"):
        # 面向服务器使用无窗口绘图，不依赖 PyCharm 或桌面图形环境。
        from matplotlib.figure import Figure
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        from matplotlib import font_manager
        with CHART_LOCK:
            fig = Figure(figsize=(9, 4.8), dpi=140, facecolor="#ffffff", layout="constrained")
            FigureCanvasAgg(fig)
            ax = fig.subplots()
            installed = {font.name for font in font_manager.fontManager.ttflist}
            font = next((f for f in ["Microsoft YaHei", "SimHei", "Noto Sans CJK SC", "Noto Sans CJK JP", "DejaVu Sans"] if f in installed), "DejaVu Sans")
            if kind == "product":
                values = self.product_sales().sort_values(ascending=False).head(20)
                ax.bar(values.index, values.values, color="#127b68", width=0.6)
                title = "商品销售额（最多显示前20名）"
            else:
                values = self.frame.groupby("date")["sales_amount"].sum().tail(366)
                ax.plot(values.index, values.values, color="#127b68", marker="o", linewidth=2.5)
                title = "每日销售趋势（最多显示最近366个有记录日期）"
            ax.set_title(title, fontname=font, fontsize=13, pad=18)
            ax.set_ylabel("销售额（币种未指定）", fontname=font)
            ax.grid(axis="y", color="#e6eeeb")
            ax.set_axisbelow(True)
            for side in ["top", "right"]:
                ax.spines[side].set_visible(False)
            # 日期多时只显示约八个横轴标签，保留所有数据点。
            step = max(1, len(values) // 8)
            ax.set_xticks(range(0, len(values), step), values.index[::step], rotation=20 if len(values) > 6 else 0)
            for label in ax.get_xticklabels():
                label.set_fontname(font)
            self.output_dir.mkdir(parents=True, exist_ok=True)
            filename = uuid4().hex + ".png"
            fig.savefig(self.output_dir / filename)
            fig.clear()
        return {"chart_kind": kind, "artifact": {"id": filename, "kind": "chart", "mime_type": "image/png",
                "url": self.artifact_prefix + "/" + filename}, "displayed_points": len(values)}
