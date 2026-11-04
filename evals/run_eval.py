"""运行26题固定评测；demo不调用模型，live和baseline会产生真实API请求。"""
import argparse
from dataclasses import asdict
from datetime import datetime
import json
from pathlib import Path
import re
import statistics
import time
from datapilot.agent import AgentSession
from datapilot.config import ROOT, Settings
from datapilot.data import load_sales
from datapilot.demo import DemoGateway
from datapilot.models import create_gateway, ModelError
from datapilot.tools import ToolRegistry


def contains(actual, expected):
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(key in actual and contains(actual[key], value) for key, value in expected.items())
    if isinstance(expected, list):
        return isinstance(actual, list) and len(actual) == len(expected) and all(contains(a, e) for a, e in zip(actual, expected))
    return actual == expected


def answer_ok(text, case):
    normalized = text.replace(",", "").replace("，", "").casefold()
    if not re.search(r"[\u4e00-\u9fff]", text):
        return False
    if case["id"] == "missing-product":
        return any(term in text for term in ["没有", "未找到", "不存在", "未查到", "未能找到"])
    return all(term.casefold() in normalized for term in case.get("terms", []))


def run(mode="demo", baseline=False, max_cases=26, cases_path=None, provider=None, model=None):
    settings, frame = Settings.from_env().select(provider, model), load_sales()
    case_file = Path(cases_path) if cases_path else ROOT / "evals" / "cases.json"
    cases = json.loads(case_file.read_text(encoding="utf-8"))[:max_cases]
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    folder = settings.output_dir / "evaluations" / (mode + "-" + stamp)
    folder.mkdir(parents=True, exist_ok=True)
    sessions, rows, baseline_histories = {}, [], {}
    gateway = create_gateway(settings) if mode == "live" else None
    for index, case in enumerate(cases, 1):
        group = case.get("group", case["id"])
        if group not in sessions:
            registry = ToolRegistry(frame, folder / "charts")
            sessions[group] = AgentSession(registry, gateway or DemoGateway(frame["product"].unique()), settings)
        started = time.perf_counter()
        row = {"id": case["id"], "question": case["question"], "mode": mode}
        try:
            result = sessions[group].ask(case["question"])
            matching = [trace for trace in result.traces if trace["name"] == case["tool"]]
            tool_ok = any(contains(trace["result"], case["expected"]) for trace in matching)
            if case.get("additional_tool"):
                tool_ok = tool_ok and any(t["name"] == case["additional_tool"] for t in result.traces)
            final_ok = answer_ok(result.answer, case)
            if case["id"].startswith("chart-"):
                tool_ok = tool_ok and bool(result.artifacts) and all((folder / "charts" / a["id"]).is_file() for a in result.artifacts)
            row.update(asdict(result), tool_success=tool_ok, answer_success=final_ok, success=tool_ok and final_ok)
        except (ModelError, ValueError) as error:
            row.update(success=False, tool_success=False, answer_success=False, error=str(error),
                       duration_ms=round((time.perf_counter() - started) * 1000), usage={})
        # 基线获得相同CSV和同组历史，但只允许一次模型请求，不提供工具。
        if baseline and mode == "live" and case.get("baseline", True):
            history = baseline_histories.setdefault(group, [{"role": "system", "content":
                "你是销售分析助手，用简体中文简洁回答。根据以下CSV自行计算，商品名保留原样，未知商品不要编造，币种未指定。\n" + (ROOT / "sales.csv").read_text(encoding="utf-8-sig")}])
            history.append({"role": "user", "content": case["question"]})
            base_start = time.perf_counter()
            try:
                reply = gateway.complete(history, [], allow_tools=False)
                history.append(reply.as_message())
                row["baseline"] = {"answer": reply.content, "success": answer_ok(reply.content or "", case),
                                   "usage": reply.usage, "duration_ms": round((time.perf_counter() - base_start) * 1000)}
            except ModelError as error:
                row["baseline"] = {"success": False, "error": str(error)}
        rows.append(row)
        print(f"[{index:02}/{len(cases)}] {case['id']}: {'PASS' if row['success'] else 'FAIL'}", flush=True)
        # 每完成一题就保留结果，网络中断也不会丢失已测记录。
        (folder / "results.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    baseline_rows = [row["baseline"] for row in rows if "baseline" in row]
    summary = {"mode": mode, "provider":settings.provider if mode == "live" else "demo", "model": settings.model if mode == "live" else "规则演示（非LLM）", "cases_file":case_file.name,"cases": len(rows),
               "passed": sum(bool(row["success"]) for row in rows),
               "tool_passed": sum(bool(row["tool_success"]) for row in rows),
               "answer_passed": sum(bool(row["answer_success"]) for row in rows),
               "median_latency_ms": round(statistics.median(row["duration_ms"] for row in rows)),
               "prompt_tokens": sum(row.get("usage", {}).get("prompt_tokens", 0) for row in rows),
               "completion_tokens": sum(row.get("usage", {}).get("completion_tokens", 0) for row in rows),
               "baseline_cases": len(baseline_rows), "baseline_passed": sum(bool(row["success"]) for row in baseline_rows),
               "failures": [row["id"] for row in rows if not row["success"]]}
    (folder / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# DataPilot 评测报告", "", f"运行时间：{stamp}", f"模式：{mode}", f"模型：{summary['model']}", "",
             f"- 完整任务校验：{summary['passed']}/{len(rows)}", f"- 工具结果字段校验：{summary['tool_passed']}/{len(rows)}",
             f"- 回答关键词及中文规则：{summary['answer_passed']}/{len(rows)}", f"- 中位耗时：{summary['median_latency_ms']} ms",
             f"- 输入/输出 Token：{summary['prompt_tokens']} / {summary['completion_tokens']}",
             f"- 单次模型生成基线：{summary['baseline_passed']}/{summary['baseline_cases']}（不含绘图题）", "",
             "## 逐题结果", "", "| 编号 | 问题 | 工具字段 | 回答规则 | 完整任务 |", "|---|---|---|---|---|"]
    for row in rows:
        lines.append(f"| {row['id']} | {row['question']} | {row['tool_success']} | {row['answer_success']} | {row['success']} |")
    lines += ["", "## 指标边界", "", "这是固定五行示例数据上的26题功能回归，不是泛化能力或行业基准。",
              "工具校验比较实际计算的结构化字段；回答校验使用中文及关键词规则，不能替代人工语义审查。",
              "demo 使用规则路由，其通过率不得当作真实模型准确率。live 使用所选服务商的真实工具调用。",
              "基线使用同模型、同CSV、同组历史和同输出上限，一次生成，不提供工具；其答案只做关键词校验，评判标准比Agent工具字段校验宽松。",
              "Token来自服务返回值；实际账单与缓存计价可能不同。未配置单价时不估算金额。"]
    (folder / "report.md").write_text("\n".join(lines), encoding="utf-8")
    print("REPORT=" + str(folder), flush=True)
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    return summary, folder


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["demo", "live"], default="demo")
    parser.add_argument("--baseline", action="store_true")
    parser.add_argument("--max-cases", type=int, default=26)
    parser.add_argument("--cases", help="自定义题集JSON路径")
    parser.add_argument("--provider", choices=["deepseek","openai","anthropic","compatible"])
    parser.add_argument("--model", help="模型 ID")
    args = parser.parse_args()
    run(args.mode, args.baseline, args.max_cases, args.cases, args.provider, args.model)
