"""命令行入口，与网页共用 Agent、工具、规则和异常处理。"""
import argparse
from .agent import AgentSession
from .config import Settings
from .data import DataError, load_sales
from .demo import DemoGateway
from .models import DeepSeekGateway, ModelError
from .tools import ToolRegistry


def main():
    parser = argparse.ArgumentParser(description="DataPilot 销售分析 Agent")
    parser.add_argument("--demo", action="store_true", help="使用离线规则演示，不调用模型")
    parser.add_argument("--csv", help="销售CSV路径，默认使用项目sales.csv")
    args = parser.parse_args()
    try:
        settings = Settings.from_env()
        frame = load_sales(args.csv)
        gateway = DemoGateway(frame["product"].unique()) if args.demo else DeepSeekGateway(settings)
        session = AgentSession(ToolRegistry(frame, settings.output_dir / "cli"), gateway, settings)
    except (DataError, ModelError, ValueError) as error:
        print("无法启动：", error)
        return
    print("DataPilot · " + ("离线规则演示" if args.demo else "DeepSeek 实时分析"))
    while True:
        try:
            question = input("\n请输入问题，输入“退出”结束：").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nDataPilot 已退出。")
            break
        if question in ["退出", "exit", "quit"]:
            print("DataPilot 已退出。")
            break
        if not question:
            print("请输入一个问题。")
            continue
        try:
            result = session.ask(question)
            for trace in result.traces:
                print("工具：", trace["name"], "参数：", trace["arguments"])
                print("结果：", trace["result"])
            print("\n" + result.answer)
        except (ModelError, ValueError) as error:
            print("本次分析未完成：", error)
            print("可以修改问题后继续提问。")
