"""从可审查的版本化文件读取指标口径，生成受控SQL。"""
from datetime import date
import json
from pathlib import Path
from .config import ROOT


class MetricCatalog:
    def __init__(self, path=None):
        self.contract = json.loads(Path(path or ROOT / "semantic" / "metrics.json").read_text(encoding="utf-8"))
        self.metrics = {entry["name"]: entry for entry in self.contract["metrics"]}

    def describe(self):
        return self.contract

    def query(self, engine, metric, group_by=None, start_date=None, end_date=None):
        if metric not in self.metrics:
            return {"error": "未知指标，请先调用 get_business_metrics 查看可用指标。", "code": "unknown_metric"}
        if group_by not in [None, "product", "date"]:
            return {"error": "分组仅支持 product 或 date。", "code": "invalid_dimension"}
        if start_date and end_date and start_date > end_date:
            return {"error": "开始日期不能晚于结束日期。", "code": "invalid_date_range"}
        expression = self.metrics[metric]["expression"]
        selected = (group_by + ", ") if group_by else ""
        sql = f"SELECT {selected}{expression} AS value FROM sales"
        conditions, parameters = [], []
        for name, value, operator in [("date", start_date, ">="), ("date", end_date, "<=")]:
            if value:
                conditions.append(f"{name} {operator} ?")
                parameters.append(value.isoformat())
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        if group_by:
            sql += f" GROUP BY {group_by} ORDER BY {group_by}"
        result = engine.query(sql, parameters)
        return {"metric": metric, "definition_version": self.contract["version"], **result}
